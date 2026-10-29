"""`agent-eval run`: validate everything that costs nothing (run_steps.py),
run the trials through Inspect, then write the run records, never a
secret. Inspect is imported only inside this command: it loads slowly."""

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

import typer

from agent_eval import REPO_ROOT
from agent_eval.compare import EXIT_UNDECIDED
from agent_eval.providers import model_args_for
from agent_eval.records import ordered_json, sha256_hex, write_run
from agent_eval.suites import (
    suite_hash,
    suite_task_hashes,
)

from agent_eval.cli.common import (
    RAW_LOG_DIR,
    TRIAL_TIME_LIMIT_S,
    TRIAL_TOKEN_LIMIT,
    RETRIES_PER_TRIAL,
    EnvFile,
    Prices,
    app,
    fail,
    utc_stamp,
    write_report,
)
from agent_eval.cli.run_steps import (
    load_suite_or_exit,
    choose_target,
    read_env,
    check_keys,
    export_keys_for_inspect,
    secrets_to_redact,
    new_run_dir,
    plan_spend,
    print_plan,
    traceable_commit,
    choose_system_prompt,
    preflight_target,
    tool_allowlist,
)

if TYPE_CHECKING:  # for the type checker only: importing Inspect is slow
    from inspect_ai.log import EvalLog


def _cost_limits(
    model: str, price: dict[str, Any] | None, budget: dict[str, Any]
) -> dict[str, Any]:
    """Inspect's per-trial cost cap and prices; none for an unpriced model."""
    from inspect_ai.model import ModelCost

    if price is None:
        return {}
    cost = ModelCost(
        input=float(price["input"]),
        output=float(price["output"]),
        # Cache writes cost the full input price; reads use the cached
        # price when the table has one.
        input_cache_write=float(price["input"]),
        input_cache_read=float(price.get("cache_read", price["input"])),
    )
    return {"cost_limit": budget["per_trial_cap_usd"], "model_cost_config": {model: cost}}


def _run_trials(  # noqa: PLR0913 -- keyword-only step inputs
    *,
    suite: dict[str, Any],
    target: dict[str, Any],
    agent: dict[str, Any],
    auth_token: str,
    max_samples: int,
    price: dict[str, Any] | None,
    budget: dict[str, Any],
    harness_git: str,
) -> "EvalLog":
    """Runs every trial through Inspect and returns its log. This is the
    step that spends money. With an OTLP endpoint set, each trial also
    sends a trace (agent_eval/tracing.py)."""
    from inspect_ai import eval as inspect_eval  # pyright: ignore[reportUnknownVariableType]

    from agent_eval.export import INCOMPLETE_ERROR_SHARE
    from agent_eval.inspect_tasks import build_task
    from agent_eval.tracing import tracing_if_configured

    with tracing_if_configured(service_version=harness_git):
        [log] = inspect_eval(
            build_task(suite, target, agent, auth_token),
            model=agent["model"],
            model_args=agent["model_args"],
            epochs=agent["epochs"],
            max_samples=max_samples,
            retry_on_error=RETRIES_PER_TRIAL,
            # Past this share of errored trials the run is incomplete anyway,
            # so stop spending on it.
            fail_on_error=INCOMPLETE_ERROR_SHARE,
            log_dir=str(RAW_LOG_DIR),
            display="none",
            **_cost_limits(agent["model"], price, budget),
        )
    return log


def _keep_inspect_log(log: "EvalLog", run_dir: Path, secrets: list[str]) -> None:
    """Copies Inspect's raw log next to the run records, unless it contains
    a secret: then it stays in the gitignored raw log folder."""
    from agent_eval.export import inspect_log_contains_secret

    raw_log = Path(log.location)
    if inspect_log_contains_secret(raw_log, secrets):
        print(f"note: Inspect log contains a secret; kept only in {RAW_LOG_DIR.name}/")
        return
    shutil.copy2(raw_log, run_dir / "inspect.eval")


def _print_run_summary(run_id: str, meta: dict[str, Any]) -> None:
    totals = meta["totals"]
    print(
        f"{run_id}: {meta['status']} | strict {totals['pass_strict']}/{totals['trials']} "
        f"| errors {totals['errors']} | tokens {totals['input_tokens']}+{totals['output_tokens']}"
    )


