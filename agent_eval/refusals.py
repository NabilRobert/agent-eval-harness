"""Counts how often the server refused the agent's queries, and why
(MCP-backbone's accuracy-benchmark-plan.md, D5). Pure: it reads the
`queries` each trial records (the status and error of every `run_query`
result, agent_eval/inspect_tasks.py), so a change to the rules here
reaches every recorded run, as a grader fix does.

The reasons follow MCP-backbone's exact messages (app/query/cost_check.py,
validation.py and service.py). Two results look like refusals and aren't:
- a rate limit is the harness's problem, already an `error` trial (ADR-007);
- "could not parse SQL" is the agent's syntax, not the server refusing a
  query it understood, so it's counted on its own."""

from collections import Counter
from dataclasses import dataclass
from typing import Any

# The server's reasons for refusing a query it understood, in report order.
REFUSAL_REASONS = ("validator", "cost", "timeout")
UNPARSED = "parse"

_COST_PREFIX = "estimated cost "
_PARSE_PREFIX = "could not parse SQL"
_RATE_LIMIT = "rate limit of"


def refusal_reason(query: dict[str, Any]) -> str | None:
    """Why a query was refused: "validator", "cost", "timeout" or "parse".
    None for anything else, including a rate limit."""
    error = query.get("error") or ""
    if query.get("status") == "timed_out":
        return "timeout"
    if query.get("status") != "rejected" or _RATE_LIMIT in error:
        return None
    if error.startswith(_COST_PREFIX):
        return "cost"
    if error.startswith(_PARSE_PREFIX):
        return UNPARSED
    return "validator"


@dataclass(frozen=True)
class RefusalCounts:
    trials: int  # graded trials that recorded their queries
    trials_refused: int  # of those, the ones with at least one refused query
    queries: int  # every `run_query` call in them
    refused: int  # the calls the server refused
    by_reason: dict[str, int]
    unparsed: int  # calls refused as unparsable SQL, not counted in `refused`


def count_refusals(trials: list[dict[str, Any]]) -> RefusalCounts | None:
    """Counts over the graded trials; None when no trial recorded its
    queries (runs exported before the harness stored them)."""
    recorded = [t for t in trials if t.get("queries") is not None and t["outcome"] != "error"]
    if not recorded:
        return None
    reasons: Counter[str] = Counter()
    trials_refused = 0
    for trial in recorded:
        trial_reasons = [refusal_reason(q) for q in trial["queries"]]
        reasons.update(r for r in trial_reasons if r is not None)
        if any(r in REFUSAL_REASONS for r in trial_reasons):
            trials_refused += 1
    by_reason = {reason: reasons[reason] for reason in REFUSAL_REASONS}
    return RefusalCounts(
        trials=len(recorded),
        trials_refused=trials_refused,
        queries=sum(len(t["queries"]) for t in recorded),
        refused=sum(by_reason.values()),
        by_reason=by_reason,
        unparsed=reasons[UNPARSED],
    )
