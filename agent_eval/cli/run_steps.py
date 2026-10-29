"""The steps of `agent-eval run` that come before any money is spent, in
the order the command takes them: load the suite, pick the target, read
the keys, plan the budget, check the commit, preflight the target."""

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any


from agent_eval.budget import (
    SMOKE_MAX_TRIALS,
    BudgetError,
    load_prices,
    measured_tokens_per_trial,
    price_for,
)
from agent_eval.budget import plan as plan_budget
from agent_eval.envfile import parse_env_text, read_env_file
from agent_eval.providers import is_secret_name, required_env
from agent_eval.suites import (
    PAGILA_SYSTEM_PROMPT,
    SuiteError,
    data_mismatch,
    load_suite,
    required_tools,
)
from agent_eval.targets import TARGETS
from agent_eval.version import harness_git as current_harness_git

from agent_eval.cli.common import fail, require_variable


def load_suite_or_exit(suite_path: str, tasks: str | None) -> dict[str, Any]:
    try:
        return load_suite(Path(suite_path), tasks.split(",") if tasks else None)
    except (SuiteError, OSError) as exc:
        fail(str(exc))


def choose_target(
    suite: dict[str, Any], target_name: str | None, configuration: str | None
) -> dict[str, Any]:
    """The target to run against, with the configuration it's reached in.
    Gateway targets must say whether the gateway is on or off; any other
    target is reached directly."""
    name = target_name or suite["target"]
    target = TARGETS.get(name)
    if target is None:
        fail(f"unknown target {name!r}")
    is_gateway = bool(target.get("gateway"))
    configuration = configuration or (None if is_gateway else "direct")
    if is_gateway and configuration not in ("gateway-off", "gateway-on"):
        fail(
            f"target {target['name']!r} is a gateway: say --configuration gateway-off or gateway-on"
        )
    if not is_gateway and configuration != "direct":
        fail(f"target {target['name']!r} isn't a gateway, so its configuration is direct")
    # --target can only swap in another server for the same suite (a local
    # copy, a gateway in front of it), never a different one.
    if target_name and target.get("serves", target["name"]) != suite["target"]:
        fail(f"target {target_name!r} doesn't serve suite target {suite['target']!r}")
    return dict(target, configuration=configuration)


def read_env(target: dict[str, Any], env_file: str) -> dict[str, str]:
    """The env file's variables, plus the target's key when the target
    hands it out by command (the local reproduction stack)."""
    env = read_env_file(Path(env_file))
    if not target.get("auth_env_command"):
        return env
    try:
        out = subprocess.run(
            target["auth_env_command"], capture_output=True, text=True, timeout=30, check=True
        ).stdout
    except (OSError, subprocess.SubprocessError):
        fail(
            f"couldn't read the {target['name']} key; is it running? "
            "(docker compose -f repro/compose.yaml up -d)"
        )
    return {**env, **parse_env_text(out)}


def check_keys(env: dict[str, str], target: dict[str, Any], model: str) -> str:
    """Checks the model's keys are set and returns the target's key ("" if
    the target needs none)."""
    for name in required_env(model):
        require_variable(env, name)
    if not target.get("auth_env"):
        return ""
    return require_variable(env, target["auth_env"])


def export_keys_for_inspect(env: dict[str, str]) -> None:
    """Inspect's providers read their keys from this process's environment:
    its openai-api/<service>/<model> route wants <SERVICE>_API_KEY and
    <SERVICE>_BASE_URL, the native ones OPENAI_API_KEY and so on."""
    for name, value in env.items():
        os.environ.setdefault(name, value)
    if "SUMOPOD_AI_API_KEY" in env:
        os.environ["SUMOPOD_API_KEY"] = env["SUMOPOD_AI_API_KEY"]
    os.environ.setdefault("INSPECT_DISPLAY", "none")


