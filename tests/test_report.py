from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_eval.records import load_run
from agent_eval.report import _fence, headline, render  # pyright: ignore[reportPrivateUsage]
from tests.conftest import make_trial

RunFactory = Callable[..., Path]
GOOD, BAD = [{"count": 1000}], [{"count": 1}]
REPO = Path(__file__).resolve().parent.parent


def _meta_extras(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "agent": {"model": "m", "model_args": {}, "system_prompt_sha256": "p",
                  "tool_allowlist": None, "limits": {}, "epochs": 3},
        "totals": {"trials": 3, "input_tokens": 300, "output_tokens": 30,
                   "cost_usd": {"usd": None, "complete": False}},
    }
    base.update(kw)
    return base


def _trial(attempt: int, rows: Any, outcome: str | None = None, cost: float | None = None) -> dict[str, Any]:
    t = make_trial(attempt, rows, outcome)
    t.update({"input_tokens": 100, "output_tokens": 10, "seconds": 1.0 + attempt,
              "cost_usd": cost, "tool_calls": [], "stop_reason": "completed"})
    return t


def test_rates_leave_errors_out_and_show_them_beside(run_factory: RunFactory) -> None:
    run = load_run(run_factory([_trial(1, GOOD), _trial(2, BAD), _trial(3, None, "error")],
                               **_meta_extras()))
    h = headline(run)
    assert (h["graded"], h["strict"], h["errors"]) == (2, 1, 1)
    text = render(run)
    assert "**Strict pass rate (headline): 1/2 (50.0%)**" in text
    assert "Errors (not counted as fails, not in the rates above): 1 of 3 trials" in text


def test_pass_hat_k_needs_every_attempt_and_skips_tasks_with_errors(run_factory: RunFactory) -> None:
    all_pass = load_run(run_factory([_trial(i, GOOD) for i in (1, 2, 3)], **_meta_extras()))
    one_fail = load_run(run_factory([_trial(1, GOOD), _trial(2, BAD), _trial(3, GOOD)], **_meta_extras()))
    with_error = load_run(run_factory([_trial(1, GOOD), _trial(2, None, "error")], **_meta_extras()))
    assert (headline(all_pass)["pass_all_k"], headline(all_pass)["pass_any_k"]) == (1, 1)
    assert (headline(one_fail)["pass_all_k"], headline(one_fail)["pass_any_k"]) == (0, 1)
    assert headline(with_error)["tasks_counted"] == 0


def test_unknown_cost_is_never_shown_as_zero(run_factory: RunFactory) -> None:
    text = render(load_run(run_factory([_trial(1, GOOD)], **_meta_extras())))
    assert "**Total cost:** unknown (model has no price in prices.yaml)" in text
    assert "$0.0000" not in text


def test_partly_priced_total_is_labelled_a_lower_bound(run_factory: RunFactory) -> None:
    extras = _meta_extras(totals={"trials": 2, "input_tokens": 1, "output_tokens": 1,
                                  "cost_usd": {"usd": 0.01, "complete": False}})
    text = render(load_run(run_factory([_trial(1, GOOD, cost=0.01), _trial(2, GOOD)], **extras)))
    assert "$0.0100 (lower bound" in text


def test_agent_text_cannot_break_out_of_its_fence() -> None:
    nasty = "select 1 ```\n# Injected heading\n```"
    fenced = _fence(nasty)
    fence = fenced.splitlines()[0]
    assert set(fence) == {"`"} and len(fence) > 3
    assert fenced.endswith("\n" + fence) and nasty in fenced


def test_failed_trials_are_explained(run_factory: RunFactory) -> None:
    text = render(load_run(run_factory([_trial(1, BAD)], **_meta_extras())))
    assert "### easy-01 attempt 1: fail" in text
    assert "- Expected: [1000]" in text and "- Got: [1]" in text


def test_render_is_deterministic(run_factory: RunFactory) -> None:
    run = load_run(run_factory([_trial(1, GOOD), _trial(2, BAD)], **_meta_extras()))
    assert render(run) == render(run)


def test_every_committed_report_matches_its_records() -> None:
    """A committed report can't drift from (or be edited away from) the
    records it claims to summarise."""
    for meta in sorted((REPO / "runs").glob("*/meta.json")):
        run_dir = meta.parent
        assert (run_dir / "report.md").read_text() == render(load_run(run_dir)), run_dir.name
