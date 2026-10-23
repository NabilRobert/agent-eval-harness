"""The whole pipeline, offline: real Inspect, its mock model and a local
`run_query` tool instead of MCP-backbone. Covers the outcomes the Phase 3
invariants define, and checks each one is classified correctly:
pass, fail, a server refusal (error, never fail), a runaway agent hitting
its cap (fail) and a model that crashes (error). No network, no key."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from inspect_ai import eval as inspect_eval  # pyright: ignore[reportUnknownVariableType]
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.tool import Tool, tool

from agent_eval.export import build_meta, trial_from_sample
from agent_eval.inspect_tasks import build_task
from agent_eval.suites import PAGILA_SYSTEM_PROMPT, suite_task_hashes
from agent_eval.targets import TARGETS

SUITE: dict[str, Any] = {
    "suite": "offline",
    "target": "mcp-backbone",
    "tasks": [
        {
            "id": "t1",
            "prompt": "How many films?",
            "graders": [{"result_match": {"tool": "run_query", "expected": [{"count": 1000}]}}],
        }
    ],
}
AGENT: dict[str, Any] = {
    "model": "mockllm/model", "model_args": {}, "system_prompt": PAGILA_SYSTEM_PROMPT,
    "tool_allowlist": None, "message_limit": 8, "time_limit": 60, "token_limit": 60_000,
    "epochs": 1,
}


def fake_run_query(payload: dict[str, Any]) -> Tool:
    @tool(name="run_query")
    def run_query() -> Tool:
        async def execute(sql: str) -> str:
            """Run a read-only SQL query.

            Args:
                sql: The query.
            """
            return json.dumps(payload)

        return execute

    return run_query()


def query_then_submit() -> list[ModelOutput]:
    return [
        ModelOutput.for_tool_call("mockllm/model", "run_query", {"sql": "select count(*) from film"}),
        ModelOutput.for_tool_call("mockllm/model", "submit", {"answer": "1000"}),
    ]


def run_offline(tmp_path: Path, payload: dict[str, Any], outputs: Any) -> dict[str, Any]:
    task = build_task(SUITE, TARGETS["mcp-backbone"], AGENT, "unused",
                      tools_override=[fake_run_query(payload)])
    model = get_model("mockllm/model", custom_outputs=outputs)
    [log] = inspect_eval(task, model=model, log_dir=str(tmp_path), display="none",
                         fail_on_error=False, retry_on_error=0)
    [sample] = log.samples or []
    trial = trial_from_sample(sample, suite_task_hashes(SUITE))
    trial["_meta"] = build_meta(
        log, [trial], run_id="r", suite=SUITE, task_hashes=suite_task_hashes(SUITE),
        agent=AGENT, preflight_info={}, harness_git="x", system_prompt_sha256="p",
    )
    return trial


def test_correct_answer_passes(tmp_path: Path) -> None:
    trial = run_offline(tmp_path, {"status": "succeeded", "rows": [{"n": 1000}]},
                        query_then_submit())
    assert (trial["outcome"], trial["strict"], trial["lenient"]) == ("pass", True, True)
    assert trial["graders"][0]["input"]["graded_rows"] == [{"n": 1000}]
    assert trial["_meta"]["status"] == "complete"


def test_wrong_answer_fails(tmp_path: Path) -> None:
    trial = run_offline(tmp_path, {"status": "succeeded", "rows": [{"n": 999}]},
                        query_then_submit())
    assert (trial["outcome"], trial["strict"]) == ("fail", False)


def test_rejected_query_fails_as_the_agents_fault(tmp_path: Path) -> None:
    """MCP-backbone rejecting a bad query is feedback to the agent, not an
    infrastructure error (Phase 4)."""
    trial = run_offline(tmp_path, {"status": "rejected", "rows": [], "error": "not a SELECT"},
                        query_then_submit())
    assert trial["outcome"] == "fail"
    assert trial["graders"][0]["input"]["graded_rows"] is None


def test_rate_limited_query_is_an_error_never_a_fail(tmp_path: Path) -> None:
    """ADR-007: without this, every rate-limited trial would be scored as
    the agent getting the answer wrong."""
    payload: dict[str, Any] = {"status": "rejected", "rows": [],
               "error": "rate limit of 5 requests per window exceeded"}
    trial = run_offline(tmp_path, payload, query_then_submit())
    assert trial["outcome"] == "error"
    assert trial["error_kind"] == "target_refused:rate limit of"
    assert trial["_meta"]["status"] == "incomplete"  # 1 of 1 errored, over 10%


def test_runaway_agent_hits_its_cap_and_fails(tmp_path: Path) -> None:
    def forever() -> Iterator[ModelOutput]:
        while True:
            yield ModelOutput.for_tool_call("mockllm/model", "run_query", {"sql": "select 1"})

    trial = run_offline(tmp_path, {"status": "succeeded", "rows": [{"n": 1000}]}, forever())
    assert trial["outcome"] == "fail"
    assert trial["stop_reason"] == "message"
    assert not trial["strict"]


def test_crashing_model_is_an_error(tmp_path: Path) -> None:
    def crash() -> Iterator[ModelOutput]:
        raise RuntimeError("provider exploded")
        yield  # pragma: no cover  (makes this a generator)

    trial = run_offline(tmp_path, {"status": "succeeded", "rows": [{"n": 1000}]}, crash())
    assert trial["outcome"] == "error"
    assert trial["error_kind"] == "provider_or_harness"


def test_tool_calls_and_model_calls_are_recorded(tmp_path: Path) -> None:
    trial = run_offline(tmp_path, {"status": "succeeded", "rows": [{"n": 1000}]},
                        query_then_submit())
    assert [c["tool"] for c in trial["tool_calls"]] == ["run_query", "submit"]
    assert trial["tool_calls"][0]["arguments"] == {"sql": "select count(*) from film"}
    assert len(trial["model_calls"]) == 2
