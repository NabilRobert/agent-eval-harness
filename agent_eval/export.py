"""Turns an Inspect log into this harness's run records (ADR-004 as
amended by ADR-009). The only module that reads Inspect's log format, so
a format change breaks here, visibly, and nowhere else.

Also where `error` is told apart from `fail` (Phase 3): a provider or
infrastructure failure is the harness's problem, never the agent's."""

import importlib.metadata
from pathlib import Path
from typing import Any

from inspect_ai.log import EvalLog, EvalSample, read_eval_log, resolve_sample_attachments

from agent_eval.budget import cost_usd
from agent_eval.grading import GRADER_VERSION, grade_one
from agent_eval.records import ordered_json, sha256_hex, task_hash
from agent_eval.suites import FROZEN_SUITES

# More than this share of errored trials and the run can't be compared.
INCOMPLETE_ERROR_SHARE = 0.10
# Bump when export output changes; `reexport` records which version
# rebuilt a run's trials.
EXPORT_VERSION = 4  # v2: column order, attachments; v3: task tags; v4: grades recomputed at export


class SecretLeakError(Exception):
    """A secret value showed up in something about to be written. Nothing
    is written; the run directory keeps whatever it had before."""


def clean_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """MCP-backbone advertises an optional api_key argument, so models may
    send "api_key": null. It's noise, and a key must never be recorded
    even if a model ever filled one in."""
    return {k: v for k, v in (arguments or {}).items() if k != "api_key"}


def _tool_calls(sample: EvalSample) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for event in sample.events:
        if event.event != "tool":
            continue
        arguments = clean_arguments(event.arguments)
        calls.append(
            {
                "tool": event.function,
                "arguments": arguments,
                "seconds": round(event.working_time, 3) if event.working_time else None,
                "error": event.error.message if event.error else None,
            }
        )
    return calls


def _model_calls(sample: EvalSample) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for event in sample.events:
        if event.event != "model":
            continue
        usage = event.output.usage
        calls.append(
            {
                # The model name the provider says it served, which can
                # differ from the one asked for (Phase 3 provenance).
                "model_reported": event.output.model,
                "input_tokens": usage.input_tokens if usage else None,
                "output_tokens": usage.output_tokens if usage else None,
                "reasoning_tokens": usage.reasoning_tokens if usage else None,
                "seconds": round(event.working_time, 3) if event.working_time else None,
            }
        )
    return calls


def trial_from_sample(
    sample: EvalSample, task_hashes: dict[str, str], price: dict[str, Any] | None = None
) -> dict[str, Any]:
    # Inspect moves long strings (e.g. a long SQL query) out to an
    # attachments table and leaves "attachment://<id>" in their place;
    # without resolving them the record would hold the reference, not the
    # query (found by the slice B smoke run).
    sample = resolve_sample_attachments(sample, "full")
    score = (sample.scores or {}).get("suite_scorer")
    score_meta: dict[str, Any] = (score.metadata or {}) if score else {}
    # Grades are recomputed from the stored grader inputs with the current
    # grader code, so a rebuilt run reflects the graders as they are now
    # (`compare` would otherwise flag every trial a grader fix changed).
    graders: list[dict[str, Any]] = []
    for g in score_meta.get("graders", []):
        spec = g.get("spec") or {"tool": g.get("tool"), "expected": g.get("expected")}
        g = {**g}
        g["strict"], g["lenient"] = grade_one(g["kind"], spec, g["input"])
        graders.append(g)
    strict = bool(graders) and all(g["strict"] for g in graders)
    lenient = bool(graders) and all(g["lenient"] for g in graders)

    error_kind: str | None = None
    if sample.error is not None:
        error_kind = "provider_or_harness"
    elif score_meta.get("infra_error"):
        error_kind = f"target_refused:{score_meta['infra_error']}"
    elif score is None:
        error_kind = "not_scored"

    stop_reason = sample.limit.type if sample.limit else "completed"
    if error_kind:
        outcome = "error"
    elif sample.limit is not None:
        # Hitting a turn/time/token cap is the agent's fault: a fail.
        outcome = "fail"
        strict = lenient = False
    else:
        outcome = "pass" if strict else "fail"

    model_calls = _model_calls(sample)
    input_tokens = sum(c["input_tokens"] or 0 for c in model_calls)
    output_tokens = sum(c["output_tokens"] or 0 for c in model_calls)
    task_id = str(sample.id)
    return {
        "task_id": task_id,
        "task_hash": task_hashes[task_id],
        "attempt": sample.epoch,
        "outcome": outcome,
        "strict": strict,
        "lenient": lenient,
        "error_kind": error_kind,
        "error_message": sample.error.message if sample.error else None,
        "stop_reason": stop_reason,
        "grader_version": GRADER_VERSION,
        "graders": graders,
        "final_answer": sample.output.completion if sample.output else None,
        "tool_calls": _tool_calls(sample),
        "model_calls": model_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        # Unknown (None), never 0, when the model has no price (Phase 3).
        "cost_usd": cost_usd(input_tokens, output_tokens, price),
        "seconds": round(sample.total_time, 3) if sample.total_time else None,
    }


