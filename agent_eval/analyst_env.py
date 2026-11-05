"""Reads sql-analyst-env's public tasks (Project 13's `tasks/public.yaml`)
into a harness suite source, for the accuracy benchmark (MCP-backbone's
accuracy-benchmark-plan.md, D1 and step 1b). `generate-expected` then
runs it against copy A (agent_eval/expected.py).

The file is read at a pinned commit with `git show`, never from a working
tree that could have moved, and the source records that commit and the
file's sha256. Only the train and dev splits are public: a task from any
other split stops the build, so a held-out task can't slip in."""

import subprocess
from pathlib import Path
from typing import Any, cast

import yaml

from agent_eval.records import sha256_hex

REPOSITORY = "NabilRobert/sql-analyst-env"
# The commit Project 13 named for the benchmark: 70 public tasks.
PINNED_COMMIT = "af1067846a66e69eb7639ab7065f5c212f242c84"
TASK_FILE = "tasks/public.yaml"
PUBLIC_SPLITS = ("train", "dev")
TARGET = "analyst-env-copy-a"


class TaskFileError(Exception):
    """The task file can't become a suite as it is. Nothing is written."""


def read_pinned_task_file(repo: Path, commit: str = PINNED_COMMIT) -> str:
    """The task file's text at `commit`, from a local clone of the repo."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo), "show", f"{commit}:{TASK_FILE}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise TaskFileError(
            f"couldn't read {TASK_FILE} at {commit[:7]} from {repo}: "
            f"clone {REPOSITORY} there, or pass --repo"
        ) from exc


def _source_task(task: dict[str, Any]) -> dict[str, Any]:
    """One task as generate-expected reads it. The family and the split
    become tags, so a report can group by them and a run can pick the dev
    split by id."""
    if task.get("split") not in PUBLIC_SPLITS:
        raise TaskFileError(
            f"task {task.get('id')!r} is in split {task.get('split')!r}, not a public one: "
            "held-out tasks are never read"
        )
    out: dict[str, Any] = {
        "id": task["id"],
        "tags": [*task["tags"], task["family"], task["split"]],
        "prompt": task["prompt"],
        "reference_sql": task["reference_sql"],
        "alternative_sql": task["alternative_sql"],
        "wrong_sql": task["wrong_sql"],
    }
    if task.get("is_ordered"):
        out["is_ordered"] = True
    return out


def source_from_task_file(text: str, commit: str = PINNED_COMMIT) -> dict[str, Any]:
    """The suite source for generate-expected: every public task, plus the
    canary and where the tasks came from."""
    loaded = cast(dict[str, Any], yaml.safe_load(text))
    return {
        "suite": loaded["suite"],
        "version": loaded["version"],
        "target": TARGET,
        "description": (
            f"{loaded['description']} Read from {REPOSITORY} {TASK_FILE} at {commit[:7]}; "
            "graded on copy A only."
        ),
        # Kept so the suite can be spotted in training data, as the source asks.
        "canary": loaded["canary"],
        "source": {
            "repository": REPOSITORY,
            "commit": commit,
            "path": TASK_FILE,
            "sha256": sha256_hex(text),
        },
        "tasks": [_source_task(task) for task in loaded["tasks"]],
    }
