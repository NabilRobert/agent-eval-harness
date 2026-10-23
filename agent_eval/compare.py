"""Compares a candidate run with a baseline from the files alone (Phase 4).
Pure: no Inspect, no network, no key, so CI can run it.

Slice A scope: the integrity and comparability checks, regrading, the
provenance diff, and per-task pass rates. The statistical gate (ADR-001)
lands in slice D; until then any change in a pass rate is reported as
"undecided" (exit 2) rather than guessed at."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_eval.grading import grade_result_match
from agent_eval.records import RecordError, Run, load_run

EXIT_OK, EXIT_REGRESSION, EXIT_UNDECIDED = 0, 1, 2

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


def regrade(trial: dict[str, Any]) -> tuple[bool, bool]:
    """Recomputes (strict, lenient) from the stored grader inputs with the
    current grader code, so a grader fix can't make an old baseline mean
    something different. Error trials stay errors."""
    results = [
        grade_result_match(g["input"]["graded_rows"], g["expected"])
        for g in trial["graders"]
        if g["kind"] == "result_match"
    ]
    return all(r[0] for r in results), all(r[1] for r in results)


def _pass_rates(run: Run) -> dict[str, float]:
    """Strict pass rate per task over its non-error trials."""
    by_task: dict[str, list[bool]] = {}
    for trial in run.trials:
        if trial["outcome"] == "error":
            continue
        strict, _ = regrade(trial)
        by_task.setdefault(trial["task_id"], []).append(strict)
    return {task: sum(v) / len(v) for task, v in by_task.items() if v}


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

    b_rates, c_rates = _pass_rates(baseline), _pass_rates(candidate)
    shared = sorted(set(b_rates) & set(c_rates))
    per_task = {t: (b_rates[t], c_rates[t]) for t in shared}
    if not shared:
        return Comparison(EXIT_UNDECIDED, "undecided", ["no tasks in common"], differences)
    if all(b == c for b, c in per_task.values()):
        return Comparison(EXIT_OK, "no change", [], differences, regrade_mismatches, per_task)
    return Comparison(
        EXIT_UNDECIDED,
        "undecided",
        ["pass rates differ; the statistical gate (ADR-001) arrives in slice D"],
        differences,
        regrade_mismatches,
        per_task,
    )

