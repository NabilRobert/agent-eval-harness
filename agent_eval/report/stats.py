"""The numbers a report and the published tables are built from: per-task
counts (attempts, graded, errors, passes, medians, cost) and the run's
headline (strict and lenient rates, pass^k, pass@k)."""

import statistics
from collections import defaultdict
from typing import Any

from agent_eval.records import Run


def median_or_none(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def per_task_stats(run: Run) -> dict[str, dict[str, Any]]:
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trial in run.trials:
        by_task[trial["task_id"]].append(trial)
    out: dict[str, dict[str, Any]] = {}
    for task_id, trials in by_task.items():
        graded = [t for t in trials if t["outcome"] != "error"]
        out[task_id] = {
            "attempts": len(trials),
            "graded": len(graded),
            "errors": len(trials) - len(graded),
            "strict": sum(1 for t in graded if t["strict"]),
            "lenient": sum(1 for t in graded if t["lenient"]),
            "median_tokens": median_or_none(
                [t["input_tokens"] + t["output_tokens"] for t in trials]
            ),
            "median_seconds": median_or_none(
                [t["seconds"] for t in trials if t["seconds"] is not None]
            ),
            "cost": None
            if any(t["cost_usd"] is None for t in trials)
            else sum(t["cost_usd"] for t in trials),
        }
    return out


def headline(run: Run) -> dict[str, Any]:
    graded = [t for t in run.trials if t["outcome"] != "error"]
    stats = per_task_stats(run)
    clean = [s for s in stats.values() if s["errors"] == 0 and s["graded"]]
    return {
        "trials": len(run.trials),
        "graded": len(graded),
        "errors": len(run.trials) - len(graded),
        "strict": sum(1 for t in graded if t["strict"]),
        "lenient": sum(1 for t in graded if t["lenient"]),
        # pass^k: the share of tasks that passed on every attempt (Yao et
        # al., tau-bench). Only tasks with no errored attempts count, since
        # an errored attempt says nothing either way.
        "pass_all_k": sum(1 for s in clean if s["strict"] == s["graded"]),
        "pass_any_k": sum(1 for s in clean if s["strict"] > 0),
        "tasks_counted": len(clean),
        "tasks": len(stats),
    }
