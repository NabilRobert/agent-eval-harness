"""Renders `report.md` from a run's records alone (Phase 3: pure, no
Inspect, no network). Deterministic: the same records always render the
same bytes, so CI can check a committed report against a fresh render.

Strict pass rate is the headline (Phase 2); lenient sits next to it so the
lenient number never has to be taken on trust. Errors are always shown
beside pass rates, never folded into them."""

import statistics
from collections import defaultdict
from typing import Any

from agent_eval.records import Run

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


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _rows(rows: list[dict[str, Any]] | None) -> str:
    if rows is None:
        return "(no successful result)"
    shown = [str(list(r.values())) for r in rows[:_MAX_ROWS_SHOWN]]
    more = f" … +{len(rows) - _MAX_ROWS_SHOWN} rows" if len(rows) > _MAX_ROWS_SHOWN else ""
    return "; ".join(shown) + more


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
            "median_tokens": _median([t["input_tokens"] + t["output_tokens"] for t in trials]),
            "median_seconds": _median([t["seconds"] for t in trials if t["seconds"] is not None]),
            "cost": None if any(t["cost_usd"] is None for t in trials)
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


def render(run: Run) -> str:
    meta, prov = run.meta, run.meta["provenance"]
    h = headline(run)
    stats = per_task_stats(run)
    tags: dict[str, list[str]] = meta["suite"].get("task_tags") or {}
    epochs = meta["agent"]["epochs"]
    out: list[str] = []
    add = out.append

    add(f"# Run `{meta['run_id']}`")
    add("")
    add(f"- **Model:** `{meta['agent']['model']}` (provider reported: "
        f"{', '.join(prov.get('models_reported') or []) or 'unknown'})")
    add(f"- **Suite:** `{meta['suite']['name']}`, {h['tasks']} tasks × {epochs} attempts, "
        f"suite sha256 `{(meta['suite'].get('sha256') or 'unknown')[:12]}`, "
        f"{'**frozen**' if meta['suite'].get('frozen') else 'not the frozen suite (subset or unfrozen)'}")
    add(f"- **Status:** {meta['status']} (Inspect: {meta.get('inspect_status')})"
        f"{'; rebuilt from its Inspect log ' + str(len(meta['reexports'])) + '×' if meta.get('reexports') else ''}")
    add(f"- **Run at:** {meta.get('created_at')}")
    add("")

    add("## Result")
    add("")
    add(f"- **Strict pass rate (headline): {_pct(h['strict'], h['graded'])}** of graded trials")
    add(f"- Lenient pass rate: {_pct(h['lenient'], h['graded'])}")
    add(f"- Errors (not counted as fails, not in the rates above): {h['errors']} of {h['trials']} trials")
    add(f"- pass^{epochs} (every attempt passed, strict): {_pct(h['pass_all_k'], h['tasks_counted'])} of tasks")
    add(f"- pass@{epochs} (at least one attempt passed, strict): {_pct(h['pass_any_k'], h['tasks_counted'])} of tasks")
    add("")

    by_tag: dict[str, list[str]] = defaultdict(list)
    for task_id in stats:
        by_tag[(tags.get(task_id) or ["untagged"])[0]].append(task_id)
    if len(by_tag) > 1 or "untagged" not in by_tag:
        add("| Difficulty | Tasks | Strict | Lenient | Errors |")
        add("|---|---|---|---|---|")
        for tag, ids in by_tag.items():
            g = sum(stats[i]["graded"] for i in ids)
            add(f"| {tag} | {len(ids)} | {_pct(sum(stats[i]['strict'] for i in ids), g)} | "
                f"{_pct(sum(stats[i]['lenient'] for i in ids), g)} | {sum(stats[i]['errors'] for i in ids)} |")
        add("")

    totals = meta["totals"]
    cost: dict[str, Any] = totals.get("cost_usd") or {}
    secs = [t["seconds"] for t in run.trials if t["seconds"] is not None]
    toks = [t["input_tokens"] + t["output_tokens"] for t in run.trials]
    add("## Cost and latency")
    add("")
    total_cost = cost.get("usd")
    complete = cost.get("complete", False)
    add(f"- **Total cost:** {_usd(total_cost)}"
        f"{'' if complete else ' (lower bound: some trials have no price)' if total_cost is not None else ' (model has no price in prices.yaml)'}")
    add(f"- **Tokens:** {totals['input_tokens']:,} input + {totals['output_tokens']:,} output; "
        f"median {_median([float(t) for t in toks]) or 0:,.0f} per trial")
    if secs:
        q = statistics.quantiles(secs, n=10) if len(secs) >= 2 else [secs[0]] * 9
        add(f"- **Latency per trial:** median {statistics.median(secs):.1f} s, p90 {q[-1]:.1f} s, "
            f"max {max(secs):.1f} s")
    add("- Latency is wall time for the whole trial (all model and tool calls), measured by Inspect.")
    add("")

    add("## Per task")
    add("")
    add("| Task | Difficulty | Strict | Lenient | Errors | Median tokens | Median s | Cost |")
    add("|---|---|---|---|---|---|---|---|")
    for task_id, s in stats.items():
        add(f"| {task_id} | {(tags.get(task_id) or ['–'])[0]} | {s['strict']}/{s['graded']} | "
            f"{s['lenient']}/{s['graded']} | {s['errors']} | {s['median_tokens'] or 0:,.0f} | "
            f"{(s['median_seconds'] or 0):.1f} | {_usd(s['cost'])} |")
    add("")

    failures = [t for t in run.trials if t["outcome"] != "pass"]
    add("## Trials that didn't pass strictly")
    add("")
    if not failures:
        add("None.")
        add("")
    for t in failures:
        add(f"### {t['task_id']} attempt {t['attempt']}: {t['outcome']}")
        add("")
        add(f"- Stop reason: {t['stop_reason']}"
            f"{'; error: ' + str(t['error_kind']) if t.get('error_kind') else ''}"
            f"; lenient: {'pass' if t['lenient'] else 'fail'}")
        add(f"- Tools called: {' → '.join(c['tool'] for c in t['tool_calls']) or 'none'}")
        for g in t["graders"]:
            mark = "pass" if g["strict"] else "fail"
            if g["kind"] == "result_match":
                add(f"- Expected: {_rows(g['expected'])}")
                add(f"- Got: {_rows(g['input']['graded_rows'])}")
            elif g["kind"] == "answer_match":
                add(f"- Answer must contain: {g['spec']['contains']} ({mark})")
                add("- Final answer:")
                add("")
                add(_fence(_clip(str(g["input"]["final_answer"] or "(none)"))))
                add("")
            else:
                used = sorted(set(g["input"]["tools_called"]) & set(g["spec"]))
                add(f"- Forbidden tools: {'none used' if not used else 'USED ' + ', '.join(used)} ({mark})")
        sql = [c["arguments"].get("sql") for c in t["tool_calls"] if c["tool"] == "run_query"]
        if sql and sql[-1]:
            add("- Last query:")
            add("")
            add(_fence(_clip(str(sql[-1]))))
        if t.get("error_message"):
            add("- Error message:")
            add("")
            add(_fence(_clip(str(t["error_message"]))))
        add("")

    add("## Provenance")
    add("")
    add(f"- Data fingerprint: `{prov.get('data_fingerprint') or 'not taken'}`")
    add(f"- Server: `{prov.get('server_name')}` build `{prov.get('server_version') or 'not reported'}`"
        f" (/healthz: `{prov.get('healthz_version') or 'not reported'}`)")
    add(f"- Tool list sha256: `{(prov.get('tool_list_sha256') or '')[:12]}` ({', '.join(prov.get('tool_names') or [])})")
    add(f"- Harness: `{prov.get('harness_git')}`, Inspect AI {prov.get('inspect_ai_version')}, "
        f"export v{meta.get('export_version', 1)}")
    add(f"- Agent settings: {meta['agent'].get('model_args')}, limits {meta['agent'].get('limits')}")
    price: dict[str, Any] | None = meta.get("price")
    if price:
        add(f"- Priced at ${price['input']}/M input, ${price['output']}/M output "
            f"({price['source']}, checked {price['checked']}); every input token at the full "
            "input price, so cost errs high if any input was cached")
    budget: dict[str, Any] = meta.get("budget") or {}
    if budget:
        if budget.get("priced"):
            add(f"- Budget: ${budget['budget_usd']:.2f}, estimate {_usd(budget.get('estimate_usd'))} "
                f"({budget.get('token_basis')} tokens), per-trial cap {_usd(budget.get('per_trial_cap_usd'))}")
        else:
            add(f"- Budget: ${budget['budget_usd']:.2f}; model unpriced, so no dollar cap: "
                "limited to a smoke-sized run, each trial capped by its token limit")
    add("")
    return "\n".join(out) + "\n"
