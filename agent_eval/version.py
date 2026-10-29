"""Which harness build is running: recorded in every run's provenance
and, when tracing is on, as the trace's `service.version`."""

import os
import subprocess

from agent_eval import REPO_ROOT

GIT_TIMEOUT_SECONDS = 5


def harness_git() -> str:
    """The exact harness commit, `-dirty` if the checkout has edits. In the
    container (no .git) it's the commit stamped in at build time."""
    stamped = os.environ.get("AGENT_EVAL_HARNESS_GIT")
    if stamped:
        return stamped
    try:
        out = subprocess.run(
            ["git", "describe", "--always", "--dirty", "--abbrev=12"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=True,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"
