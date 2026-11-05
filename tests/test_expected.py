"""generate-expected's checks on one task, with the endpoint replaced by a
table of SQL -> result: what's refused, and what a written task holds."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from agent_eval.expected import suite_task

REFERENCE = "select count(*) from film"
ALTERNATIVE = "select count(distinct film_id) from film"
WRONG = "select count(*) from inventory"


def _ok(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"status": "succeeded", "rows": rows, "truncated": False}


def _check(task: dict[str, Any], results: dict[str, dict[str, Any]]) -> Any:
    async def query(sql: str) -> dict[str, Any]:
        return results[sql]

    return asyncio.run(suite_task(task, query, "run_query"))


TASK: dict[str, Any] = {
    "id": "e01",
    "tags": ["easy"],
    "prompt": "How many films?",
    "reference_sql": REFERENCE,
    "alternative_sql": ALTERNATIVE,
    "wrong_sql": WRONG,
}
RIGHT = {REFERENCE: _ok([{"count": 987}]), ALTERNATIVE: _ok([{"n": 987}])}


def test_a_task_whose_self_tests_hold_is_written_with_its_expected_rows() -> None:
    written, problem = _check(TASK, {**RIGHT, WRONG: _ok([{"count": 4401}])})
    assert problem is None
    assert written["graders"] == [
        {"result_match": {"tool": "run_query", "expected": [{"count": 987}]}}
    ]
    assert "alternative_sql" not in written and "wrong_sql" not in written


def test_an_alternative_that_grades_wrong_refuses_the_task() -> None:
    results = {**RIGHT, ALTERNATIVE: _ok([{"n": 986}]), WRONG: _ok([{"count": 4401}])}
    written, problem = _check(TASK, results)
    assert written is None
    assert problem == "e01: alternative_sql should grade right but grades wrong"


def test_a_wrong_reading_that_grades_right_refuses_the_task() -> None:
    written, problem = _check(TASK, {**RIGHT, WRONG: _ok([{"count": 987}])})
    assert written is None
    assert problem == "e01: wrong_sql should grade wrong but grades right"


def test_a_wrong_reading_the_server_wont_run_proves_nothing() -> None:
    rejected = {"status": "rejected", "error": "only a single SELECT statement is allowed"}
    written, problem = _check(TASK, {**RIGHT, WRONG: rejected})
    assert written is None
    assert problem is not None and "wrong_sql: rejected" in problem


def test_an_ordered_task_is_written_ordered_and_self_tested_in_order() -> None:
    rows = [{"m": "2025-01", "n": 3}, {"m": "2025-02", "n": 5}]
    task = {**TASK, "is_ordered": True}
    results = {
        REFERENCE: _ok(rows),
        ALTERNATIVE: _ok(rows),
        WRONG: _ok(rows[::-1]),  # the same rows, in the wrong order
    }
    written, problem = _check(task, results)
    assert problem is None
    assert written["graders"][0]["result_match"]["is_ordered"] is True


def test_a_task_without_self_tests_is_checked_as_before() -> None:
    task = {key: TASK[key] for key in ("id", "tags", "prompt", "reference_sql")}
    written, problem = _check(task, RIGHT)
    assert problem is None and written["id"] == "e01"


def test_generate_carries_the_canary_and_the_task_files_pin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole command's path, with the endpoint faked: what a suite
    generated from sql-analyst-env's tasks keeps."""
    from agent_eval import expected

    @asynccontextmanager
    async def fake_connect(url: str, auth_token: str) -> AsyncIterator[Any]:
        info = SimpleNamespace(server_info=SimpleNamespace(name="mcp-backbone", version="v"))

        async def initialize() -> Any:
            return info

        yield SimpleNamespace(initialize=initialize)

    async def fake_fingerprint(session: Any, target: dict[str, Any]) -> dict[str, str]:
        return {"sha256": "f" * 64}

    results = {
        **RIGHT,
        WRONG: _ok([{"count": 4401}]),
        "offset": _ok([{"utc_offset_seconds": "0"}]),
    }

    async def fake_call_json(session: Any, tool: str, arguments: dict[str, Any]) -> Any:
        return results[arguments["sql"]]

    monkeypatch.setattr(expected, "connect", fake_connect)
    monkeypatch.setattr(expected, "fingerprint", fake_fingerprint)
    monkeypatch.setattr(expected, "call_json", fake_call_json)
    source = {
        "suite": "analyst-env-public",
        "version": 1,
        "target": "analyst-env-copy-a",
        "description": "d",
        "canary": "ec2d5d8f",
        "source": {"commit": "af10678"},
        "tasks": [TASK],
    }
    source_path = tmp_path / "source.yaml"
    source_path.write_text(yaml.safe_dump(source), encoding="utf-8")
    target = {"url": "u", "query_tool": "run_query", "utc_offset_query": "offset"}
    suite = asyncio.run(expected.generate(source_path, target, "key"))
    assert suite["canary"] == "ec2d5d8f"
    assert suite["source"] == {"commit": "af10678"}
    assert [task["id"] for task in suite["tasks"]] == ["e01"]
