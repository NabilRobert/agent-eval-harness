"""Reproducing the results with your own provider's key (Phase 1)."""

from pathlib import Path

import pytest

from agent_eval.cli import main
from agent_eval.providers import is_secret_name, model_args_for, required_env


def test_strict_tools_off_only_on_the_openai_compatible_route() -> None:
    assert model_args_for("openai-api/sumopod/gpt-5-mini") == {"strict_tools": False}
    assert model_args_for("openai/gpt-5-mini") == {}
    assert model_args_for("anthropic/claude-haiku-4-5") == {}


def test_sumopod_variables_are_required_only_for_sumopod_models() -> None:
    assert required_env("openai-api/sumopod/gpt-5-mini") == [
        "SUMOPOD_AI_API_KEY",
        "SUMOPOD_BASE_URL",
    ]
    assert required_env("openai/gpt-5-mini") == []


def test_secret_names_are_recognised() -> None:
    assert all(is_secret_name(n) for n in ["OPENAI_API_KEY", "SUMOPOD_AI_API_KEY", "GH_TOKEN"])
    assert not is_secret_name("SUMOPOD_BASE_URL")


def test_an_openai_key_alone_is_enough_to_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("SUMOPOD_AI_API_KEY", "SUMOPOD_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-test-not-real\n")
    code = main(
        [
            "run",
            "--suite",
            "suites/filesystem.yaml",
            "--tasks",
            "f01,f17",
            "--epochs",
            "1",
            "--model",
            "openai/gpt-5-mini",
            "--env-file",
            str(env),
            "--plan-only",
        ]
    )
    assert code == 0
    assert "plan: 2 trials" in capsys.readouterr().out


def test_an_unpriced_provider_cant_do_a_full_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Never costed at someone else's prices: unpriced means smoke-sized only."""
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-test-not-real\n")
    code = main(
        [
            "run",
            "--suite",
            "suites/filesystem.yaml",
            "--model",
            "openai/gpt-5-mini",
            "--env-file",
            str(env),
            "--plan-only",
        ]
    )
    assert code == 2
    assert "no price" in capsys.readouterr().err
