"""Validates the `confirm` step (ADR-001, a Should) before it's used: a
Monte Carlo of the two-stage procedure on the measured Pagila pass rates.

Stage 1 is the normal gate on the full suite (5 attempts per task). If it
says "inconclusive" (a drop of at least 5 points whose interval crosses 0),
stage 2 reruns only the tasks that dropped, for both agents, with fresh
trials, and applies the same gate to the fresh trials alone. The question
is whether that keeps the A/A false-alarm rate at or under 5% while
catching small drops more often than stage 1 alone.

    uv run python scripts/simulate_confirm.py PAIRS RESAMPLES STAGE2_ATTEMPTS BASE_RUNS [-- CAND_RUNS]

BASE_RUNS give the baseline per-task rates (pooled). With `-- CAND_RUNS`,
the candidate's rates are measured too (a realistic, uneven drop), in
addition to the uniform drops.
"""

import random
import sys

from agent_eval.compare import INCONCLUSIVE_DROP, bootstrap_interval, broken_tasks
from simulate_gate import measured_rates  # pyright: ignore[reportMissingImports]

K1 = 5


def draw(rng: random.Random, rates: dict[str, float], k: int) -> dict[str, tuple[int, int]]:
    return {t: (rng.binomialvariate(k, p), k) for t, p in rates.items()}


def gate(
    base: dict[str, tuple[int, int]], cand: dict[str, tuple[int, int]], resamples: int, seed: int
) -> tuple[bool, bool, list[str]]:
    """(regression, inconclusive, dropped tasks)."""
    tasks = sorted(base)
    _, high, point = bootstrap_interval(base, cand, tasks, resamples=resamples, seed=seed)
    regression = high < 0 or bool(broken_tasks(base, cand, tasks))
    dropped = [t for t in tasks if cand[t][0] / cand[t][1] < base[t][0] / base[t][1]]
    return regression, (not regression and point <= INCONCLUSIVE_DROP), dropped


def two_stage(  # noqa: PLR0913 -- the simulation's parameters, passed by the sweep
    rng: random.Random,
    base_rates: dict[str, float],
    cand_rates: dict[str, float],
    resamples: int,
    k2: int,
    seed: int,
) -> tuple[bool, bool]:
    """(flagged by stage 1 alone, flagged by the two-stage procedure)."""
    reg, inconclusive, dropped = gate(
        draw(rng, base_rates, K1), draw(rng, cand_rates, K1), resamples, seed
    )
    if reg or not inconclusive or not dropped:
        return reg, reg
    sub_b = draw(rng, {t: base_rates[t] for t in dropped}, k2)
    sub_c = draw(rng, {t: cand_rates[t] for t in dropped}, k2)
    reg2, _, _ = gate(sub_b, sub_c, resamples, seed + 1)
    return False, reg2


def main() -> None:
    pairs, resamples, k2 = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    rest = sys.argv[4:]
    base_dirs, cand_dirs = (
        (rest[: rest.index("--")], rest[rest.index("--") + 1 :]) if "--" in rest else (rest, [])
    )
    rates = {f"t{i:02d}": p for i, p in enumerate(measured_rates(base_dirs))}
    rng = random.Random(11)
    print(
        f"{pairs} pairs per case, {resamples} resamples, stage 2 at {k2} attempts per task, "
        f"{len(rates)} measured tasks"
    )
    for drop in (0.0, 0.03, 0.05, 0.10):
        cand = {t: max(0.0, p - drop) for t, p in rates.items()}
        results = [two_stage(rng, rates, cand, resamples, k2, i) for i in range(pairs)]
        s1 = sum(r[0] for r in results) / pairs
        s2 = sum(r[1] for r in results) / pairs
        label = "A/A (no change)" if drop == 0 else f"uniform drop {drop:.0%}"
        print(f"{label}: stage 1 alone {s1:.1%}, with confirm {s2:.1%}")
    if cand_dirs:
        cand = {f"t{i:02d}": p for i, p in enumerate(measured_rates(cand_dirs))}
        mean_drop = sum(rates[t] - cand[t] for t in rates) / len(rates)
        results = [two_stage(rng, rates, cand, resamples, k2, i) for i in range(pairs)]
        print(
            f"measured candidate {cand_dirs} (mean drop {mean_drop:.1%}): stage 1 alone "
            f"{sum(r[0] for r in results) / pairs:.1%}, with confirm {sum(r[1] for r in results) / pairs:.1%}"
        )


if __name__ == "__main__":
    main()