def secrets_to_redact(env: dict[str, str], auth_token: str) -> list[str]:
    """Every secret-looking value from the env file, plus the target's key:
    none may appear in the run records."""
    secrets = [value for name, value in env.items() if value and is_secret_name(name)]
    if auth_token:
        secrets.append(auth_token)
    return secrets


def new_run_dir(out: str, run_id: str) -> Path:
    run_dir = Path(out) / run_id
    if run_dir.exists():
        fail(f"{run_dir} already exists; run records are never overwritten")
    return run_dir


def plan_spend(  # noqa: PLR0913 -- keyword-only step inputs
    *,
    model: str,
    prices_path: str,
    n_trials: int,
    budget_usd: float,
    runs_dir: Path,
    suite_name: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """The model's price (None if unpriced) and the budget plan, before
    anything is spent. Refuses a run the budget can't cover."""
    try:
        price = price_for(model, load_prices(Path(prices_path)))
        budget = plan_budget(
            n_trials=n_trials,
            budget=budget_usd,
            price=price,
            tokens_per_trial=measured_tokens_per_trial(runs_dir, suite_name, model),
        )
    except BudgetError as exc:
        fail(str(exc))
    return price, budget


def print_plan(n_trials: int, budget: dict[str, Any], budget_usd: float) -> None:
    if budget["estimate_usd"] is None:
        estimate = "unpriced"
    else:
        estimate = f"${budget['estimate_usd']:.2f}"
    print(
        f"plan: {n_trials} trials, estimate {estimate} ({budget['token_basis']} tokens), "
        f"budget ${budget_usd:.2f}"
    )


def traceable_commit(n_trials: int) -> str:
    """The harness commit to record. A full run is evidence, so it must
    trace back to one exact commit; smoke runs may come from a dirty tree."""
    harness_git = current_harness_git()
    is_traceable = not (harness_git.endswith("-dirty") or harness_git == "unknown")
    if n_trials > SMOKE_MAX_TRIALS and not is_traceable:
        fail(
            f"harness checkout is {harness_git}; commit first (full runs need a clean "
            "tree, smoke runs don't)"
        )
    return harness_git


def choose_system_prompt(
    suite: dict[str, Any], system_prompt: str | None, system_prompt_file: str | None
) -> str:
    if system_prompt:
        return system_prompt
    if system_prompt_file:
        return Path(system_prompt_file).read_text(encoding="utf-8").strip()
    # A suite can carry its own prompt; Pagila uses MCP-backbone's.
    return suite.get("system_prompt") or PAGILA_SYSTEM_PROMPT


def preflight_target(
    target: dict[str, Any], auth_token: str, suite: dict[str, Any]
) -> dict[str, Any]:
    """Checks the target before any trial: its tools, versions and data.
    Returns what it found, which goes into the run's meta.json."""
    from agent_eval.preflight import PreflightError, preflight  # the MCP client: slow to import

    try:
        info = asyncio.run(preflight(target, auth_token, required_tools(suite)))
    except PreflightError as exc:
        fail(f"preflight failed: {exc}")
    # The suite's expected answers were generated against one specific
    # dataset; grading against any other would score right answers wrong.
    mismatch = data_mismatch(suite, info["data_fingerprint"], info.get("session_utc_offset"))
    if mismatch:
        fail(mismatch)
    return info


def tool_allowlist(exclude_tools: str, tool_names: list[str], suite: dict[str, Any]) -> list[str]:
    """The target's tools minus the excluded ones: a deliberately degraded
    agent (the regression proof). Recorded in the meta, so `compare` names
    it as the difference between the runs."""
    excluded = set(exclude_tools.split(","))
    unknown = excluded - set(tool_names)
    needed_by_graders = excluded & required_tools(suite)
    if unknown or needed_by_graders:
        fail(
            f"can't exclude {sorted(excluded)}: unknown {sorted(unknown)}, or "
            f"needed by the graders {sorted(needed_by_graders)}"
        )
    return [name for name in tool_names if name not in excluded]
