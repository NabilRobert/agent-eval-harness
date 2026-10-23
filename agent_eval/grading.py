"""Pure graders: given what the agent's tool returned and the expected
answer, decide pass or fail. No I/O and no Inspect imports, so CI can
regrade committed runs with no API key and no network (Phase 3).

`rows_equal` and `rows_equal_strict` are ported from MCP-backbone's
app/benchmark/grading.py, where they were built and tested against real
benchmark runs; see that file's history for why each tolerance exists."""

from decimal import Decimal, InvalidOperation
from typing import Any

# Bump whenever a grader's behaviour changes. Stored on every trial, so a
# comparison can tell grades made by different grader code apart (and
# `compare` regrades both runs with the current code anyway).
GRADER_VERSION = 1

# Absorbs an agent rounding a price-style value to 2 decimal places; a
# genuinely different answer is off by far more than half a cent.
_NUMERIC_TOLERANCE = Decimal("0.005")

Row = dict[str, Any]


def _normalize_value(value: Any) -> Any:
    """Numbers can arrive as numbers or as numeric strings (JSON has no
    Decimal), so both are turned into Decimal before comparing.
    Tradeoff: a numeric-looking string (a zip code with a leading zero)
    loses that distinction."""
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            return value
    return value


def _values_match(expected_value: Any, actual_value: Any) -> bool:
    if isinstance(expected_value, Decimal) and isinstance(actual_value, Decimal):
        return abs(expected_value - actual_value) < _NUMERIC_TOLERANCE
    return expected_value == actual_value


def _is_subsequence_match(expected_row: tuple[Any, ...], actual_row: tuple[Any, ...]) -> bool:
    """Every expected value appears in the actual row, in the same
    relative order: extra columns are tolerated, a column swap is not."""
    actual_iter = iter(actual_row)
    for expected_value in expected_row:
        if not any(_values_match(expected_value, actual_value) for actual_value in actual_iter):
            return False
    return True


def rows_equal(actual: list[Row], expected: list[Row]) -> bool:
    """Lenient execution accuracy: compares row values, not column names
    (an alias is a naming choice, not a wrong answer); row order and
    extra columns are tolerated, and numbers match within half a cent.
    Rows are matched greedily one to one, fine at this suite's scale."""
    actual_rows = [tuple(_normalize_value(v) for v in row.values()) for row in actual]
    expected_rows = [tuple(_normalize_value(v) for v in row.values()) for row in expected]
    if len(actual_rows) != len(expected_rows):
        return False
    unmatched_actual = list(actual_rows)
    for expected_row in expected_rows:
        match_index = next(
            (i for i, a in enumerate(unmatched_actual) if _is_subsequence_match(expected_row, a)),
            None,
        )
        if match_index is None:
            return False
        unmatched_actual.pop(match_index)
    return True


def rows_equal_strict(actual: list[Row], expected: list[Row]) -> bool:
    """Strict execution accuracy, the headline number: same columns in the
    same order, exactly equal values, rows in any order. The only
    normalisation is number-vs-numeric-string, which fixes how a value is
    represented, not whether it's right."""
    actual_rows = sorted(repr(tuple(_normalize_value(v) for v in row.values())) for row in actual)
    expected_rows = sorted(
        repr(tuple(_normalize_value(v) for v in row.values())) for row in expected
    )
    return actual_rows == expected_rows


def grade_result_match(graded_rows: list[Row] | None, expected: list[Row]) -> tuple[bool, bool]:
    """(strict, lenient) for a `result_match` grader. `graded_rows` is None
    when the agent never got a successful result from the graded tool,
    which fails both."""
    if graded_rows is None:
        return False, False
    return rows_equal_strict(graded_rows, expected), rows_equal(graded_rows, expected)
