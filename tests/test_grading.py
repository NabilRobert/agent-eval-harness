"""Ported from MCP-backbone's tests/test_grading.py, plus the new
`grade_result_match` wrapper. Rows here arrive as JSON (via MCP), so
numbers may be numbers or numeric strings."""

from decimal import Decimal

import pytest

from agent_eval.compare import regrade
from agent_eval.grading import (
    grade_one,
    grade_result_match,
    rows_equal,
    rows_equal_strict,
    stored_spec,
)


def test_different_alias_same_value_is_equal() -> None:
    assert rows_equal([{"total": "10.50"}], [{"revenue": Decimal("10.50")}])


def test_different_row_order_same_set_is_equal() -> None:
    actual = [{"s": "a", "c": 1}, {"s": "b", "c": 2}]
    assert rows_equal(actual, list(reversed(actual)))


def test_genuinely_different_values_is_not_equal() -> None:
    assert not rows_equal([{"c": 5}], [{"c": 3}])


def test_different_row_count_is_not_equal() -> None:
    assert not rows_equal([{"c": 1}], [{"c": 1}, {"c": 2}])


def test_column_order_matters_documented_limitation() -> None:
    assert not rows_equal([{"name": "a", "price": 5}], [{"price": 5, "name": "a"}])


def test_rounding_within_half_a_cent_is_lenient_only() -> None:
    actual, expected = [{"v": "290.65"}], [{"v": "290.65125"}]
    assert rows_equal(actual, expected)
    assert not rows_equal_strict(actual, expected)


def test_extra_column_is_lenient_only() -> None:
    actual, expected = [{"country": "India", "n": 60}], [{"country": "India"}]
    assert rows_equal(actual, expected)
    assert not rows_equal_strict(actual, expected)


def test_number_vs_numeric_string_is_strictly_equal() -> None:
    assert rows_equal_strict([{"count": "1000"}], [{"count": 1000}])


def test_no_successful_result_fails_both() -> None:
    assert grade_result_match(None, [{"count": 1000}]) == (False, False)


def test_correct_result_passes_both() -> None:
    assert grade_result_match([{"film_count": 1000}], [{"count": 1000}]) == (True, True)


def test_answer_match_needs_whole_tokens() -> None:
    from agent_eval.grading import grade_answer_match

    assert grade_answer_match("There are 17 ERROR lines in total.", ["17"]) == (True, True)
    assert grade_answer_match("There are 170 ERROR lines.", ["17"]) == (False, False)
    assert grade_answer_match("Released in 2017.", ["17"]) == (False, False)
    assert grade_answer_match("It's set in config/server.toml.", ["config/server.toml"]) == (
        True,
        True,
    )
    assert grade_answer_match("The total is 1,234 orders", ["1234"]) == (True, True)
    assert grade_answer_match(
        "Port 8443 in Config/Server.toml", ["8443", "config/server.toml"]
    ) == (True, True)
    assert grade_answer_match("Port 8443", ["8443", "config/server.toml"]) == (False, False)
    assert grade_answer_match(None, ["x"]) == (False, False)
    # Words may take a suffix; numbers may not.
    assert grade_answer_match("The sync moved to Thursdays.", ["thursday"]) == (True, True)
    assert grade_answer_match("C0170 placed most", ["C017"]) == (False, False)


def test_forbidden_tool_fails_even_once() -> None:
    from agent_eval.grading import grade_forbidden_tools

    assert grade_forbidden_tools(["list_directory", "read_text_file"], ["write_file"]) == (
        True,
        True,
    )
    assert grade_forbidden_tools(["read_text_file", "write_file"], ["write_file", "edit_file"]) == (
        False,
        False,
    )


def test_required_tools_must_all_be_called() -> None:
    from agent_eval.grading import grade_one, grade_required_tools

    assert grade_required_tools(["list_tables", "run_query", "submit"], ["run_query"]) == (
        True,
        True,
    )
    assert grade_required_tools(["list_tables", "submit"], ["run_query"]) == (False, False)
    assert grade_required_tools(["run_query"], ["run_query", "describe_table"]) == (False, False)
    assert grade_one("required_tools", ["run_query"], {"tools_called": ["run_query"]}) == (
        True,
        True,
    )


