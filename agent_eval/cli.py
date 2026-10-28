"""`agent-eval run` and `agent-eval compare`.

Exit codes (Phase 2): 0 = no regression, 1 = regression, 2 = the harness
couldn't decide (bad config, unreachable target, incomparable runs)."""

import asyncio
import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

import typer

from agent_eval.compare import EXIT_UNDECIDED, compare_runs
from agent_eval.envfile import parse_env_text, read_env_file
from agent_eval.records import ordered_json, sha256_hex, write_run
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

REPO_ROOT = Path(__file__).resolve().parent.parent
# Raw Inspect logs land here first (gitignored). One is copied next to the
# run records only after it's been checked for secrets.
RAW_LOG_DIR = REPO_ROOT / ".inspect-logs"

# Options shared by several commands. Defaults inside the checkout are
# shown relative to it, not as this machine's absolute path.
Gate = Literal["v1", "v2"]
EnvFile = Annotated[str, typer.Option(show_default="<repo>/.env")]
Prices = Annotated[str, typer.Option("--prices", show_default="<repo>/prices.yaml")]

# Plain tracebacks: Typer's pretty ones can print local variables, and
# `run` holds the keys from the env file in locals.
app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__,
                  pretty_exceptions_enable=False)


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


def _require(env: dict[str, str], name: str) -> str:
    value = env.get(name) or os.environ.get(name)
    if not value:
        raise SystemExit(f"error: {name} is not set (in the env file or the environment)")
    return value


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
    from agent_eval.budget import (  # Inspect is imported only for `run`
        BudgetError,
        load_prices,
        measured_tokens_per_trial,
        plan,
        price_for,
    )
    from agent_eval.export import (
        SecretLeakError,
        assert_no_secrets,
        build_meta,
        inspect_log_contains_secret,
        trial_from_sample,
    )
    from agent_eval.inspect_tasks import build_task
    from agent_eval.preflight import PreflightError, preflight

    # 1. Validate everything that costs nothing (Phase 4, step 1).
    try:
        suite = load_suite(Path(suite_path), tasks.split(",") if tasks else None)
    except (SuiteError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise typer.Exit(EXIT_UNDECIDED) from exc
    target = TARGETS.get(target_name or suite["target"])
    if target is None:
        print(f"error: unknown target {target_name or suite['target']!r}", file=sys.stderr)
        raise typer.Exit(EXIT_UNDECIDED)
    configuration = configuration or ("direct" if not target.get("gateway") else None)
    if target.get("gateway") and configuration not in ("gateway-off", "gateway-on"):
        print(f"error: target {target['name']!r} is a gateway: say --configuration gateway-off or gateway-on",
              file=sys.stderr)
        raise typer.Exit(EXIT_UNDECIDED)
    if not target.get("gateway") and configuration != "direct":
        print(f"error: target {target['name']!r} isn't a gateway, so its configuration is direct", file=sys.stderr)
        raise typer.Exit(EXIT_UNDECIDED)
    target = dict(target, configuration=configuration)
    if target_name and target.get("serves", target["name"]) != suite["target"]:
        print(f"error: target {target_name!r} doesn't serve suite target {suite['target']!r}",
              file=sys.stderr)
        raise typer.Exit(EXIT_UNDECIDED)
    from agent_eval.providers import is_secret_name, model_args_for, required_env

    env = read_env_file(Path(env_file))
    if target.get("auth_env_command"):
        try:
            out = subprocess.run(target["auth_env_command"], capture_output=True, text=True,
                                 timeout=30, check=True).stdout
        except (OSError, subprocess.SubprocessError):
            print(f"error: couldn't read the {target['name']} key; is it running? "
                  "(docker compose -f repro/compose.yaml up -d)", file=sys.stderr)
            raise typer.Exit(EXIT_UNDECIDED)
        env = {**env, **parse_env_text(out)}
    for name in required_env(model):
        _require(env, name)
    auth_token = _require(env, target["auth_env"]) if target.get("auth_env") else ""
    # Inspect's providers read their keys from this process's environment:
    # its openai-api/<service>/<model> route wants <SERVICE>_API_KEY and
    # <SERVICE>_BASE_URL, the native ones OPENAI_API_KEY and so on.
    for name, value in env.items():
        os.environ.setdefault(name, value)
    if "SUMOPOD_AI_API_KEY" in env:
        os.environ["SUMOPOD_API_KEY"] = env["SUMOPOD_AI_API_KEY"]
    os.environ.setdefault("INSPECT_DISPLAY", "none")
    # Every secret-looking value from .env, plus the target's key: none may
    # appear in the run records.
    secrets = [v for k, v in env.items() if v and is_secret_name(k)]
    secrets += [auth_token] if auth_token else []

    run_id = run_id or (
        datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        + "-" + model.rsplit("/", 1)[-1]
    )
    runs_dir = Path(out)
    run_dir = runs_dir / run_id
    if run_dir.exists():
        print(f"error: {run_dir} already exists; run records are never overwritten", file=sys.stderr)
        raise typer.Exit(EXIT_UNDECIDED)

    # 2. Budget (before anything is spent).
    n_trials = len(suite["tasks"]) * epochs
    try:
        prices = load_prices(Path(prices_path))
        price = price_for(model, prices)
        budget = plan(
            n_trials=n_trials, budget=budget_usd, price=price,
            tokens_per_trial=measured_tokens_per_trial(runs_dir, suite["suite"], model),
        )
    except BudgetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise typer.Exit(EXIT_UNDECIDED) from exc
    estimate = f"${budget['estimate_usd']:.2f}" if budget["estimate_usd"] is not None else "unpriced"
    print(f"plan: {n_trials} trials, estimate {estimate} ({budget['token_basis']} tokens), "
          f"budget ${budget_usd:.2f}")
    if plan_only:
        return

    from agent_eval.budget import SMOKE_MAX_TRIALS

    harness_git = _harness_git()
    if n_trials > SMOKE_MAX_TRIALS and (harness_git.endswith("-dirty") or harness_git == "unknown"):
        # A full run is evidence: it must trace back to one exact commit.
        print(f"error: harness checkout is {harness_git}; commit first (full runs need a clean "
              "tree, smoke runs don't)", file=sys.stderr)
        raise typer.Exit(EXIT_UNDECIDED)

    agent: dict[str, Any] = {
        "model": model,
        # Per provider: strict tool schemas off on the OpenAI-compatible
        # route, as in every published run (see model_args_for).
        "model_args": model_args_for(model),
        "system_prompt": (
            system_prompt if system_prompt
            else Path(system_prompt_file).read_text(encoding="utf-8").strip()
            if system_prompt_file
            # A suite can carry its own prompt; Pagila uses MCP-backbone's.
            else suite.get("system_prompt") or PAGILA_SYSTEM_PROMPT
        ),
        "tool_allowlist": None,
        "message_limit": message_limit,
        "time_limit": 120,
        "token_limit": 60_000,
        "epochs": epochs,
    }

    # 3. Preflight the target: tools, versions, data fingerprint.
    try:
        info = asyncio.run(preflight(target, auth_token, required_tools(suite)))
    except PreflightError as exc:
        print(f"error: preflight failed: {exc}", file=sys.stderr)
        raise typer.Exit(EXIT_UNDECIDED) from exc
    # The suite's expected answers were generated against one specific
    # dataset; grading against any other would score right answers wrong.
    mismatch = data_mismatch(suite, info["data_fingerprint"], info.get("session_utc_offset"))
    if mismatch:
        print(f"error: {mismatch}", file=sys.stderr)
        raise typer.Exit(EXIT_UNDECIDED)
    if exclude_tools:
        # A deliberately degraded agent (the regression proof): the same
        # model and prompt with tools taken away. Recorded in the meta, so
        # `compare` names it as the difference between the runs.
        excluded = set(exclude_tools.split(","))
        unknown = excluded - set(info["tool_names"])
        if unknown or excluded & required_tools(suite):
            print(f"error: can't exclude {sorted(excluded)}: unknown {sorted(unknown)}, or "
                  f"needed by the graders {sorted(excluded & required_tools(suite))}", file=sys.stderr)
            raise typer.Exit(EXIT_UNDECIDED)
        agent["tool_allowlist"] = [t for t in info["tool_names"] if t not in excluded]

    from inspect_ai import eval as inspect_eval  # pyright: ignore[reportUnknownVariableType]
    from inspect_ai.model import ModelCost

    task_hashes = suite_task_hashes(suite)
    task = build_task(suite, target, agent, auth_token)
    cost_args: dict[str, Any] = {}
    if price is not None:
        cost_args = {
            "cost_limit": budget["per_trial_cap_usd"],
            "model_cost_config": {
                model: ModelCost(
                    input=float(price["input"]), output=float(price["output"]),
                    # Cache writes cost the full input price; reads use the
                    # cached price when the table has one.
                    input_cache_write=float(price["input"]),
                    input_cache_read=float(price.get("cache_read", price["input"])),
                )
            },
        }
    [log] = inspect_eval(
        task,
        model=model,
        model_args=agent["model_args"],
        epochs=epochs,
        max_samples=max_samples,
        # Provider hiccups: retry a failed trial, then record it as an
        # error rather than aborting the run, unless errors pass the share
        # that makes a run incomplete anyway (then stop spending).
        retry_on_error=2,
        fail_on_error=0.1,
        log_dir=str(RAW_LOG_DIR),
        display="none",
        **cost_args,
    )
    trials = [trial_from_sample(s, task_hashes, price) for s in (log.samples or [])]
    meta = build_meta(
        log, trials, run_id=run_id, suite=suite, task_hashes=task_hashes, agent=agent,
        preflight_info=info, harness_git=harness_git,
        system_prompt_sha256=sha256_hex(agent["system_prompt"]),
        suite_sha256=suite_hash(suite), budget_plan=budget, price=price, target=target,
    )
    try:
        assert_no_secrets([ordered_json(meta)] + [ordered_json(t) for t in trials], secrets)
    except SecretLeakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise typer.Exit(EXIT_UNDECIDED) from exc
    write_run(run_dir, meta, trials)
    _write_report(run_dir)

    raw_log = Path(log.location)
    if inspect_log_contains_secret(raw_log, secrets):
        print(f"note: Inspect log contains a secret; kept only in {RAW_LOG_DIR.name}/")
    else:
        shutil.copy2(raw_log, run_dir / "inspect.eval")

    totals = meta["totals"]
    print(
        f"{run_id}: {meta['status']} | strict {totals['pass_strict']}/{totals['trials']} "
        f"| errors {totals['errors']} | tokens {totals['input_tokens']}+{totals['output_tokens']}"
    )
    if meta["status"] != "complete":
        raise typer.Exit(EXIT_UNDECIDED)


@app.command(help="fill a suite's expected answers via the endpoint")
def generate_expected(
    source: str, output: str, env_file: EnvFile = str(REPO_ROOT / ".env")
) -> None:
    from agent_eval.expected import ExpectedError, generate, write_suite

    source_path = Path(source)
    import yaml

    target = TARGETS[yaml.safe_load(source_path.read_text(encoding="utf-8"))["target"]]
    auth_token = _require(read_env_file(Path(env_file)), target["auth_env"])
    try:
        suite = asyncio.run(generate(source_path, target, auth_token))
    except ExpectedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise typer.Exit(EXIT_UNDECIDED) from exc
    write_suite(suite, Path(output))
    print(f"wrote {output}: {len(suite['tasks'])} tasks, suite sha256 {suite_hash(suite)}")


@app.command(help="rebuild a run's records from its saved Inspect log")
def reexport(run_dir: Path, prices_path: Prices = str(REPO_ROOT / "prices.yaml")) -> None:
    from agent_eval.budget import load_prices, price_for
    from agent_eval.export import reexport as rebuild
    from agent_eval.records import RecordError, load_run

    try:
        record = load_run(run_dir)  # refuses a hand-edited run before rebuilding it
    except RecordError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise typer.Exit(EXIT_UNDECIDED) from exc
    log_path = run_dir / "inspect.eval"
    if not log_path.is_file():
        print(f"error: {log_path} not found; nothing to rebuild from", file=sys.stderr)
        raise typer.Exit(EXIT_UNDECIDED)
    price = price_for(record.meta["agent"]["model"], load_prices(Path(prices_path)))
    at = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    meta, trials = rebuild(record.meta, log_path, price, at)
    write_run(run_dir, meta, trials)
    _write_report(run_dir)
    print(f"{run_dir.name}: rebuilt {len(trials)} trials with export v{meta['export_version']}")


def _write_report(run_dir: Path) -> None:
    from agent_eval.records import load_run
    from agent_eval.report import render

    (run_dir / "report.md").write_text(render(load_run(run_dir)), encoding="utf-8")


@app.command(help="render report.md from a run's records")
def report(
    run_dir: Path,
    check: Annotated[bool, typer.Option("--check", help="fail if report.md is out of date")] = False,
) -> None:
    """Renders report.md from the records; with --check, fails (exit 1) if
    the committed report doesn't match what the records render to."""
    from agent_eval.records import RecordError, load_run
    from agent_eval.report import render

    try:
        text = render(load_run(run_dir))
    except RecordError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise typer.Exit(EXIT_UNDECIDED) from exc
    path = run_dir / "report.md"
    if check:
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            print(f"{path}: out of date with its records (run `agent-eval report {run_dir}`)")
            raise typer.Exit(1)
        print(f"{path}: up to date")
        return
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")


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
    import json

    from agent_eval.confirm import ConfirmError, plan

    try:
        p = plan(baseline, candidate, REPO_ROOT / "suites", epochs, gate)
    except ConfirmError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise typer.Exit(EXIT_UNDECIDED) from exc
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    ids = {"baseline": f"confirm-{stamp}-baseline", "candidate": f"confirm-{stamp}-candidate"}
    print(f"confirming {p['candidate']} vs {p['baseline']}: {len(p['tasks'])} dropped tasks "
          f"x {p['epochs']} attempts, both agents: {p['tasks']}")
    for side in ("baseline", "candidate"):
        cmd = [sys.executable, "-m", "agent_eval.cli", "run", *p[f"{side}_args"],
               "--run-id", ids[side], "--out", out, "--budget", str(budget)]
        code = subprocess.run(cmd, cwd=REPO_ROOT, check=False).returncode
        if code != 0:
            print(f"error: the {side} confirmation run failed (exit {code})", file=sys.stderr)
            raise typer.Exit(EXIT_UNDECIDED)
    result = compare_runs(Path(out) / ids["baseline"], Path(out) / ids["candidate"], gate)
    record = {**{k: v for k, v in p.items() if not k.endswith("_args")}, "runs": ids,
              "verdict": result.verdict, "exit_code": result.exit_code,
              "point": result.point, "interval": result.interval, "reasons": result.reasons}
    confirmations = REPO_ROOT / "confirmations"
    confirmations.mkdir(exist_ok=True)
    (confirmations / f"{stamp}.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
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
    from agent_eval.publish import apply_readme, render

    results_md, block = render(REPO_ROOT)
    readme_path, results_path = REPO_ROOT / "README.md", REPO_ROOT / "RESULTS.md"
    readme = apply_readme(readme_path.read_text(encoding="utf-8"), block)
    if check:
        stale = [p.name for p, text in ((results_path, results_md), (readme_path, readme))
                 if not p.is_file() or p.read_text(encoding="utf-8") != text]
        if stale:
            print(f"out of date with the run records: {stale} (run `agent-eval publish`)")
            raise typer.Exit(1)
        print("RESULTS.md and README results are up to date")
        return
    results_path.write_text(results_md, encoding="utf-8")
    readme_path.write_text(readme, encoding="utf-8")
    print("wrote RESULTS.md and the README results block")


@app.command(help="compare a candidate run with a baseline")
def compare(
    baseline: Path,
    candidate: Path,
    gate: Annotated[Gate, typer.Option(
        help="decision rule (ADR-001); v1 for comparisons pre-registered with it")] = "v2",
) -> None:
    result = compare_runs(baseline, candidate, gate)
    print(f"verdict: {result.verdict} (exit {result.exit_code}, gate {result.gate})")
    if result.gate_verdicts:
        print("  all gates: " + ", ".join(f"{g}: {v}" for g, v in result.gate_verdicts.items()))
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
    for task, (b, c) in result.per_task.items():
        if b != c:
            print(f"  {task}: {b:.0%} -> {c:.0%}")
    raise typer.Exit(result.exit_code)


def main(argv: list[str] | None = None) -> int:
    """The `agent-eval` entry point. Returns the exit code instead of
    exiting, so tests can call it in-process."""
    try:
        app(args=argv, prog_name="agent-eval")
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        raise  # `_require`'s message: Python prints it and exits 1, as before
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
