"""Gate v3 (paired conversations, ADR-014) on synthetic runs shaped like
AI Flight School's: one scenario per task, a pass when the simulated
customer ended `###DONE###`, graded by `result_match` over one row."""

import math
import random
import statistics
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_eval.cli import main
from agent_eval.compare import (
    EXIT_OK,
    EXIT_REGRESSION,
    EXIT_UNDECIDED,
    Z_CRITICAL,
    compare_runs,
    paired_bootstrap_interval,
)
from agent_eval.records import task_hash

RunFactory = Callable[..., Path]
SCENARIOS = 50
DONE, GAVE_UP = "###DONE###", "###GAVE_UP###"


def _task(i: int) -> dict[str, Any]:
    expected = [{"stop_marker": DONE}]
    return {
        "id": f"s{i:02d}",
        "prompt": f"persona {i}",
        "graders": [{"result_match": {"expected": expected}}],
    }


TASKS = [_task(i) for i in range(SCENARIOS)]


def _trial(task: dict[str, Any], attempt: int, passed: bool) -> dict[str, Any]:
    spec = task["graders"][0]["result_match"]
    rows = [{"stop_marker": DONE if passed else GAVE_UP}]
    grader = {"kind": "result_match", "spec": spec, "input": {"graded_rows": rows}}
    return {
        "task_id": task["id"],
        "task_hash": task_hash(task),
        "attempt": attempt,
        "outcome": "pass" if passed else "fail",
        "strict": passed,
        "lenient": passed,
        "graders": [grader | {"strict": passed, "lenient": passed}],
    }


def _trials(passing: set[int]) -> list[dict[str, Any]]:
    """One conversation per scenario; scenarios in `passing` pass."""
    return [_trial(task, 1, i in passing) for i, task in enumerate(TASKS)]


def _suite() -> dict[str, Any]:
    return {"name": "pilot", "task_hashes": {t["id"]: task_hash(t) for t in TASKS}}


def _run(run_factory: RunFactory, trials: list[dict[str, Any]]) -> Path:
    return run_factory(trials, suite=_suite())


HEALTHY = set(range(40))  # 80% pass, the thesis pilot's assumed baseline


def test_the_same_conversations_are_not_a_regression(run_factory: RunFactory) -> None:
    run = _run(run_factory, _trials(HEALTHY))
    result = compare_runs(run, run, "v3")
    assert (result.exit_code, result.verdict, result.point) == (EXIT_OK, "no regression", 0.0)
    assert result.gate_verdicts == {"v3": "no regression"}


def test_a_30_point_paired_drop_is_a_regression(run_factory: RunFactory) -> None:
    degraded = set(range(25))  # 15 of the healthy passes now fail: -30 points
    result = compare_runs(
        _run(run_factory, _trials(HEALTHY)), _run(run_factory, _trials(degraded)), "v3"
    )
    assert (result.exit_code, result.verdict) == (EXIT_REGRESSION, "regression")
    assert result.point is not None and math.isclose(result.point, -0.30)
    assert any("50 pairs" in reason for reason in result.reasons)


def test_a_small_paired_drop_is_inconclusive(run_factory: RunFactory) -> None:
    # 4 healthy passes now fail and 1 healthy fail now passes: -6 points.
    slightly_worse = (HEALTHY - {0, 1, 2, 3}) | {45}
    result = compare_runs(
        _run(run_factory, _trials(HEALTHY)), _run(run_factory, _trials(slightly_worse)), "v3"
    )
    assert (result.exit_code, result.verdict) == (EXIT_OK, "inconclusive")
    assert any("plan-pairs" in reason for reason in result.reasons)


def test_pairs_missing_or_errored_on_one_side_are_left_out_and_listed(
    run_factory: RunFactory,
) -> None:
    candidate = _trials(HEALTHY)
    candidate[0]["outcome"] = "error"
    del candidate[1]
    result = compare_runs(_run(run_factory, _trials(HEALTHY)), _run(run_factory, candidate), "v3")
    assert result.unpaired == ["s00#1", "s01#1"]
    assert result.verdict == "no regression"


def test_runs_with_no_pairs_in_common_are_undecided(run_factory: RunFactory) -> None:
    errored = _trials(HEALTHY)
    for trial in errored:
        trial["outcome"] = "error"
    result = compare_runs(_run(run_factory, _trials(HEALTHY)), _run(run_factory, errored), "v3")
    assert (result.exit_code, result.verdict) == (EXIT_UNDECIDED, "undecided")


def test_the_interval_resamples_scenarios_not_single_conversations() -> None:
    """Two attempts of one scenario share its difficulty. Resampling them
    together gives a wider interval than treating all 40 as independent."""
    rng = random.Random(1)
    per_scenario = [rng.choice([-1, 0, 0, 1]) for _ in range(20)]
    clustered = {f"s{i}": [d, d] for i, d in enumerate(per_scenario)}
    independent = {f"s{i}-{a}": [d] for i, d in enumerate(per_scenario) for a in range(2)}
    low_c, high_c, point_c = paired_bootstrap_interval(clustered)
    low_i, high_i, point_i = paired_bootstrap_interval(independent)
    assert point_c == point_i
    assert high_c - low_c > high_i - low_i


def test_with_one_attempt_per_scenario_the_interval_is_the_normal_one() -> None:
    """plan-pairs simulates gate v3 with this approximation (ADR-015)."""
    rng = random.Random(2)
    differences = [rng.choice([-1, -1, 0, 0, 0, 1]) for _ in range(200)]
    low, high, point = paired_bootstrap_interval({f"s{i}": [d] for i, d in enumerate(differences)})
    half_width = Z_CRITICAL * statistics.stdev(differences) / math.sqrt(len(differences))
    assert abs(low - (point - half_width)) < 0.01
    assert abs(high - (point + half_width)) < 0.01


def test_compare_with_gate_v3_exits_1_on_a_paired_regression(
    run_factory: RunFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = _run(run_factory, _trials(HEALTHY))
    candidate = _run(run_factory, _trials(set(range(25))))
    assert main(["compare", str(baseline), str(candidate), "--gate", "v3"]) == EXIT_REGRESSION
    assert "gate v3" in capsys.readouterr().out
