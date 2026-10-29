"""Starts the filesystem MCP server on a fresh copy of a fixture directory.

Inspect starts a new server process per trial (one session per sample
task), so copying here gives every trial its own copy: a write in one
trial can never leak into the next, and the committed fixture is never
handed to the server at all (Phase 3 invariant). The copy is deleted when
the server exits.

    python -m agent_eval.fs_server FIXTURE_DIR
"""

import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from types import FrameType

from agent_eval import REPO_ROOT

SERVER_JS = (
    REPO_ROOT
    / "tools"
    / "fs-server"
    / "node_modules"
    / "@modelcontextprotocol"
    / "server-filesystem"
    / "dist"
    / "index.js"
)
TEMP_PREFIX = "agent-eval-fs-"


def main() -> int:
    fixture = Path(sys.argv[1]).resolve()
    if not fixture.is_dir():
        print(f"fixture {fixture} not found", file=sys.stderr)
        return 2
    if not SERVER_JS.is_file():
        print("filesystem server not installed: run `npm ci` in tools/fs-server", file=sys.stderr)
        return 2
    # realpath: on macOS the temp dir lives under /var, a symlink to
    # /private/var, and the server checks paths against resolved ones.
    work = Path(os.path.realpath(tempfile.mkdtemp(prefix=TEMP_PREFIX)))
    copy = work / fixture.name
    shutil.copytree(fixture, copy)

    def stop(signum: int, frame: FrameType | None) -> None:  # noqa: ARG001
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    process: subprocess.Popen[bytes] | None = None
    try:
        # stdin/stdout pass straight through: this process is just a
        # launcher, the MCP conversation is between Inspect and node.
        process = subprocess.Popen(["node", str(SERVER_JS), str(copy)])
        return process.wait()
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
