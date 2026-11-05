"""The steps `agent-eval run` takes before anything is spent: where keys
are read from, and what stops a run with exit 2."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import typer
from inspect_ai import Task
from inspect_ai import eval as inspect_eval  # pyright: ignore[reportUnknownVariableType]
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.solver import generate

from agent_eval import REPO_ROOT as REPO
from agent_eval.cli import main, run_command, run_steps
from agent_eval.compare import EXIT_UNDECIDED
from agent_eval.targets import TARGETS

ENVIRONMENT_KEY = "sk-from-the-environment"
FILE_KEY = "sk-from-the-env-file"


@pytest.fixture
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Sumopod variables, restored afterwards even when a step sets one."""
    for name in ("SUMOPOD_AI_API_KEY", "SUMOPOD_API_KEY", "SUMOPOD_BASE_URL"):
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)


def test_a_key_only_in_the_environment_reaches_inspect(
    clean_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUMOPOD_AI_API_KEY", ENVIRONMENT_KEY)
    run_steps.export_keys_for_inspect({})
    assert os.environ["SUMOPOD_API_KEY"] == ENVIRONMENT_KEY


def test_a_key_only_in_the_environment_is_scanned_for(
    clean_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUMOPOD_AI_API_KEY", ENVIRONMENT_KEY)
    assert ENVIRONMENT_KEY in run_steps.secrets_to_redact({}, "")


def test_another_providers_key_in_the_environment_is_scanned_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", ENVIRONMENT_KEY)
    assert ENVIRONMENT_KEY in run_steps.secrets_to_redact({}, "")


def test_a_key_in_the_env_file_is_scanned_for(clean_environment: None) -> None:
    assert FILE_KEY in run_steps.secrets_to_redact({"SUMOPOD_AI_API_KEY": FILE_KEY}, "")


def test_both_copies_are_scanned_when_file_and_environment_differ(
    clean_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUMOPOD_AI_API_KEY", ENVIRONMENT_KEY)
    secrets = run_steps.secrets_to_redact({"SUMOPOD_AI_API_KEY": FILE_KEY}, "")
    assert {ENVIRONMENT_KEY, FILE_KEY} <= set(secrets)


def test_the_env_file_wins_for_the_key_inspect_gets(
    clean_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUMOPOD_AI_API_KEY", ENVIRONMENT_KEY)
    run_steps.export_keys_for_inspect({"SUMOPOD_AI_API_KEY": FILE_KEY})
    assert os.environ["SUMOPOD_API_KEY"] == FILE_KEY


def test_the_targets_key_is_scanned_for_whatever_its_name(clean_environment: None) -> None:
    assert "a-target-key" in run_steps.secrets_to_redact({}, "a-target-key")


def test_a_path_is_not_a_secret(clean_environment: None, tmp_path: Path) -> None:
    assert str(tmp_path) not in run_steps.secrets_to_redact({"PATH_TO_THINGS": str(tmp_path)}, "")


FS_SUITE = str(REPO / "suites" / "filesystem.yaml")
PLAN_ONLY_RUN = [
    "run",
    "--suite",
    FS_SUITE,
    "--tasks",
    "f01",
    "--model",
    "openai/gpt-5-mini",
    "--env-file",
    "/dev/null",
    "--plan-only",
]


def malformed_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "malformed.yaml"
    path.write_text("a: [1\n", encoding="utf-8")
    return path


def test_a_missing_key_exits_2_and_names_it(
    clean_environment: None, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["run", "--suite", FS_SUITE, "--tasks", "f01", "--env-file", "/dev/null"])
    assert code == EXIT_UNDECIDED
    assert "SUMOPOD_AI_API_KEY is not set" in capsys.readouterr().err


def test_a_missing_price_table_exits_2_without_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([*PLAN_ONLY_RUN, "--prices", "/nonexistent.yaml"]) == EXIT_UNDECIDED
    err = capsys.readouterr().err
    assert "/nonexistent.yaml" in err
    assert "Traceback" not in err


def test_a_malformed_price_table_exits_2_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*PLAN_ONLY_RUN, "--prices", str(malformed_yaml(tmp_path))]) == EXIT_UNDECIDED
    assert "Traceback" not in capsys.readouterr().err


def test_reexport_with_a_missing_price_table_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["reexport", str(REPO / "runs" / "skeleton"), "--prices", "/nonexistent.yaml"])
    assert code == EXIT_UNDECIDED
    assert "Traceback" not in capsys.readouterr().err


def test_a_missing_system_prompt_file_stops_the_run() -> None:
    with pytest.raises(typer.Exit) as stopped:
        run_steps.choose_system_prompt({}, None, "/nonexistent.txt")
    assert stopped.value.exit_code == EXIT_UNDECIDED


def test_a_binary_system_prompt_file_stops_the_run(tmp_path: Path) -> None:
    binary = tmp_path / "prompt.txt"
    binary.write_bytes(b"\xff\xfe")
    with pytest.raises(typer.Exit) as stopped:
        run_steps.choose_system_prompt({}, None, str(binary))
    assert stopped.value.exit_code == EXIT_UNDECIDED


def test_a_malformed_suite_exits_2_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["run", "--suite", str(malformed_yaml(tmp_path)), "--env-file", "/dev/null"])
    assert code == EXIT_UNDECIDED
    assert "Traceback" not in capsys.readouterr().err


