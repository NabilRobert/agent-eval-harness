"""Gate v3 (ADR-014): pairs single conversations and decides a verdict.

Pure, like gates.py: it works on each run's regraded strict passes keyed by
(task_id, attempt), and comparison.py turns the verdict into a Comparison.
A pair is the same simulated customer (scenario and seed) met by both
agents, so a scenario's difficulty cancels out of the pair's difference."""

from agent_eval.compare.gates import INCONCLUSIVE_DROP, paired_bootstrap_interval

PairPasses = dict[tuple[str, int], bool | None]  # (task_id, attempt) -> pass; None for an error


def pair_differences(base: PairPasses, cand: PairPasses) -> tuple[dict[str, list[int]], list[str]]:
    """Candidate pass minus baseline pass for every pair both runs graded,
    grouped by task; and the "task#attempt" pairs left out because one side
    errored or doesn't have them."""
    differences: dict[str, list[int]] = {}
    unpaired: list[str] = []
    for task_id, attempt in sorted(set(base) | set(cand)):
        base_pass, cand_pass = base.get((task_id, attempt)), cand.get((task_id, attempt))
        if base_pass is None or cand_pass is None:
            unpaired.append(f"{task_id}#{attempt}")
            continue
        differences.setdefault(task_id, []).append(int(cand_pass) - int(base_pass))
    return differences, unpaired


def paired_verdict(
    differences: dict[str, list[int]],
) -> tuple[str, list[str], tuple[float, float], float]:
    """(verdict, reasons, interval, point) under gate v3. There's no "task
    broke" rule: with one attempt per scenario it would fire on a single
    conversation."""
    low, high, point = paired_bootstrap_interval(differences)
    pairs = sum(len(task_differences) for task_differences in differences.values())
    interval = f"95% interval {low:+.1%} to {high:+.1%}"
    if high < 0:
        why = f"paired pass rate dropped {-point:.1%} over {pairs} pairs ({interval}, entirely below 0)"
        return "regression", [why], (low, high), point
    if point <= INCONCLUSIVE_DROP:
        why = (
            f"paired pass rate down {-point:.1%} over {pairs} pairs, but not significant "
            f"({interval}); `agent-eval plan-pairs` says how many pairs would resolve it"
        )
        return "inconclusive", [why], (low, high), point
    return "no regression", [], (low, high), point
