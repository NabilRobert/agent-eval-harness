"""Compares a candidate run with a baseline from the files alone (Phase 4).
Pure: no Inspect, no network, no key, so CI can run it.

Order: integrity and comparability checks (exit 2 if the runs can't be
compared), regrading both runs with the current graders, the provenance
diff, then the regression gate (ADR-001):

1. **Suite level.** A paired bootstrap of the mean per-task change in
   strict pass rate (candidate − baseline): resample tasks with
   replacement, then each drawn task's trials with replacement. Resampling
   n Bernoulli trials with replacement is a Binomial(n, observed rate)
   draw, so that's what's drawn. 10,000 resamples, fixed seed, 95%
   percentile interval. Regression if the whole interval is below 0.
2. **Task level.** Any task that went from all-pass to zero-pass, with at
   least 5 graded trials on each side. (Tightened from "≤1/5" by Spike 5,
   whose false-alarm rate was 5–11%.)

A drop of 5 points or more whose interval still crosses 0 is
"inconclusive": exit 0, with the tasks that dropped named.

Two gates (ADR-001, amended 2026-10-24):
- **v1**, the bootstrap above: every comparison published before the
  amendment was pre-registered with it, and stays pinned to it.
- **v2**, the default for new comparisons: a pooled two-proportion z-test
  on strict passes (one-sided, flag at z > 1.96) plus the same task rule.
  In simulation it was as safe as v1 and caught more on every suite
  (scripts/compare_rules.py), and it's a closed-form test: no seed.
`compare` reports both verdicts; the exit code follows the chosen gate.

gates.py holds the statistics; comparison.py loads, checks and decides.
Everything other modules and the scripts use is importable from here."""

from agent_eval.compare.comparison import (
    EXIT_OK,
    EXIT_REGRESSION,
    EXIT_UNDECIDED,
    Comparison,
    compare_runs,
    regrade,
    task_counts,
)
from agent_eval.compare.gates import (
    DEFAULT_GATE,
    GATES,
    INCONCLUSIVE_DROP,
    Z_CRITICAL,
    bootstrap_interval,
    broken_tasks,
    pooled_test,
)

__all__ = [
    "DEFAULT_GATE",
    "EXIT_OK",
    "EXIT_REGRESSION",
    "EXIT_UNDECIDED",
    "GATES",
    "INCONCLUSIVE_DROP",
    "Z_CRITICAL",
    "Comparison",
    "bootstrap_interval",
    "broken_tasks",
    "compare_runs",
    "pooled_test",
    "regrade",
    "task_counts",
]
