"""The budget guard (Phase 2: at most $5 per full run, Arthur: keep spend
conservative). Two layers:

1. Before the run: an estimate from measured token use, refused if over
   budget.
2. During it: each trial gets a cost cap of budget / number of trials
   (Inspect's per-sample `cost_limit`), so even if every trial ran to its
   cap, the run can't exceed the budget. That closes the gap Phase 4
   flagged (trials already in flight overshooting a run-level check).

A model with no price can't be capped in dollars, so it may only run
smoke-sized runs, still bounded by the per-trial token limit."""

import json
from pathlib import Path
from typing import Any, cast

import yaml

SMOKE_MAX_TRIALS = 10
# Used when no earlier complete run of this suite and model exists to
# measure from. Deliberately pessimistic: the heaviest trial measured so
# far used ~3.6k tokens.
DEFAULT_TOKENS_PER_TRIAL = (15_000, 4_000)


class BudgetError(Exception):
    pass


def load_prices(path: Path) -> dict[str, dict[str, Any]]:
    doc = cast(dict[str, Any], yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    models = cast(dict[str, dict[str, Any]], doc.get("models") or {})
    for name, entry in models.items():
        for field in ("input", "output", "source", "checked"):
            if field not in entry:
                raise BudgetError(f"prices.yaml: {name} has no {field!r}")
        # YAML reads 2026-10-23 as a date object, which JSON can't hold.
        entry["checked"] = str(entry["checked"])
    return models


def price_for(model: str, prices: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Prices are keyed by the full model id, provider included: the same
    model costs different amounts through different providers, and an
    OpenAI run must never be costed at Sumopod's prices."""
    return prices.get(model)


TOKENS_PER_PRICE_UNIT = 1_000_000  # prices.yaml is in US dollars per million tokens


def cost_usd(
    input_tokens: int,
    output_tokens: int,
    price: dict[str, Any] | None,
    cached_input_tokens: int = 0,
) -> float | None:
    """What these tokens cost at `price`, or None when there's no price.
    `input_tokens` counts every input token, cached ones included;
    `cached_input_tokens` of them are charged at the table's `cache_read`
    price (the full input price when it has none), as the provider bills
    them and as Inspect's per-trial cost cap counts them."""
    if price is None:
        return None
    input_price = float(price["input"])
    cache_read_price = float(price.get("cache_read", input_price))
    uncached_input_tokens = input_tokens - cached_input_tokens
    dollars_per_unit = (
        uncached_input_tokens * input_price
        + cached_input_tokens * cache_read_price
        + output_tokens * float(price["output"])
    )
    return dollars_per_unit / TOKENS_PER_PRICE_UNIT


def measured_tokens_per_trial(runs_dir: Path, suite: str, model: str) -> tuple[int, int] | None:
    """Mean tokens per trial over earlier complete runs of the same suite
    and model, read from their meta.json totals."""
    totals: list[tuple[int, int, int]] = []
    for meta_path in sorted(runs_dir.glob("*/meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (
            meta.get("status") == "complete"
            and meta["suite"]["name"] == suite
            and meta["agent"]["model"] == model
            and meta["totals"]["trials"]
        ):
            t = meta["totals"]
            totals.append((t["input_tokens"], t["output_tokens"], t["trials"]))
    if not totals:
        return None
    n = sum(t[2] for t in totals)
    return sum(t[0] for t in totals) // n, sum(t[1] for t in totals) // n


def plan(
    *,
    n_trials: int,
    budget: float,
    price: dict[str, Any] | None,
    tokens_per_trial: tuple[int, int] | None,
) -> dict[str, Any]:
    """The run's spending plan, or BudgetError if it can't be run safely."""
    basis = "measured" if tokens_per_trial else "default (pessimistic)"
    per_trial = tokens_per_trial or DEFAULT_TOKENS_PER_TRIAL
    if price is None:
        if n_trials > SMOKE_MAX_TRIALS:
            raise BudgetError(
                f"model has no price in prices.yaml, so only smoke runs (<= {SMOKE_MAX_TRIALS} "
                f"trials) are allowed; this run has {n_trials}"
            )
        return {
            "budget_usd": budget,
            "estimate_usd": None,
            "per_trial_cap_usd": None,
            "token_basis": basis,
            "priced": False,
        }
    estimate = n_trials * (cost_usd(per_trial[0], per_trial[1], price) or 0.0)
    if estimate > budget:
        raise BudgetError(f"estimated ${estimate:.2f} is over the ${budget:.2f} budget")
    return {
        "budget_usd": budget,
        "estimate_usd": round(estimate, 4),
        "per_trial_cap_usd": budget / n_trials,
        "token_basis": basis,
        "priced": True,
    }
