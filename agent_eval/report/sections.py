"""report.md, one section at a time: header, result, difficulty table,
cost and latency, per task, the trials that didn't pass, provenance.
`render` joins them. Model and tool text is fenced and clipped so nothing
an agent writes can break the Markdown."""

import statistics
from collections import defaultdict
from typing import Any

from agent_eval.records import Run
from agent_eval.report.stats import headline, median_or_none, per_task_stats

_MAX_ROWS_SHOWN = 6
_MAX_TEXT = 600


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.1f}%)" if d else "n/a"


def _fence(text: str) -> str:
    """Model and tool text goes in a fence longer than any backtick run
    inside it, so nothing an agent writes can break the report's Markdown."""
    longest = run = 0
    for ch in text:
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def _clip(text: str, limit: int = _MAX_TEXT) -> str:
    return text if len(text) <= limit else text[:limit] + f"… [{len(text) - limit} more chars]"


def _usd(value: float | None) -> str:
    return "unknown" if value is None else f"${value:.4f}"


def _rows(rows: list[dict[str, Any]] | None) -> str:
    if rows is None:
        return "(no successful result)"
    shown = [str(list(r.values())) for r in rows[:_MAX_ROWS_SHOWN]]
    more = f" … +{len(rows) - _MAX_ROWS_SHOWN} rows" if len(rows) > _MAX_ROWS_SHOWN else ""
    return "; ".join(shown) + more


def _header(run: Run, h: dict[str, Any]) -> list[str]:
    meta, prov = run.meta, run.meta["provenance"]
    suite = meta["suite"]
    reported = ", ".join(prov.get("models_reported") or []) or "unknown"
    frozen = "**frozen**" if suite.get("frozen") else "not the frozen suite (subset or unfrozen)"
    reexports = meta.get("reexports")
    rebuilt = f"; rebuilt from its Inspect log {len(reexports)}×" if reexports else ""
    return [
        f"# Run `{meta['run_id']}`",
        "",
        f"- **Model:** `{meta['agent']['model']}` (provider reported: {reported})",
        f"- **Suite:** `{suite['name']}`, {h['tasks']} tasks × {meta['agent']['epochs']} attempts, "
        f"suite sha256 `{(suite.get('sha256') or 'unknown')[:12]}`, {frozen}",
        f"- **Status:** {meta['status']} (Inspect: {meta.get('inspect_status')}){rebuilt}",
        f"- **Run at:** {meta.get('created_at')}",
        "",
    ]


def _result(h: dict[str, Any], epochs: int) -> list[str]:
    errors = h["errors"]
    return [
        "## Result",
        "",
        f"- **Strict pass rate (headline): {_pct(h['strict'], h['graded'])}** of graded trials",
        f"- Lenient pass rate: {_pct(h['lenient'], h['graded'])}",
        f"- Errors (not counted as fails, not in the rates above): {errors} of {h['trials']} trials",
        f"- pass^{epochs} (every attempt passed, strict): "
        f"{_pct(h['pass_all_k'], h['tasks_counted'])} of tasks",
        f"- pass@{epochs} (at least one attempt passed, strict): "
        f"{_pct(h['pass_any_k'], h['tasks_counted'])} of tasks",
        "",
    ]


def _difficulty_table(stats: dict[str, dict[str, Any]], tags: dict[str, list[str]]) -> list[str]:
    """Pass rates per difficulty tag; nothing when no task is tagged."""
    by_tag: dict[str, list[str]] = defaultdict(list)
    for task_id in stats:
        by_tag[(tags.get(task_id) or ["untagged"])[0]].append(task_id)
    if len(by_tag) == 1 and "untagged" in by_tag:
        return []
    out = ["| Difficulty | Tasks | Strict | Lenient | Errors |", "|---|---|---|---|---|"]
    for tag, ids in by_tag.items():
        graded = sum(stats[i]["graded"] for i in ids)
        strict = _pct(sum(stats[i]["strict"] for i in ids), graded)
        lenient = _pct(sum(stats[i]["lenient"] for i in ids), graded)
        errors = sum(stats[i]["errors"] for i in ids)
        out.append(f"| {tag} | {len(ids)} | {strict} | {lenient} | {errors} |")
    out.append("")
    return out


