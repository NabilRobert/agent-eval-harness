"""Export is checked against a real Inspect log (the committed skeleton
run), so a change in Inspect's log format or in our export shows up here
rather than as quietly different run records."""

import json
from pathlib import Path
from typing import Any, cast

from inspect_ai.event import ModelEvent
from inspect_ai.log import read_eval_log

from agent_eval.export import clean_arguments, trial_from_sample
from agent_eval.records import ordered_json, load_run

SKELETON = Path(__file__).resolve().parent.parent / "runs" / "skeleton"


def test_exporting_the_committed_log_reproduces_the_committed_trials() -> None:
    log = read_eval_log(str(SKELETON / "inspect.eval"))
    meta = load_run(SKELETON).meta
    hashes = meta["suite"]["task_hashes"]
    exported = [
        ordered_json(trial_from_sample(s, hashes, meta["price"])) for s in (log.samples or [])
    ]
    committed = (SKELETON / "trials.jsonl").read_text().splitlines()
    assert exported == committed


def test_skeleton_trial_records_what_graders_and_reports_need() -> None:
    [trial] = load_run(SKELETON).trials
    assert trial["outcome"] == "pass" and trial["strict"] and trial["lenient"]
    assert [c["tool"] for c in trial["tool_calls"]][-1] == "submit"
    assert "run_query" in {c["tool"] for c in trial["tool_calls"]}
    assert all(c["input_tokens"] and c["output_tokens"] for c in trial["model_calls"])
    assert trial["graders"][0]["input"]["graded_rows"]
    # tokens x the price the run records, per million
    assert trial["cost_usd"] == (trial["input_tokens"] * 0.25 + trial["output_tokens"] * 2.0) / 1e6


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


SMOKE = Path(__file__).resolve().parent.parent / "runs" / "smoke-b1"


def test_long_tool_arguments_are_resolved_not_left_as_attachment_refs() -> None:
    """Inspect stores long strings as "attachment://<id>". The slice B smoke
    run caught the export recording the reference instead of the SQL."""
    log = read_eval_log(str(SMOKE / "inspect.eval"))
    hashes = load_run(SMOKE).meta["suite"]["task_hashes"]
    trials = [trial_from_sample(s, hashes) for s in (log.samples or [])]
    text = json.dumps(trials)
    assert "attachment://" not in text
    sqls = [
        c["arguments"]["sql"] for t in trials for c in t["tool_calls"] if c["tool"] == "run_query"
    ]
    assert any(len(sql) > 100 for sql in sqls)  # long ones present, and resolved


def test_exporting_the_smoke_log_reproduces_its_committed_trials() -> None:
    log = read_eval_log(str(SMOKE / "inspect.eval"))
    meta = load_run(SMOKE).meta
    exported = [
        ordered_json(trial_from_sample(s, meta["suite"]["task_hashes"], meta["price"]))
        for s in (log.samples or [])
    ]
    assert exported == (SMOKE / "trials.jsonl").read_text().splitlines()


SMOKE_E1 = Path(__file__).resolve().parent.parent / "runs" / "smoke-e1"


def raw_usage(event: ModelEvent) -> dict[str, Any]:
    """The usage block of the provider's own response, as Inspect logged it."""
    assert event.call is not None
    response = cast(dict[str, Any], event.call.response)
    return cast(dict[str, Any], response["usage"])


def test_input_tokens_include_the_cached_ones_the_provider_reports() -> None:
    """The provider's raw usage is the fixture: `prompt_tokens` counts every
    input token and `prompt_tokens_details.cached_tokens` the cached ones.
    Inspect splits them apart, and export must add them back."""
    log = read_eval_log(str(SMOKE_E1 / "inspect.eval"))
    meta = load_run(SMOKE_E1).meta
    checked = 0
    for sample in log.samples or []:
        trial = trial_from_sample(sample, meta["suite"]["task_hashes"], meta["price"])
        raw_usages = [raw_usage(event) for event in sample.events if event.event == "model"]
        for call, usage in zip(trial["model_calls"], raw_usages, strict=True):
            assert call["input_tokens"] == usage["prompt_tokens"]
            assert call["cached_input_tokens"] == usage["prompt_tokens_details"]["cached_tokens"]
            checked += 1
    assert checked and load_run(SMOKE_E1).meta["totals"]["cached_input_tokens"] > 0
