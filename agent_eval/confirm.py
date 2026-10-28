"""The confirmation step for an inconclusive comparison (ADR-001, a
Should; validated by scripts/simulate_confirm.py before use).

When `compare` says "inconclusive" (a drop of at least 5 points whose
interval still crosses 0), this reruns only the tasks that dropped, for
**both** agents, with fresh trials, and decides on those fresh trials
alone. Deciding on fresh data is what keeps picking "the tasks that
dropped" from biasing the result: those tasks dropped partly by chance,
and fresh trials don't share that chance.

Pure planning lives here (testable without a network); the CLI runs it."""

from pathlib import Path
from typing import Any

from agent_eval.compare import compare_runs
from agent_eval.records import Run, load_run, sha256_hex
from agent_eval.suites import PAGILA_SYSTEM_PROMPT, load_suite, suite_task_hashes

CONFIRM_EPOCHS = 10


class ConfirmError(Exception):
    """This pair can't be confirmed (not inconclusive, or an agent can't be
    reproduced exactly)."""


def agent_args(run: Run, suite_path: Path, tasks: list[str], epochs: int) -> list[str]:
    """`agent-eval run` arguments that reproduce this run's agent exactly
    on a subset of its tasks, or ConfirmError if anything about it can't be
    reproduced (an unknown prompt, a changed task)."""
    agent, prov = run.meta["agent"], run.meta["provenance"]
    prompt = agent.get("system_prompt")
    if prompt is None:
        # Runs made before the prompt text was recorded: accept only if the
        # recorded hash proves it was the suite's default prompt.
        suite = load_suite(suite_path)
        default = suite.get("system_prompt") or PAGILA_SYSTEM_PROMPT
        if sha256_hex(default) != agent["system_prompt_sha256"]:
            raise ConfirmError(
                f"{run.meta['run_id']}: prompt text not recorded and not the default"
            )
        prompt = default
    if sha256_hex(prompt) != agent["system_prompt_sha256"]:
        raise ConfirmError(f"{run.meta['run_id']}: recorded prompt doesn't match its hash")
    current = suite_task_hashes(load_suite(suite_path, tasks))
    recorded = run.meta["suite"]["task_hashes"]
    changed = [t for t in tasks if current[t] != recorded.get(t)]
    if changed:
        raise ConfirmError(f"{run.meta['run_id']}: tasks changed since the run: {changed}")
    args = [
        "--suite",
        str(suite_path),
        "--tasks",
        ",".join(tasks),
        "--epochs",
        str(epochs),
        "--model",
        agent["model"],
        "--message-limit",
        str(agent.get("limits", {}).get("message_limit", 20)),
    ]
    allowlist = agent.get("tool_allowlist")
    if allowlist is not None:
        excluded = sorted(set(prov["tool_names"]) - set(allowlist))
        if excluded:
            args += ["--exclude-tools", ",".join(excluded)]
    from agent_eval.providers import model_args_for

    if agent.get("model_args") != model_args_for(agent["model"]):
        # `run` derives model_args from the model; anything else couldn't be
        # reproduced through the CLI.
        raise ConfirmError(f"{run.meta['run_id']}: unexpected model_args {agent.get('model_args')}")
    return [*args, "--system-prompt", prompt]


def plan(
    baseline_dir: Path,
    candidate_dir: Path,
    suites_dir: Path,
    epochs: int = CONFIRM_EPOCHS,
    gate: str = "v2",
) -> dict[str, Any]:
    result = compare_runs(baseline_dir, candidate_dir, gate)
    if result.verdict != "inconclusive":
        raise ConfirmError(
            f"the comparison is {result.verdict!r}; confirm only runs on an inconclusive one"
        )
    baseline, candidate = load_run(baseline_dir), load_run(candidate_dir)
    name = baseline.meta["suite"]["name"]
    if candidate.meta["suite"]["name"] != name:
        raise ConfirmError("the two runs used different suites")
    suite_path = suites_dir / f"{name}.yaml"
    tasks = result.dropped
    return {
        "baseline": baseline.meta["run_id"],
        "candidate": candidate.meta["run_id"],
        "gate": gate,
        "original": {"point": result.point, "interval": result.interval},
        "tasks": tasks,
        "epochs": epochs,
        "baseline_args": agent_args(baseline, suite_path, tasks, epochs),
        "candidate_args": agent_args(candidate, suite_path, tasks, epochs),
    }