def test_an_empty_suite_exits_2_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    assert main(["run", "--suite", str(empty), "--env-file", "/dev/null"]) == EXIT_UNDECIDED
    assert "Traceback" not in capsys.readouterr().err


def test_comparing_a_corrupt_run_exits_2_and_says_why(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skeleton = REPO / "runs" / "skeleton"
    corrupt = tmp_path / "corrupt"
    shutil.copytree(skeleton, corrupt)
    (corrupt / "meta.json").write_text("{not json", encoding="utf-8")
    assert main(["compare", str(skeleton), str(corrupt)]) == EXIT_UNDECIDED
    assert "meta.json isn't valid JSON" in capsys.readouterr().out


def test_an_unexpected_crash_exits_2_not_the_regression_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A run file with valid JSON but a field missing: nothing handles it
    by name, so the safety net in `main` has to."""
    skeleton = REPO / "runs" / "skeleton"
    edited = tmp_path / "edited"
    shutil.copytree(skeleton, edited)
    meta = json.loads((edited / "meta.json").read_text(encoding="utf-8"))
    del meta["provenance"]
    (edited / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert main(["compare", str(skeleton), str(edited)]) == EXIT_UNDECIDED
    assert "KeyError" in capsys.readouterr().err


def test_a_crashed_trial_isnt_retried_so_its_cost_cap_cant_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inspect gives every retry a fresh cost cap, so one retry would let a
    trial spend its share of the budget twice. Runs real Inspect."""
    calls: list[int] = []

    def crash(*_: object) -> ModelOutput:
        calls.append(1)
        raise RuntimeError("the provider crashed")

    def task_that_generates(*_: object) -> Task:
        return Task(dataset=[Sample(id="t1", input="q")], solver=[generate()])

    monkeypatch.setattr("agent_eval.inspect_tasks.build_task", task_that_generates)
    monkeypatch.setattr(run_command, "RAW_LOG_DIR", tmp_path)

    def spy(task: Task, **options: Any) -> Any:
        options["model"] = get_model("mockllm/model", custom_outputs=crash)
        return inspect_eval(task, **options)

    monkeypatch.setattr("inspect_ai.eval", spy)
    agent: dict[str, Any] = {"model": "mockllm/model", "model_args": {}, "epochs": 1}
    run_command._run_trials(  # pyright: ignore[reportPrivateUsage]
        suite={},
        target={},
        agent=agent,
        auth_token="",
        max_samples=1,
        price=None,
        budget={},
        harness_git="abc123",
    )
    assert len(calls) == 1


COPY_A = "analyst-env-copy-a"


def test_copy_a_key_is_read_from_the_running_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sql-analyst-env writes its keys to /out/keys.json inside the stack;
    the harness reads it there, never from a file on the host."""
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: Any) -> Any:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ANALYST_ENV_COPY_A_KEY=k-a\n")

    monkeypatch.setattr(run_steps.subprocess, "run", fake_run)
    env = run_steps.read_env(TARGETS[COPY_A], "/dev/null")
    assert env["ANALYST_ENV_COPY_A_KEY"] == "k-a"
    [command] = commands
    assert command[:2] == ["docker", "exec"] and "/out/keys.json" in " ".join(command)


def test_a_stopped_stack_says_how_to_start_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_container(command: list[str], **_: Any) -> Any:
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(run_steps.subprocess, "run", no_container)
    with pytest.raises(typer.Exit):
        run_steps.read_env(TARGETS[COPY_A], "/dev/null")
    assert "docker compose up -d --wait" in capsys.readouterr().err


def test_an_ollama_models_sampling_and_reply_cap_reach_inspect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    options_seen: dict[str, Any] = {}

    def spy(task: Task, **options: Any) -> Any:
        options_seen.update(options)
        options["model"] = get_model("mockllm/model")
        return inspect_eval(task, **options)

    def tiny_task(*_: object) -> Task:
        return Task(dataset=[Sample(id="t1", input="q")], solver=[generate()])

    monkeypatch.setattr("agent_eval.inspect_tasks.build_task", tiny_task)
    monkeypatch.setattr(run_command, "RAW_LOG_DIR", tmp_path)
    monkeypatch.setattr("inspect_ai.eval", spy)
    settings = run_steps.generation_settings_or_exit("ollama/qwen3:1.7b")
    agent: dict[str, Any] = {
        "model": "mockllm/model",
        "model_args": {},
        "epochs": 1,
        "generate_config": settings,
    }
    run_command._run_trials(  # pyright: ignore[reportPrivateUsage]
        suite={},
        target={},
        agent=agent,
        auth_token="",
        max_samples=1,
        price=None,
        budget={},
        harness_git="abc123",
    )
    assert (options_seen["temperature"], options_seen["max_tokens"]) == (0.6, 4096)


def test_an_ollama_model_without_settings_stops_the_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(typer.Exit):
        run_steps.generation_settings_or_exit("ollama/unknown:1b")
    assert "no sampling settings for ollama/unknown:1b" in capsys.readouterr().err
