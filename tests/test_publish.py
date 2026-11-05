from pathlib import Path

from agent_eval.publish import README_END, README_START, apply_readme, render
from agent_eval.records import write_run
from tests.conftest import make_meta, make_trial

REPO = Path(__file__).resolve().parent.parent


def test_published_results_match_the_records() -> None:
    """RESULTS.md and the README's results block are exactly what the
    committed records render to: nothing published is typed by hand."""
    results_md, block = render(REPO)
    assert (REPO / "RESULTS.md").read_text() == results_md
    readme = (REPO / "README.md").read_text()
    assert apply_readme(readme, block) == readme


def test_render_is_deterministic() -> None:
    assert render(REPO) == render(REPO)


def test_failed_proofs_are_marked_not_hidden() -> None:
    results_md, _ = render(REPO)
    assert results_md.count("**(not as expected)**") == 3
    assert "Filesystem: discovery tools removed | v1 | flagged | regression (1) |" in results_md


def test_readme_block_is_replaced_not_duplicated() -> None:
    readme = f"intro\n{README_START}\nold\n{README_END}\noutro\n"
    out = apply_readme(readme, f"{README_START}\nnew\n{README_END}")
    assert out == f"intro\n{README_START}\nnew\n{README_END}\noutro\n"


def test_runs_that_recorded_their_queries_get_a_refusals_table(tmp_path: Path) -> None:
    write = {"status": "rejected", "error": "only a single SELECT statement is allowed"}
    trial = {
        **make_trial(1, [{"count": 1000}]),
        "queries": [write, {"status": "succeeded", "error": None}],
        "cost_usd": 0.0,
        "seconds": 1.0,
        "input_tokens": 100,
        "output_tokens": 10,
    }
    meta = make_meta(created_at="2026-11-05", totals={"cost_usd": {"usd": 0.0}})
    meta["agent"]["epochs"] = 1
    write_run(tmp_path / "runs" / "local", meta, [trial])
    (tmp_path / "results.yaml").write_text(
        "runs: [{run: local, label: Local}]\ncomparisons: []\n", encoding="utf-8"
    )
    results_md, _ = render(tmp_path)
    assert "| Local (`local`) | 1 of 1 | 1 of 2 | 1 | 0 | 0 | 0 |" in results_md


def test_runs_without_query_records_add_no_refusals_table() -> None:
    results_md, _ = render(REPO)
    assert "## Refusals" not in results_md
