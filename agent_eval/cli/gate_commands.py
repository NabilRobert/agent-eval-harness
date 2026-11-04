"""The regression gate's commands: `compare` (a candidate run against a
baseline, exit 0/1/2), `confirm` (fresh trials for an inconclusive
comparison) and `plan-pairs` (how many conversation pairs gate v3 needs,
before a run)."""

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
from agent_eval.pair_planning import MAX_PAIRS, PairModel, detection_rate, pairs_needed

from agent_eval.cli.common import Gate, TaskGate, app, fail, utc_stamp


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
    gate: Annotated[TaskGate, typer.Option()] = "v2",
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
    _print_left_out(result)
    _print_explanations(result)


def _print_left_out(result: Comparison) -> None:
    if result.missing:
        print(f"  only in one run (not compared): {result.missing}")
    if result.unpaired:
        print(f"  pairs left out (an error or missing on one side): {result.unpaired}")


def _print_explanations(result: Comparison) -> None:
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
        typer.Option(
            help="decision rule (ADR-001); v1 for comparisons pre-registered with it, "
            "v3 for paired conversations (ADR-014)"
        ),
    ] = "v2",
) -> None:
    result = compare_runs(baseline, candidate, gate)
    _print_comparison(result)
    raise typer.Exit(result.exit_code)


def _check_pair_model(model: PairModel, power: float) -> None:
    if not 0 < model.baseline <= 1:
        fail(f"--baseline must be a pass rate above 0 and at most 1, not {model.baseline}")
    if not 0 <= model.drop <= model.baseline:
        fail(f"--drop must be between 0 and --baseline ({model.baseline}), not {model.drop}")
    if not 0 <= model.grader_error < 0.5:
        fail(f"--grader-error must be at least 0 and below 0.5, not {model.grader_error}")
    if not 0 <= model.pair_correlation <= 1:
        fail(f"--pair-correlation must be between 0 and 1, not {model.pair_correlation}")
    if not 0 < power < 1:
        fail(f"--power must be between 0 and 1, not {power}")


@app.command("plan-pairs", help="how many conversation pairs gate v3 needs to catch a drop")
def plan_pairs(
    baseline: Annotated[float, typer.Option(help="the healthy agent's expected pass rate")],
    drop: Annotated[float, typer.Option(help="the drop to catch, e.g. 0.10 for 10 points")],
    grader_error: Annotated[
        float, typer.Option(help="how often the grader flips a verdict; 0 for a stop marker")
    ] = 0.0,
    pair_correlation: Annotated[
        float, typer.Option(help="assumed until an A/A run measures it")
    ] = 0.5,
    power: Annotated[float, typer.Option(help="how often the drop must be caught")] = 0.8,
) -> None:
    """Simulates gate v3 under the thesis pilot's model of a pair
    (agent_eval/pair_planning.py) and prints the pairs needed."""
    model = PairModel(baseline, drop, grader_error, pair_correlation)
    _check_pair_model(model, power)
    needed = pairs_needed(model, power)
    assumptions = (
        f"  assumed: baseline {baseline:.0%}, grader error {grader_error:.0%}, "
        f"pair correlation {pair_correlation:.2f}"
    )
    if needed is None:
        print(
            f"pairs needed: more than {MAX_PAIRS:,} to catch a {drop * 100:.0f}-point drop "
            f"{power:.0%} of the time"
        )
        print(assumptions)
        return
    no_drop = PairModel(baseline, 0.0, grader_error, pair_correlation)
    print(
        f"pairs needed: {needed} (gate v3 catches a {drop * 100:.0f}-point drop in "
        f"{detection_rate(model, needed):.1%} of simulated runs)"
    )
    print(assumptions)
    print(f"  false alarms at {needed} pairs with no drop: {detection_rate(no_drop, needed):.1%}")