def test_required_tools_alternatives_any_one_counts() -> None:
    """Juku's c03 and c04: `get_plan` or `get_progress` are both right."""
    from agent_eval.grading import grade_one, grade_required_tools

    either: list[str | list[str]] = ["submit", ["get_plan", "get_progress"]]
    assert grade_required_tools(["get_progress", "submit"], either) == (True, True)
    assert grade_required_tools(["get_plan", "submit"], either) == (True, True)
    assert grade_required_tools(["submit"], either) == (False, False)
    assert grade_required_tools(["get_plan"], either) == (False, False)
    assert grade_one("required_tools", either, {"tools_called": ["get_plan", "submit"]}) == (
        True,
        True,
    )


def test_answer_match_alternatives_any_one_counts() -> None:
    from agent_eval.grading import grade_answer_match

    date = ["2026-03-14", "March 14, 2026", "14 March 2026"]
    assert grade_answer_match("It was released on March 14, 2026.", [date]) == (True, True)
    assert grade_answer_match("Released 2026-03-14.", [date]) == (True, True)
    assert grade_answer_match("Released March 15, 2026.", [date]) == (False, False)
    # Mixed: a plain item and an alternatives item must both be present.
    assert grade_answer_match("shipping, 12 s", ["shipping", ["12", "twelve"]]) == (True, True)
    assert grade_answer_match("shipping", ["shipping", ["12", "twelve"]]) == (False, False)


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        (5.0, 5),
        ("5.00", 5),
        ("1.50", 1.5),
        ("1e3", 1000),
        ("-0.0", 0),
    ],
)
def test_strict_compares_numbers_by_value_not_by_how_they_are_written(
    actual: object, expected: object
) -> None:
    assert rows_equal_strict([{"a": actual}], [{"a": expected}])


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        (1.5, 1.51),
        (5, 50),
        ("1.000000000000000000000000000000000001", 1),
    ],
)
def test_strict_still_fails_a_different_number(actual: object, expected: object) -> None:
    assert not rows_equal_strict([{"a": actual}], [{"a": expected}])


@pytest.mark.parametrize(
    "not_a_number",
    ["NaN", "nan", "sNaN", "Infinity", "-Infinity", float("nan"), float("inf")],
)
def test_a_non_finite_value_fails_instead_of_crashing(not_a_number: object) -> None:
    assert grade_result_match([{"a": not_a_number}], [{"a": 1}]) == (False, False)


def test_nan_text_matches_the_same_text() -> None:
    assert grade_result_match([{"a": "NaN"}], [{"a": "NaN"}]) == (True, True)


@pytest.mark.parametrize("huge", ["1E+999999", "1E+9999999", "-1E+9999999", "9.9E+999999"])
def test_a_huge_number_fails_instead_of_crashing(huge: str) -> None:
    assert grade_result_match([{"a": huge}], [{"a": -1}]) == (False, False)


@pytest.mark.parametrize("kind", ["required_tools", "forbidden_tools"])
def test_an_empty_tool_list_regrades_as_it_was_graded(kind: str) -> None:
    # Reachable only by records that skip suite validation (Juku's do).
    empty_spec: list[str] = []
    inputs = {"tools_called": ["tool"]}
    grader = {"kind": kind, "spec": empty_spec, "input": inputs}
    trial = {"stop_reason": "completed", "graders": [grader]}
    assert regrade(trial) == grade_one(kind, empty_spec, inputs)


def test_a_record_from_before_specs_were_stored_uses_its_top_level_rows() -> None:
    record = {"kind": "result_match", "tool": "run_query", "expected": [{"n": 1}]}
    assert stored_spec(record) == {"tool": "run_query", "expected": [{"n": 1}]}
