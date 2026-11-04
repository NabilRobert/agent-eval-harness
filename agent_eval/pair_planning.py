"""Plans how many conversation pairs gate v3 needs, before any run is spent
(ADR-015). `agent-eval plan-pairs` calls it.

The model of a pair is the thesis pilot's (`power_simulation.py` in
Arthur's S2 Proposals/pilot):
- **Shared difficulty:** with probability `pair_correlation`, both agents
  face the scenario's shared difficulty, so the candidate fails wherever
  the baseline does. Otherwise their outcomes are independent. For an
  A/A pair, this is the correlation of the two arms' outcomes, so the
  pilot's healthy-twice run measures it.
- **Grader noise:** the grader flips each verdict with probability
  `grader_error`. It's 0 for a stop marker, and a judge's measured error
  rate otherwise.

From that model each pair's difference (candidate − baseline) has an
exact distribution over -1, 0 and +1, so a simulated run is two binomial
draws, not a loop over conversations. The decision uses the normal
approximation of gate v3's bootstrap interval. With one attempt per
scenario the two agree (tests/test_paired_gate.py checks it), and
simulating the bootstrap itself would take minutes per plan."""

import itertools
import math
import random
from dataclasses import dataclass

from agent_eval.compare.gates import Z_CRITICAL

SIMULATIONS = 4_000  # simulated runs per pair count: power within about +/- 1.3 points
PLANNING_SEED = 20261104  # fixed, so the same question always gets the same plan
PAIR_STEP = 10  # plans are in tens of pairs
MAX_PAIRS = 20_000  # past this, report that no plan was found


@dataclass(frozen=True)
class PairModel:
    baseline: float  # the healthy agent's pass rate
    drop: float  # how much lower the candidate's true pass rate is
    grader_error: float
    pair_correlation: float


def difference_probabilities(model: PairModel) -> tuple[float, float]:
    """(P(difference = -1), P(difference = +1)) for one pair."""
    p, q, rho = model.baseline, model.baseline - model.drop, model.pair_correlation
    true_outcomes = {  # (baseline passes, candidate passes) -> probability
        (1, 1): rho * q + (1 - rho) * p * q,
        (1, 0): rho * (p - q) + (1 - rho) * p * (1 - q),
        (0, 1): (1 - rho) * (1 - p) * q,
        (0, 0): rho * (1 - p) + (1 - rho) * (1 - p) * (1 - q),
    }
    e = model.grader_error
    down = up = 0.0
    flips = (0, 1)
    for ((base, cand), probability), base_flip, cand_flip in itertools.product(
        true_outcomes.items(), flips, flips
    ):
        weight = probability * (e if base_flip else 1 - e) * (e if cand_flip else 1 - e)
        seen_base, seen_cand = base ^ base_flip, cand ^ cand_flip
        if seen_cand < seen_base:
            down += weight
        elif seen_cand > seen_base:
            up += weight
    return down, up


def _gate_flags(worse: int, better: int, pairs: int) -> bool:
    """Gate v3's rule on one run: the 95% interval is entirely below 0."""
    mean = (better - worse) / pairs
    variance = ((better + worse) / pairs - mean**2) * pairs / (pairs - 1)
    return mean + Z_CRITICAL * math.sqrt(variance / pairs) < 0


def detection_rate(model: PairModel, pairs: int) -> float:
    """The share of simulated runs of `pairs` pairs that gate v3 flags."""
    down, up = difference_probabilities(model)
    rng = random.Random(PLANNING_SEED)
    flagged = 0
    for _ in range(SIMULATIONS):
        worse = rng.binomialvariate(pairs, down)
        better = rng.binomialvariate(pairs - worse, up / (1 - down)) if down < 1 else 0
        if _gate_flags(worse, better, pairs):
            flagged += 1
    return flagged / SIMULATIONS


def pairs_needed(model: PairModel, target_power: float) -> int | None:
    """The fewest pairs, in steps of PAIR_STEP, at which gate v3 flags the
    drop at least `target_power` of the time; None past MAX_PAIRS."""
    if detection_rate(model, MAX_PAIRS) < target_power:
        return None
    low, high = 1, MAX_PAIRS // PAIR_STEP  # in units of PAIR_STEP
    while low < high:
        middle = (low + high) // 2
        if detection_rate(model, middle * PAIR_STEP) >= target_power:
            high = middle
        else:
            low = middle + 1
    return low * PAIR_STEP
