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
"inconclusive": exit 0, with the tasks that dropped named."""

import random
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_eval.grading import grade_one
from agent_eval.records import RecordError, Run, load_run

EXIT_OK, EXIT_REGRESSION, EXIT_UNDECIDED = 0, 1, 2

BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261023  # fixed: the same two runs always get the same verdict
INCONCLUSIVE_DROP = -0.05
BROKEN_MIN_TRIALS = 5
WARN_INCREASE = 0.25  # median cost or latency per trial up by 25%: a warning, not a gate

# Provenance fields worth naming when they differ: any of them can explain
# a change in scores without the agent itself changing.
_PROVENANCE_FIELDS = [
    "server_name",
    "server_version",
    "healthz_version",
    "tool_list_sha256",
    "models_reported",
    "data_fingerprint",
    "harness_git",
    "inspect_ai_version",
]


@dataclass
class Comparison:
    exit_code: int
    verdict: str
    reasons: list[str] = field(default_factory=lambda: list[str]())
    differences: list[str] = field(default_factory=lambda: list[str]())
    regrade_mismatches: list[str] = field(default_factory=lambda: list[str]())
    per_task: dict[str, tuple[float, float]] = field(default_factory=lambda: dict[str, tuple[float, float]]())
    interval: tuple[float, float] | None = None
    point: float | None = None
    broken: list[str] = field(default_factory=lambda: list[str]())
    dropped: list[str] = field(default_factory=lambda: list[str]())
    warnings: list[str] = field(default_factory=lambda: list[str]())
    missing: list[str] = field(default_factory=lambda: list[str]())


def regrade(trial: dict[str, Any]) -> tuple[bool, bool]:
    """Recomputes (strict, lenient) from the stored grader inputs with the
    current grader code, so a grader fix can't make an old baseline mean
    something different. Error trials stay errors.

    A trial that stopped on a limit (turns, time, tokens, cost) fails
    whatever its rows say, the same rule the export applies (Phase 3). The
    first live proof run caught regrading without it: a trial that ran the
    right query and then hit the message cap was regraded as a pass."""
    if trial.get("stop_reason") not in (None, "completed"):
        return False, False
    results = [
        grade_one(g["kind"], g.get("spec") or {"tool": g.get("tool"), "expected": g.get("expected")},
                  g["input"])
        for g in trial["graders"]
    ]
    return all(r[0] for r in results), all(r[1] for r in results)


def task_counts(run: Run) -> dict[str, tuple[int, int]]:
    """(strict passes, graded trials) per task, regraded with the current
    graders. Errored trials say nothing about the agent and are left out."""
    by_task: dict[str, list[bool]] = {}
    for trial in run.trials:
        if trial["outcome"] == "error":
            continue
        strict, _ = regrade(trial)
        by_task.setdefault(trial["task_id"], []).append(strict)
    return {task: (sum(v), len(v)) for task, v in by_task.items() if v}


def bootstrap_interval(
    base: dict[str, tuple[int, int]],
    cand: dict[str, tuple[int, int]],
    tasks: list[str],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    level: float = 0.95,
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
    tail = (1 - level) / 2
    low = means[int(tail * resamples)]
    high = means[min(resamples - 1, int((1 - tail) * resamples))]
    return low, high, point


def broken_tasks(
    base: dict[str, tuple[int, int]], cand: dict[str, tuple[int, int]], tasks: list[str]
) -> list[str]:
    return [
        t for t in tasks
        if base[t][1] >= BROKEN_MIN_TRIALS and cand[t][1] >= BROKEN_MIN_TRIALS
        and base[t][0] == base[t][1] and cand[t][0] == 0
    ]


def _median_per_trial(run: Run, key: str) -> float | None:
    values = [t[key] for t in run.trials if t.get(key) is not None]
    return statistics.median(values) if values else None


def _warnings(baseline: Run, candidate: Run) -> list[str]:
    out: list[str] = []
    for key, label in (("cost_usd", "cost"), ("seconds", "latency")):
        b, c = _median_per_trial(baseline, key), _median_per_trial(candidate, key)
        if b and c and (c - b) / b >= WARN_INCREASE:
            out.append(f"median {label} per trial up {100 * (c - b) / b:.0f}% ({b:.4g} -> {c:.4g})")
    return out


def _differences(baseline: Run, candidate: Run) -> list[str]:
    out: list[str] = []
    for name in _PROVENANCE_FIELDS:
        b, c = baseline.meta["provenance"].get(name), candidate.meta["provenance"].get(name)
        if b != c:
            out.append(f"{name}: {b!r} -> {c!r}")
    for name in ["model", "model_args", "system_prompt_sha256", "tool_allowlist", "limits"]:
        b, c = baseline.meta["agent"].get(name), candidate.meta["agent"].get(name)
        if b != c:
            out.append(f"agent.{name}: {b!r} -> {c!r}")
    return out


def compare_runs(baseline_dir: Path, candidate_dir: Path) -> Comparison:
    try:
        baseline, candidate = load_run(baseline_dir), load_run(candidate_dir)
    except RecordError as exc:
        return Comparison(EXIT_UNDECIDED, "undecided", reasons=[str(exc)])

    reasons: list[str] = []
    for label, run in (("baseline", baseline), ("candidate", candidate)):
        if run.meta["status"] != "complete":
            reasons.append(f"{label} run is {run.meta['status']}, not complete")
    b_hashes = baseline.meta["suite"]["task_hashes"]
    c_hashes = candidate.meta["suite"]["task_hashes"]
    changed = sorted(t for t in set(b_hashes) & set(c_hashes) if b_hashes[t] != c_hashes[t])
    if changed:
        reasons.append(f"tasks changed between runs (different hashes): {changed}")
    b_fp = baseline.meta["provenance"].get("data_fingerprint")
    c_fp = candidate.meta["provenance"].get("data_fingerprint")
    if b_fp != c_fp:
        reasons.append("data fingerprints differ: the runs were graded against different data")

    regrade_mismatches = [
        f"{run_label} {t['task_id']}#{t['attempt']}: stored {t['strict']}/{t['lenient']}, "
        f"regraded {regrade(t)[0]}/{regrade(t)[1]}"
        for run_label, run in (("baseline", baseline), ("candidate", candidate))
        for t in run.trials
        if t["outcome"] != "error" and (t["strict"], t["lenient"]) != regrade(t)
    ]
    differences = _differences(baseline, candidate)
    if reasons:
        return Comparison(
            EXIT_UNDECIDED, "undecided", reasons, differences, regrade_mismatches
        )

    base, cand = task_counts(baseline), task_counts(candidate)
    shared = sorted(set(base) & set(cand))
    missing = sorted(set(base) ^ set(cand))
    per_task = {t: (base[t][0] / base[t][1], cand[t][0] / cand[t][1]) for t in shared}
    if not shared:
        return Comparison(EXIT_UNDECIDED, "undecided", ["no tasks in common"], differences)

    low, high, point = bootstrap_interval(base, cand, shared)
    broken = broken_tasks(base, cand, shared)
    dropped = [t for t in shared if per_task[t][1] < per_task[t][0]]
    warnings = _warnings(baseline, candidate)

    def result(exit_code: int, verdict: str, why: list[str]) -> Comparison:
        return Comparison(
            exit_code, verdict, why, differences, regrade_mismatches, per_task,
            interval=(low, high), point=point, broken=broken, dropped=dropped,
            warnings=warnings, missing=missing,
        )

    why: list[str] = []
    if high < 0:
        why.append(
            f"suite pass rate dropped {-point:.1%} (95% interval {low:+.1%} to {high:+.1%}, "
            "entirely below 0)"
        )
    if broken:
        why.append(f"task(s) went from every attempt passing to none: {broken}")
    if why:
        return result(EXIT_REGRESSION, "regression", why)
    if point <= INCONCLUSIVE_DROP:
        return result(EXIT_OK, "inconclusive", [
            f"suite pass rate down {-point:.1%}, but the 95% interval ({low:+.1%} to "
            f"{high:+.1%}) includes no change; rerun the dropped tasks to confirm"
        ])
    return result(EXIT_OK, "no regression", [])

