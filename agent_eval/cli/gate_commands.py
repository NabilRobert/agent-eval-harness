"""The regression gate's commands: `compare` (a candidate run against a
baseline, exit 0/1/2) and `confirm` (fresh trials for an inconclusive
comparison)."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from agent_eval import REPO_ROOT
from agent_eval.compare import Comparison, compare_runs
from agent_eval.confirm import ConfirmError
from agent_eval.confirm import plan as plan_confirmation

from agent_eval.cli.common import Gate, app, fail, utc_stamp


def _start_confirmation_run(
    side: str, run_args: list[str], run_id: str, out: str, budget: float
) -> None:
    """One side's rerun, as a separate `agent-eval run` process, so it is
    recorded exactly like any other run."""
    command = [
        sys.executable,
        "-m",
        "agent_eval.cli",
        "run",
        *run_args,
        "--run-id",
        run_id,
        "--out",
        out,
        "--budget",
        str(budget),
    ]
    code = subprocess.run(command, cwd=REPO_ROOT, check=False).returncode
    if code != 0:
        fail(f"the {side} confirmation run failed (exit {code})")


def _save_confirmation(
    stamp: str, confirmation: dict[str, Any], run_ids: dict[str, str], result: Comparison
) -> None:
    """Records the confirmation and its verdict in confirmations/<stamp>.json."""
    record = {name: value for name, value in confirmation.items() if not name.endswith("_args")}
    record.update(
        {
            "runs": run_ids,
            "verdict": result.verdict,
            "exit_code": result.exit_code,
            "point": result.point,
            "interval": result.interval,
            "reasons": result.reasons,
        }
    )
    folder = REPO_ROOT / "confirmations"
    folder.mkdir(exist_ok=True)
    (folder / f"{stamp}.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


@app.command(help="rerun the dropped tasks of an inconclusive comparison")
def confirm(  # noqa: PLR0913 -- each parameter is one of the command's CLI options
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
        fail(str(exc))
    stamp = utc_stamp()
    run_ids = {"baseline": f"confirm-{stamp}-baseline", "candidate": f"confirm-{stamp}-candidate"}
    print(
        f"confirming {confirmation['candidate']} vs {confirmation['baseline']}: "
        f"{len(confirmation['tasks'])} dropped tasks x {confirmation['epochs']} attempts, "
        f"both agents: {confirmation['tasks']}"
    )
    for side in ("baseline", "candidate"):
        _start_confirmation_run(side, confirmation[f"{side}_args"], run_ids[side], out, budget)
    result = compare_runs(Path(out) / run_ids["baseline"], Path(out) / run_ids["candidate"], gate)
    _save_confirmation(stamp, confirmation, run_ids, result)
    print(f"confirmation verdict (fresh trials only): {result.verdict} (exit {result.exit_code})")
    if result.interval is not None and result.point is not None:
        print(
            f"  change {result.point:+.1%} (95% interval {result.interval[0]:+.1%} to "
            f"{result.interval[1]:+.1%})"
        )
    for line in result.reasons:
        print(f"  reason: {line}")
    raise typer.Exit(result.exit_code)


def _print_comparison(result: Comparison) -> None:
    print(f"verdict: {result.verdict} (exit {result.exit_code}, gate {result.gate})")
    if result.gate_verdicts:
        verdicts = [f"{gate}: {verdict}" for gate, verdict in result.gate_verdicts.items()]
        print("  all gates: " + ", ".join(verdicts))
    if result.interval is not None and result.point is not None:
        low, high = result.interval
        print(
            f"  suite strict pass rate change: {result.point:+.1%} "
            f"(95% interval {low:+.1%} to {high:+.1%})"
        )
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
    gate: Annotated[
        Gate,
        typer.Option(help="decision rule (ADR-001); v1 for comparisons pre-registered with it"),
    ] = "v2",
) -> None:
    result = compare_runs(baseline, candidate, gate)
    _print_comparison(result)
    raise typer.Exit(result.exit_code)