def _total_cost_line(cost: dict[str, Any]) -> str:
    total_cost = cost.get("usd")
    if total_cost is None:
        note = " (model has no price in prices.yaml)"
    elif not cost.get("complete", False):
        note = " (lower bound: some trials have no price)"
    else:
        note = ""
    return f"- **Total cost:** {_usd(total_cost)}{note}"


def _cost_and_latency(run: Run) -> list[str]:
    totals = run.meta["totals"]
    secs = [t["seconds"] for t in run.trials if t["seconds"] is not None]
    toks = [float(t["input_tokens"] + t["output_tokens"]) for t in run.trials]
    out = [
        "## Cost and latency",
        "",
        _total_cost_line(totals.get("cost_usd") or {}),
        f"- **Tokens:** {totals['input_tokens']:,} input "
        f"({totals.get('cached_input_tokens', 0):,} of them cached) + "
        f"{totals['output_tokens']:,} output; "
        f"median {median_or_none(toks) or 0:,.0f} per trial",
    ]
    if secs:
        q = statistics.quantiles(secs, n=10) if len(secs) >= 2 else [secs[0]] * 9
        out.append(
            f"- **Latency per trial:** median {statistics.median(secs):.1f} s, p90 {q[-1]:.1f} s, "
            f"max {max(secs):.1f} s"
        )
    out += [
        "- Latency is wall time for the whole trial (all model and tool calls), measured by Inspect.",
        "",
    ]
    return out


