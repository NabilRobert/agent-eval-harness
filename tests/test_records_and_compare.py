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
    assert (result.exit_code, result.verdict) == (EXIT_OK, "no regression")


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


def test_error_trials_are_left_out_of_pass_rates(run_factory: RunFactory) -> None:
    run = run_factory([make_trial(1, GOOD), make_trial(2, None, outcome="error")])
    assert compare_runs(run, run).per_task == {"easy-01": (1.0, 1.0)}


def test_column_order_survives_writing_and_loading(run_factory: RunFactory) -> None:
    """The bug the slice B smoke run caught: records written with sorted
    keys reordered every row's columns, so regrading a stored correct
    multi-column answer failed it. Columns here are deliberately not in
    alphabetical order."""
    rows = [{"rating": "G", "title": "CAT CONEHEADS", "n": 123}]
    trial = make_trial(1, rows)
    trial["graders"][0]["expected"] = [{"rating": "G", "title": "CAT CONEHEADS", "n": 123}]
    trial["strict"] = trial["lenient"] = True
    trial["outcome"] = "pass"
    run = run_factory([trial])
    [loaded] = load_run(run).trials
    assert list(loaded["graders"][0]["input"]["graded_rows"][0]) == ["rating", "title", "n"]
    result = compare_runs(run, run)
    assert result.regrade_mismatches == []


def test_task_hash_notices_reordered_expected_columns() -> None:
    from agent_eval.records import task_hash

    a = {"prompt": "q", "graders": [{"result_match": {"tool": "t", "expected": [{"x": 1, "y": 2}]}}]}
    b = {"prompt": "q", "graders": [{"result_match": {"tool": "t", "expected": [{"y": 2, "x": 1}]}}]}
    assert task_hash(a) != task_hash(b)


def test_every_committed_run_is_intact_and_regrades_to_its_stored_grades() -> None:
    """Runs off the repo: CI fails if any committed run was edited, or if
    the current graders would grade any stored trial differently."""
    runs = sorted(p.parent for p in (Path(__file__).resolve().parent.parent / "runs").glob("*/meta.json"))
    assert runs
    for run_dir in runs:
        result = compare_runs(run_dir, run_dir)
        assert result.regrade_mismatches == [], run_dir.name
        assert result.exit_code == EXIT_OK, (run_dir.name, result.reasons)


def test_a_meta_that_cant_be_written_leaves_the_run_untouched(tmp_path: Path) -> None:
    """The bug a reexport hit: a value JSON can't hold made the meta write
    fail after trials.jsonl was already replaced, leaving a run whose
    files disagreed. Now nothing is written unless everything serialises."""
    import datetime

    from agent_eval.records import write_run

    run = tmp_path / "run"
    write_run(run, make_meta(), [make_trial(1, GOOD)])
    before = {p.name: p.read_text() for p in run.iterdir()}
    with pytest.raises(TypeError):
        write_run(run, make_meta(price={"checked": datetime.date(2026, 10, 23)}),
                  [make_trial(1, [{"count": 1}])])
    assert {p.name: p.read_text() for p in run.iterdir()} == before
    load_run(run)  # still consistent
