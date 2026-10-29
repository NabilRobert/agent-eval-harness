"""The commands that build files from run records: `generate-expected`
(a suite's expected answers), `reexport` (a run's records from its saved
Inspect log), `report` (report.md) and `publish` (RESULTS.md and the
README's results)."""

import asyncio
import datetime
from pathlib import Path
from typing import Annotated

import typer
import yaml

from agent_eval import REPO_ROOT
from agent_eval.budget import (
    load_prices,
    price_for,
)
from agent_eval.envfile import read_env_file
from agent_eval.publish import apply_readme
from agent_eval.publish import render as render_results
from agent_eval.records import RecordError, load_run, write_run
from agent_eval.report import render as render_report
from agent_eval.suites import (
    suite_hash,
)
from agent_eval.targets import TARGETS

from agent_eval.cli.common import (
    EXIT_OUT_OF_DATE,
    EnvFile,
    Prices,
    app,
    fail,
    require_variable,
    write_report,
)


@app.command(help="fill a suite's expected answers via the endpoint")
def generate_expected(
    source: str, output: str, env_file: EnvFile = str(REPO_ROOT / ".env")
) -> None:
    from agent_eval.expected import ExpectedError, generate, write_suite  # the MCP client

    source_path = Path(source)
    target = TARGETS[yaml.safe_load(source_path.read_text(encoding="utf-8"))["target"]]
    auth_token = require_variable(read_env_file(Path(env_file)), target["auth_env"])
    try:
        suite = asyncio.run(generate(source_path, target, auth_token))
    except ExpectedError as exc:
        fail(str(exc))
    write_suite(suite, Path(output))
    print(f"wrote {output}: {len(suite['tasks'])} tasks, suite sha256 {suite_hash(suite)}")


@app.command(help="rebuild a run's records from its saved Inspect log")
def reexport(run_dir: Path, prices_path: Prices = str(REPO_ROOT / "prices.yaml")) -> None:
    from agent_eval.export import reexport as rebuild_records  # imports Inspect

    try:
        record = load_run(run_dir)  # refuses a hand-edited run before rebuilding it
    except RecordError as exc:
        fail(str(exc))
    log_path = run_dir / "inspect.eval"
    if not log_path.is_file():
        fail(f"{log_path} not found; nothing to rebuild from")
    price = price_for(record.meta["agent"]["model"], load_prices(Path(prices_path)))
    rebuilt_at = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    meta, trials = rebuild_records(record.meta, log_path, price, rebuilt_at)
    write_run(run_dir, meta, trials)
    write_report(run_dir)
    print(f"{run_dir.name}: rebuilt {len(trials)} trials with export v{meta['export_version']}")


@app.command(help="render report.md from a run's records")
def report(
    run_dir: Path,
    check: Annotated[
        bool, typer.Option("--check", help="fail if report.md is out of date")
    ] = False,
) -> None:
    """Renders report.md from the records; with --check, fails (exit 1) if
    the committed report doesn't match what the records render to."""
    try:
        text = render_report(load_run(run_dir))
    except RecordError as exc:
        fail(str(exc))
    path = run_dir / "report.md"
    if not check:
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")
        return
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        print(f"{path}: out of date with its records (run `agent-eval report {run_dir}`)")
        raise typer.Exit(EXIT_OUT_OF_DATE)
    print(f"{path}: up to date")


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
