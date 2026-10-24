"""Suites (YAML) and the agent configs they run with. A suite is
validated in full before any money is spent: anything the harness can't
grade is refused up front, not discovered mid-run."""

from pathlib import Path
from typing import Any, cast

import yaml

from agent_eval.records import ordered_json, sha256_hex, task_hash

KNOWN_GRADERS = {"result_match", "answer_match", "forbidden_tools", "required_tools"}

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


def validate_suite(suite: dict[str, Any]) -> None:
    for key in ("suite", "target", "tasks"):
        if key not in suite:
            raise SuiteError(f"suite is missing {key!r}")
    if not suite["tasks"]:
        raise SuiteError("suite has no tasks")
    seen: set[str] = set()
    for task in suite["tasks"]:
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
            raise SuiteError(f"task {task_id!r} has no graders (run scripts/generate_expected.py?)")
        for grader in graders:
            if len(grader) != 1 or set(grader) - KNOWN_GRADERS:
                raise SuiteError(f"task {task_id!r}: unknown grader {sorted(grader)}")
            [(kind, spec)] = grader.items()
            if kind == "result_match":
                expected = spec.get("expected")
                if not spec.get("tool") or not isinstance(expected, list) or not all(
                    isinstance(row, dict) for row in cast(list[Any], expected)
                ):
                    raise SuiteError(f"task {task_id!r}: result_match needs a tool and a list of rows")
            elif kind == "answer_match":
                contains: Any = cast(dict[str, Any], spec).get("contains") if isinstance(spec, dict) else None
                if not contains or not all(isinstance(c, str) and c for c in cast(list[Any], contains)):
                    raise SuiteError(f"task {task_id!r}: answer_match needs non-empty 'contains'")
            elif not spec or not all(isinstance(t, str) for t in cast(list[Any], spec)):
                raise SuiteError(f"task {task_id!r}: {kind} needs a list of tool names")


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
        return (f"target data fingerprint {str(target_fingerprint)[:12]} doesn't match the "
                f"{expected[:12]} this suite's answers were generated against")
    expected_offset: int | None = generated.get("session_utc_offset")
    if expected_offset is not None and target_utc_offset != expected_offset:
        actual = "unknown" if target_utc_offset is None else f"{target_utc_offset}s"
        return (f"target database session is at UTC offset {actual}, but this suite "
                f"was generated and published at {expected_offset}s; answers to questions about "
                "dates would be graded differently")
    return None


def required_tools(suite: dict[str, Any]) -> set[str]:
    """Tools the graders read results from: an agent config may not
    withhold them, and the target must have them."""
    return {g["result_match"]["tool"] for t in suite["tasks"] for g in t["graders"]
            if "result_match" in g}
