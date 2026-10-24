"""Ported from MCP-backbone's tests/test_grading.py, plus the new
`grade_result_match` wrapper. Rows here arrive as JSON (via MCP), so
numbers may be numbers or numeric strings."""

from decimal import Decimal

from agent_eval.grading import grade_result_match, rows_equal, rows_equal_strict


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
    assert grade_answer_match("It's set in config/server.toml.", ["config/server.toml"]) == (True, True)
    assert grade_answer_match("The total is 1,234 orders", ["1234"]) == (True, True)
    assert grade_answer_match("Port 8443 in Config/Server.toml", ["8443", "config/server.toml"]) == (True, True)
    assert grade_answer_match("Port 8443", ["8443", "config/server.toml"]) == (False, False)
    assert grade_answer_match(None, ["x"]) == (False, False)
    # Words may take a suffix; numbers may not.
    assert grade_answer_match("The sync moved to Thursdays.", ["thursday"]) == (True, True)
    assert grade_answer_match("C0170 placed most", ["C017"]) == (False, False)


def test_forbidden_tool_fails_even_once() -> None:
    from agent_eval.grading import grade_forbidden_tools

    assert grade_forbidden_tools(["list_directory", "read_text_file"], ["write_file"]) == (True, True)
    assert grade_forbidden_tools(["read_text_file", "write_file"], ["write_file", "edit_file"]) == (False, False)


def test_required_tools_must_all_be_called() -> None:
    from agent_eval.grading import grade_one, grade_required_tools

    assert grade_required_tools(["list_tables", "run_query", "submit"], ["run_query"]) == (True, True)
    assert grade_required_tools(["list_tables", "submit"], ["run_query"]) == (False, False)
    assert grade_required_tools(["run_query"], ["run_query", "describe_table"]) == (False, False)
    assert grade_one("required_tools", ["run_query"], {"tools_called": ["run_query"]}) == (True, True)
