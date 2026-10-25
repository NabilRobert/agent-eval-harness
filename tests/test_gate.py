"""The regression gates (ADR-001) on synthetic runs, where the right answer
is known. The live proofs (A/A pairs not flagged, degraded agents
flagged) come from real runs; these pin each rule's behaviour exactly.
Most tests pin gate v1 (the rule every published comparison used); the v2
tests are at the end."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_eval.compare import (
    EXIT_OK,
    EXIT_REGRESSION,
    bootstrap_interval,
    broken_tasks,
    compare_runs,
)
from agent_eval.records import task_hash

RunFactory = Callable[..., Path]
N_TASKS, K = 30, 5


def _task(i: int) -> dict[str, Any]:
    return {"id": f"t{i:02d}", "prompt": f"q{i}",
            "graders": [{"result_match": {"tool": "run_query", "expected": [{"n": i}]}}]}


TASKS = [_task(i) for i in range(N_TASKS)]


def _trials(passes: list[int]) -> list[dict[str, Any]]:
    """passes[i] of K attempts of task i pass (strictly), the rest fail."""
    out: list[dict[str, Any]] = []
    for task, p in zip(TASKS, passes, strict=True):
        expected = task["graders"][0]["result_match"]["expected"]
        for attempt in range(1, K + 1):
            ok = attempt <= p
            rows = expected if ok else [{"n": -1}]
            out.append({
                "task_id": task["id"], "task_hash": task_hash(task), "attempt": attempt,
                "outcome": "pass" if ok else "fail", "strict": ok, "lenient": ok,
                "graders": [{"kind": "result_match", "tool": "run_query", "expected": expected,
                             "input": {"graded_rows": rows}, "strict": ok, "lenient": ok}],
                "cost_usd": 0.003, "seconds": 10.0,
            })
    return out


def _suite() -> dict[str, Any]:
    return {"name": "synthetic", "task_hashes": {t["id"]: task_hash(t) for t in TASKS}}


def _compare(run_factory: RunFactory, base: list[int], cand: list[int], gate: str = "v1"):  # pyright: ignore[reportUnknownParameterType]
    return compare_runs(run_factory(_trials(base), suite=_suite()),
                        run_factory(_trials(cand), suite=_suite()), gate)


MOSTLY_EASY = [5] * 24 + [4, 4, 3, 3, 2, 2]


def test_same_results_are_not_a_regression(run_factory: RunFactory) -> None:
    result = _compare(run_factory, MOSTLY_EASY, MOSTLY_EASY)
    assert (result.exit_code, result.verdict) == (EXIT_OK, "no regression")
    assert result.interval is not None and result.interval[0] <= 0 <= result.interval[1]


def test_a_broad_drop_is_a_regression(run_factory: RunFactory) -> None:
    """Every task loses 2 of its 5 passes: about a 40-point drop."""
    worse = [max(0, p - 2) for p in MOSTLY_EASY]
    result = _compare(run_factory, MOSTLY_EASY, worse)
    assert (result.exit_code, result.verdict) == (EXIT_REGRESSION, "regression")
    assert result.interval is not None and result.interval[1] < 0
    assert any("entirely below 0" in r for r in result.reasons)


def test_one_collapsed_task_is_a_regression_even_if_the_suite_average_barely_moves(
    run_factory: RunFactory,
) -> None:
    worse = list(MOSTLY_EASY)
    worse[0] = 0  # t00: 5/5 -> 0/5
    result = _compare(run_factory, MOSTLY_EASY, worse)
    assert result.exit_code == EXIT_REGRESSION
    assert result.broken == ["t00"]
    assert result.interval is not None and result.interval[1] >= 0  # caught by the task rule alone


def test_five_to_one_is_not_called_broken(run_factory: RunFactory) -> None:
    """The rule Spike 5 rejected (5/5 -> <=1/5) fired on 5-11% of A/A
    pairs; the adopted rule needs a drop to zero."""
    worse = list(MOSTLY_EASY)
    worse[0] = 1
    result = _compare(run_factory, MOSTLY_EASY, worse)
    assert result.broken == []
    assert result.exit_code == EXIT_OK


def test_a_moderate_drop_with_a_wide_interval_is_inconclusive(run_factory: RunFactory) -> None:
    base = [3] * N_TASKS
    cand = [3] * 22 + [1] * 8  # -10.7 points on noisy tasks
    result = _compare(run_factory, base, cand)
    assert result.verdict == "inconclusive" and result.exit_code == EXIT_OK
    assert len(result.dropped) == 8


def test_improvement_is_not_a_regression(run_factory: RunFactory) -> None:
    result = _compare(run_factory, [3] * N_TASKS, [5] * N_TASKS)
    assert result.verdict == "no regression" and result.point is not None and result.point > 0


def test_same_inputs_always_give_the_same_interval() -> None:
    base = {t["id"]: (p, K) for t, p in zip(TASKS, MOSTLY_EASY, strict=True)}
    cand = {t["id"]: (max(0, p - 1), K) for t, p in zip(TASKS, MOSTLY_EASY, strict=True)}
    tasks = sorted(base)
    assert bootstrap_interval(base, cand, tasks) == bootstrap_interval(base, cand, tasks)


def test_broken_rule_needs_enough_trials_on_both_sides() -> None:
    assert broken_tasks({"a": (4, 4)}, {"a": (0, 5)}, ["a"]) == []
    assert broken_tasks({"a": (5, 5)}, {"a": (0, 5)}, ["a"]) == ["a"]


def test_cost_increase_is_a_warning_not_a_regression(run_factory: RunFactory) -> None:
    pricier = _trials(MOSTLY_EASY)
    for t in pricier:
        t["cost_usd"] = 0.006
    result = compare_runs(run_factory(_trials(MOSTLY_EASY), suite=_suite()),
                          run_factory(pricier, suite=_suite()), "v1")
    assert result.exit_code == EXIT_OK
    assert any("median cost per trial up 100%" in w for w in result.warnings)


# --- gate v2: pooled two-proportion z-test + the same task rule ---

SIX_LOSE_TWO = [max(0, p - 2) if i < 6 else p for i, p in enumerate(MOSTLY_EASY)]


def test_v2_same_results_are_not_a_regression(run_factory: RunFactory) -> None:
    result = _compare(run_factory, MOSTLY_EASY, MOSTLY_EASY, "v2")
    assert (result.exit_code, result.verdict) == (EXIT_OK, "no regression")


def test_v2_flags_a_drop_v1_misses(run_factory: RunFactory) -> None:
    """Six tasks each lose 2 of 5 passes (-8 points): v1's task-resampling
    interval just reaches 0, v2's pooled test flags it (z = 2.13). The
    sensitivity difference simulation showed, pinned on one case."""
    v1 = _compare(run_factory, MOSTLY_EASY, SIX_LOSE_TWO, "v1")
    v2 = _compare(run_factory, MOSTLY_EASY, SIX_LOSE_TWO, "v2")
    assert v1.exit_code == EXIT_OK
    assert (v2.exit_code, v2.verdict) == (EXIT_REGRESSION, "regression")
    assert any("pooled z = 2.13" in r for r in v2.reasons)
    assert v2.gate_verdicts == {"v1": v1.verdict, "v2": "regression"}


def test_v2_keeps_the_task_rule(run_factory: RunFactory) -> None:
    worse = list(MOSTLY_EASY)
    worse[0] = 0
    result = _compare(run_factory, MOSTLY_EASY, worse, "v2")
    assert result.exit_code == EXIT_REGRESSION and result.broken == ["t00"]


def test_v2_improvement_is_not_a_regression(run_factory: RunFactory) -> None:
    result = _compare(run_factory, [3] * N_TASKS, [5] * N_TASKS, "v2")
    assert result.verdict == "no regression"


def test_v2_is_a_formula_not_a_simulation() -> None:
    """No resampling, so no seed: the same counts give the same z."""
    from agent_eval.compare import pooled_test

    base = {"a": (5, 5), "b": (4, 5)}
    cand = {"a": (3, 5), "b": (2, 5)}
    z, low, high = pooled_test(base, cand, ["a", "b"])
    assert round(z, 4) == round(pooled_test(base, cand, ["a", "b"])[0], 4)
    assert z > 0 and low < (5 / 10 - 9 / 10) < high
