"""The `agent-eval` command line, on Typer: one function per subcommand.

Each command reads its options, calls the modules that do the work
(suites, budget, preflight, export, compare, report, publish) and turns
the outcome into printed lines and an exit code. Nothing here grades or
decides a verdict; that lives in grading.py and compare/.

Exit codes are shared by every command: 0 = ok or no regression,
1 = a regression or an out-of-date file, 2 = the harness couldn't decide
(bad config, unreachable target, incomparable runs). `main` returns the
code instead of exiting, so the tests can call it in-process.

Inspect AI and the MCP client load slowly, so they're imported inside the
functions that use them: `report`, `publish` and `compare`, which CI runs
on every push, never load them.

The commands register themselves on the shared Typer app (common.py)
when their module is imported:
- run_steps.py and run_command.py: `run`;
- record_commands.py: `generate-expected`, `reexport`, `report`, `publish`;
- gate_commands.py: `compare` and `confirm`.
"""

import traceback

# Imported for their side effect, in this order on purpose: each module
# registers its commands on the app, and `agent-eval --help` lists them in
# registration order, `run` first.
from agent_eval.cli.common import app  # noqa: I001
from agent_eval.cli import run_command as run_command
from agent_eval.cli import record_commands as record_commands
from agent_eval.cli import gate_commands as gate_commands
from agent_eval.compare import EXIT_UNDECIDED


def main(argv: list[str] | None = None) -> int:
    """The `agent-eval` entry point. Returns the exit code instead of
    exiting, so tests can call it in-process. An unexpected crash exits 2:
    left alone, Python would exit 1, and CI reads 1 as a regression."""
    try:
        app(args=argv, prog_name="agent-eval")
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception:  # see the docstring: a crash decides nothing
        traceback.print_exc()
        return EXIT_UNDECIDED
    return 0
