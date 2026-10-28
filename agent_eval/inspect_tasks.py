"""Builds an Inspect AI task from a suite (ADR-009): Inspect runs the
agent loop, repeats and limits; this module only says what to run and how
to score it. The scorer stores each grader's full input on the sample, so
any trial can be regraded later from the record alone."""

import json
from typing import Any, cast

from inspect_ai import Task
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageTool
from inspect_ai.scorer import Score, Target, mean, scorer
from inspect_ai.solver import TaskState
import sys

from inspect_ai.tool import mcp_server_http, mcp_server_stdio, mcp_tools

from agent_eval.grading import GRADER_VERSION, grade_one
from agent_eval.records import task_hash


def _tool_payload(message: ChatMessageTool) -> dict[str, Any] | None:
    """MCP-backbone returns JSON text; anything else isn't gradable."""
    try:
        payload: object = json.loads(message.text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return cast(dict[str, Any], payload)


def _infra_error(messages: list[ChatMessageTool], patterns: list[str]) -> str | None:
    for message in messages:
        text = message.text.lower()
        for pattern in patterns:
            if pattern.lower() in text:
                return pattern
    return None


@scorer(metrics={"strict": [mean()], "lenient": [mean()]})
def suite_scorer(infra_error_patterns: list[str]):  # pyright: ignore[reportUnknownParameterType]
    """Grades a finished trial with every grader its task lists. A trial
    passes strictly only if every grader passes strictly (Phase 3)."""

    async def score(state: TaskState, target: Target) -> Score:  # noqa: ARG001
        task: dict[str, Any] = state.metadata["task"]
        tool_messages = [m for m in state.messages if isinstance(m, ChatMessageTool)]
        grader_results: list[dict[str, Any]] = []
        for grader in task["graders"]:
            [(kind, spec)] = grader.items()
            record: dict[str, Any] = {"kind": kind, "spec": spec}
            if kind == "result_match":
                calls = [m for m in tool_messages if m.function == spec["tool"]]
                payload = _tool_payload(calls[-1]) if calls else None
                # The last call to the graded tool is the agent's answer; if
                # it didn't succeed, there are no rows to grade.
                rows = (
                    payload.get("rows")
                    if payload and payload.get("status") == "succeeded"
                    else None
                )
                # "tool"/"expected" kept at the top level: the record shape
                # committed runs already use.
                record.update(
                    {
                        "tool": spec["tool"],
                        "expected": spec["expected"],
                        "input": {"graded_rows": rows, "graded_payload": payload},
                    }
                )
            elif kind in ("answer_match", "answer_excludes"):
                record["input"] = {
                    "final_answer": state.output.completion if state.output else None
                }
            else:
                record["input"] = {
                    "tools_called": [m.function for m in tool_messages if m.function]
                }
            record["strict"], record["lenient"] = grade_one(kind, spec, record["input"])
            grader_results.append(record)
        strict_all = all(r["strict"] for r in grader_results)
        lenient_all = all(r["lenient"] for r in grader_results)
        return Score(
            value={"strict": float(strict_all), "lenient": float(lenient_all)},
            metadata={
                "grader_version": GRADER_VERSION,
                "graders": grader_results,
                "infra_error": _infra_error(tool_messages, infra_error_patterns),
            },
        )

    return score


def build_task(
    suite: dict[str, Any],
    target: dict[str, Any],
    agent: dict[str, Any],
    auth_token: str,
    tools_override: list[Any] | None = None,
) -> Task:
    """One Inspect sample per suite task. The auth token goes only into the
    MCP connection's headers; it never enters a sample, a score or a
    prompt. `tools_override` replaces the MCP server with local tools, so
    tests can run the whole pipeline offline against Inspect's mock model."""
    tools: Any
    if tools_override is not None:
        tools = tools_override
    else:
        if target.get("transport") == "stdio":
            # A fresh server, on a fresh copy of the fixture, per trial.
            server = mcp_server_stdio(
                name=target["name"],
                command=sys.executable,
                args=["-m", "agent_eval.fs_server", target["fixture"]],
            )
        else:
            server = mcp_server_http(
                name=target["name"],
                url=target["url"],
                headers={"Authorization": f"Bearer {auth_token}"},
            )
        tools = [mcp_tools(server, tools=agent.get("tool_allowlist") or "all")]
    dataset = [
        Sample(
            id=task["id"],
            input=task["prompt"],
            metadata={"task": task, "task_hash": task_hash(task)},
        )
        for task in suite["tasks"]
    ]
    return Task(
        dataset=dataset,
        solver=react(prompt=agent["system_prompt"], tools=tools),
        scorer=suite_scorer(target["infra_error_patterns"]),
        message_limit=agent["message_limit"],
        time_limit=agent["time_limit"],
        token_limit=agent["token_limit"],
    )