def build_meta(
    log: EvalLog,
    trials: list[dict[str, Any]],
    *,
    run_id: str,
    suite: dict[str, Any],
    task_hashes: dict[str, str],
    agent: dict[str, Any],
    preflight_info: dict[str, Any],
    harness_git: str,
    system_prompt_sha256: str,
    suite_sha256: str | None = None,
    budget_plan: dict[str, Any] | None = None,
    price: dict[str, Any] | None = None,
    target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = run_status(log.status, trials)
    reported = sorted(
        {c["model_reported"] for t in trials for c in t["model_calls"] if c["model_reported"]}
    )
    return {
        "run_id": run_id,
        "created_at": log.eval.created,
        "status": status,
        "inspect_status": log.status,
        "suite": {
            "name": suite["suite"],
            "sha256": suite_sha256,
            # True only for the whole frozen suite, never a subset of it.
            "frozen": suite_sha256 is not None
            and FROZEN_SUITES.get(suite["suite"]) == suite_sha256,
            "task_hashes": task_hashes,
            "task_tags": {t["id"]: t.get("tags", []) for t in suite["tasks"]},
        },
        "budget": budget_plan,
        # The exact price the costs below were computed with, and its source.
        "price": price,
        # What the run talked to: never a key, only where (Phase 2).
        "target": None
        if target is None
        else {
            "name": target["name"],
            "transport": target.get("transport", "streamable-http"),
            "address": target.get("url") or target.get("fixture"),
            # direct / gateway-off / gateway-on (Project 4b); absent on older runs.
            "configuration": target.get("configuration"),
        },
        "agent": {
            "model": agent["model"],
            "model_args": agent["model_args"],
            "system_prompt_sha256": system_prompt_sha256,
            # The text too, not only its hash: it isn't secret, and a reader
            # comparing two runs should be able to see what changed.
            "system_prompt": agent["system_prompt"],
            "tool_allowlist": agent.get("tool_allowlist"),
            "limits": {
                "message_limit": agent["message_limit"],
                "time_limit": agent["time_limit"],
                "token_limit": agent["token_limit"],
            },
            "epochs": agent["epochs"],
        },
        "provenance": {
            **preflight_info,
            "models_reported": reported,
            "harness_git": harness_git,
            "inspect_ai_version": importlib.metadata.version("inspect-ai"),
        },
        "export_version": EXPORT_VERSION,
        "totals": totals(trials),
    }


def run_status(inspect_status: str, trials: list[dict[str, Any]]) -> str:
    errors = sum(1 for t in trials if t["outcome"] == "error")
    ok = inspect_status == "success" and trials and errors / len(trials) <= INCOMPLETE_ERROR_SHARE
    return "complete" if ok else "incomplete"


def totals(trials: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "trials": len(trials),
        "pass_strict": sum(1 for t in trials if t["outcome"] == "pass"),
        "pass_lenient": sum(1 for t in trials if t["outcome"] != "error" and t["lenient"]),
        "errors": sum(1 for t in trials if t["outcome"] == "error"),
        "input_tokens": sum(t["input_tokens"] for t in trials),
        "output_tokens": sum(t["output_tokens"] for t in trials),
        "cost_usd": _total_cost(trials),
    }


def _total_cost(trials: list[dict[str, Any]]) -> dict[str, Any]:
    """A total that includes an unknown trial cost is a lower bound, and
    says so (Phase 3), rather than quietly counting it as $0."""
    known = [t["cost_usd"] for t in trials if t["cost_usd"] is not None]
    return {"usd": round(sum(known), 6) if known else None, "complete": len(known) == len(trials)}


def assert_no_secrets(texts: list[str], secrets: list[str]) -> None:
    """Refuses to write if any secret value appears anywhere in the
    output. Checks the values themselves, so it catches a leak however it
    got there (a header in a log, a model echoing a key)."""
    for secret in secrets:
        if len(secret) >= 8 and any(secret in text for text in texts):
            raise SecretLeakError("a secret value appears in the run records; nothing written")


def inspect_log_contains_secret(log_path: Path, secrets: list[str]) -> bool:
    """Inspect's .eval file is a zip, so it's checked decoded, not as bytes."""
    log = read_eval_log(str(log_path))
    text = ordered_json(log.model_dump(mode="json"))
    return any(len(s) >= 8 and s in text for s in secrets)


def reexport(
    meta: dict[str, Any], log_path: Path, price: dict[str, Any] | None, at: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Rebuilds a run's trials from its saved Inspect log with the current
    export code, so an export bug never needs a paid re-run. The raw log is
    the evidence and is untouched; the rebuild is recorded in the meta, so
    it can't happen silently."""
    log = read_eval_log(str(log_path))
    # Task hashes are recomputed from the task each sample carries, so a
    # change in how hashes are computed (export v2 keeps column order)
    # reaches old runs too, in the meta's own task order.
    from_samples = {str(s.id): task_hash(s.metadata["task"]) for s in (log.samples or [])}
    old: dict[str, str] = meta["suite"]["task_hashes"]
    hashes: dict[str, str] = {tid: from_samples.get(tid, h) for tid, h in old.items()}
    trials = [trial_from_sample(s, hashes, price) for s in (log.samples or [])]
    new_meta = {k: v for k, v in meta.items() if k not in ("schema_version", "trials_sha256")}
    tags = {str(s.id): s.metadata["task"].get("tags", []) for s in (log.samples or [])}
    new_meta["suite"] = {
        **meta["suite"],
        "task_hashes": hashes,
        "task_tags": {tid: tags.get(tid, []) for tid in hashes},
        "sha256": sha256_hex(ordered_json([[tid, h] for tid, h in hashes.items()])),
    }
    new_meta["status"] = run_status(log.status, trials)
    new_meta["price"] = price
    new_meta["totals"] = totals(trials)
    new_meta["reexports"] = [
        *meta.get("reexports", []),
        {
            "at": at,
            "from_export_version": meta.get("export_version", 1),
            "to_export_version": EXPORT_VERSION,
            "price_checked": price.get("checked") if price else None,
        },
    ]
    new_meta["export_version"] = EXPORT_VERSION
    return new_meta, trials
