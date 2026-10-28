import copy
from pathlib import Path
from typing import Any

import pytest

from agent_eval.records import task_hash, write_run

TASK: dict[str, Any] = {
    "id": "easy-01",
    "prompt": "How many films are in the database?",
    "graders": [{"result_match": {"tool": "run_query", "expected": [{"count": 1000}]}}],
}


def make_trial(
    attempt: int, rows: list[dict[str, Any]] | None, outcome: str | None = None
) -> dict[str, Any]:
    from agent_eval.grading import grade_result_match

    strict, lenient = grade_result_match(rows, [{"count": 1000}])
    return {
        "task_id": TASK["id"],
        "task_hash": task_hash(TASK),
        "attempt": attempt,
        "outcome": outcome or ("pass" if strict else "fail"),
        "strict": strict,
        "lenient": lenient,
        "grader_version": 1,
        "graders": [
            {
                "kind": "result_match",
                "tool": "run_query",
                "expected": [{"count": 1000}],
                "input": {"graded_rows": rows},
                "strict": strict,
                "lenient": lenient,
            }
        ],
    }


def make_meta(**overrides: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "run_id": "r",
        "status": "complete",
        "suite": {"name": "s", "task_hashes": {TASK["id"]: task_hash(TASK)}},
        "agent": {
            "model": "m",
            "model_args": {},
            "system_prompt_sha256": "p",
            "tool_allowlist": None,
            "limits": {},
        },
        "provenance": {"server_version": "v1", "data_fingerprint": None, "models_reported": ["m"]},
    }
    for key, value in overrides.items():
        meta[key] = value
    return meta


@pytest.fixture
def run_factory(tmp_path: Path):  # pyright: ignore[reportUnknownParameterType]
    counter = {"n": 0}

    def make(trials: list[dict[str, Any]], **meta_overrides: Any) -> Path:
        counter["n"] += 1
        run_dir = tmp_path / f"run{counter['n']}"
        write_run(run_dir, make_meta(**meta_overrides), copy.deepcopy(trials))
        return run_dir

    return make
