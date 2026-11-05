"""report.md's refusals section: how often the server refused the
agent's queries, and why (agent_eval/refusals.py counts them). Shown only
for runs that recorded their queries. Kept apart from sections.py so that
file stays under the size limit."""

from typing import Any

from agent_eval.records import Run
from agent_eval.refusals import RefusalCounts, count_refusals

# Tasks that ask for a write first but need only a read (sql-analyst-env's
# "tempting" family): there a refusal is the right answer, so they get
# their own line.
TEMPTING_TAG = "tempting"


def _share(n: int, d: int, what: str) -> str:
    """For example: 3 of 40 trials had a query refused (7.5%)."""
    return f"{n} of {d} {what}" + (f" ({100 * n / d:.1f}%)" if d else "")


def _trials_line(label: str, counts: RefusalCounts) -> str:
    share = _share(counts.trials_refused, counts.trials, "trials had a query refused")
    return f"- **{label}:** {share}"


def refusal_lines(run: Run) -> list[str]:
    counts = count_refusals(run.trials)
    if counts is None:
        return []
    reasons = ", ".join(f"{reason} {n}" for reason, n in counts.by_reason.items())
    out = [
        "## Refusals",
        "",
        _trials_line("Per question", counts),
        f"- **Per query:** {_share(counts.refused, counts.queries, '`run_query` calls refused')}",
        f"- **By reason:** {reasons}",
        f"- **Not counted as refusals:** unparsable SQL ({counts.unparsed}), which is the "
        "agent's syntax, and rate limits, which make the trial an error.",
    ]
    tags: dict[str, list[str]] = run.meta["suite"].get("task_tags") or {}
    tempting: list[dict[str, Any]] = [
        t for t in run.trials if TEMPTING_TAG in tags.get(t["task_id"], [])
    ]
    tempting_counts = count_refusals(tempting)
    if tempting_counts is not None:
        out.append(
            _trials_line("Tempting tasks (they ask for a write)", tempting_counts)
            + f"; {_share(tempting_counts.refused, tempting_counts.queries, 'queries refused')}. "
            "Here a refusal is the right answer."
        )
    return [*out, ""]
