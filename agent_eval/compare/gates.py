"""The regression gate's statistics: pure arithmetic on per-task
(passes, trials) counts, with no run records and no I/O. Gate v1 is the
paired bootstrap, gate v2 the pooled two-proportion z-test; both share the
task-level "went from all-pass to none" rule. comparison.py decides a
verdict with them; the scripts/ simulations call them directly."""

import math
import random
import statistics


GATES = ("v1", "v2")
DEFAULT_GATE = "v2"
Z_CRITICAL = 1.96  # one-sided alpha = 0.025, the same tail as v1's 95% interval
BOOTSTRAP_RESAMPLES = 10_000
INTERVAL_LEVEL = 0.95  # both gates report a 95% interval
BOOTSTRAP_SEED = 20261023  # fixed: the same two runs always get the same verdict
INCONCLUSIVE_DROP = -0.05
BROKEN_MIN_TRIALS = 5


def bootstrap_interval(
    base: dict[str, tuple[int, int]],
    cand: dict[str, tuple[int, int]],
    tasks: list[str],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float, float]:
    """(low, high, point) for the mean per-task change in pass rate."""
    point = statistics.fmean(cand[t][0] / cand[t][1] - base[t][0] / base[t][1] for t in tasks)
    rng = random.Random(seed)
    n = len(tasks)
    means: list[float] = []
    for _ in range(resamples):
        total = 0.0
        for _ in range(n):
            task = tasks[rng.randrange(n)]
            (bs, bn), (cs, cn) = base[task], cand[task]
            total += rng.binomialvariate(cn, cs / cn) / cn - rng.binomialvariate(bn, bs / bn) / bn
        means.append(total / n)
    means.sort()
    tail = (1 - INTERVAL_LEVEL) / 2
    low = means[int(tail * resamples)]
    high = means[min(resamples - 1, int((1 - tail) * resamples))]
    return low, high, point


def pooled_test(
    base: dict[str, tuple[int, int]], cand: dict[str, tuple[int, int]], tasks: list[str]
) -> tuple[float, float, float]:
    """Gate v2: (z, low, high). z for "the candidate passes less often",
    with attempts pooled across the shared tasks; (low, high) is the 95%
    Wald interval of the change in pooled pass rate. Pooling treats the
    suite as fixed, the question a CI gate asks, and conditioning on the
    same tasks on both sides makes it conservative rather than optimistic."""
    bp, bn = sum(base[t][0] for t in tasks), sum(base[t][1] for t in tasks)
    cp, cn = sum(cand[t][0] for t in tasks), sum(cand[t][1] for t in tasks)
    rb, rc = bp / bn, cp / cn
    pooled = (bp + cp) / (bn + cn)
    se0 = math.sqrt(pooled * (1 - pooled) * (1 / bn + 1 / cn))
    z = (rb - rc) / se0 if se0 > 0 else 0.0
    se = math.sqrt(rb * (1 - rb) / bn + rc * (1 - rc) / cn)
    return z, (rc - rb) - Z_CRITICAL * se, (rc - rb) + Z_CRITICAL * se


def broken_tasks(
    base: dict[str, tuple[int, int]], cand: dict[str, tuple[int, int]], tasks: list[str]
) -> list[str]:
    return [
        t
        for t in tasks
        if base[t][1] >= BROKEN_MIN_TRIALS
        and cand[t][1] >= BROKEN_MIN_TRIALS
        and base[t][0] == base[t][1]
        and cand[t][0] == 0
    ]
