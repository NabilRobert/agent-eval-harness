"""Refusals: how often MCP-backbone refused the agent's queries, and why
(MCP-backbone's accuracy-benchmark-plan.md, D5). Read from `run_query`'s
structured result, so the reasons follow MCP-backbone's exact messages."""

from typing import Any

import pytest

from agent_eval.refusals import count_refusals, refusal_reason


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ({"status": "rejected", "error": "estimated cost 9001.0 exceeds threshold 5000"}, "cost"),
        ({"status": "timed_out", "error": "statement timeout exceeded"}, "timeout"),
        ({"status": "rejected", "error": "only a single SELECT statement is allowed"}, "validator"),
        ({"status": "rejected", "error": "could not parse SQL: syntax error at 'form'"}, "parse"),
    ],
)
def test_a_refused_query_is_put_down_to_its_reason(query: dict[str, Any], reason: str) -> None:
    assert refusal_reason(query) == reason


@pytest.mark.parametrize(
    "query",
    [
        {"status": "succeeded", "error": None},
        {"status": "errored", "error": "target database unreachable"},
        {"status": None, "error": None},  # the tool's result wasn't JSON
    ],
)
def test_a_query_the_server_didnt_refuse_has_no_reason(query: dict[str, Any]) -> None:
    assert refusal_reason(query) is None


def test_a_rate_limit_is_an_infra_error_not_a_refusal() -> None:
    query = {"status": "rejected", "error": "rate limit of 5 requests per window exceeded"}
    assert refusal_reason(query) is None


def _trial(task_id: str, statuses: list[tuple[str, str | None]], outcome: str = "fail") -> Any:
    queries = [{"status": status, "error": error} for status, error in statuses]
    return {"task_id": task_id, "outcome": outcome, "queries": queries}


WRITE = ("rejected", "only a single SELECT statement is allowed")
OK = ("succeeded", None)
TYPO = ("rejected", "could not parse SQL: syntax error")


def test_refusals_are_counted_per_question_and_per_query() -> None:
    counts = count_refusals([_trial("a", [WRITE, WRITE, OK]), _trial("b", [OK])])
    assert counts is not None
    assert (counts.trials_refused, counts.trials) == (1, 2)
    assert (counts.refused, counts.queries) == (2, 4)
    assert counts.by_reason == {"validator": 2, "cost": 0, "timeout": 0}


def test_unparsable_sql_is_counted_apart_from_the_refusals() -> None:
    """The agent's syntax, not the server refusing a query it understood."""
    counts = count_refusals([_trial("a", [TYPO, OK])])
    assert counts is not None
    assert (counts.trials_refused, counts.refused, counts.unparsed) == (0, 0, 1)


def test_errored_trials_are_left_out_of_the_refusal_counts() -> None:
    counts = count_refusals([_trial("a", [WRITE], outcome="error"), _trial("b", [OK])])
    assert counts is not None
    assert (counts.trials, counts.queries, counts.refused) == (1, 1, 0)


def test_runs_recorded_before_queries_were_stored_have_no_counts() -> None:
    assert count_refusals([{"task_id": "a", "outcome": "pass"}]) is None
