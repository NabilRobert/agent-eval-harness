"""The `agent-eval` command line: arguments, defaults, errors and exit codes.

No model is called: `run` is only ever planned (--plan-only), and the
other commands work on the committed run records."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from agent_eval import REPO_ROOT
from agent_eval.cli import app, main, record_commands

RUN = REPO_ROOT / "runs" / "smoke-b1"
FS_SUITE = str(REPO_ROOT / "suites" / "filesystem.yaml")
COMMANDS = ["run", "generate-expected", "reexport", "report", "confirm", "publish", "compare"]


def invoke(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def text(result: Result) -> str:
    """Everything printed, without the colour codes Typer adds when it
    thinks it's on a terminal (it does on GitHub Actions)."""
    return re.sub(r"\x1b\[[0-9;]*m", "", result.output)


@pytest.fixture
def no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """No keys in the environment, and none left behind: `run` copies the
    env file's values into os.environ."""
    for name in (
        "SUMOPOD_AI_API_KEY",
        "SUMOPOD_API_KEY",
        "SUMOPOD_BASE_URL",
        "OPENAI_API_KEY",
        "MCP_GATEWAY_KEY",
        "MCP_BACKBONE_EVAL_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def env_file(tmp_path: Path) -> str:
    path = tmp_path / ".env"
    path.write_text(
        "SUMOPOD_AI_API_KEY=sk-test-not-real\nSUMOPOD_BASE_URL=http://localhost:1\n"
        "OPENAI_API_KEY=sk-test-not-real\n"
    )
    return str(path)


def plan(env_file: str, *extra: str) -> Result:
    return invoke(
        "run", "--suite", FS_SUITE, "--tasks", "f01", "--env-file", env_file, "--plan-only", *extra
    )


# The whole CLI


def test_help_lists_every_command() -> None:
    result = invoke("--help")
    assert result.exit_code == 0
    assert all(c in text(result) for c in COMMANDS)
    assert "Exit codes" in text(result)


def test_no_command_shows_help_and_exits_2() -> None:
    result = invoke()
    assert result.exit_code == 2
    assert "Commands" in text(result)


def test_an_unknown_command_exits_2() -> None:
    assert invoke("frobnicate").exit_code == 2


@pytest.mark.parametrize("command", COMMANDS)
def test_every_command_has_help(command: str) -> None:
    result = invoke(command, "--help")
    assert result.exit_code == 0
    assert str(REPO_ROOT) not in text(result)


@pytest.mark.parametrize("command", ["run", "generate-expected", "reexport"])
def test_defaults_in_the_checkout_are_shown_relative_to_it(command: str) -> None:
    assert "(<repo>/" in text(invoke(command, "--help"))


def test_main_returns_the_exit_code_instead_of_exiting() -> None:
    assert main(["compare", str(RUN), str(RUN)]) == 0
    assert main(["compare", str(RUN), str(RUN), "--gate", "v3"]) == 2
    assert main([]) == 2


def test_a_missing_key_exits_1_with_its_name(no_keys: None) -> None:
    with pytest.raises(SystemExit) as exc:
        main(
            ["run", "--suite", FS_SUITE, "--tasks", "f01", "--env-file", "/dev/null", "--plan-only"]
        )
    assert (
        exc.value.code
        == "error: SUMOPOD_AI_API_KEY is not set (in the env file or the environment)"
    )


def test_importing_the_cli_doesnt_import_inspect() -> None:
    code = "import sys, agent_eval.cli; assert 'inspect_ai' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)


def test_the_module_runs_as_a_script() -> None:
    """`confirm` starts its runs with `python -m agent_eval.cli run ...`."""
    out = subprocess.run(
        [sys.executable, "-m", "agent_eval.cli", "report", str(RUN), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    assert "up to date" in out.stdout


# run (plan only)


def test_run_plans_with_the_defaults(no_keys: None, env_file: str) -> None:
    result = plan(env_file)
    assert result.exit_code == 0, text(result)
    assert "plan: 5 trials" in text(result)  # --epochs defaults to 5
    assert "budget $5.00" in text(result)


def test_run_takes_its_options(no_keys: None, env_file: str) -> None:
    result = plan(
        env_file,
        "--epochs",
        "2",
        "--budget",
        "0.5",
        "--max-samples",
        "1",
        "--message-limit",
        "3",
        "--model",
        "openai/gpt-5-mini",
        "--run-id",
        "x",
        "--out",
        "runs",
        "--exclude-tools",
        "a,b",
        "--prices",
        str(REPO_ROOT / "prices.yaml"),
        "--system-prompt",
        "hidden, used by confirm",
    )
    assert result.exit_code == 0, text(result)
    assert "plan: 2 trials" in text(result)
    assert "budget $0.50" in text(result)


def test_run_reads_its_keys_from_the_env_file(no_keys: None, env_file: str) -> None:
    missing = plan("/dev/null")
    assert missing.exit_code == 1
    assert "SUMOPOD_AI_API_KEY is not set" in text(missing)
    assert plan(env_file).exit_code == 0


def test_run_hides_the_exact_system_prompt_option() -> None:
    result = invoke("run", "--help")
    assert "--system-prompt-file" in text(result)
    assert "--system-prompt " not in text(result)


@pytest.mark.parametrize(
    "args",
    [
        ["--configuration", "nope"],
        ["--epochs", "x"],
        ["--budget", "lots"],
        ["--no-such-option"],
    ],
)
def test_run_rejects_bad_arguments_before_planning(env_file: str, args: list[str]) -> None:
    result = plan(env_file, *args)
    assert result.exit_code == 2
    assert "plan:" not in text(result)


def test_run_offers_the_three_configurations(env_file: str) -> None:
    result = plan(env_file, "--configuration", "nope")
    assert result.exit_code == 2
    assert all(c in text(result) for c in ("'direct'", "'gateway-off'", "'gateway-on'"))


def test_run_names_an_unknown_target(env_file: str) -> None:
    result = plan(env_file, "--target", "nope")
    assert result.exit_code == 2
    assert "unknown target 'nope'" in text(result)


def test_run_names_a_missing_suite(env_file: str) -> None:
    result = invoke("run", "--suite", "nope.yaml", "--env-file", env_file, "--plan-only")
    assert result.exit_code == 2
    assert "error:" in text(result)


def test_a_gateway_run_takes_its_configuration(no_keys: None, tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-test-not-real\nMCP_GATEWAY_KEY=gw-test-not-real\n")
    args = ["--model", "openai/gpt-5-mini", "--epochs", "1", "--target", "filesystem-gateway"]
    assert plan(str(env), *args, "--configuration", "gateway-on").exit_code == 0
    assert plan(str(env), *args).exit_code == 2


# report


def test_report_check_passes_on_a_committed_run() -> None:
    result = invoke("report", str(RUN), "--check")
    assert result.exit_code == 0
    assert "up to date" in text(result)


def test_report_check_fails_on_a_stale_report_and_report_fixes_it(tmp_path: Path) -> None:
    run = tmp_path / "run"
    shutil.copytree(RUN, run)
    (run / "report.md").write_text("stale\n")
    stale = invoke("report", str(run), "--check")
    assert stale.exit_code == 1
    assert "out of date with its records" in text(stale)
    written = invoke("report", str(run))
    assert written.exit_code == 0
    assert "wrote" in text(written)
    assert invoke("report", str(run), "--check").exit_code == 0


def test_report_on_a_missing_run_exits_2(tmp_path: Path) -> None:
    result = invoke("report", str(tmp_path / "nope"))
    assert result.exit_code == 2
    assert "error:" in text(result)


def test_report_needs_a_run() -> None:
    assert invoke("report").exit_code == 2


# publish


def test_publish_check_passes_on_the_committed_results() -> None:
    result = invoke("publish", "--check")
    assert result.exit_code == 0
    assert "up to date" in text(result)


def test_publish_check_fails_when_the_results_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    def drifted(root: Path) -> tuple[str, str]:
        return "drifted\n", "drifted\n"

    monkeypatch.setattr(record_commands, "render_results", drifted)
    result = invoke("publish", "--check")
    assert result.exit_code == 1
    assert "out of date with the run records" in text(result)


# compare


def test_compare_a_run_with_itself() -> None:
    result = invoke("compare", str(RUN), str(RUN))
    assert result.exit_code == 0
    assert "gate v2" in text(result)  # the default gate


def test_compare_takes_the_v1_gate() -> None:
    result = invoke("compare", str(RUN), str(RUN), "--gate", "v1")
    assert result.exit_code == 0
    assert "gate v1" in text(result)


@pytest.mark.parametrize("args", [[str(RUN)], [str(RUN), str(RUN), "--gate", "v3"]])
def test_compare_rejects_bad_arguments(args: list[str]) -> None:
    result = invoke("compare", *args)
    assert result.exit_code == 2
    assert "verdict" not in text(result)


def test_compare_with_a_missing_run_is_undecided(tmp_path: Path) -> None:
    assert invoke("compare", str(tmp_path / "nope"), str(RUN)).exit_code == 2


# confirm, reexport, generate-expected: only the paths that spend nothing


def test_confirm_refuses_runs_it_cant_read(tmp_path: Path) -> None:
    result = invoke(
        "confirm",
        str(tmp_path / "a"),
        str(tmp_path / "b"),
        "--epochs",
        "2",
        "--budget",
        "1",
        "--out",
        str(tmp_path),
    )
    assert result.exit_code == 2
    assert "error:" in text(result)


@pytest.mark.parametrize(
    "args", [["only-one"], ["a", "b", "--gate", "v3"], ["a", "b", "--epochs", "x"]]
)
def test_confirm_rejects_bad_arguments(args: list[str]) -> None:
    result = invoke("confirm", *args)
    assert result.exit_code == 2
    assert "confirming" not in text(result)


def test_reexport_needs_the_saved_inspect_log(tmp_path: Path) -> None:
    run = tmp_path / "run"
    shutil.copytree(RUN, run, ignore=shutil.ignore_patterns("inspect.eval"))
    result = invoke("reexport", str(run))
    assert result.exit_code == 2
    assert "nothing to rebuild from" in text(result)


def test_reexport_on_a_missing_run_exits_2(tmp_path: Path) -> None:
    assert invoke("reexport", str(tmp_path / "nope")).exit_code == 2


def test_generate_expected_needs_source_and_output() -> None:
    assert invoke("generate-expected").exit_code == 2
    assert invoke("generate-expected", "only-source").exit_code == 2


def test_generate_expected_needs_the_target_key(no_keys: None, tmp_path: Path) -> None:
    result = invoke(
        "generate-expected",
        str(REPO_ROOT / "suites" / "pagila.source.yaml"),
        str(tmp_path / "out.yaml"),
        "--env-file",
        "/dev/null",
    )
    assert result.exit_code == 1
    assert "MCP_BACKBONE_EVAL_KEY is not set" in text(result)
    assert not (tmp_path / "out.yaml").exists()
