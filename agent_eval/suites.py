"""Suites and agent configs. Slice A has one hard-coded task; slice B
replaces this with YAML suites and expected answers generated through the
endpoint."""

from typing import Any

from agent_eval.records import task_hash

# MCP-backbone's live endpoint. The key is named, never stored: it's read
# from the environment variable at run time (Phase 3: no secrets in records).
MCP_BACKBONE_TARGET: dict[str, Any] = {
    "name": "mcp-backbone",
    "url": "https://mcp.my.id/mcp/",
    "healthz_url": "https://mcp.my.id/healthz",
    "auth_env": "MCP_BACKBONE_EVAL_KEY",
    # A tool result containing one of these is the server refusing for its
    # own reasons, not the agent being wrong: the trial becomes an `error`,
    # never a `fail` (ADR-007). MCP-backbone's wording: "rate limit of N
    # requests per window exceeded".
    "infra_error_patterns": ["rate limit of"],
}

SKELETON_SUITE: dict[str, Any] = {
    "suite": "pagila-skeleton",
    "target": "mcp-backbone",
    "tasks": [
        {
            "id": "easy-01",
            "tags": ["easy"],
            "prompt": "How many films are in the database?",
            # Generated through the live endpoint in Spike 4 (reference SQL
            # `select count(*) from film`).
            "graders": [{"result_match": {"tool": "run_query", "expected": [{"count": 1000}]}}],
        }
    ],
}

# The instructions MCP-backbone's own benchmark used, so results stay
# comparable with its published runs.
PAGILA_SYSTEM_PROMPT = (
    "You answer questions about a database by using the available tools: "
    "list_tables, describe_table, sample_rows, and run_query. Always "
    "explore the schema before writing SQL. Call run_query exactly once "
    "with your final answer query."
)

KNOWN_GRADERS = {"result_match"}


def validate_suite(suite: dict[str, Any]) -> None:
    """Refuses a suite the harness can't grade, before any money is spent."""
    seen: set[str] = set()
    for task in suite["tasks"]:
        if task["id"] in seen:
            raise ValueError(f"duplicate task id {task['id']!r}")
        seen.add(task["id"])
        for grader in task["graders"]:
            unknown = set(grader) - KNOWN_GRADERS
            if unknown or len(grader) != 1:
                raise ValueError(f"task {task['id']!r}: unknown grader {sorted(grader)}")


def suite_task_hashes(suite: dict[str, Any]) -> dict[str, str]:
    return {task["id"]: task_hash(task) for task in suite["tasks"]}
