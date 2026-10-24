"""Does the bootstrap gate beat simpler rules? (answers a reviewer's question
with data rather than the ADR's reasoning alone). No API calls.

Every rule sees the same simulated run pairs, drawn from per-task pass rates
measured in real runs, and is scored on its false-alarm rate (no change) and
its detection rate (uniform drops, and a measured uneven drop).

    uv run python scripts/compare_rules.py PAIRS RESAMPLES BASE_RUNS... [-- CAND_RUNS...]
    uv run python scripts/compare_rules.py PAIRS RESAMPLES mixed   # a flakier, assumed suite
"""

import math
import random
import sys
from collections.abc import Callable

from agent_eval.compare import bootstrap_interval, broken_tasks
from simulate_gate import measured_rates  # pyright: ignore[reportMissingImports]

K = 5
Counts = dict[str, tuple[int, int]]


def fisher_one_sided(b_pass: int, b_n: int, c_pass: int, c_n: int) -> float:
    """P(candidate this low or lower | the margins), the one-sided Fisher
    exact test for "the candidate passes less often"."""
    total_pass, total = b_pass + c_pass, b_n + c_n
    denom = math.comb(total, c_n)
    return sum(math.comb(total_pass, k) * math.comb(total - total_pass, c_n - k)
               for k in range(max(0, c_n - (total - total_pass)), c_pass + 1)) / denom


def pooled_z_flag(base: Counts, cand: Counts, z_crit: float = 1.96) -> bool:
    """Two-proportion z-test on pooled counts: treats 200 attempts as 200
    independent trials, ignoring that attempts cluster within tasks."""
    bp, bn = sum(v[0] for v in base.values()), sum(v[1] for v in base.values())
    cp, cn = sum(v[0] for v in cand.values()), sum(v[1] for v in cand.values())
    p = (bp + cp) / (bn + cn)
    if p in (0.0, 1.0):
        return False
    se = math.sqrt(p * (1 - p) * (1 / bn + 1 / cn))
    return (bp / bn - cp / cn) / se > z_crit


def drop(base: Counts, cand: Counts) -> float:
    return sum(base[t][0] / base[t][1] - cand[t][0] / cand[t][1] for t in base) / len(base)


def within_task_interval(base: Counts, cand: Counts, resamples: int, seed: int) -> float:
    """Upper 97.5% bound of the mean per-task change, resampling only each
    task's attempts, not the tasks: inference about *this* suite rather
    than about tasks like these."""
    rng = random.Random(seed)
    tasks = sorted(base)
    means = sorted(
        sum(rng.binomialvariate(cand[t][1], cand[t][0] / cand[t][1]) / cand[t][1]
            - rng.binomialvariate(base[t][1], base[t][0] / base[t][1]) / base[t][1] for t in tasks) / len(tasks)
        for _ in range(resamples))
    return means[min(resamples - 1, int(0.975 * resamples))]


def rules(resamples: int) -> dict[str, Callable[[Counts, Counts, int], bool]]:
    def shipped(b: Counts, c: Counts, seed: int) -> bool:
        tasks = sorted(b)
        _, high, _ = bootstrap_interval(b, c, tasks, resamples=resamples, seed=seed)
        return high < 0 or bool(broken_tasks(b, c, tasks))

    def fisher_any(alpha: float) -> Callable[[Counts, Counts, int], bool]:
        return lambda b, c, _s: any(fisher_one_sided(*b[t], *c[t]) < alpha for t in b)

    return {
        "shipped gate (bootstrap + task rule)": shipped,
        "within-task bootstrap (fixed suite) + task rule": lambda b, c, s: (
            within_task_interval(b, c, resamples, s) < 0 or bool(broken_tasks(b, c, sorted(b)))),
        "fixed threshold: drop >= 5 pts": lambda b, c, _s: drop(b, c) >= 0.05,
        "fixed threshold: drop >= 10 pts": lambda b, c, _s: drop(b, c) >= 0.10,
        "pooled two-proportion z-test": lambda b, c, _s: pooled_z_flag(b, c),
        "per-task Fisher, any task p<0.05": fisher_any(0.05),
        "per-task Fisher, Bonferroni": lambda b, c, s: fisher_any(0.05 / len(b))(b, c, s),
    }


def draw(rng: random.Random, rates: dict[str, float]) -> Counts:
    return {t: (rng.binomialvariate(K, p), K) for t, p in rates.items()}


def main() -> None:
    pairs, resamples = int(sys.argv[1]), int(sys.argv[2])
    rest = sys.argv[3:]
    base_dirs, cand_dirs = (rest[:rest.index("--")], rest[rest.index("--") + 1:]) if "--" in rest else (rest, [])
    if base_dirs == ["mixed"]:
        # ADR-001's assumed flakier suite: 30 tasks from 30% to 100%.
        base_rates = {f"t{i:02d}": 0.3 + 0.7 * i / 29 for i in range(30)}
    else:
        base_rates = {f"t{i:02d}": p for i, p in enumerate(measured_rates(base_dirs))}
    cases: dict[str, dict[str, float]] = {"no change (false alarm)": base_rates}
    for d in (0.03, 0.05, 0.10, 0.15):
        cases[f"uniform drop {d:.0%}"] = {t: max(0.0, p - d) for t, p in base_rates.items()}
    if cand_dirs:
        cand = {f"t{i:02d}": p for i, p in enumerate(measured_rates(cand_dirs))}
        mean = sum(base_rates[t] - cand[t] for t in base_rates) / len(base_rates)
        cases[f"measured uneven drop ({mean:.1%})"] = cand
    rule_set = rules(resamples)
    print(f"{len(base_rates)} tasks x {K} attempts, {pairs} simulated pairs per case, base {base_dirs}")
    header = "| Rule | " + " | ".join(cases) + " |"
    print(header)
    print("|" + "---|" * (len(cases) + 1))
    rng = random.Random(3)
    samples = {name: [(draw(rng, base_rates), draw(rng, rates)) for _ in range(pairs)]
               for name, rates in cases.items()}
    for rule_name, rule in rule_set.items():
        cells = [f"{sum(rule(b, c, i) for i, (b, c) in enumerate(samples[name])) / pairs:.1%}"
                 for name in cases]
        print(f"| {rule_name} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
