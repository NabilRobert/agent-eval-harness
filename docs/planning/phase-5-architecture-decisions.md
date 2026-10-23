# Phase 5 — Architecture and Decisions

## Components

Modules as in Phase 3 (`suites`, `targets`, `agent`, `grading`, `runner`,
`compare`, `report`, `cli`). The one rule that matters: `grading`, `compare`
and `report` are pure and never import `targets` or `agent`, so CI can run
`compare` with no API key and no network.

## Stack

- **Python 3.12**, packaged as one installable package with an
  `agent-eval` console command. CLI built on `argparse` (one fewer
  dependency; three subcommands don't need more).
- **Agent loop and MCP client:** pydantic-ai (ADR-003).
- **Statistics:** standard library + `random.Random(seed)`. The bootstrap is
  about 20 lines, so pulling in numpy/scipy isn't worth it.
- **Tooling:** ruff, pyright (strict), pytest, GitHub Actions, the same as
  MCP-backbone.
- **Filesystem target:** `@modelcontextprotocol/server-filesystem` run with
  `npx` at a **pinned exact version**, so a server update can't silently
  shift scores.

## Cross-cutting concerns

- **Config and secrets:** YAML refers to env var *names*; values are read at
  run time and redacted from anything written.
- **Errors:** one exception type per class (`ConfigError` → exit 2,
  `InfraError` → trial `error`, `HarnessBug` → `grader_error`). Anything
  else unexpected crashes loudly instead of being scored.
- **Schema versioning:** every `meta.json` and trial line carries
  `schema_version`. Loaders refuse versions they don't know.

## ADRs

### ADR-001: How a regression is decided
**Context:** 5 repeats per task, about 30 tasks per suite. Pass rates move
by chance between identical runs, so "the pass rate went down" alone gives
false alarms.
**Options:** (a) fixed threshold on the change in suite pass rate; (b)
significance test per task (e.g. Fisher's exact test); (c) paired bootstrap
CI at suite level + a "task broke" rule; (d) gate on pass^k.
**Decision:** (c). CI fails if **either**:
1. The paired bootstrap 95% CI of the average change in pass rate per task
   (candidate − baseline) lies entirely below 0. Resampling: draw tasks with
   replacement, then within each drawn task draw its baseline and candidate
   trials with replacement. 10,000 resamples, fixed seed, percentile
   interval.
2. Any task went from 5/5 to 1/5 or less. If its true pass rate is 90%,
   the chance of that is about 1 in 2,000, so it holds up across 30 tasks
   without false alarms.

pass^k is reported, not used as a gate. Cost (+25% median) and latency only
**warn** by default.
**Why not the others:** (a) isn't calibrated to noise; (b) has almost no
power with 5 trials, and 30 tests stacked together give false alarms;
(d) is too blunt for a single number.
**Proof required (Phase 7):** a degraded agent **is** flagged; an A/A run
(the same agent twice) is **not**.
**Consequences:** the smallest drop it reliably detects is about 10 points
of pass rate. Smaller drops show in the report but don't fail CI, and the
README says so. The percentile bootstrap with ~30 clusters is approximate;
that's acceptable for a gate, and stated.
**Revisit if:** suites grow past ~100 tasks (consider a clustered standard
error instead), or repeats change.
**Sources:** E. Miller, [Adding Error Bars to Evals](https://arxiv.org/abs/2411.00640)
(2024): paired differences and clustering by question; S. Yao et al.,
[τ-bench](https://arxiv.org/abs/2406.12045) (2024): pass^k; Efron &
Tibshirani, *An Introduction to the Bootstrap* (1993).

### ADR-002: Deterministic grading first, LLM judge optional
**Context:** Grades must be reproducible, cheap, and something Arthur can
defend line by line.
**Options:** deterministic graders only; LLM judge for everything; mixed.
**Decision:** Deterministic in v1 (`result_match`, `answer_match`,
`required_tools`, `forbidden_tools`). An LLM judge, if ever added, is a
separate grader kind whose results are reported apart from the others and
never feed the gate.
**Consequences:** some tasks can't be written (open-ended prose), and the
suites deliberately avoid them. In exchange, regrading is free and exact.
**Revisit if:** a target's tasks genuinely have no checkable answer.
**Sources:** L. Zheng et al., [Judging LLM-as-a-Judge](https://arxiv.org/abs/2306.05685)
(2023): position, verbosity and self-preference biases in judges.

### ADR-003: pydantic-ai as the agent loop, behind the `agent` module
**Context:** We need a model ↔ MCP tool loop with a turn cap, a full
message trace and token usage, over an OpenAI-compatible API (Sumopod).
**Options:** pydantic-ai; a hand-written loop on the OpenAI SDK + `mcp` SDK;
LangGraph.
**Decision:** pydantic-ai. MCP-backbone's benchmark already proved it
against Sumopod. It has stdio and streamable-HTTP MCP toolsets, request
limits (= the turn cap) and per-run usage. It lives entirely inside
`agent`, so swapping it out touches one module.
**Consequences:** the harness evaluates "a pydantic-ai agent", not every
possible agent. That's acceptable for v1, and the adapter boundary is where
a second loop would plug in. The exact usage fields and trace format are
confirmed in a Phase 6 spike.
**Rejected:** a hand-written loop (more code, nothing gained to show);
LangGraph (a framework to build agents with, which is a non-goal).
**Revisit if:** pydantic-ai can't expose per-call usage or tool timings.

### ADR-004: Run records as files (`meta.json` + `trials.jsonl`), not a DB
**Context:** Runs must be committable as public evidence, comparable
offline in CI, and readable without the tool.
**Options:** JSONL files; SQLite; a hosted tracker (MLflow, Langfuse).
**Decision:** a directory per run: `meta.json` (config snapshot, hashes,
status, totals, hash of the trials file), `trials.jsonl` (appended one
trial at a time), `report.md`.
**Consequences:** appending can't corrupt earlier trials, diffs are
readable in git, and there's no service to run. Querying across many runs
is manual, which is fine at this scale.
**Rejected:** SQLite (binary in git, can't be diffed); hosted trackers
(an extra service, and a reviewer can't open the evidence without it).
**Revisit if:** we start comparing dozens of runs regularly.

### ADR-005: Cost = provider-reported tokens × a committed price table
**Context:** Cost per task is a headline metric, so it can't be guessed.
**Options:** provider usage × price table; counting tokens locally
(tiktoken); the provider's billing dashboard.
**Decision:** usage from each model response × `prices.yaml` (model →
$/M input, $/M output, source URL, date checked). Missing usage → `null`
cost, totals shown as "≥ $X".
**Rejected:** local counting (misses tool schemas and provider overhead,
and doesn't match the bill); the dashboard (no per-trial breakdown).
**Consequences:** cost is only as right as `prices.yaml`; the report
prints the price date. Whether Sumopod returns usage is a Phase 6 spike.

### ADR-006: Temperature left at the provider default, and recorded
**Context:** Should runs pin `temperature=0` for repeatability?
**Options:** pin 0; provider default; configurable per agent.
**Decision:** the provider default, recorded in every run; it can be
overridden in the agent config.
**Why:** temperature 0 doesn't make hosted models deterministic anyway
(batching and hardware nondeterminism), some reasoning models only accept
the default, and real users run defaults. Variance is handled by the 5
repeats and ADR-001, not by pretending it isn't there.
**Consequences:** single runs are noisier, which is exactly what the
repeats and the A/A test exist to measure.

### ADR-007: Running against MCP-backbone's live endpoint despite its rate limit
**Context:** MCP-backbone limits *every* workspace to 5 `run_query` and 30
`sample_rows` calls per hour (`app/config.py`). A full Pagila run needs
about 150 trials × 1–3 queries. Worse, a rate-limited query comes back as a
normal "rejected" result, so the harness would score it as an agent
**fail**, which would silently corrupt every result. The live VPS value
hasn't been checked (it may be overridden in the VPS `.env`).
**Options:**
(a) Add a per-workspace rate-limit override to MCP-backbone (a nullable
column + migration), and create an `eval` workspace on the VPS with a
higher limit;
(b) raise the global limit on the VPS (also weakens the public demo's
protection);
(c) run MCP-backbone locally for the big runs, and do one small run on the
live endpoint;
(d) spread runs over hours to stay under the limit.
**Decision (2026-10-23): (a).** The VPS check confirmed the live limit is 5/hour,
with no override. Implemented in MCP-backbone on branch `feat/limit-tests`
(`4b9e5ea`), alongside a role-level `statement_timeout` for `pagila_ro`
that the same check found missing (`81c52d1`).
**Why (a):** It's small, defensible ("a trusted eval workspace
gets its own budget") and keeps the success metric honest (the real
endpoint). It also links the two projects in a way a reviewer will notice.
It means a small MCP-backbone change and a VPS deploy, which go through
Arthur.
**Either way:** a target can declare **infra-error patterns** (e.g.
MCP-backbone's rate-limit message). A tool result matching one is turned
into an `InfraError`, so a limit hit is never scored as the agent's fault.
**Revisit:** decided before Phase 7 slice 1 (it gates the first live run).