def _per_task(stats: dict[str, dict[str, Any]], tags: dict[str, list[str]]) -> list[str]:
    out = [
        "## Per task",
        "",
        "| Task | Difficulty | Strict | Lenient | Errors | Median tokens | Median s | Cost |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for task_id, s in stats.items():
        out.append(
            f"| {task_id} | {(tags.get(task_id) or ['–'])[0]} | {s['strict']}/{s['graded']} | "
            f"{s['lenient']}/{s['graded']} | {s['errors']} | {s['median_tokens'] or 0:,.0f} | "
            f"{(s['median_seconds'] or 0):.1f} | {_usd(s['cost'])} |"
        )
    out.append("")
    return out


def _named(label: str, names: list[str]) -> str:
    return f"{label} {', '.join(names)}"


def _grader_lines(g: dict[str, Any]) -> list[str]:
    """Why one grader passed or failed, for a trial that didn't pass."""
    mark = "pass" if g["strict"] else "fail"
    kind, inputs = g["kind"], g["input"]
    spec: Any = g.get("spec")  # absent on result_match records from before export v2
    if kind == "result_match":
        return [f"- Expected: {_rows(g['expected'])}", f"- Got: {_rows(inputs['graded_rows'])}"]
    if kind == "answer_match":
        answer = _fence(_clip(str(inputs["final_answer"] or "(none)")))
        return [
            f"- Answer must contain: {spec['contains']} ({mark})",
            "- Final answer:",
            "",
            answer,
            "",
        ]
    if kind == "answer_excludes":
        answer = str(inputs["final_answer"] or "").lower()
        leaked = [x for x in spec["excludes"] if x.lower() in answer]
        shown = _named("LEAKED", leaked) if leaked else "none leaked"
        return [f"- Must not appear: {shown} ({mark})"]
    if kind == "forbidden_tools":
        used = sorted(set(inputs["tools_called"]) & set(spec))
        shown = _named("USED", used) if used else "none used"
        return [f"- Forbidden tools: {shown} ({mark})"]
    missing = sorted(set(spec) - set(inputs["tools_called"]))
    shown = _named("NOT CALLED", missing) if missing else "all called"
    return [f"- Required tools: {shown} ({mark})"]


def _failure(t: dict[str, Any]) -> list[str]:
    error = f"; error: {t['error_kind']}" if t.get("error_kind") else ""
    lenient = "pass" if t["lenient"] else "fail"
    out = [
        f"### {t['task_id']} attempt {t['attempt']}: {t['outcome']}",
        "",
        f"- Stop reason: {t['stop_reason']}{error}; lenient: {lenient}",
        f"- Tools called: {' → '.join(c['tool'] for c in t['tool_calls']) or 'none'}",
    ]
    for g in t["graders"]:
        out += _grader_lines(g)
    sql = [c["arguments"].get("sql") for c in t["tool_calls"] if c["tool"] == "run_query"]
    if sql and sql[-1]:
        out += ["- Last query:", "", _fence(_clip(str(sql[-1])))]
    if t.get("error_message"):
        out += ["- Error message:", "", _fence(_clip(str(t["error_message"])))]
    out.append("")
    return out


def _failures(run: Run) -> list[str]:
    failures = [t for t in run.trials if t["outcome"] != "pass"]
    out = ["## Trials that didn't pass strictly", ""]
    if not failures:
        out += ["None.", ""]
    for trial in failures:
        out += _failure(trial)
    return out


def _price_and_budget(meta: dict[str, Any]) -> list[str]:
    out: list[str] = []
    price: dict[str, Any] | None = meta.get("price")
    if price:
        out.append(
            f"- Priced at ${price['input']}/M input "
            f"(${price.get('cache_read', price['input'])}/M cached), ${price['output']}/M output "
            f"({price['source']}, checked {price['checked']})"
        )
    budget: dict[str, Any] = meta.get("budget") or {}
    if budget.get("priced"):
        out.append(
            f"- Budget: ${budget['budget_usd']:.2f}, estimate {_usd(budget.get('estimate_usd'))} "
            f"({budget.get('token_basis')} tokens), "
            f"per-trial cap {_usd(budget.get('per_trial_cap_usd'))}"
        )
    elif budget:
        out.append(
            f"- Budget: ${budget['budget_usd']:.2f}; model unpriced, so no dollar cap: "
            "limited to a smoke-sized run, each trial capped by its token limit"
        )
    return out


def _provenance(meta: dict[str, Any]) -> list[str]:
    prov = meta["provenance"]
    out = ["## Provenance", ""]
    target: dict[str, Any] | None = meta.get("target")
    if target:
        out.append(f"- Target: `{target['name']}` ({target['transport']}, `{target['address']}`)")
    tool_hash = (prov.get("tool_list_sha256") or "")[:12]
    out += [
        f"- Data fingerprint: `{prov.get('data_fingerprint') or 'not taken'}`",
        f"- Server: `{prov.get('server_name')}` build `{prov.get('server_version') or 'not reported'}`"
        f" (/healthz: `{prov.get('healthz_version') or 'not reported'}`)",
        f"- Tool list sha256: `{tool_hash}` ({', '.join(prov.get('tool_names') or [])})",
        f"- Harness: `{prov.get('harness_git')}`, Inspect AI {prov.get('inspect_ai_version')}, "
        f"export v{meta.get('export_version', 1)}",
        f"- Agent settings: {meta['agent'].get('model_args')}, limits {meta['agent'].get('limits')}",
    ]
    out += _price_and_budget(meta)
    out.append("")
    return out


def render(run: Run) -> str:
    """The whole report, one section after another."""
    h = headline(run)
    stats = per_task_stats(run)
    tags: dict[str, list[str]] = run.meta["suite"].get("task_tags") or {}
    sections = [
        _header(run, h),
        _result(h, run.meta["agent"]["epochs"]),
        _difficulty_table(stats, tags),
        _cost_and_latency(run),
        _per_task(stats, tags),
        _failures(run),
        _provenance(run.meta),
    ]
    return "\n".join(line for section in sections for line in section) + "\n"
