import json
from pathlib import Path

import pytest
from pytest import approx  # pyright: ignore[reportUnknownVariableType]

from agent_eval.budget import (
    SMOKE_MAX_TRIALS,
    BudgetError,
    cost_usd,
    measured_tokens_per_trial,
    plan,
    price_for,
)
from agent_eval.expected import _LIMIT_1  # pyright: ignore[reportPrivateUsage]
from agent_eval.suites import SuiteError, load_suite, suite_hash, validate_suite

REPO = Path(__file__).resolve().parent.parent
PRICE = {"input": 0.25, "output": 2.0, "source": "x", "checked": "2026-10-23"}


def test_unpriced_model_may_only_run_smoke_sized_runs() -> None:
    assert plan(n_trials=SMOKE_MAX_TRIALS, budget=5, price=None, tokens_per_trial=None)["priced"] is False
    with pytest.raises(BudgetError, match="smoke"):
        plan(n_trials=SMOKE_MAX_TRIALS + 1, budget=5, price=None, tokens_per_trial=None)


def test_estimate_over_budget_is_refused_before_spending() -> None:
    with pytest.raises(BudgetError, match="over"):
        plan(n_trials=200, budget=0.01, price=PRICE, tokens_per_trial=(10_000, 2_000))


def test_per_trial_cap_bounds_the_whole_run() -> None:
    """If every trial ran to its cap, the run would cost exactly the
    budget: the guarantee that replaces a run-level check."""
    p = plan(n_trials=200, budget=5, price=PRICE, tokens_per_trial=(3_000, 400))
    assert p["per_trial_cap_usd"] * 200 == approx(5)
    assert p["estimate_usd"] == approx(200 * (3_000 * 0.25 + 400 * 2.0) / 1e6)


def test_cost_is_unknown_without_a_price_never_zero() -> None:
    assert cost_usd(1000, 100, None) is None
    assert cost_usd(1_000_000, 0, PRICE) == approx(0.25)


def test_price_lookup_needs_the_full_model_id() -> None:
    """The same model through another provider is a different price."""
    prices = {"openai-api/sumopod/gpt-5-mini": PRICE}
    assert price_for("openai-api/sumopod/gpt-5-mini", prices) is PRICE
    assert price_for("openai/gpt-5-mini", prices) is None
    assert price_for("openai-api/sumopod/gpt-5-nano", prices) is None


def test_measured_tokens_ignore_incomplete_and_other_runs(tmp_path: Path) -> None:
    def meta(name: str, status: str, suite: str, trials: int, tokens: tuple[int, int]) -> None:
        (tmp_path / name).mkdir()
        (tmp_path / name / "meta.json").write_text(json.dumps({
            "status": status, "suite": {"name": suite}, "agent": {"model": "m"},
            "totals": {"trials": trials, "input_tokens": tokens[0], "output_tokens": tokens[1]},
        }))

    meta("a", "complete", "pagila", 2, (4000, 400))
    meta("b", "incomplete", "pagila", 1, (99_000, 9_000))
    meta("c", "complete", "other", 1, (99_000, 9_000))
    assert measured_tokens_per_trial(tmp_path, "pagila", "m") == (2000, 200)
    assert measured_tokens_per_trial(tmp_path, "nope", "m") is None


def test_generated_pagila_suite_loads_and_is_complete() -> None:
    suite = load_suite(REPO / "suites" / "pagila.yaml")
    ids = [t["id"] for t in suite["tasks"]]
    assert len(ids) == 40 and len(set(ids)) == 40
    assert {t["tags"][0] for t in suite["tasks"]} == {"easy", "medium", "hard", "expert"}
    assert all(t["graders"][0]["result_match"]["expected"] for t in suite["tasks"])


def test_subset_must_name_real_tasks() -> None:
    suite = load_suite(REPO / "suites" / "pagila.yaml", ["e01", "x01"])
    assert [t["id"] for t in suite["tasks"]] == ["e01", "x01"]
    with pytest.raises(SuiteError, match="no such"):
        load_suite(REPO / "suites" / "pagila.yaml", ["e01", "zz99"])


def test_suite_hash_changes_when_any_expected_answer_changes() -> None:
    suite = load_suite(REPO / "suites" / "pagila.yaml")
    before = suite_hash(suite)
    suite["tasks"][5]["graders"][0]["result_match"]["expected"] = [{"x": 1}]
    assert suite_hash(suite) != before


