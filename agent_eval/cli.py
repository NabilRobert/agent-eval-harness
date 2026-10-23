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
from agent_eval.records import canonical_json, sha256_hex, write_run
from agent_eval.suites import (
    MCP_BACKBONE_TARGET,
    PAGILA_SYSTEM_PROMPT,
    SKELETON_SUITE,
    suite_task_hashes,
    validate_suite,
)

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
    from agent_eval.export import (  # Inspect is imported only for `run`
        SecretLeakError,
        assert_no_secrets,
        build_meta,
        inspect_log_contains_secret,
        trial_from_sample,
    )
    from agent_eval.inspect_tasks import build_task
    from agent_eval.preflight import PreflightError, preflight

    env = read_env_file(Path(args.env_file))
    sumopod_key = _require(env, "SUMOPOD_AI_API_KEY")
    base_url = _require(env, "SUMOPOD_BASE_URL")
    target = MCP_BACKBONE_TARGET
    auth_token = _require(env, target["auth_env"])
    # Inspect's openai-api/<service>/<model> provider reads <SERVICE>_API_KEY
    # and <SERVICE>_BASE_URL from this process's environment.
    os.environ["SUMOPOD_API_KEY"] = sumopod_key
    os.environ["SUMOPOD_BASE_URL"] = base_url
    os.environ.setdefault("INSPECT_DISPLAY", "none")
    secrets = [sumopod_key, auth_token]

    suite = SKELETON_SUITE
    validate_suite(suite)
    task_hashes = suite_task_hashes(suite)
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
    required_tools = {
        g["result_match"]["tool"] for t in suite["tasks"] for g in t["graders"]
    }
    try:
        info = asyncio.run(preflight(target, auth_token, required_tools))
    except PreflightError as exc:
        print(f"error: preflight failed: {exc}", file=sys.stderr)
        return EXIT_UNDECIDED

    from inspect_ai import eval as inspect_eval  # pyright: ignore[reportUnknownVariableType]

    run_id = args.run_id or (
        datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        + "-" + args.model.rsplit("/", 1)[-1]
    )
    run_dir = Path(args.out) / run_id
    if run_dir.exists():
        print(f"error: {run_dir} already exists; run records are never overwritten", file=sys.stderr)
        return EXIT_UNDECIDED

    task = build_task(suite, target, agent, auth_token)
    [log] = inspect_eval(
        task,
        model=args.model,
        model_args=agent["model_args"],
        epochs=args.epochs,
        log_dir=str(RAW_LOG_DIR),
        display="none",
    )
    trials = [trial_from_sample(s, task_hashes) for s in (log.samples or [])]
    meta = build_meta(
        log, trials, run_id=run_id, suite=suite, task_hashes=task_hashes, agent=agent,
        preflight_info=info, harness_git=_harness_git(),
        system_prompt_sha256=sha256_hex(agent["system_prompt"]),
    )
    try:
        assert_no_secrets([canonical_json(meta)] + [canonical_json(t) for t in trials], secrets)
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

    run = sub.add_parser("run", help="run the suite and write run records")
    run.add_argument("--model", default="openai-api/sumopod/gpt-5-mini")
    run.add_argument("--epochs", type=int, default=1)
    run.add_argument("--out", default="runs")
    run.add_argument("--run-id")
    run.add_argument("--env-file", default=str(REPO_ROOT / ".env"))
    run.set_defaults(func=cmd_run)

    cmp = sub.add_parser("compare", help="compare a candidate run with a baseline")
    cmp.add_argument("baseline")
    cmp.add_argument("candidate")
    cmp.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
