"""Export is checked against a real Inspect log (the committed skeleton
run), so a change in Inspect's log format or in our export shows up here
rather than as quietly different run records."""

import json
from pathlib import Path

from inspect_ai.log import read_eval_log

from agent_eval.export import clean_arguments, trial_from_sample
from agent_eval.records import canonical_json, load_run
from agent_eval.suites import SKELETON_SUITE, suite_task_hashes

SKELETON = Path(__file__).resolve().parent.parent / "runs" / "skeleton"


def test_exporting_the_committed_log_reproduces_the_committed_trials() -> None:
    log = read_eval_log(str(SKELETON / "inspect.eval"))
    hashes = suite_task_hashes(SKELETON_SUITE)
    exported = [canonical_json(trial_from_sample(s, hashes)) for s in (log.samples or [])]
    committed = (SKELETON / "trials.jsonl").read_text().splitlines()
    assert exported == committed


def test_skeleton_trial_records_what_graders_and_reports_need() -> None:
    [trial] = load_run(SKELETON).trials
    assert trial["outcome"] == "pass" and trial["strict"] and trial["lenient"]
    assert [c["tool"] for c in trial["tool_calls"]][-1] == "submit"
    assert "run_query" in {c["tool"] for c in trial["tool_calls"]}
    assert all(c["input_tokens"] and c["output_tokens"] for c in trial["model_calls"])
    assert trial["graders"][0]["input"]["graded_rows"]
    assert trial["cost_usd"] is None  # no price table yet: unknown, not 0


def test_skeleton_meta_records_provenance() -> None:
    meta = json.loads((SKELETON / "meta.json").read_text())
    provenance = meta["provenance"]
    assert provenance["models_reported"] == ["gpt-5-mini"]
    assert provenance["tool_list_sha256"]
    assert provenance["server_name"] == "database-mcp"


def test_api_key_argument_is_never_recorded() -> None:
    """Unit-tested directly: the skeleton run's model never sent api_key,
    so the committed log can't show this working."""
    assert clean_arguments({"sql": "select 1", "api_key": "dbmcp_x"}) == {"sql": "select 1"}
    assert clean_arguments({"api_key": None}) == {}
    assert clean_arguments(None) == {}
