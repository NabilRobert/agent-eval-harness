from pathlib import Path

import pytest

from agent_eval.confirm import ConfirmError, plan
from agent_eval.records import load_run

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "runs"


def test_only_an_inconclusive_comparison_can_be_confirmed() -> None:
    """a vs nano was 'no regression' (-4.5 pts): not eligible, so confirm
    can't be used to go fishing after a clean result."""
    with pytest.raises(ConfirmError, match="'no regression'"):
        plan(RUNS / "proof-mini-a", RUNS / "proof-nano", REPO / "suites", gate="v1")


def test_plan_reruns_exactly_the_dropped_tasks_with_each_agent_reproduced() -> None:
    p = plan(RUNS / "proof-mini-b", RUNS / "proof-nano", REPO / "suites", gate="v1")
    assert p["tasks"] and p["epochs"] == 10
    base, cand = p["baseline_args"], p["candidate_args"]
    assert base[base.index("--model") + 1] == "openai-api/sumopod/gpt-5-mini"
    assert cand[cand.index("--model") + 1] == "openai-api/sumopod/gpt-5-nano"
    assert base[base.index("--tasks") + 1].split(",") == p["tasks"]
    # Both prompts are the one the runs used (proven by its recorded hash).
    meta = load_run(RUNS / "proof-mini-b").meta
    from agent_eval.records import sha256_hex

    assert (
        sha256_hex(base[base.index("--system-prompt") + 1]) == meta["agent"]["system_prompt_sha256"]
    )


def test_withheld_tools_are_reproduced(tmp_path: Path) -> None:
    from agent_eval.confirm import agent_args

    run = load_run(RUNS / "proof-mini-degraded")
    args = agent_args(run, REPO / "suites" / "pagila.yaml", ["e01"], 10)
    assert args[args.index("--exclude-tools") + 1] == "describe_table,sample_rows"


def test_the_message_limit_is_reproduced() -> None:
    from agent_eval.confirm import agent_args

    args = agent_args(load_run(RUNS / "proof-mini-a"), REPO / "suites" / "pagila.yaml", ["e01"], 10)
    assert args[args.index("--message-limit") + 1] == "20"


def test_the_time_and_token_limits_are_reproduced() -> None:
    """A confirmation reruns the same agent, so a benchmark run's longer
    limits (600 s, 250,000 tokens for a local model) must carry over."""
    from agent_eval.confirm import agent_args

    run = load_run(RUNS / "proof-mini-a")
    run.meta["agent"]["limits"].update({"time_limit": 600, "token_limit": 250_000})
    args = agent_args(run, REPO / "suites" / "pagila.yaml", ["e01"], 10)
    assert args[args.index("--time-limit") + 1] == "600"
    assert args[args.index("--token-limit") + 1] == "250000"
