"""`agent-eval plan-pairs` (ADR-015): how many conversation pairs gate v3
needs, planned before a run, under the thesis pilot's model of a pair."""

import math

import pytest

from agent_eval.cli import main
from agent_eval.compare import EXIT_OK, EXIT_UNDECIDED
from agent_eval.pair_planning import (
    PairModel,
    detection_rate,
    difference_probabilities,
    pairs_needed,
)

TARGET_POWER = 0.80


def test_pairs_that_share_all_difficulty_differ_only_where_the_drop_bites() -> None:
    model = PairModel(baseline=0.8, drop=0.1, grader_error=0.0, pair_correlation=1.0)
    down, up = difference_probabilities(model)
    assert math.isclose(down, 0.1) and up == 0.0


def test_with_no_drop_the_gate_flags_about_its_one_sided_alpha() -> None:
    model = PairModel(baseline=0.8, drop=0.0, grader_error=0.1, pair_correlation=0.5)
    assert 0.015 < detection_rate(model, 400) < 0.035


def test_planned_pairs_agree_with_the_thesis_power_simulation() -> None:
    """power_simulation.py (S2 Proposals/pilot) reports 206 pairs for a
    10-point drop with a perfect judge and 404 with a 10% judge error.
    Its search steps by x1.25, so the true minimum lies after its previous
    grid point (164 and 324)."""
    perfect = PairModel(baseline=0.8, drop=0.1, grader_error=0.0, pair_correlation=0.5)
    noisy = PairModel(baseline=0.8, drop=0.1, grader_error=0.1, pair_correlation=0.5)
    assert 164 < (pairs_needed(perfect, TARGET_POWER) or 0) <= 210
    assert 324 < (pairs_needed(noisy, TARGET_POWER) or 0) <= 410


def test_a_drop_the_gate_cant_resolve_within_the_cap_has_no_plan() -> None:
    model = PairModel(baseline=0.8, drop=0.0, grader_error=0.0, pair_correlation=0.5)
    assert pairs_needed(model, TARGET_POWER) is None


def test_plan_pairs_prints_the_pairs_needed(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["plan-pairs", "--baseline", "0.8", "--drop", "0.3"]) == EXIT_OK
    assert "pairs needed:" in capsys.readouterr().out


def test_plan_pairs_refuses_a_drop_larger_than_the_baseline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The message, not just exit 2: the crash safety net in `main` exits 2 too.
    assert main(["plan-pairs", "--baseline", "0.2", "--drop", "0.3"]) == EXIT_UNDECIDED
    assert "--drop must be between 0 and --baseline" in capsys.readouterr().err
