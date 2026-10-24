"""Monte Carlo check of the shipped regression gate (agent_eval.compare),
re-running Spike 5 against the real code instead of a throwaway copy.
No API calls.

    uv run python scripts/simulate_gate.py [pairs] [resamples] [run_dir ...]

With run directories, the per-task pass rates are *measured*: pooled over
those runs (e.g. the A/A pair). Without, they're the assumed suites of
ADR-001.
"""

import random
import sys
from pathlib import Path

from agent_eval.compare import bootstrap_interval, broken_tasks, task_counts
from agent_eval.records import load_run

K = 5
SUITES = {
    "mostly-easy": [0.97] * 24 + [0.8, 0.7, 0.6, 0.6, 0.5, 0.4],
    "mixed": [0.3 + 0.7 * i / 29 for i in range(30)],
}


def draw(rng: random.Random, rates: list[float]) -> dict[str, tuple[int, int]]:
    return {f"t{i:02d}": (rng.binomialvariate(K, p), K) for i, p in enumerate(rates)}


def flagged(base: dict[str, tuple[int, int]], cand: dict[str, tuple[int, int]],
            resamples: int, seed: int) -> bool:
    tasks = sorted(base)
    _, high, _ = bootstrap_interval(base, cand, tasks, resamples=resamples, seed=seed)
    return high < 0 or bool(broken_tasks(base, cand, tasks))


def measured_rates(run_dirs: list[str]) -> list[float]:
    pooled: dict[str, list[int]] = {}
    for run_dir in run_dirs:
        for task, (passes, graded) in task_counts(load_run(Path(run_dir))).items():
            p = pooled.setdefault(task, [0, 0])
            p[0] += passes
            p[1] += graded
    return [p / n for p, n in (pooled[t] for t in sorted(pooled))]


def main() -> None:
    pairs = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    resamples = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
    suites = SUITES
    if len(sys.argv) > 3:
        rates = measured_rates(sys.argv[3:])
        suites = {f"measured ({len(rates)} tasks)": rates}
        print(f"measured per-task rates from {sys.argv[3:]}: "
              f"{sum(r == 1 for r in rates)} tasks at 100%, lowest {min(rates):.0%}")
    rng = random.Random(7)
    print(f"{pairs} simulated pairs per case, {resamples} bootstrap resamples, {K} attempts per task")
    for name, rates in suites.items():
        cases: dict[str, list[float]] = {"A/A (no change)": rates}
        for drop in (0.03, 0.05, 0.10, 0.15, 0.20):
            cases[f"uniform drop {drop:.0%}"] = [max(0.0, p - drop) for p in rates]
        for label, cand_rates in cases.items():
            hits = sum(flagged(draw(rng, rates), draw(rng, cand_rates), resamples, i)
                       for i in range(pairs))
            print(f"[{name}] {label}: flagged {hits / pairs:.1%}")
        # Collapse the most reliable task: a task that rarely starts at 5/5
        # would leave this case with nothing to measure.
        best = max(range(len(rates)), key=lambda i: rates[i])
        collapsed = [0.0 if i == best else p for i, p in enumerate(rates)]
        key = f"t{best:02d}"
        hits = total = 0
        for i in range(pairs):
            base = draw(rng, rates)
            if base[key][0] == K:
                total += 1
                hits += flagged(base, draw(rng, collapsed), resamples, i)
        print(f"[{name}] task {key} (p={rates[best]:.2f}) collapses to 0: "
              f"flagged {hits}/{total} where its baseline was 5/5")


if __name__ == "__main__":
    main()
