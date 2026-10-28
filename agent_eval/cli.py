"""The `agent-eval` command line, on Typer: one function per subcommand.

Each command reads its options, calls the modules that do the work
(suites, budget, preflight, export, compare, report, publish) and turns
the outcome into printed lines and an exit code. Nothing here grades or
decides a verdict; that lives in grading.py and compare.py.

Exit codes are shared by every command: 0 = ok or no regression,
1 = a regression or an out-of-date file, 2 = the harness couldn't decide
(bad config, unreachable target, incomparable runs). `main` returns the
code instead of exiting, so the tests can call it in-process.

Inspect AI and the MCP client load slowly, so they're imported inside the
functions that use them: `report`, `publish` and `compare`, which CI runs
on every push, never load them.
"""

import asyncio
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, NoReturn

import typer
import yaml

from agent_eval.budget import (
    SMOKE_MAX_TRIALS,
    BudgetError,
    load_prices,
    measured_tokens_per_trial,
    price_for,
)
from agent_eval.budget import plan as plan_budget
from agent_eval.compare import EXIT_UNDECIDED, Comparison, compare_runs
from agent_eval.confirm import ConfirmError
from agent_eval.confirm import plan as plan_confirmation
from agent_eval.envfile import parse_env_text, read_env_file
from agent_eval.providers import is_secret_name, model_args_for, required_env
from agent_eval.publish import apply_readme
from agent_eval.publish import render as render_results
from agent_eval.records import RecordError, load_run, ordered_json, sha256_hex, write_run
from agent_eval.report import render as render_report
from agent_eval.suites import (
    PAGILA_SYSTEM_PROMPT,
    SuiteError,
    data_mismatch,
    load_suite,
    required_tools,
    suite_hash,
    suite_task_hashes,
)
from agent_eval.targets import TARGETS

if TYPE_CHECKING:  # for the type checker only: importing Inspect is slow
    from inspect_ai.log import EvalLog

REPO_ROOT = Path(__file__).resolve().parent.parent
# Raw Inspect logs land here first (gitignored). One is copied next to the
# run records only after it's been checked for secrets.
RAW_LOG_DIR = REPO_ROOT / ".inspect-logs"

# `report --check` and `publish --check`: a committed file differs from
# what its records render to.
EXIT_OUT_OF_DATE = 1

# Per-trial caps, recorded in every run's meta.json. A trial that hits one
# is scored as a fail, not retried.
TRIAL_TIME_LIMIT_S = 120
TRIAL_TOKEN_LIMIT = 60_000
# Provider hiccups: a failed trial is retried this many times, then
# recorded as an error rather than aborting the run.
RETRIES_PER_TRIAL = 2
# The confirmation runs and default run ids are stamped with UTC time.
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"

# The text of `agent-eval --help`.
HELP = """`agent-eval run` and `agent-eval compare`.

Exit codes (Phase 2): 0 = no regression, 1 = regression, 2 = the harness
couldn't decide (bad config, unreachable target, incomparable runs)."""

# Options shared by several commands. Defaults inside the checkout are
# shown relative to it, not as this machine's absolute path.
Gate = Literal["v1", "v2"]
EnvFile = Annotated[str, typer.Option(show_default="<repo>/.env")]
Prices = Annotated[str, typer.Option("--prices", show_default="<repo>/prices.yaml")]

# Plain tracebacks: Typer's pretty ones can print local variables, and
# `run` holds the keys from the env file in locals.
app = typer.Typer(add_completion=False, no_args_is_help=True, help=HELP,
                  pretty_exceptions_enable=False)


# Shared helpers


def _fail(message: str) -> NoReturn:
    """Print an error and exit 2: the harness couldn't decide."""
    print(f"error: {message}", file=sys.stderr)
    raise typer.Exit(EXIT_UNDECIDED)


def _require_variable(env: dict[str, str], name: str) -> str:
    """A value from the env file, else from the environment. Missing, it
    stops the command with exit 1 and names the variable."""
    value = env.get(name) or os.environ.get(name)
    if not value:
        raise SystemExit(f"error: {name} is not set (in the env file or the environment)")
    return value


def _utc_stamp() -> str:
    return datetime.datetime.now(datetime.UTC).strftime(STAMP_FORMAT)


