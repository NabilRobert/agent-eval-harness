"""Generates a suite's expected answers by running each task's reference
SQL through the live endpoint: the same path, limits and data the agent
gets (Spike 4), so no task can expect something the agent can't reach.

Refuses, rather than writes, any task whose answer couldn't be graded
fairly: an empty, truncated or oversized result, or a "top 1" question
whose first two rows tie (two equally right answers). A task that brings
its own self-tests (`alternative_sql`, `wrong_sql`: sql-analyst-env's)
is refused unless the alternative grades right and the wrong reading
grades wrong."""

import datetime
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

import yaml

from agent_eval.grading import Row, grade_result_match
from agent_eval.mcp_client import call_json, connect
from agent_eval.preflight import fingerprint
from agent_eval.records import sha256_hex

MAX_EXPECTED_ROWS = 50
_LIMIT_1 = re.compile(r"\blimit\s+1\s*;?\s*$", re.IGNORECASE)


class ExpectedError(Exception):
    pass


Query = Callable[[str], Awaitable[dict[str, Any]]]
# Each self-test, and whether its SQL must grade right (sql-analyst-env's
# task checks C6 and C7): another way of writing the answer must match,
# and the likeliest wrong reading must not.
_SELF_TESTS = (("alternative_sql", True), ("wrong_sql", False))


async def _reference_rows(task: dict[str, Any], query: Query) -> tuple[list[Row], str | None]:
    """The reference answer's rows, or why they can't be an expected answer."""
    result = await query(task["reference_sql"])
    rows = cast(list[Row], result.get("rows") or [])
    if result.get("status") != "succeeded":
        return rows, f"{task['id']}: {result.get('status')}: {result.get('error')}"
    if result.get("truncated") or not rows or len(rows) > MAX_EXPECTED_ROWS:
        return rows, f"{task['id']}: {len(rows)} rows (truncated={result.get('truncated')})"
    return rows, None


async def _tie_problem(task: dict[str, Any], query: Query) -> str | None:
    """A "top 1" question whose first two rows tie has two right answers."""
    sql: str = task["reference_sql"]
    if not _LIMIT_1.search(sql):
        return None
    top_rows = cast(list[Row], (await query(_LIMIT_1.sub("limit 2", sql))).get("rows") or [])
    if len(top_rows) == 2 and list(top_rows[0].values())[-1] == list(top_rows[1].values())[-1]:
        return f"{task['id']}: first two rows tie: {top_rows}"
    return None


async def _self_test_problem(task: dict[str, Any], query: Query, expected: list[Row]) -> str | None:
    """Why the task's alternative or wrong SQL disagrees with its key, if it does."""
    for key, should_pass in _SELF_TESTS:
        if key not in task:
            continue
        result = await query(task[key])
        if result.get("status") != "succeeded":
            return f"{task['id']}: {key}: {result.get('status')}: {result.get('error')}"
        rows = cast(list[Row], result.get("rows") or [])
        passes, _ = grade_result_match(rows, expected, is_ordered=task.get("is_ordered", False))
        if passes != should_pass:
            want, got = ("right", "wrong") if should_pass else ("wrong", "right")
            return f"{task['id']}: {key} should grade {want} but grades {got}"
    return None


async def suite_task(
    task: dict[str, Any], query: Query, tool: str
) -> tuple[dict[str, Any] | None, str | None]:
    """(the task as the suite holds it, None), or (None, why it's refused)."""
    rows, problem = await _reference_rows(task, query)
    problem = problem or await _tie_problem(task, query)
    problem = problem or await _self_test_problem(task, query, rows)
    if problem:
        return None, problem
    spec: dict[str, Any] = {"tool": tool, "expected": rows}
    if task.get("is_ordered"):
        spec["is_ordered"] = True
    written = {key: task[key] for key in ("id", "tags", "prompt", "reference_sql")}
    return {**written, "graders": [{"result_match": spec}]}, None


async def generate(source_path: Path, target: dict[str, Any], auth_token: str) -> dict[str, Any]:
    source_text = source_path.read_text(encoding="utf-8")
    source = cast(dict[str, Any], yaml.safe_load(source_text))
    problems: list[str] = []
    tasks: list[dict[str, Any]] = []
    async with connect(target["url"], auth_token) as session:

        async def query(sql: str) -> dict[str, Any]:
            return await call_json(session, target["query_tool"], {"sql": sql})

        init = await session.initialize()
        data = await fingerprint(session, target)
        offset_rows = (await query(target["utc_offset_query"]))["rows"]
        for task in source["tasks"]:
            written, problem = await suite_task(task, query, target["query_tool"])
            if problem:
                problems.append(problem)
            if written:
                tasks.append(written)
    if problems:
        raise ExpectedError("refusing to write the suite:\n  " + "\n  ".join(problems))
    # The canary and the task file's pin, when the source has them
    # (agent_eval/analyst_env.py), are carried into the suite.
    carried = {key: source[key] for key in ("canary", "source") if key in source}
    return {
        "suite": source["suite"],
        "version": source["version"],
        "target": source["target"],
        "description": source["description"],
        **carried,
        "generated": {
            "at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "from": source_path.name,
            "source_sha256": sha256_hex(source_text),
            "server_name": init.server_info.name,
            "server_version": init.server_info.version or None,
            "data_fingerprint": data["sha256"],
            "session_utc_offset": int(float(offset_rows[0]["utc_offset_seconds"])),
        },
        "tasks": tasks,
    }


def write_suite(suite: dict[str, Any], path: Path) -> None:
    header = (
        "# GENERATED by `agent-eval generate-expected` from "
        f"{suite['generated']['from']}. Do not edit by hand.\n"
    )
    path.write_text(
        header + yaml.safe_dump(suite, sort_keys=False, width=100, allow_unicode=True),
        encoding="utf-8",
    )
