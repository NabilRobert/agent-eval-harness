"""Monte Carlo check of the shipped regression gate (agent_eval.compare),
re-running Spike 5 against the real code instead of a throwaway copy.
No API calls. Pass rates are *assumed* (see ADR-001); slice D reruns this
with the per-task rates measured in the A/A pair.

    uv run python scripts/simulate_gate.py [pairs] [resamples]
"""

import random
import sys

from agent_eval.compare import bootstrap_interval, broken_tasks

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


def main() -> None:
    pairs = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    resamples = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
    rng = random.Random(7)
    print(f"{pairs} simulated pairs per case, {resamples} bootstrap resamples, {K} attempts per task")
    for name, rates in SUITES.items():
        cases: dict[str, list[float]] = {"A/A (no change)": rates}
        for drop in (0.10, 0.15, 0.20):
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
