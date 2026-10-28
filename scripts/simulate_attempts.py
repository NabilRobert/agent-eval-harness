"""What more attempts per task would buy, before spending anything (the lever
filesystem suite v2's power analysis pointed to). No API calls.

Compares attempt allocations on per-task pass rates measured in real runs,
through the shipped gate v2 (pooled z-test + task rule):
- 5 attempts everywhere (what the published runs used);
- 10 everywhere (double the cost);
- targeted: 5 on tasks the baseline passed every time, 10 on the rest.
Cost is shown as trials per run, relative to 5 everywhere.

    uv run python scripts/simulate_attempts.py PAIRS RUN_DIR... [-- CANDIDATE_RUN_DIR...]

With `-- CANDIDATE...`, a measured, uneven drop is added: the candidate's
own per-task rates (e.g. nano's), which concentrate on the harder tasks.
"""

import random
import sys

from agent_eval.compare import Z_CRITICAL, broken_tasks, pooled_test
from simulate_gate import measured_rates  # pyright: ignore[reportMissingImports]

Counts = dict[str, tuple[int, int]]


def draw(rng: random.Random, rates: dict[str, float], attempts: dict[str, int]) -> Counts:
    return {t: (rng.binomialvariate(attempts[t], p), attempts[t]) for t, p in rates.items()}


def flagged(base: Counts, cand: Counts) -> bool:
    tasks = sorted(base)
    return pooled_test(base, cand, tasks)[0] > Z_CRITICAL or bool(broken_tasks(base, cand, tasks))


def main() -> None:
    pairs, rest = int(sys.argv[1]), sys.argv[2:]
    run_dirs, cand_dirs = (
        (rest[: rest.index("--")], rest[rest.index("--") + 1 :]) if "--" in rest else (rest, [])
    )
    rates = {f"t{i:02d}": p for i, p in enumerate(measured_rates(run_dirs))}
    measured = (
        {f"t{i:02d}": p for i, p in enumerate(measured_rates(cand_dirs))} if cand_dirs else None
    )
    flaky = {t for t, p in rates.items() if p < 1.0}
    plans = {
        "5 everywhere": {t: 5 for t in rates},
        "10 everywhere": {t: 10 for t in rates},
        f"targeted (10 on the {len(flaky)} flaky tasks)": {
            t: 10 if t in flaky else 5 for t in rates
        },
    }
    base_trials = 5 * len(rates)
    rng = random.Random(5)
    cases: dict[str, float | None] = {
        "no change": 0.0,
        "-3 pts": 0.03,
        "-5 pts": 0.05,
        "-10 pts": 0.10,
    }
    if measured:
        cases["measured uneven drop"] = None
    print(
        f"{run_dirs}: {len(rates)} tasks, {len(flaky)} below 100% in the baseline; {pairs} pairs per cell"
    )
    print("| Attempts | Trials per run (cost) | " + " | ".join(cases) + " |")
    print("|---|---|" + "---|" * len(cases))
    for name, attempts in plans.items():
        trials = sum(attempts.values())
        cells: list[str] = []
        for drop in cases.values():
            cand = (
                measured
                if drop is None and measured
                else {t: max(0.0, p - (drop or 0.0)) for t, p in rates.items()}
            )
            hits = sum(
                flagged(draw(rng, rates, attempts), draw(rng, cand, attempts)) for _ in range(pairs)
            )
            cells.append(f"{hits / pairs:.1%}")
        print(f"| {name} | {trials} ({trials / base_trials:.2f}x) | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
