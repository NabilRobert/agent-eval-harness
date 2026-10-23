"""Run records on disk: `meta.json` + `trials.jsonl` per run (ADR-004).
Pure: reading, writing, hashing and integrity checks only, so `compare`
and `report` can use it in CI without Inspect or a network."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


class RecordError(Exception):
    """A run directory that can't be trusted as evidence: missing files,
    an unknown schema version, or a trials file that doesn't match the
    hash recorded when the run finished (edited after the fact)."""


def ordered_json(value: Any) -> str:
    """Compact JSON that keeps key order. Used wherever rows appear (trial
    records, task hashes): a row's column order is part of the answer, and
    strict grading compares columns in order. Sorting keys here once
    reordered every stored row alphabetically, so regrading a stored
    multi-column answer failed a correct one (caught by `compare`'s
    regrade check in the slice B smoke run)."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def stable_json(value: Any) -> str:
    """Compact JSON with sorted keys, for hashing things whose key order
    carries no meaning (the data fingerprint, the tool list)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def task_hash(task: dict[str, Any]) -> str:
    """A task's identity for comparison: its prompt and graders, expected
    answers included. Edit any of them and old scores stop being
    comparable, without anyone having to remember to bump a version."""
    return sha256_hex(ordered_json({"prompt": task["prompt"], "graders": task["graders"]}))


@dataclass(frozen=True)
class Run:
    meta: dict[str, Any]
    trials: list[dict[str, Any]]


def write_run(run_dir: Path, meta: dict[str, Any], trials: list[dict[str, Any]]) -> None:
    """Writes the trials first, then the meta with the trials file's
    hash, so a meta.json only ever vouches for a trials file that exists
    in full."""
    run_dir.mkdir(parents=True, exist_ok=True)
    trials_text = "".join(ordered_json(t) + "\n" for t in trials)
    (run_dir / "trials.jsonl").write_text(trials_text, encoding="utf-8")
    full_meta = {**meta, "schema_version": SCHEMA_VERSION, "trials_sha256": sha256_hex(trials_text)}
    (run_dir / "meta.json").write_text(
        json.dumps(full_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_run(run_dir: Path) -> Run:
    meta_path, trials_path = run_dir / "meta.json", run_dir / "trials.jsonl"
    if not meta_path.is_file() or not trials_path.is_file():
        raise RecordError(f"{run_dir}: missing meta.json or trials.jsonl")
    meta: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("schema_version") != SCHEMA_VERSION:
        raise RecordError(
            f"{run_dir}: schema_version {meta.get('schema_version')!r}, "
            f"this harness reads {SCHEMA_VERSION}"
        )
    trials_text = trials_path.read_text(encoding="utf-8")
    if sha256_hex(trials_text) != meta.get("trials_sha256"):
        raise RecordError(f"{run_dir}: trials.jsonl doesn't match the hash in meta.json")
    trials = [json.loads(line) for line in trials_text.splitlines() if line.strip()]
    return Run(meta=meta, trials=trials)
