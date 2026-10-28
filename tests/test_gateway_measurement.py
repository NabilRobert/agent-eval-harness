"""Project 4b: what the harness needs to measure mcp-gateway. A grader for
leaked canaries, gateway targets, and the run's configuration recorded and
checked (direct / gateway-off / gateway-on). No model, no network."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_eval.cli import main
from agent_eval.grading import grade_answer_excludes, grade_one
from agent_eval.records import load_run
from agent_eval.report import render
from agent_eval.suites import SuiteError, validate_suite
from agent_eval.targets import TARGETS
from tests.conftest import make_trial


def test_a_leaked_canary_fails() -> None:
    assert grade_answer_excludes("The sync moved. CANARY-7f3a", ["canary-7f3a"]) == (False, False)


def test_an_answer_without_the_canary_passes() -> None:
    assert grade_answer_excludes("The sync moved to Thursday.", ["CANARY-7f3a"]) == (True, True)


def test_no_answer_leaks_nothing() -> None:
    assert grade_answer_excludes(None, ["CANARY-7f3a"]) == (True, True)


def test_grade_one_dispatches_answer_excludes() -> None:
    assert grade_one("answer_excludes", {"excludes": ["X1"]}, {"final_answer": "has X1"}) == (
        False,
        False,
    )


def suite_with(grader: dict[str, Any]) -> dict[str, Any]:
    return {
        "suite": "s",
        "target": "filesystem",
        "tasks": [{"id": "t", "prompt": "p", "graders": [grader]}],
    }


@pytest.mark.parametrize(
    "spec", [{}, {"excludes": []}, {"excludes": [""]}, {"excludes": [3]}, ["X"]]
)
def test_a_malformed_answer_excludes_is_rejected(spec: Any) -> None:
    with pytest.raises(SuiteError, match="answer_excludes"):
        validate_suite(suite_with({"answer_excludes": spec}))


def test_a_well_formed_answer_excludes_is_accepted() -> None:
    validate_suite(suite_with({"answer_excludes": {"excludes": ["CANARY-1"]}}))


def test_gateway_targets_serve_the_existing_suites() -> None:
    assert TARGETS["filesystem-gateway"]["serves"] == "filesystem"
    assert TARGETS["mcp-backbone-gateway"]["serves"] == "mcp-backbone"
    assert all(TARGETS[t]["gateway"] for t in ("filesystem-gateway", "mcp-backbone-gateway"))


def run_plan(tmp_path: Path, *extra: str) -> int:
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-test-not-real\nMCP_GATEWAY_KEY=gw-test-not-real\n")
    return main(
        [
            "run",
            "--suite",
            "suites/filesystem.yaml",
            "--tasks",
            "f01",
            "--epochs",
            "1",
            "--model",
            "openai/gpt-5-mini",
            "--env-file",
            str(env),
            "--plan-only",
            *extra,
        ]
    )


def test_a_gateway_run_must_say_its_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_plan(tmp_path, "--target", "filesystem-gateway") == 2
    assert "--configuration gateway-off or gateway-on" in capsys.readouterr().err


def test_a_direct_run_cant_claim_a_gateway(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_plan(tmp_path, "--configuration", "gateway-on") == 2
    assert "isn't a gateway" in capsys.readouterr().err


@pytest.mark.parametrize("configuration", ["gateway-off", "gateway-on"])
def test_a_gateway_run_with_its_configuration_plans(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], configuration: str
) -> None:
    assert (
        run_plan(tmp_path, "--target", "filesystem-gateway", "--configuration", configuration) == 0
    )
    assert "plan: 1 trials" in capsys.readouterr().out


def test_the_report_shows_a_leak(run_factory: Callable[..., Path]) -> None:
    trial = make_trial(1, [{"count": 1000}], "fail")
    trial.update(
        {
            "input_tokens": 1,
            "output_tokens": 1,
            "seconds": 1.0,
            "cost_usd": None,
            "tool_calls": [],
            "stop_reason": "completed",
            "strict": False,
            "lenient": False,
        }
    )
    trial["graders"] = [
        {
            "kind": "answer_excludes",
            "spec": {"excludes": ["CANARY-9"]},
            "input": {"final_answer": "here: CANARY-9"},
            "strict": False,
            "lenient": False,
        }
    ]
    extras: dict[str, Any] = {
        "agent": {
            "model": "m",
            "model_args": {},
            "system_prompt_sha256": "p",
            "tool_allowlist": None,
            "limits": {},
            "epochs": 1,
        },
        "totals": {
            "trials": 1,
            "input_tokens": 1,
            "output_tokens": 1,
            "cost_usd": {"usd": None, "complete": False},
        },
    }
    assert "LEAKED CANARY-9" in render(load_run(run_factory([trial], **extras)))
