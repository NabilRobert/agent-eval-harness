"""Suites (YAML) and the agent configs they run with. A suite is
validated in full before any money is spent: anything the harness can't
grade is refused up front, not discovered mid-run."""

from pathlib import Path
from typing import Any, cast

import yaml

from agent_eval.grading import GRADER_KINDS
from agent_eval.records import ordered_json, sha256_hex, task_hash


# Frozen before any published run (Phase 2): changing a frozen suite means
# a new suite version, a new hash here, and a JOURNEY.md entry saying what
# changed and why. A test fails CI if the file and the hash disagree.
FROZEN_SUITES: dict[str, str] = {
    # 2026-10-23: 30 MCP-backbone questions + 10 expert ones, expected answers
    # generated through the live endpoint against data fingerprint fa70dca8...
    "pagila": "a79b59cb863176e06d1d94197ccb4c43c3d987d57e428d0d84a2e636db2ea017",
    # 2026-10-24: 17 tasks on the synthetic acme-shop fixture (fingerprint
    # 304f7418...), built by scripts/build_filesystem_suite.py.
    "filesystem": "94ad6a86e144c2d6c15428fee4913b5b5f762d612ac7522c055cf9d27ac0f1d4",
    # 2026-10-24: v1's 17 tasks (f09 accepts other date formats) + 17 harder
    # ones on the extended acme-shop-v2 fixture, for more statistical power.
    "filesystem-v2": "4210f586d3e386afe44979f9fc31d38cbbd7f572b486d871c732ec05388f5548",
}

# The instructions MCP-backbone's own benchmark used, so results stay
# comparable with its published runs.
PAGILA_SYSTEM_PROMPT = (
    "You answer questions about a database by using the available tools: "
    "list_tables, describe_table, sample_rows, and run_query. Always "
    "explore the schema before writing SQL. Call run_query exactly once "
    "with your final answer query."
)


class SuiteError(Exception):
    """A suite that can't be run as written. Exit 2, nothing spent."""


def _contains_item_ok(item: Any) -> bool:
    """A non-empty string, or a non-empty list of non-empty strings."""
    if isinstance(item, str):
        return bool(item)
    if isinstance(item, list):
        alts = cast(list[Any], item)
        return bool(alts) and all(isinstance(a, str) and a for a in alts)
    return False


def _string_list(spec: Any, key: str) -> list[Any]:
    """`spec[key]` when spec is a mapping holding a list there, else []."""
    value: Any = cast(dict[str, Any], spec).get(key) if isinstance(spec, dict) else None
    return cast(list[Any], value) if isinstance(value, list) else []


def _result_match_problem(spec: Any) -> str | None:
    expected = spec.get("expected")
    if (
        spec.get("tool")
        and isinstance(expected, list)
        and all(isinstance(row, dict) for row in cast(list[Any], expected))
    ):
        return None
    return "result_match needs a tool and a list of rows"


def _answer_match_problem(spec: Any) -> str | None:
    items = _string_list(spec, "contains")
    if items and all(_contains_item_ok(item) for item in items):
        return None
    return "answer_match needs non-empty 'contains' (strings, or lists of alternative strings)"


def _answer_excludes_problem(spec: Any) -> str | None:
    values = _string_list(spec, "excludes")
    if values and all(isinstance(value, str) and value for value in values):
        return None
    return "answer_excludes needs non-empty 'excludes' strings"


def _tool_list_problem(kind: str, spec: Any) -> str | None:
    if spec and all(isinstance(tool, str) for tool in cast(list[Any], spec)):
        return None
    return f"{kind} needs a list of tool names"


def _grader_problem(grader: dict[str, Any]) -> str | None:
    """Why one grader entry can't be graded, or None."""
    if len(grader) != 1 or set(grader) - set(GRADER_KINDS):
        return f"unknown grader {sorted(grader)}"
    [(kind, spec)] = grader.items()
    if kind == "result_match":
        return _result_match_problem(spec)
    if kind == "answer_match":
        return _answer_match_problem(spec)
    if kind == "answer_excludes":
        return _answer_excludes_problem(spec)
    return _tool_list_problem(kind, spec)


def _validate_task(task: dict[str, Any], seen: set[str]) -> None:
    task_id = task.get("id")
    if not isinstance(task_id, str) or not task_id:
        raise SuiteError(f"task without an id: {task!r}"[:200])
    if task_id in seen:
        raise SuiteError(f"duplicate task id {task_id!r}")
    seen.add(task_id)
    if not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
        raise SuiteError(f"task {task_id!r} has no prompt")
    graders = task.get("graders")
    if not graders:
        raise SuiteError(f"task {task_id!r} has no graders (run `agent-eval generate-expected`?)")
    for grader in graders:
        problem = _grader_problem(grader)
        if problem:
            raise SuiteError(f"task {task_id!r}: {problem}")


def validate_suite(suite: dict[str, Any]) -> None:
    """SuiteError naming the first thing in the suite that can't be run or
    graded as written."""
    for key in ("suite", "target", "tasks"):
        if key not in suite:
            raise SuiteError(f"suite is missing {key!r}")
    if not suite["tasks"]:
        raise SuiteError("suite has no tasks")
    seen: set[str] = set()
    for task in suite["tasks"]:
        _validate_task(task, seen)


def load_suite(path: Path, only: list[str] | None = None) -> dict[str, Any]:
    """Loads and validates a suite; `only` picks a subset of task ids (the
    smoke suite), refusing ids that don't exist rather than silently
    running fewer tasks."""
    suite = cast(dict[str, Any], yaml.safe_load(path.read_text(encoding="utf-8")))
    validate_suite(suite)
    if only:
        by_id = {t["id"]: t for t in suite["tasks"]}
        unknown = [t for t in only if t not in by_id]
        if unknown:
            raise SuiteError(f"no such task(s) in {path.name}: {unknown}")
        suite = {**suite, "tasks": [by_id[t] for t in only]}
    return suite


def suite_task_hashes(suite: dict[str, Any]) -> dict[str, str]:
    return {task["id"]: task_hash(task) for task in suite["tasks"]}


def suite_hash(suite: dict[str, Any]) -> str:
    """The frozen-suite identity written into the methodology: every task
    hash, in order."""
    return sha256_hex(ordered_json([[t["id"], task_hash(t)] for t in suite["tasks"]]))


def data_mismatch(
    suite: dict[str, Any], target_fingerprint: str | None, target_utc_offset: int | None = None
) -> str | None:
    """Why a run must not start, or None. A suite records the fingerprint
    of the data its expected answers were generated against, and the
    database session's UTC offset; a target differing in either would score
    the same answer differently."""
    generated: dict[str, Any] = suite.get("generated") or {}
    expected: str | None = generated.get("data_fingerprint")
    if expected and target_fingerprint != expected:
        return (
            f"target data fingerprint {str(target_fingerprint)[:12]} doesn't match the "
            f"{expected[:12]} this suite's answers were generated against"
        )
    expected_offset: int | None = generated.get("session_utc_offset")
    if expected_offset is not None and target_utc_offset != expected_offset:
        actual = "unknown" if target_utc_offset is None else f"{target_utc_offset}s"
        return (
            f"target database session is at UTC offset {actual}, but this suite "
            f"was generated and published at {expected_offset}s; answers to questions about "
            "dates would be graded differently"
        )
    return None


def required_tools(suite: dict[str, Any]) -> set[str]:
    """Tools the graders read results from: an agent config may not
    withhold them, and the target must have them."""
    return {
        g["result_match"]["tool"]
        for t in suite["tasks"]
        for g in t["graders"]
        if "result_match" in g
    }
