"""`agent-eval run` and `agent-eval compare`.

Exit codes (Phase 2): 0 = no regression, 1 = regression, 2 = the harness
couldn't decide (bad config, unreachable target, incomparable runs)."""

import argparse
import asyncio
import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_eval.compare import EXIT_UNDECIDED, compare_runs
from agent_eval.envfile import read_env_file
from agent_eval.records import ordered_json, sha256_hex, write_run
from agent_eval.suites import (
    PAGILA_SYSTEM_PROMPT,
    SuiteError,
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


def _harness_git() -> str:
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


def cmd_run(args: argparse.Namespace) -> int:
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
        suite = load_suite(Path(args.suite), args.tasks.split(",") if args.tasks else None)
    except (SuiteError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_UNDECIDED
    target = TARGETS.get(suite["target"])
    if target is None:
        print(f"error: unknown target {suite['target']!r}", file=sys.stderr)
        return EXIT_UNDECIDED
    env = read_env_file(Path(args.env_file))
    sumopod_key = _require(env, "SUMOPOD_AI_API_KEY")
    base_url = _require(env, "SUMOPOD_BASE_URL")
    auth_token = _require(env, target["auth_env"])
    # Inspect's openai-api/<service>/<model> provider reads <SERVICE>_API_KEY
    # and <SERVICE>_BASE_URL from this process's environment.
    os.environ["SUMOPOD_API_KEY"] = sumopod_key
    os.environ["SUMOPOD_BASE_URL"] = base_url
    os.environ.setdefault("INSPECT_DISPLAY", "none")
    secrets = [sumopod_key, auth_token]

    run_id = args.run_id or (
        datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        + "-" + args.model.rsplit("/", 1)[-1]
    )
    runs_dir = Path(args.out)
    run_dir = runs_dir / run_id
    if run_dir.exists():
        print(f"error: {run_dir} already exists; run records are never overwritten", file=sys.stderr)
        return EXIT_UNDECIDED

    # 2. Budget (before anything is spent).
    n_trials = len(suite["tasks"]) * args.epochs
    try:
        prices = load_prices(Path(args.prices))
        price = price_for(args.model, prices)
        budget = plan(
            n_trials=n_trials, budget=args.budget, price=price,
            tokens_per_trial=measured_tokens_per_trial(runs_dir, suite["suite"], args.model),
        )
    except BudgetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_UNDECIDED
    estimate = f"${budget['estimate_usd']:.2f}" if budget["estimate_usd"] is not None else "unpriced"
    print(f"plan: {n_trials} trials, estimate {estimate} ({budget['token_basis']} tokens), "
          f"budget ${args.budget:.2f}")
    if args.plan_only:
        return 0

    agent: dict[str, Any] = {
        "model": args.model,
        # MCP-backbone's optional api_key parameter fails OpenAI strict
        # mode with a 400 (Phase 4 revision), so strict schemas are off.
        "model_args": {"strict_tools": False},
        "system_prompt": PAGILA_SYSTEM_PROMPT,
        "tool_allowlist": None,
        "message_limit": 20,
        "time_limit": 120,
        "token_limit": 60_000,
        "epochs": args.epochs,
    }

    # 3. Preflight the target: tools, versions, data fingerprint.
    try:
        info = asyncio.run(preflight(target, auth_token, required_tools(suite)))
    except PreflightError as exc:
        print(f"error: preflight failed: {exc}", file=sys.stderr)
        return EXIT_UNDECIDED

    from inspect_ai import eval as inspect_eval  # pyright: ignore[reportUnknownVariableType]
    from inspect_ai.model import ModelCost

    task_hashes = suite_task_hashes(suite)
    task = build_task(suite, target, agent, auth_token)
    cost_args: dict[str, Any] = {}
    if price is not None:
        cost_args = {
            "cost_limit": budget["per_trial_cap_usd"],
            "model_cost_config": {
                args.model: ModelCost(
                    input=float(price["input"]), output=float(price["output"]),
                    input_cache_write=float(price["input"]),
                    # No discount assumed for cached input: conservative.
                    input_cache_read=float(price["input"]),
                )
            },
        }
    [log] = inspect_eval(
        task,
        model=args.model,
        model_args=agent["model_args"],
        epochs=args.epochs,
        max_samples=args.max_samples,
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
        preflight_info=info, harness_git=_harness_git(),
        system_prompt_sha256=sha256_hex(agent["system_prompt"]),
        suite_sha256=suite_hash(suite), budget_plan=budget,
    )
    try:
        assert_no_secrets([ordered_json(meta)] + [ordered_json(t) for t in trials], secrets)
    except SecretLeakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_UNDECIDED
    write_run(run_dir, meta, trials)

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
    return 0 if meta["status"] == "complete" else EXIT_UNDECIDED


def cmd_generate_expected(args: argparse.Namespace) -> int:
    from agent_eval.expected import ExpectedError, generate, write_suite

    source = Path(args.source)
    import yaml

    target = TARGETS[yaml.safe_load(source.read_text(encoding="utf-8"))["target"]]
    auth_token = _require(read_env_file(Path(args.env_file)), target["auth_env"])
    try:
        suite = asyncio.run(generate(source, target, auth_token))
    except ExpectedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_UNDECIDED
    write_suite(suite, Path(args.output))
    print(f"wrote {args.output}: {len(suite['tasks'])} tasks, suite sha256 {suite_hash(suite)}")
    return 0


def cmd_reexport(args: argparse.Namespace) -> int:
    from agent_eval.budget import load_prices, price_for
    from agent_eval.export import reexport
    from agent_eval.records import RecordError, load_run

    run_dir = Path(args.run_dir)
    try:
        run = load_run(run_dir)  # refuses a hand-edited run before rebuilding it
    except RecordError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_UNDECIDED
    log_path = run_dir / "inspect.eval"
    if not log_path.is_file():
        print(f"error: {log_path} not found; nothing to rebuild from", file=sys.stderr)
        return EXIT_UNDECIDED
    price = price_for(run.meta["agent"]["model"], load_prices(Path(args.prices)))
    at = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    meta, trials = reexport(run.meta, log_path, price, at)
    write_run(run_dir, meta, trials)
    print(f"{run_dir.name}: rebuilt {len(trials)} trials with export v{meta['export_version']}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    result = compare_runs(Path(args.baseline), Path(args.candidate))
    print(f"verdict: {result.verdict}")
    for line in result.reasons:
        print(f"  reason: {line}")
    for line in result.differences:
        print(f"  differs: {line}")
    for line in result.regrade_mismatches:
        print(f"  regraded differently: {line}")
    for task, (b, c) in result.per_task.items():
        print(f"  {task}: {b:.0%} -> {c:.0%}")
    return result.exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a suite and write run records")
    run.add_argument("--suite", default=str(REPO_ROOT / "suites" / "pagila.yaml"))
    run.add_argument("--tasks", help="comma-separated task ids (e.g. a smoke suite)")
    run.add_argument("--model", default="openai-api/sumopod/gpt-5-mini")
    run.add_argument("--epochs", type=int, default=5)
    run.add_argument("--max-samples", type=int, default=4, help="trials running at once")
    run.add_argument("--budget", type=float, default=5.0, help="US dollars for the whole run")
    run.add_argument("--prices", default=str(REPO_ROOT / "prices.yaml"))
    run.add_argument("--plan-only", action="store_true", help="print the plan and stop")
    run.add_argument("--out", default="runs")
    run.add_argument("--run-id")
    run.add_argument("--env-file", default=str(REPO_ROOT / ".env"))
    run.set_defaults(func=cmd_run)

    gen = sub.add_parser("generate-expected", help="fill a suite's expected answers via the endpoint")
    gen.add_argument("source")
    gen.add_argument("output")
    gen.add_argument("--env-file", default=str(REPO_ROOT / ".env"))
    gen.set_defaults(func=cmd_generate_expected)

    rex = sub.add_parser("reexport", help="rebuild a run's records from its saved Inspect log")
    rex.add_argument("run_dir")
    rex.add_argument("--prices", default=str(REPO_ROOT / "prices.yaml"))
    rex.set_defaults(func=cmd_reexport)

    cmp = sub.add_parser("compare", help="compare a candidate run with a baseline")
    cmp.add_argument("baseline")
    cmp.add_argument("candidate")
    cmp.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