@app.command(help="run a suite and write run records")
def run(  # noqa: PLR0913 -- each parameter is one of the command's CLI options
    suite_path: Annotated[
        str, typer.Option("--suite", show_default="<repo>/suites/pagila.yaml")
    ] = (str(REPO_ROOT / "suites" / "pagila.yaml")),
    tasks: Annotated[
        str | None, typer.Option(help="comma-separated task ids (e.g. a smoke suite)")
    ] = None,
    model: Annotated[str, typer.Option()] = "openai-api/sumopod/gpt-5-mini",
    target_name: Annotated[
        str | None,
        typer.Option(
            "--target",
            help="run against another target serving the suite's (e.g. mcp-backbone-local)",
        ),
    ] = None,
    configuration: Annotated[
        Literal["direct", "gateway-off", "gateway-on"] | None,
        typer.Option(
            help="how the run reaches the tools (Project 4b); "
            "gateway targets need gateway-off or gateway-on"
        ),
    ] = None,
    epochs: Annotated[int, typer.Option()] = 5,
    max_samples: Annotated[int, typer.Option(help="trials running at once")] = 4,
    budget_usd: Annotated[
        float, typer.Option("--budget", help="US dollars for the whole run")
    ] = 5.0,
    prices_path: Prices = str(REPO_ROOT / "prices.yaml"),
    plan_only: Annotated[bool, typer.Option("--plan-only", help="print the plan and stop")] = False,
    exclude_tools: Annotated[
        str | None, typer.Option(help="comma-separated tools to withhold (a degraded agent)")
    ] = None,
    system_prompt_file: Annotated[
        str | None, typer.Option(help="replace the suite's system prompt (a degraded agent)")
    ] = None,
    # Exact text, used by `confirm`.
    system_prompt: Annotated[str | None, typer.Option(hidden=True)] = None,
    message_limit: Annotated[
        int, typer.Option(help="messages per trial before the trial stops as a fail (default 20)")
    ] = 20,
    out: Annotated[str, typer.Option()] = "runs",
    run_id: Annotated[str | None, typer.Option()] = None,
    env_file: EnvFile = str(REPO_ROOT / ".env"),
) -> None:
    # 1. Validate everything that costs nothing (Phase 4, step 1).
    suite = load_suite_or_exit(suite_path, tasks)
    target = choose_target(suite, target_name, configuration)
    env = read_env(target, env_file)
    auth_token = check_keys(env, target, model)
    export_keys_for_inspect(env)
    secrets = secrets_to_redact(env, auth_token)
    run_id = run_id or f"{utc_stamp()}-{model.rsplit('/', 1)[-1]}"
    run_dir = new_run_dir(out, run_id)

    # 2. Budget (before anything is spent).
    n_trials = len(suite["tasks"]) * epochs
    price, budget = plan_spend(
        model=model,
        prices_path=prices_path,
        n_trials=n_trials,
        budget_usd=budget_usd,
        runs_dir=Path(out),
        suite_name=suite["suite"],
    )
    print_plan(n_trials, budget, budget_usd)
    if plan_only:
        return
    harness_git = traceable_commit(n_trials)
    agent: dict[str, Any] = {
        "model": model,
        # Per provider: strict tool schemas off on the OpenAI-compatible
        # route, as in every published run (see model_args_for).
        "model_args": model_args_for(model),
        "system_prompt": choose_system_prompt(suite, system_prompt, system_prompt_file),
        "tool_allowlist": None,
        "message_limit": message_limit,
        "time_limit": TRIAL_TIME_LIMIT_S,
        "token_limit": TRIAL_TOKEN_LIMIT,
        "epochs": epochs,
    }

    # 3. Preflight the target: tools, versions, data fingerprint.
    info = preflight_target(target, auth_token, suite)
    if exclude_tools:
        agent["tool_allowlist"] = tool_allowlist(exclude_tools, info["tool_names"], suite)

    # 4. Run the trials, then record them (never a secret).
    from agent_eval.export import SecretLeakError, assert_no_secrets, build_meta, trial_from_sample

    log = _run_trials(
        suite=suite,
        target=target,
        agent=agent,
        auth_token=auth_token,
        max_samples=max_samples,
        price=price,
        budget=budget,
        harness_git=harness_git,
    )
    task_hashes = suite_task_hashes(suite)
    trials = [trial_from_sample(sample, task_hashes, price) for sample in (log.samples or [])]
    meta = build_meta(
        log,
        trials,
        run_id=run_id,
        suite=suite,
        task_hashes=task_hashes,
        agent=agent,
        preflight_info=info,
        harness_git=harness_git,
        system_prompt_sha256=sha256_hex(agent["system_prompt"]),
        suite_sha256=suite_hash(suite),
        budget_plan=budget,
        price=price,
        target=target,
    )
    try:
        assert_no_secrets([ordered_json(meta)] + [ordered_json(t) for t in trials], secrets)
    except SecretLeakError as exc:
        fail(str(exc))
    write_run(run_dir, meta, trials)
    write_report(run_dir)
    _keep_inspect_log(log, run_dir, secrets)
    _print_run_summary(run_id, meta)
    if meta["status"] != "complete":
        raise typer.Exit(EXIT_UNDECIDED)
