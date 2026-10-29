"""Renders `report.md` from a run's records alone (Phase 3: pure, no
Inspect, no network). Deterministic: the same records always render the
same bytes, so CI can check a committed report against a fresh render.

Strict pass rate is the headline (Phase 2); lenient sits next to it so the
lenient number never has to be taken on trust. Errors are always shown
beside pass rates, never folded into them.

stats.py computes the numbers; sections.py renders them."""

from agent_eval.report.sections import render
from agent_eval.report.stats import headline, per_task_stats

__all__ = ["headline", "per_task_stats", "render"]
