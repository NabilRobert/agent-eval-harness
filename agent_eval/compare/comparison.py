"""Compares a candidate run with a baseline from the run records: refuses
runs that can't be compared (exit 2), regrades both with the current
graders, lists what differs between them, then decides the verdict under
each gate (gates.py) and returns it as a Comparison."""

import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_eval.grading import grade_one, stored_spec
from agent_eval.records import RecordError, Run, load_run
from agent_eval.compare.gates import (
    DEFAULT_GATE,
    GATES,
    INCONCLUSIVE_DROP,
    Z_CRITICAL,
    bootstrap_interval,
    broken_tasks,
    pooled_test,
)

EXIT_OK, EXIT_REGRESSION, EXIT_UNDECIDED = 0, 1, 2
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
    "session_utc_offset",
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
    per_task: dict[str, tuple[float, float]] = field(
        default_factory=lambda: dict[str, tuple[float, float]]()
    )
    interval: tuple[float, float] | None = None
    point: float | None = None
    gate: str = DEFAULT_GATE
    gate_verdicts: dict[str, str] = field(default_factory=lambda: dict[str, str]())
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
    results = [grade_one(g["kind"], stored_spec(g), g["input"]) for g in trial["graders"]]
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
    b_target, c_target = baseline.meta.get("target"), candidate.meta.get("target")
    if b_target and c_target and b_target != c_target:
        out.append(f"target: {b_target.get('name')} -> {c_target.get('name')}")
    for name in _PROVENANCE_FIELDS:
        b, c = baseline.meta["provenance"].get(name), candidate.meta["provenance"].get(name)
        if b != c:
            out.append(f"{name}: {b!r} -> {c!r}")
    for name in ["model", "model_args", "system_prompt_sha256", "tool_allowlist", "limits"]:
        b, c = baseline.meta["agent"].get(name), candidate.meta["agent"].get(name)
        if b != c:
            out.append(f"agent.{name}: {b!r} -> {c!r}")
    return out


@dataclass(frozen=True)
class _SharedCounts:
    """What both gates decide from: per-task (passes, trials) on each side,
    the tasks both runs graded, the mean per-task change, and the tasks
    that broke."""

    base: dict[str, tuple[int, int]]
    cand: dict[str, tuple[int, int]]
    shared: list[str]
    point: float
    broken: list[str]


def _incomparable_reasons(baseline: Run, candidate: Run) -> list[str]:
    """Why the two runs can't be compared at all (exit 2), or []."""
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
    return reasons


def _regrade_mismatches(baseline: Run, candidate: Run) -> list[str]:
    """Trials whose stored grade the current graders disagree with."""
    mismatches: list[str] = []
    for label, run in (("baseline", baseline), ("candidate", candidate)):
        for trial in run.trials:
            if trial["outcome"] == "error":
                continue
            strict, lenient = regrade(trial)
            if (trial["strict"], trial["lenient"]) != (strict, lenient):
                mismatches.append(
                    f"{label} {trial['task_id']}#{trial['attempt']}: stored "
                    f"{trial['strict']}/{trial['lenient']}, regraded {strict}/{lenient}"
                )
    return mismatches


def _suite_drop(gate: str, counts: _SharedCounts) -> tuple[str | None, tuple[float, float]]:
    """The suite-level rule under `gate`: why it fired (or None), and the
    95% interval of the change."""
    drop = -counts.point
    if gate == "v1":
        low, high, _ = bootstrap_interval(counts.base, counts.cand, counts.shared)
        if high < 0:
            return (
                f"suite pass rate dropped {drop:.1%} (95% interval {low:+.1%} to "
                f"{high:+.1%}, entirely below 0)"
            ), (low, high)
        return None, (low, high)
    z, low, high = pooled_test(counts.base, counts.cand, counts.shared)
    if z > Z_CRITICAL:
        return (
            f"suite pass rate dropped {drop:.1%} (pooled z = {z:.2f} > "
            f"{Z_CRITICAL}; 95% interval {low:+.1%} to {high:+.1%})"
        ), (low, high)
    return None, (low, high)


def _decide(gate: str, counts: _SharedCounts) -> tuple[int, str, list[str], tuple[float, float]]:
    """(exit code, verdict, reasons, interval) under one gate."""
    suite_reason, (low, high) = _suite_drop(gate, counts)
    why = [suite_reason] if suite_reason else []
    if counts.broken:
        why.append(f"task(s) went from every attempt passing to none: {counts.broken}")
    if why:
        return EXIT_REGRESSION, "regression", why, (low, high)
    if counts.point <= INCONCLUSIVE_DROP:
        inconclusive = (
            f"suite pass rate down {-counts.point:.1%}, but not significant under gate {gate} "
            f"(95% interval {low:+.1%} to {high:+.1%}); rerun the dropped tasks to confirm"
        )
        return EXIT_OK, "inconclusive", [inconclusive], (low, high)
    return EXIT_OK, "no regression", [], (low, high)


def compare_runs(baseline_dir: Path, candidate_dir: Path, gate: str = DEFAULT_GATE) -> Comparison:
    if gate not in GATES:
        raise ValueError(f"unknown gate {gate!r}; one of {GATES}")
    try:
        baseline, candidate = load_run(baseline_dir), load_run(candidate_dir)
    except RecordError as exc:
        return Comparison(EXIT_UNDECIDED, "undecided", reasons=[str(exc)])

    reasons = _incomparable_reasons(baseline, candidate)
    regrade_mismatches = _regrade_mismatches(baseline, candidate)
    differences = _differences(baseline, candidate)
    if reasons:
        return Comparison(EXIT_UNDECIDED, "undecided", reasons, differences, regrade_mismatches)

    base, cand = task_counts(baseline), task_counts(candidate)
    shared = sorted(set(base) & set(cand))
    if not shared:
        return Comparison(EXIT_UNDECIDED, "undecided", ["no tasks in common"], differences)
    per_task = {t: (base[t][0] / base[t][1], cand[t][0] / cand[t][1]) for t in shared}
    point = statistics.fmean(per_task[t][1] - per_task[t][0] for t in shared)
    counts = _SharedCounts(base, cand, shared, point, broken_tasks(base, cand, shared))

    decisions = {g: _decide(g, counts) for g in GATES}
    exit_code, verdict, why, interval = decisions[gate]
    return Comparison(
        exit_code,
        verdict,
        why,
        differences,
        regrade_mismatches,
        per_task,
        interval=interval,
        point=point,
        broken=counts.broken,
        dropped=[t for t in shared if per_task[t][1] < per_task[t][0]],
        warnings=_warnings(baseline, candidate),
        missing=sorted(set(base) ^ set(cand)),
        gate=gate,
        gate_verdicts={g: d[1] for g, d in decisions.items()},
    )
