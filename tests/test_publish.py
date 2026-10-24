from pathlib import Path

from agent_eval.publish import README_END, README_START, apply_readme, render

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
    assert "Filesystem: discovery tools removed | flagged | regression (1) |" in results_md


def test_readme_block_is_replaced_not_duplicated() -> None:
    readme = f"intro\n{README_START}\nold\n{README_END}\noutro\n"
    out = apply_readme(readme, f"{README_START}\nnew\n{README_END}")
    assert out == f"intro\n{README_START}\nnew\n{README_END}\noutro\n"
