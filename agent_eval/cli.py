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
    target = TARGETS.get(args.target or suite["target"])
    if target is None:
        print(f"error: unknown target {args.target or suite['target']!r}", file=sys.stderr)
        return EXIT_UNDECIDED
    if args.target and target.get("serves", target["name"]) != suite["target"]:
        print(f"error: target {args.target!r} doesn't serve suite target {suite['target']!r}",
              file=sys.stderr)
        return EXIT_UNDECIDED
    from agent_eval.providers import is_secret_name, model_args_for, required_env

    env = read_env_file(Path(args.env_file))
    if target.get("auth_env_command"):
        try:
            out = subprocess.run(target["auth_env_command"], capture_output=True, text=True,
                                 timeout=30, check=True).stdout
        except (OSError, subprocess.SubprocessError):
            print(f"error: couldn't read the {target['name']} key; is it running? "
                  "(docker compose -f repro/compose.yaml up -d)", file=sys.stderr)
            return EXIT_UNDECIDED
        env = {**env, **parse_env_text(out)}
    for name in required_env(args.model):
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

    from agent_eval.budget import SMOKE_MAX_TRIALS

    harness_git = _harness_git()
    if n_trials > SMOKE_MAX_TRIALS and (harness_git.endswith("-dirty") or harness_git == "unknown"):
        # A full run is evidence: it must trace back to one exact commit.
        print(f"error: harness checkout is {harness_git}; commit first (full runs need a clean "
              "tree, smoke runs don't)", file=sys.stderr)
        return EXIT_UNDECIDED

    agent: dict[str, Any] = {
        "model": args.model,
        # Per provider: strict tool schemas off on the OpenAI-compatible
        # route, as in every published run (see model_args_for).
        "model_args": model_args_for(args.model),
        "system_prompt": (
            args.system_prompt if args.system_prompt
            else Path(args.system_prompt_file).read_text(encoding="utf-8").strip()
            if args.system_prompt_file
            # A suite can carry its own prompt; Pagila uses MCP-backbone's.
            else suite.get("system_prompt") or PAGILA_SYSTEM_PROMPT
        ),
        "tool_allowlist": None,
        "message_limit": args.message_limit,
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
    # The suite's expected answers were generated against one specific
    # dataset; grading against any other would score right answers wrong.
    mismatch = data_mismatch(suite, info["data_fingerprint"], info.get("session_utc_offset"))
    if mismatch:
        print(f"error: {mismatch}", file=sys.stderr)
        return EXIT_UNDECIDED
    if args.exclude_tools:
        # A deliberately degraded agent (the regression proof): the same
        # model and prompt with tools taken away. Recorded in the meta, so
        # `compare` names it as the difference between the runs.
        excluded = set(args.exclude_tools.split(","))
        unknown = excluded - set(info["tool_names"])
        if unknown or excluded & required_tools(suite):
            print(f"error: can't exclude {sorted(excluded)}: unknown {sorted(unknown)}, or "
                  f"needed by the graders {sorted(excluded & required_tools(suite))}", file=sys.stderr)
            return EXIT_UNDECIDED
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
                args.model: ModelCost(
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
        preflight_info=info, harness_git=harness_git,
        system_prompt_sha256=sha256_hex(agent["system_prompt"]),
        suite_sha256=suite_hash(suite), budget_plan=budget, price=price, target=target,
    )
    try:
        assert_no_secrets([ordered_json(meta)] + [ordered_json(t) for t in trials], secrets)
    except SecretLeakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_UNDECIDED
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
    _write_report(run_dir)
    print(f"{run_dir.name}: rebuilt {len(trials)} trials with export v{meta['export_version']}")
    return 0


def _write_report(run_dir: Path) -> None:
    from agent_eval.records import load_run
    from agent_eval.report import render

    (run_dir / "report.md").write_text(render(load_run(run_dir)), encoding="utf-8")


def cmd_report(args: argparse.Namespace) -> int:
    """Renders report.md from the records; with --check, fails (exit 1) if
    the committed report doesn't match what the records render to."""
    from agent_eval.records import RecordError, load_run
    from agent_eval.report import render

    run_dir = Path(args.run_dir)
    try:
        text = render(load_run(run_dir))
    except RecordError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_UNDECIDED
    path = run_dir / "report.md"
    if args.check:
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            print(f"{path}: out of date with its records (run `agent-eval report {run_dir}`)")
            return 1
        print(f"{path}: up to date")
        return 0
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")
    return 0


def cmd_confirm(args: argparse.Namespace) -> int:
    """Reruns the dropped tasks of an inconclusive comparison for both
    agents and decides on the fresh trials alone (agent_eval/confirm.py)."""
    import json

    from agent_eval.confirm import ConfirmError, plan

    try:
        p = plan(Path(args.baseline), Path(args.candidate), REPO_ROOT / "suites", args.epochs, args.gate)
    except ConfirmError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_UNDECIDED
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    ids = {"baseline": f"confirm-{stamp}-baseline", "candidate": f"confirm-{stamp}-candidate"}
    print(f"confirming {p['candidate']} vs {p['baseline']}: {len(p['tasks'])} dropped tasks "
          f"x {p['epochs']} attempts, both agents: {p['tasks']}")
    for side in ("baseline", "candidate"):
        cmd = [sys.executable, "-m", "agent_eval.cli", "run", *p[f"{side}_args"],
               "--run-id", ids[side], "--out", args.out, "--budget", str(args.budget)]
        code = subprocess.run(cmd, cwd=REPO_ROOT, check=False).returncode
        if code != 0:
            print(f"error: the {side} confirmation run failed (exit {code})", file=sys.stderr)
            return EXIT_UNDECIDED
    result = compare_runs(Path(args.out) / ids["baseline"], Path(args.out) / ids["candidate"], args.gate)
    record = {**{k: v for k, v in p.items() if not k.endswith("_args")}, "runs": ids,
              "verdict": result.verdict, "exit_code": result.exit_code,
              "point": result.point, "interval": result.interval, "reasons": result.reasons}
    out = REPO_ROOT / "confirmations"
    out.mkdir(exist_ok=True)
    (out / f"{stamp}.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"confirmation verdict (fresh trials only): {result.verdict} (exit {result.exit_code})")
    if result.interval is not None and result.point is not None:
        print(f"  change {result.point:+.1%} (95% interval {result.interval[0]:+.1%} to "
              f"{result.interval[1]:+.1%})")
    for line in result.reasons:
        print(f"  reason: {line}")
    return result.exit_code


def cmd_publish(args: argparse.Namespace) -> int:
    """Renders RESULTS.md and the README's results block from the records
    named in results.yaml; with --check, fails if either is out of date."""
    from agent_eval.publish import apply_readme, render

    results_md, block = render(REPO_ROOT)
    readme_path, results_path = REPO_ROOT / "README.md", REPO_ROOT / "RESULTS.md"
    readme = apply_readme(readme_path.read_text(encoding="utf-8"), block)
    if args.check:
        stale = [p.name for p, text in ((results_path, results_md), (readme_path, readme))
                 if not p.is_file() or p.read_text(encoding="utf-8") != text]
        if stale:
            print(f"out of date with the run records: {stale} (run `agent-eval publish`)")
            return 1
        print("RESULTS.md and README results are up to date")
        return 0
    results_path.write_text(results_md, encoding="utf-8")
    readme_path.write_text(readme, encoding="utf-8")
    print("wrote RESULTS.md and the README results block")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    result = compare_runs(Path(args.baseline), Path(args.candidate), args.gate)
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
    return result.exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a suite and write run records")
    run.add_argument("--suite", default=str(REPO_ROOT / "suites" / "pagila.yaml"))
    run.add_argument("--tasks", help="comma-separated task ids (e.g. a smoke suite)")
    run.add_argument("--model", default="openai-api/sumopod/gpt-5-mini")
    run.add_argument("--target", help="run against another target serving the suite's (e.g. mcp-backbone-local)")
    run.add_argument("--epochs", type=int, default=5)
    run.add_argument("--max-samples", type=int, default=4, help="trials running at once")
    run.add_argument("--budget", type=float, default=5.0, help="US dollars for the whole run")
    run.add_argument("--prices", default=str(REPO_ROOT / "prices.yaml"))
    run.add_argument("--plan-only", action="store_true", help="print the plan and stop")
    run.add_argument("--exclude-tools", help="comma-separated tools to withhold (a degraded agent)")
    run.add_argument("--system-prompt-file", help="replace the suite's system prompt (a degraded agent)")
    run.add_argument("--system-prompt", help=argparse.SUPPRESS)  # exact text, used by `confirm`
    run.add_argument("--message-limit", type=int, default=20,
                     help="messages per trial before the trial stops as a fail (default 20)")
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

    rep = sub.add_parser("report", help="render report.md from a run's records")
    rep.add_argument("run_dir")
    rep.add_argument("--check", action="store_true", help="fail if report.md is out of date")
    rep.set_defaults(func=cmd_report)

    con = sub.add_parser("confirm", help="rerun the dropped tasks of an inconclusive comparison")
    con.add_argument("baseline")
    con.add_argument("candidate")
    con.add_argument("--epochs", type=int, default=10)
    con.add_argument("--gate", choices=["v1", "v2"], default="v2")
    con.add_argument("--budget", type=float, default=5.0, help="US dollars per confirmation run")
    con.add_argument("--out", default="runs")
    con.set_defaults(func=cmd_confirm)

    pub = sub.add_parser("publish", help="render RESULTS.md and the README results from records")
    pub.add_argument("--check", action="store_true", help="fail if they're out of date")
    pub.set_defaults(func=cmd_publish)

    cmp = sub.add_parser("compare", help="compare a candidate run with a baseline")
    cmp.add_argument("baseline")
    cmp.add_argument("candidate")
    cmp.add_argument("--gate", choices=["v1", "v2"], default="v2",
                     help="decision rule (ADR-001); v1 for comparisons pre-registered with it")
    cmp.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
