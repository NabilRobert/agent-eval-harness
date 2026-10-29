"""The scripted Pagila agent: runs Pagila tasks through the harness's own
task, graders and trial export, with Inspect's mockllm deciding each step.
It always does the same three things: list_tables, then run_query with
the task's reference SQL (from suites/pagila.yaml), then submit the rows.
$0: no model is called.

It exists to drive the database path end to end for a trace (agent ->
mcp-gateway -> MCP-backbone -> Postgres; agent-observability's ADR-009),
the way scripts/gullible_agent.py drives the filesystem one. It shows
plumbing, not model behaviour. With OTEL_EXPORTER_OTLP_ENDPOINT set, each
trial sends one trace (agent_eval/tracing.py); without it, nothing is
traced.

    uv run python scripts/scripted_pagila_agent.py --target mcp-backbone-local
    MCP_GATEWAY_KEY=... uv run python scripts/scripted_pagila_agent.py --target mcp-backbone-gateway
"""

import argparse
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from inspect_ai import eval as inspect_eval  # pyright: ignore[reportUnknownVariableType]
from inspect_ai.model import (
    ChatMessage,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    get_model,
)
from inspect_ai.tool import ToolChoice, ToolInfo

from agent_eval.cli.common import TRIAL_TIME_LIMIT_S, TRIAL_TOKEN_LIMIT
from agent_eval.envfile import parse_env_text
from agent_eval.export import trial_from_sample
from agent_eval.inspect_tasks import build_task
from agent_eval.suites import PAGILA_SYSTEM_PROMPT, load_suite, suite_task_hashes
from agent_eval.targets import TARGETS
from agent_eval.tracing import tracing_if_configured
from agent_eval.version import harness_git

REPO = Path(__file__).resolve().parent.parent
MODEL = "mockllm/model"
# Three steps and their tool results, plus the prompts: well under this.
MESSAGE_LIMIT = 12
KEY_COMMAND_TIMEOUT_SECONDS = 30


MockOutputs = Callable[[list[ChatMessage], list[ToolInfo], ToolChoice, GenerateConfig], ModelOutput]


def scripted_steps(reference_sql: dict[str, str]) -> MockOutputs:
    """The mock model's next output, chosen from the conversation so far.
    `reference_sql` maps each task's prompt to its reference query."""

    def next_output(
        messages: list[ChatMessage],
        tools: list[ToolInfo],  # noqa: ARG001
        tool_choice: ToolChoice,  # noqa: ARG001
        config: GenerateConfig,  # noqa: ARG001
    ) -> ModelOutput:
        prompt = next(m.text for m in messages if isinstance(m, ChatMessageUser))
        called = [m.function for m in messages if isinstance(m, ChatMessageTool)]
        if "list_tables" not in called:
            return ModelOutput.for_tool_call(MODEL, "list_tables", {})
        if "run_query" not in called:
            return ModelOutput.for_tool_call(MODEL, "run_query", {"sql": reference_sql[prompt]})
        query_results = [
            m.text for m in messages if isinstance(m, ChatMessageTool) and m.function == "run_query"
        ]
        return ModelOutput.for_tool_call(MODEL, "submit", {"answer": query_results[-1]})

    return next_output


def target_key(target: dict[str, Any]) -> str:
    """The target's key: from its environment variable, or for the local
    reproduction stack, read from the running container."""
    if not target.get("auth_env"):
        return ""
    if target.get("auth_env_command"):
        out = subprocess.run(
            target["auth_env_command"],
            capture_output=True,
            text=True,
            timeout=KEY_COMMAND_TIMEOUT_SECONDS,
            check=True,
        ).stdout
        return parse_env_text(out).get(target["auth_env"], "")
    key = os.environ.get(target["auth_env"], "")
    if not key:
        raise SystemExit(f"error: {target['auth_env']} is not set: export it before running")
    return key


def run_scripted(
    suite: dict[str, Any],
    target: dict[str, Any],
    auth_token: str,
    tools_override: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Runs every task in `suite` once with the scripted agent and returns
    the trials, exported exactly as `agent-eval run` exports them.
    `tools_override` swaps the target's server for local tools (tests)."""
    reference_sql = {task["prompt"]: task["reference_sql"] for task in suite["tasks"]}
    agent: dict[str, Any] = {
        "model": MODEL,
        "model_args": {},
        "system_prompt": suite.get("system_prompt") or PAGILA_SYSTEM_PROMPT,
        "tool_allowlist": None,
        "message_limit": MESSAGE_LIMIT,
        "time_limit": TRIAL_TIME_LIMIT_S,
        "token_limit": TRIAL_TOKEN_LIMIT,
        "epochs": 1,
    }
    task = build_task(suite, target, agent, auth_token, tools_override)
    model = get_model(MODEL, custom_outputs=scripted_steps(reference_sql))
    with tempfile.TemporaryDirectory() as logs:
        [log] = inspect_eval(
            task, model=model, log_dir=logs, display="none", retry_on_error=0, max_samples=1
        )
        return [trial_from_sample(s, suite_task_hashes(suite)) for s in log.samples or []]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Pagila tasks with the scripted agent ($0).")
    parser.add_argument("--target", default="mcp-backbone-gateway")
    parser.add_argument("--suite", default=str(REPO / "suites" / "pagila.yaml"))
    parser.add_argument("--tasks", default="e01", help="comma-separated task ids")
    args = parser.parse_args()
    suite = load_suite(Path(args.suite), args.tasks.split(","))
    target = TARGETS[args.target]
    with tracing_if_configured(service_version=harness_git()):
        trials = run_scripted(suite, target, target_key(target))
    for trial in trials:
        tools = " > ".join(call["tool"] for call in trial["tool_calls"])
        print(f"{trial['task_id']}  {trial['outcome']}  tools {tools}")
    return 0 if all(trial["outcome"] == "pass" for trial in trials) else 1


if __name__ == "__main__":
    sys.exit(main())
