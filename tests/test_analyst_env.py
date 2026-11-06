"""Reading sql-analyst-env's public tasks into a suite source (step 1b of
MCP-backbone's accuracy-benchmark-plan.md)."""

import subprocess
from pathlib import Path

import pytest
import yaml

from agent_eval import REPO_ROOT
from agent_eval.analyst_env import (
    PINNED_COMMIT,
    TaskFileError,
    read_pinned_task_file,
    source_from_task_file,
)
from agent_eval.records import sha256_hex

TASK_FILE_TEXT = """\
suite: analyst-env-public
version: 1
description: Business questions.
canary: ec2d5d8f-0000-0000-0000-000000000000
tasks:
- id: e01
  tags: [easy]
  family: counting
  split: train
  source: mcp-backbone
  prompt: How many films?
  reference_sql: select count(*) from film
  alternative_sql: select count(distinct film_id) from film
  wrong_sql: select count(*) from inventory
- id: n31
  tags: [expert]
  family: windows
  split: dev
  source: new
  prompt: Monthly rentals in 2025, in order?
  reference_sql: select 1
  alternative_sql: select 1
  wrong_sql: select 2
  is_ordered: true
"""
SOURCE = REPO_ROOT / "suites" / "analyst-env.source.yaml"
LOCAL_CLONE = REPO_ROOT.parent / "sql-analyst-env"


def test_the_source_keeps_the_canary_and_records_where_it_came_from() -> None:
    source = source_from_task_file(TASK_FILE_TEXT, "c0ffee" * 6)
    assert source["canary"] == "ec2d5d8f-0000-0000-0000-000000000000"
    assert source["source"]["commit"] == "c0ffee" * 6
    assert source["source"]["sha256"] == sha256_hex(TASK_FILE_TEXT)
    assert source["target"] == "analyst-env-copy-a"


def test_each_task_keeps_its_keys_and_gains_its_family_and_split_as_tags() -> None:
    [e01, n31] = source_from_task_file(TASK_FILE_TEXT)["tasks"]
    assert e01["tags"] == ["easy", "counting", "train"]
    assert e01["alternative_sql"] == "select count(distinct film_id) from film"
    assert e01["wrong_sql"] == "select count(*) from inventory"
    assert "is_ordered" not in e01
    assert n31["is_ordered"] is True


def test_a_task_from_a_held_out_split_stops_the_build() -> None:
    text = TASK_FILE_TEXT.replace("split: dev", "split: heldout")
    with pytest.raises(TaskFileError, match="held-out"):
        source_from_task_file(text)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_the_task_file_is_read_at_the_pinned_commit_not_the_working_tree(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "public.yaml").write_text("pinned\n", encoding="utf-8")
    _git(tmp_path, "add", "tasks/public.yaml")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "pin")
    commit = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "tasks" / "public.yaml").write_text("moved on\n", encoding="utf-8")
    assert read_pinned_task_file(tmp_path, commit) == "pinned\n"


def test_a_missing_clone_says_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(TaskFileError, match="clone NabilRobert/sql-analyst-env"):
        read_pinned_task_file(tmp_path)


def test_the_committed_source_is_the_pinned_file_with_its_70_public_tasks() -> None:
    source = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    assert source["source"]["commit"] == PINNED_COMMIT
    assert len(source["tasks"]) == 70
    assert {task["tags"][-1] for task in source["tasks"]} == {"train", "dev"}


@pytest.mark.skipif(not LOCAL_CLONE.exists(), reason="needs a clone of sql-analyst-env")
def test_the_committed_source_rebuilds_from_the_pinned_file() -> None:
    rebuilt = source_from_task_file(read_pinned_task_file(LOCAL_CLONE))
    assert yaml.safe_load(SOURCE.read_text(encoding="utf-8")) == rebuilt
