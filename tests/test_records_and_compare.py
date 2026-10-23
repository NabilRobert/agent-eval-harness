import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_eval.compare import EXIT_OK, EXIT_UNDECIDED, compare_runs
from agent_eval.records import RecordError, load_run
from tests.conftest import make_meta, make_trial

RunFactory = Callable[..., Path]
GOOD = [{"count": 1000}]


def test_a_run_compared_with_itself_is_no_change(run_factory: RunFactory) -> None:
    run = run_factory([make_trial(1, GOOD)])
    result = compare_runs(run, run)
    assert (result.exit_code, result.verdict) == (EXIT_OK, "no change")


def test_hand_edited_trials_file_is_refused(run_factory: RunFactory) -> None:
    """Committed runs are evidence: editing one after the fact (here,
    turning a fail into a pass) must be caught, not compared."""
    run = run_factory([make_trial(1, [{"count": 999}])])
    path = run / "trials.jsonl"
    path.write_text(path.read_text().replace('"outcome":"fail"', '"outcome":"pass"'))
    with pytest.raises(RecordError, match="hash"):
        load_run(run)
    assert compare_runs(run, run).exit_code == EXIT_UNDECIDED


def test_unknown_schema_version_is_refused(run_factory: RunFactory) -> None:
    run = run_factory([make_trial(1, GOOD)])
    meta = json.loads((run / "meta.json").read_text())
    meta["schema_version"] = 99
    (run / "meta.json").write_text(json.dumps(meta))
    with pytest.raises(RecordError, match="schema_version"):
        load_run(run)


def test_changed_task_is_not_compared(run_factory: RunFactory) -> None:
    baseline = run_factory([make_trial(1, GOOD)])
    other = make_meta()["suite"]
    other = {**other, "task_hashes": {"easy-01": "a-different-hash"}}
    candidate = run_factory([make_trial(1, GOOD)], suite=other)
    result = compare_runs(baseline, candidate)
    assert result.exit_code == EXIT_UNDECIDED
    assert any("different hashes" in r for r in result.reasons)


def test_different_data_is_not_compared(run_factory: RunFactory) -> None:
    provenance: dict[str, Any] = {**make_meta()["provenance"], "data_fingerprint": "other-data"}
    result = compare_runs(run_factory([make_trial(1, GOOD)]),
                          run_factory([make_trial(1, GOOD)], provenance=provenance))
    assert result.exit_code == EXIT_UNDECIDED
    assert any("fingerprint" in r for r in result.reasons)


def test_incomplete_run_is_not_compared(run_factory: RunFactory) -> None:
    result = compare_runs(run_factory([make_trial(1, GOOD)]),
                          run_factory([make_trial(1, GOOD)], status="incomplete"))
    assert result.exit_code == EXIT_UNDECIDED


def test_provenance_differences_are_listed(run_factory: RunFactory) -> None:
    provenance: dict[str, Any] = {**make_meta()["provenance"], "server_version": "v2"}
    result = compare_runs(run_factory([make_trial(1, GOOD)]),
                          run_factory([make_trial(1, GOOD)], provenance=provenance))
    assert result.differences == ["server_version: 'v1' -> 'v2'"]


def test_stored_grade_that_current_graders_disagree_with_is_reported(
    run_factory: RunFactory,
) -> None:
    """Regrading uses the stored grader inputs, not the stored verdicts: a
    trial recorded as passing whose rows don't actually match is caught."""
    trial = make_trial(1, [{"count": 999}])
    trial["strict"] = trial["lenient"] = True
    trial["outcome"] = "pass"
    run = run_factory([trial])
    result = compare_runs(run, run)
    assert result.regrade_mismatches
    assert result.per_task == {"easy-01": (0.0, 0.0)}


def test_changed_pass_rate_is_undecided_until_the_gate_exists(run_factory: RunFactory) -> None:
    result = compare_runs(run_factory([make_trial(1, GOOD)]),
                          run_factory([make_trial(1, [{"count": 1}])]))
    assert result.exit_code == EXIT_UNDECIDED
    assert result.per_task == {"easy-01": (1.0, 0.0)}


def test_error_trials_are_left_out_of_pass_rates(run_factory: RunFactory) -> None:
    run = run_factory([make_trial(1, GOOD), make_trial(2, None, outcome="error")])
    assert compare_runs(run, run).per_task == {"easy-01": (1.0, 1.0)}