def _harness_git() -> str:
    """The exact harness commit, `-dirty` if the checkout has edits. In the
    container (no .git) it's the commit stamped in at build time."""
    stamped = os.environ.get("AGENT_EVAL_HARNESS_GIT")
    if stamped:
        return stamped
    try:
        out = subprocess.run(
            ["git", "describe", "--always", "--dirty", "--abbrev=12"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=5, check=True,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _write_report(run_dir: Path) -> None:
    (run_dir / "report.md").write_text(render_report(load_run(run_dir)), encoding="utf-8")


# run: the steps, in the order the command takes them


def _load_suite(suite_path: str, tasks: str | None) -> dict[str, Any]:
    try:
        return load_suite(Path(suite_path), tasks.split(",") if tasks else None)
    except (SuiteError, OSError) as exc:
        _fail(str(exc))


def _choose_target(
    suite: dict[str, Any], target_name: str | None, configuration: str | None
) -> dict[str, Any]:
    """The target to run against, with the configuration it's reached in.
    Gateway targets must say whether the gateway is on or off; any other
    target is reached directly."""
    name = target_name or suite["target"]
    target = TARGETS.get(name)
    if target is None:
        _fail(f"unknown target {name!r}")
    is_gateway = bool(target.get("gateway"))
    configuration = configuration or (None if is_gateway else "direct")
    if is_gateway and configuration not in ("gateway-off", "gateway-on"):
        _fail(f"target {target['name']!r} is a gateway: say --configuration gateway-off or gateway-on")
    if not is_gateway and configuration != "direct":
        _fail(f"target {target['name']!r} isn't a gateway, so its configuration is direct")
    # --target can only swap in another server for the same suite (a local
    # copy, a gateway in front of it), never a different one.
    if target_name and target.get("serves", target["name"]) != suite["target"]:
        _fail(f"target {target_name!r} doesn't serve suite target {suite['target']!r}")
    return dict(target, configuration=configuration)


def _read_env(target: dict[str, Any], env_file: str) -> dict[str, str]:
    """The env file's variables, plus the target's key when the target
    hands it out by command (the local reproduction stack)."""
    env = read_env_file(Path(env_file))
    if not target.get("auth_env_command"):
        return env
    try:
        out = subprocess.run(target["auth_env_command"], capture_output=True, text=True,
                             timeout=30, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        _fail(f"couldn't read the {target['name']} key; is it running? "
              "(docker compose -f repro/compose.yaml up -d)")
    return {**env, **parse_env_text(out)}


def _check_keys(env: dict[str, str], target: dict[str, Any], model: str) -> str:
    """Checks the model's keys are set and returns the target's key ("" if
    the target needs none)."""
    for name in required_env(model):
        _require_variable(env, name)
    if not target.get("auth_env"):
        return ""
    return _require_variable(env, target["auth_env"])


def _export_keys_for_inspect(env: dict[str, str]) -> None:
    """Inspect's providers read their keys from this process's environment:
    its openai-api/<service>/<model> route wants <SERVICE>_API_KEY and
    <SERVICE>_BASE_URL, the native ones OPENAI_API_KEY and so on."""
    for name, value in env.items():
        os.environ.setdefault(name, value)
    if "SUMOPOD_AI_API_KEY" in env:
        os.environ["SUMOPOD_API_KEY"] = env["SUMOPOD_AI_API_KEY"]
    os.environ.setdefault("INSPECT_DISPLAY", "none")


def _secrets_to_redact(env: dict[str, str], auth_token: str) -> list[str]:
    """Every secret-looking value from the env file, plus the target's key:
    none may appear in the run records."""
    secrets = [value for name, value in env.items() if value and is_secret_name(name)]
    if auth_token:
        secrets.append(auth_token)
    return secrets


def _new_run_dir(out: str, run_id: str) -> Path:
    run_dir = Path(out) / run_id
    if run_dir.exists():
        _fail(f"{run_dir} already exists; run records are never overwritten")
    return run_dir


def _plan_spend(
    *, model: str, prices_path: str, n_trials: int, budget_usd: float, runs_dir: Path, suite_name: str
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """The model's price (None if unpriced) and the budget plan, before
    anything is spent. Refuses a run the budget can't cover."""
    try:
        price = price_for(model, load_prices(Path(prices_path)))
        budget = plan_budget(
            n_trials=n_trials, budget=budget_usd, price=price,
            tokens_per_trial=measured_tokens_per_trial(runs_dir, suite_name, model),
        )
    except BudgetError as exc:
        _fail(str(exc))
    return price, budget


def _print_plan(n_trials: int, budget: dict[str, Any], budget_usd: float) -> None:
    if budget["estimate_usd"] is None:
        estimate = "unpriced"
    else:
        estimate = f"${budget['estimate_usd']:.2f}"
    print(f"plan: {n_trials} trials, estimate {estimate} ({budget['token_basis']} tokens), "
          f"budget ${budget_usd:.2f}")


def _traceable_commit(n_trials: int) -> str:
    """The harness commit to record. A full run is evidence, so it must
    trace back to one exact commit; smoke runs may come from a dirty tree."""
    harness_git = _harness_git()
    is_traceable = not (harness_git.endswith("-dirty") or harness_git == "unknown")
    if n_trials > SMOKE_MAX_TRIALS and not is_traceable:
        _fail(f"harness checkout is {harness_git}; commit first (full runs need a clean "
              "tree, smoke runs don't)")
    return harness_git


def _system_prompt(
    suite: dict[str, Any], system_prompt: str | None, system_prompt_file: str | None
) -> str:
    if system_prompt:
        return system_prompt
    if system_prompt_file:
        return Path(system_prompt_file).read_text(encoding="utf-8").strip()
    # A suite can carry its own prompt; Pagila uses MCP-backbone's.
    return suite.get("system_prompt") or PAGILA_SYSTEM_PROMPT


def _preflight_target(target: dict[str, Any], auth_token: str, suite: dict[str, Any]) -> dict[str, Any]:
    """Checks the target before any trial: its tools, versions and data.
    Returns what it found, which goes into the run's meta.json."""
    from agent_eval.preflight import PreflightError, preflight  # the MCP client: slow to import

    try:
        info = asyncio.run(preflight(target, auth_token, required_tools(suite)))
    except PreflightError as exc:
        _fail(f"preflight failed: {exc}")
    # The suite's expected answers were generated against one specific
    # dataset; grading against any other would score right answers wrong.
    mismatch = data_mismatch(suite, info["data_fingerprint"], info.get("session_utc_offset"))
    if mismatch:
        _fail(mismatch)
    return info


def _tool_allowlist(exclude_tools: str, tool_names: list[str], suite: dict[str, Any]) -> list[str]:
    """The target's tools minus the excluded ones: a deliberately degraded
    agent (the regression proof). Recorded in the meta, so `compare` names
    it as the difference between the runs."""
    excluded = set(exclude_tools.split(","))
    unknown = excluded - set(tool_names)
    needed_by_graders = excluded & required_tools(suite)
    if unknown or needed_by_graders:
        _fail(f"can't exclude {sorted(excluded)}: unknown {sorted(unknown)}, or "
              f"needed by the graders {sorted(needed_by_graders)}")
    return [name for name in tool_names if name not in excluded]


def _cost_limits(model: str, price: dict[str, Any] | None, budget: dict[str, Any]) -> dict[str, Any]:
    """Inspect's per-trial cost cap and prices; none for an unpriced model."""
    from inspect_ai.model import ModelCost

    if price is None:
        return {}
    cost = ModelCost(
        input=float(price["input"]), output=float(price["output"]),
        # Cache writes cost the full input price; reads use the cached
        # price when the table has one.
        input_cache_write=float(price["input"]),
        input_cache_read=float(price.get("cache_read", price["input"])),
    )
    return {"cost_limit": budget["per_trial_cap_usd"], "model_cost_config": {model: cost}}


def _run_trials(
    *, suite: dict[str, Any], target: dict[str, Any], agent: dict[str, Any], auth_token: str,
    max_samples: int, price: dict[str, Any] | None, budget: dict[str, Any],
) -> "EvalLog":
    """Runs every trial through Inspect and returns its log. This is the
    step that spends money."""
    from inspect_ai import eval as inspect_eval  # pyright: ignore[reportUnknownVariableType]

    from agent_eval.export import INCOMPLETE_ERROR_SHARE
    from agent_eval.inspect_tasks import build_task

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
def run(
    suite_path: Annotated[str, typer.Option("--suite", show_default="<repo>/suites/pagila.yaml")] = (
        str(REPO_ROOT / "suites" / "pagila.yaml")
    ),
    tasks: Annotated[str | None, typer.Option(
        help="comma-separated task ids (e.g. a smoke suite)")] = None,
    model: Annotated[str, typer.Option()] = "openai-api/sumopod/gpt-5-mini",
    target_name: Annotated[str | None, typer.Option(
        "--target",
        help="run against another target serving the suite's (e.g. mcp-backbone-local)")] = None,
    configuration: Annotated[Literal["direct", "gateway-off", "gateway-on"] | None, typer.Option(
        help="how the run reaches the tools (Project 4b); "
        "gateway targets need gateway-off or gateway-on")] = None,
    epochs: Annotated[int, typer.Option()] = 5,
    max_samples: Annotated[int, typer.Option(help="trials running at once")] = 4,
    budget_usd: Annotated[float, typer.Option(
        "--budget", help="US dollars for the whole run")] = 5.0,
    prices_path: Prices = str(REPO_ROOT / "prices.yaml"),
    plan_only: Annotated[bool, typer.Option("--plan-only", help="print the plan and stop")] = False,
    exclude_tools: Annotated[str | None, typer.Option(
        help="comma-separated tools to withhold (a degraded agent)")] = None,
    system_prompt_file: Annotated[str | None, typer.Option(
        help="replace the suite's system prompt (a degraded agent)")] = None,
    # Exact text, used by `confirm`.
    system_prompt: Annotated[str | None, typer.Option(hidden=True)] = None,
    message_limit: Annotated[int, typer.Option(
        help="messages per trial before the trial stops as a fail (default 20)")] = 20,
    out: Annotated[str, typer.Option()] = "runs",
    run_id: Annotated[str | None, typer.Option()] = None,
    env_file: EnvFile = str(REPO_ROOT / ".env"),
) -> None:
    # 1. Validate everything that costs nothing (Phase 4, step 1).
    suite = _load_suite(suite_path, tasks)
    target = _choose_target(suite, target_name, configuration)
    env = _read_env(target, env_file)
    auth_token = _check_keys(env, target, model)
    _export_keys_for_inspect(env)
    secrets = _secrets_to_redact(env, auth_token)
    run_id = run_id or f"{_utc_stamp()}-{model.rsplit('/', 1)[-1]}"
    run_dir = _new_run_dir(out, run_id)

    # 2. Budget (before anything is spent).
    n_trials = len(suite["tasks"]) * epochs
    price, budget = _plan_spend(model=model, prices_path=prices_path, n_trials=n_trials,
                                budget_usd=budget_usd, runs_dir=Path(out), suite_name=suite["suite"])
    _print_plan(n_trials, budget, budget_usd)
    if plan_only:
        return
    harness_git = _traceable_commit(n_trials)
    agent: dict[str, Any] = {
        "model": model,
        # Per provider: strict tool schemas off on the OpenAI-compatible
        # route, as in every published run (see model_args_for).
        "model_args": model_args_for(model),
        "system_prompt": _system_prompt(suite, system_prompt, system_prompt_file),
        "tool_allowlist": None,
        "message_limit": message_limit,
        "time_limit": TRIAL_TIME_LIMIT_S,
        "token_limit": TRIAL_TOKEN_LIMIT,
        "epochs": epochs,
    }

    # 3. Preflight the target: tools, versions, data fingerprint.
    info = _preflight_target(target, auth_token, suite)
    if exclude_tools:
        agent["tool_allowlist"] = _tool_allowlist(exclude_tools, info["tool_names"], suite)

    # 4. Run the trials, then record them (never a secret).
    from agent_eval.export import SecretLeakError, assert_no_secrets, build_meta, trial_from_sample

    log = _run_trials(suite=suite, target=target, agent=agent, auth_token=auth_token,
                      max_samples=max_samples, price=price, budget=budget)
    task_hashes = suite_task_hashes(suite)
    trials = [trial_from_sample(sample, task_hashes, price) for sample in (log.samples or [])]
    meta = build_meta(
        log, trials, run_id=run_id, suite=suite, task_hashes=task_hashes, agent=agent,
        preflight_info=info, harness_git=harness_git,
        system_prompt_sha256=sha256_hex(agent["system_prompt"]),
        suite_sha256=suite_hash(suite), budget_plan=budget, price=price, target=target,
    )
    try:
        assert_no_secrets([ordered_json(meta)] + [ordered_json(t) for t in trials], secrets)
    except SecretLeakError as exc:
        _fail(str(exc))
    write_run(run_dir, meta, trials)
    _write_report(run_dir)
    _keep_inspect_log(log, run_dir, secrets)
    _print_run_summary(run_id, meta)
    if meta["status"] != "complete":
        raise typer.Exit(EXIT_UNDECIDED)


# The other commands


@app.command(help="fill a suite's expected answers via the endpoint")
def generate_expected(
    source: str, output: str, env_file: EnvFile = str(REPO_ROOT / ".env")
) -> None:
    from agent_eval.expected import ExpectedError, generate, write_suite  # the MCP client

    source_path = Path(source)
    target = TARGETS[yaml.safe_load(source_path.read_text(encoding="utf-8"))["target"]]
    auth_token = _require_variable(read_env_file(Path(env_file)), target["auth_env"])
    try:
        suite = asyncio.run(generate(source_path, target, auth_token))
    except ExpectedError as exc:
        _fail(str(exc))
    write_suite(suite, Path(output))
    print(f"wrote {output}: {len(suite['tasks'])} tasks, suite sha256 {suite_hash(suite)}")


@app.command(help="rebuild a run's records from its saved Inspect log")
def reexport(run_dir: Path, prices_path: Prices = str(REPO_ROOT / "prices.yaml")) -> None:
    from agent_eval.export import reexport as rebuild_records  # imports Inspect

    try:
        record = load_run(run_dir)  # refuses a hand-edited run before rebuilding it
    except RecordError as exc:
        _fail(str(exc))
    log_path = run_dir / "inspect.eval"
    if not log_path.is_file():
        _fail(f"{log_path} not found; nothing to rebuild from")
    price = price_for(record.meta["agent"]["model"], load_prices(Path(prices_path)))
    rebuilt_at = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    meta, trials = rebuild_records(record.meta, log_path, price, rebuilt_at)
    write_run(run_dir, meta, trials)
    _write_report(run_dir)
    print(f"{run_dir.name}: rebuilt {len(trials)} trials with export v{meta['export_version']}")


@app.command(help="render report.md from a run's records")
def report(
    run_dir: Path,
    check: Annotated[bool, typer.Option("--check", help="fail if report.md is out of date")] = False,
) -> None:
    """Renders report.md from the records; with --check, fails (exit 1) if
    the committed report doesn't match what the records render to."""
    try:
        text = render_report(load_run(run_dir))
    except RecordError as exc:
        _fail(str(exc))
    path = run_dir / "report.md"
    if not check:
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")
        return
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        print(f"{path}: out of date with its records (run `agent-eval report {run_dir}`)")
        raise typer.Exit(EXIT_OUT_OF_DATE)
    print(f"{path}: up to date")


def _start_confirmation_run(side: str, run_args: list[str], run_id: str, out: str, budget: float) -> None:
    """One side's rerun, as a separate `agent-eval run` process, so it is
    recorded exactly like any other run."""
    command = [sys.executable, "-m", "agent_eval.cli", "run", *run_args,
               "--run-id", run_id, "--out", out, "--budget", str(budget)]
    code = subprocess.run(command, cwd=REPO_ROOT, check=False).returncode
    if code != 0:
        _fail(f"the {side} confirmation run failed (exit {code})")


def _save_confirmation(
    stamp: str, confirmation: dict[str, Any], run_ids: dict[str, str], result: Comparison
) -> None:
    """Records the confirmation and its verdict in confirmations/<stamp>.json."""
    record = {name: value for name, value in confirmation.items() if not name.endswith("_args")}
    record.update({
        "runs": run_ids, "verdict": result.verdict, "exit_code": result.exit_code,
        "point": result.point, "interval": result.interval, "reasons": result.reasons,
    })
    folder = REPO_ROOT / "confirmations"
    folder.mkdir(exist_ok=True)
    (folder / f"{stamp}.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


@app.command(help="rerun the dropped tasks of an inconclusive comparison")
def confirm(
    baseline: Path,
    candidate: Path,
    epochs: Annotated[int, typer.Option()] = 10,
    gate: Annotated[Gate, typer.Option()] = "v2",
    budget: Annotated[float, typer.Option(help="US dollars per confirmation run")] = 5.0,
    out: Annotated[str, typer.Option()] = "runs",
) -> None:
    """Reruns the dropped tasks of an inconclusive comparison for both
    agents and decides on the fresh trials alone (agent_eval/confirm.py)."""
    try:
        confirmation = plan_confirmation(baseline, candidate, REPO_ROOT / "suites", epochs, gate)
    except ConfirmError as exc:
        _fail(str(exc))
    stamp = _utc_stamp()
    run_ids = {"baseline": f"confirm-{stamp}-baseline", "candidate": f"confirm-{stamp}-candidate"}
    print(f"confirming {confirmation['candidate']} vs {confirmation['baseline']}: "
          f"{len(confirmation['tasks'])} dropped tasks x {confirmation['epochs']} attempts, "
          f"both agents: {confirmation['tasks']}")
    for side in ("baseline", "candidate"):
        _start_confirmation_run(side, confirmation[f"{side}_args"], run_ids[side], out, budget)
    result = compare_runs(Path(out) / run_ids["baseline"], Path(out) / run_ids["candidate"], gate)
    _save_confirmation(stamp, confirmation, run_ids, result)
    print(f"confirmation verdict (fresh trials only): {result.verdict} (exit {result.exit_code})")
    if result.interval is not None and result.point is not None:
        print(f"  change {result.point:+.1%} (95% interval {result.interval[0]:+.1%} to "
              f"{result.interval[1]:+.1%})")
    for line in result.reasons:
        print(f"  reason: {line}")
    raise typer.Exit(result.exit_code)


@app.command(help="render RESULTS.md and the README results from records")
def publish(
    check: Annotated[bool, typer.Option("--check", help="fail if they're out of date")] = False,
) -> None:
    """Renders RESULTS.md and the README's results block from the records
    named in results.yaml; with --check, fails if either is out of date."""
    results_md, block = render_results(REPO_ROOT)
    readme_path, results_path = REPO_ROOT / "README.md", REPO_ROOT / "RESULTS.md"
    readme = apply_readme(readme_path.read_text(encoding="utf-8"), block)
    if not check:
        results_path.write_text(results_md, encoding="utf-8")
        readme_path.write_text(readme, encoding="utf-8")
        print("wrote RESULTS.md and the README results block")
        return
    stale: list[str] = []
    for path, expected in ((results_path, results_md), (readme_path, readme)):
        if not path.is_file() or path.read_text(encoding="utf-8") != expected:
            stale.append(path.name)
    if stale:
        print(f"out of date with the run records: {stale} (run `agent-eval publish`)")
        raise typer.Exit(EXIT_OUT_OF_DATE)
    print("RESULTS.md and README results are up to date")


def _print_comparison(result: Comparison) -> None:
    print(f"verdict: {result.verdict} (exit {result.exit_code}, gate {result.gate})")
    if result.gate_verdicts:
        verdicts = [f"{gate}: {verdict}" for gate, verdict in result.gate_verdicts.items()]
        print("  all gates: " + ", ".join(verdicts))
    if result.interval is not None and result.point is not None:
        low, high = result.interval
        print(f"  suite strict pass rate change: {result.point:+.1%} "
              f"(95% interval {low:+.1%} to {high:+.1%})")
    for line in result.warnings:
        print(f"  warning: {line}")
    if result.missing:
        print(f"  only in one run (not compared): {result.missing}")
    for line in result.reasons:
        print(f"  reason: {line}")
    for line in result.differences:
        print(f"  differs: {line}")
    for line in result.regrade_mismatches:
        print(f"  regraded differently: {line}")
    for task, (baseline_rate, candidate_rate) in result.per_task.items():
        if baseline_rate != candidate_rate:
            print(f"  {task}: {baseline_rate:.0%} -> {candidate_rate:.0%}")


@app.command(help="compare a candidate run with a baseline")
def compare(
    baseline: Path,
    candidate: Path,
    gate: Annotated[Gate, typer.Option(
        help="decision rule (ADR-001); v1 for comparisons pre-registered with it")] = "v2",
) -> None:
    result = compare_runs(baseline, candidate, gate)
    _print_comparison(result)
    raise typer.Exit(result.exit_code)


def main(argv: list[str] | None = None) -> int:
    """The `agent-eval` entry point. Returns the exit code instead of
    exiting, so tests can call it in-process."""
    try:
        app(args=argv, prog_name="agent-eval")
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        raise  # `_require_variable`'s message: Python prints it and exits 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