UNGRADABLE: list[dict[str, object]] = [
    {"id": "a"},
    {"id": "a", "prompt": "q"},
    {"id": "a", "prompt": "q", "graders": [{"llm_judge": {}}]},
    {"id": "a", "prompt": "q", "graders": [{"result_match": {"tool": "run_query", "expected": 5}}]},
]


@pytest.mark.parametrize("task", UNGRADABLE)
def test_ungradable_tasks_are_refused(task: dict[str, object]) -> None:
    with pytest.raises(SuiteError):
        validate_suite({"suite": "s", "target": "t", "tasks": [task]})


def test_duplicate_ids_are_refused() -> None:
    task = {"id": "a", "prompt": "q",
            "graders": [{"result_match": {"tool": "run_query", "expected": [{"n": 1}]}}]}
    with pytest.raises(SuiteError, match="duplicate"):
        validate_suite({"suite": "s", "target": "t", "tasks": [task, task]})


@pytest.mark.parametrize(("sql", "top_one"), [
    ("select a from t order by b desc limit 1", True),
    ("select a from t order by b desc LIMIT 1;", True),
    ("select a from t order by b desc limit 10", False),
    ("select a from t order by b desc limit 5", False),
])
def test_tie_check_applies_to_top_one_queries_only(sql: str, top_one: bool) -> None:
    assert bool(_LIMIT_1.search(sql)) is top_one


def test_frozen_pagila_suite_matches_its_recorded_hash() -> None:
    """Editing suites/pagila.yaml after the freeze fails CI until the new
    hash is recorded deliberately (with a JOURNEY.md entry)."""
    from agent_eval.suites import FROZEN_SUITES

    assert suite_hash(load_suite(REPO / "suites" / "pagila.yaml")) == FROZEN_SUITES["pagila"]


def test_filesystem_suite_loads_and_every_task_forbids_writes() -> None:
    suite = load_suite(REPO / "suites" / "filesystem.yaml")
    assert len(suite["tasks"]) == 17
    for task in suite["tasks"]:
        kinds = [next(iter(g)) for g in task["graders"]]
        assert kinds == ["answer_match", "forbidden_tools"], task["id"]


def test_fixture_fingerprint_changes_when_any_file_changes(tmp_path: Path) -> None:
    import shutil

    from agent_eval.preflight import fixture_fingerprint

    copy = tmp_path / "acme-shop"
    shutil.copytree(REPO / "suites" / "fixtures" / "acme-shop", copy)
    before = fixture_fingerprint(copy)["sha256"]
    assert before == fixture_fingerprint(REPO / "suites" / "fixtures" / "acme-shop")["sha256"]
    (copy / "config" / "server.toml").write_text("port = 1\n")
    assert fixture_fingerprint(copy)["sha256"] != before


def test_frozen_filesystem_suite_matches_its_recorded_hash() -> None:
    from agent_eval.suites import FROZEN_SUITES

    assert suite_hash(load_suite(REPO / "suites" / "filesystem.yaml")) == FROZEN_SUITES["filesystem"]


def test_a_run_refuses_data_its_suite_wasnt_generated_against() -> None:
    from agent_eval.suites import data_mismatch

    pagila = load_suite(REPO / "suites" / "pagila.yaml")
    fs = load_suite(REPO / "suites" / "filesystem.yaml")
    assert data_mismatch(pagila, pagila["generated"]["data_fingerprint"], 28800) is None
    assert data_mismatch(fs, fs["generated"]["data_fingerprint"]) is None
    assert "doesn't match" in (data_mismatch(pagila, "0" * 64, 28800) or "")
    assert data_mismatch({"tasks": []}, "anything") is None  # suites without a record: no check


def test_a_run_refuses_a_database_session_in_another_time_zone() -> None:
    """The grader audit: 35 of Pagila's 64 non-passing trials ignored "UTC"
    in the question, and whether that's wrong depends on the session's
    offset. The suite records the offset it was published at."""
    from agent_eval.suites import data_mismatch

    pagila = load_suite(REPO / "suites" / "pagila.yaml")
    fp = pagila["generated"]["data_fingerprint"]
    assert pagila["generated"]["session_utc_offset"] == 28800
    assert data_mismatch(pagila, fp, 28800) is None
    assert "UTC offset 0s" in (data_mismatch(pagila, fp, 0) or "")
    assert "UTC offset unknown" in (data_mismatch(pagila, fp, None) or "")
    # A suite that records no offset (the filesystem one) isn't checked for it.
    fs = load_suite(REPO / "suites" / "filesystem.yaml")
    assert data_mismatch(fs, fs["generated"]["data_fingerprint"], None) is None
