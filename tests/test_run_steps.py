"""The steps `agent-eval run` takes before anything is spent: where keys
are read from, and what stops a run with exit 2."""

import os
from pathlib import Path

import pytest

from agent_eval.cli import run_steps

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
