"""Turns an Inspect log into this harness's run records (ADR-004 as
amended by ADR-009). The only module that reads Inspect's log format, so
a format change breaks here, visibly, and nowhere else.

Also where `error` is told apart from `fail` (Phase 3): a provider or
infrastructure failure is the harness's problem, never the agent's."""

import importlib.metadata
from pathlib import Path
from typing import Any

from inspect_ai.log import EvalLog, EvalSample, read_eval_log

from agent_eval.records import canonical_json

# More than this share of errored trials and the run can't be compared.
INCOMPLETE_ERROR_SHARE = 0.10


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


def trial_from_sample(sample: EvalSample, task_hashes: dict[str, str]) -> dict[str, Any]:
    score = (sample.scores or {}).get("suite_scorer")
    score_meta: dict[str, Any] = (score.metadata or {}) if score else {}
    value: dict[str, Any] = score.value if score and isinstance(score.value, dict) else {}  # pyright: ignore[reportUnknownMemberType]
    strict = bool(value.get("strict"))
    lenient = bool(value.get("lenient"))

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
        "grader_version": score_meta.get("grader_version"),
        "graders": score_meta.get("graders", []),
        "final_answer": sample.output.completion if sample.output else None,
        "tool_calls": _tool_calls(sample),
        "model_calls": model_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        # No price table yet (slice C): unknown, never 0 (Phase 3).
        "cost_usd": None,
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
) -> dict[str, Any]:
    errors = sum(1 for t in trials if t["outcome"] == "error")
    finished = log.status == "success"
    status = (
        "complete"
        if finished and trials and errors / len(trials) <= INCOMPLETE_ERROR_SHARE
        else "incomplete"
    )
    reported = sorted({c["model_reported"] for t in trials for c in t["model_calls"] if c["model_reported"]})
    return {
        "run_id": run_id,
        "created_at": log.eval.created,
        "status": status,
        "inspect_status": log.status,
        "suite": {"name": suite["suite"], "task_hashes": task_hashes},
        "agent": {
            "model": agent["model"],
            "model_args": agent["model_args"],
            "system_prompt_sha256": system_prompt_sha256,
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
            "data_fingerprint": None,  # slice B
        },
        "totals": {
            "trials": len(trials),
            "pass_strict": sum(1 for t in trials if t["outcome"] == "pass"),
            "pass_lenient": sum(1 for t in trials if t["outcome"] != "error" and t["lenient"]),
            "errors": errors,
            "input_tokens": sum(t["input_tokens"] for t in trials),
            "output_tokens": sum(t["output_tokens"] for t in trials),
            "cost_usd": None,
        },
    }


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
    text = canonical_json(log.model_dump(mode="json"))
    return any(len(s) >= 8 and s in text for s in secrets)
