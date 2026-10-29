"""What every `agent-eval` command shares: the Typer app, the exit codes
and per-trial limits, the options several commands take, and the helpers
that print an error or write a report."""

import datetime
import os
import sys
from pathlib import Path
from typing import Annotated, Literal, NoReturn

import typer

from agent_eval import REPO_ROOT
from agent_eval.compare import EXIT_UNDECIDED
from agent_eval.records import load_run
from agent_eval.report import render as render_report


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
app = typer.Typer(
    add_completion=False, no_args_is_help=True, help=HELP, pretty_exceptions_enable=False
)


# Shared helpers


def fail(message: str) -> NoReturn:
    """Print an error and exit 2: the harness couldn't decide."""
    print(f"error: {message}", file=sys.stderr)
    raise typer.Exit(EXIT_UNDECIDED)


def require_variable(env: dict[str, str], name: str) -> str:
    """A value from the env file, else from the environment. Missing, it
    stops the command with exit 1 and names the variable."""
    value = env.get(name) or os.environ.get(name)
    if not value:
        raise SystemExit(f"error: {name} is not set (in the env file or the environment)")
    return value


def utc_stamp() -> str:
    return datetime.datetime.now(datetime.UTC).strftime(STAMP_FORMAT)


def write_report(run_dir: Path) -> None:
    (run_dir / "report.md").write_text(render_report(load_run(run_dir)), encoding="utf-8")
