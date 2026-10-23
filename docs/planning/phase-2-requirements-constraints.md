# Phase 2 — Requirements & Constraints

**Scope:** v1 is a command-line tool that runs task suites against agents
built as "a model + an MCP server". Two targets: MCP-backbone (SQL, over its
live endpoint) and the reference filesystem MCP server (files, local). No web
app and no leaderboard (see the Phase 1 non-goals).

## Core functional scenario

Arthur runs one command naming a suite, a target and a model. The harness
runs every task 5 times, grades each trial deterministically, and writes a
run record (every trial with its tool calls, tokens, cost and latency) plus
a Markdown report. A second command compares that run against a saved
baseline **from the files alone, without re-running anything**, and exits
non-zero if the run is a regression.

## Resolved edge cases

- **Flaky tasks:** expected, not a bug. Handled by 5 repeats per task and
  the regression rule (suite-level paired bootstrap CI, plus the "task broke"
  rule: 5/5 → ≤1/5). The details go in an ADR in Phase 5.
- **Infra errors vs agent failures:** an API 5xx, rate limit, timeout from
  the provider, or an MCP server that is down is an **error**, not a fail.
  These are retried with backoff. A trial that still errors after retries is
  excluded from the pass rate and counted separately. If more than 10% of
  trials error, the run is marked incomplete and can't be used for a
  comparison.
- **Runaway agent** (loops on tool calls): each trial has a cap on turns
  (proposed 15) and on wall time (proposed 120 s). Hitting a cap is a
  **fail**, because it's the agent's fault, not the infrastructure's.
- **Exit codes:** 0 = no regression, 1 = regression, 2 = the harness itself
  couldn't decide (incomplete run, bad config, runs that can't be compared).
  CI can then tell "the agent got worse" apart from "the check broke".
- **Comparing different suites:** the comparison uses only the tasks both
  runs share, and lists the ones that are missing. If the two runs used
  different versions of the same task, it refuses to compare (exit 2).
- **State leaking between trials:** each filesystem trial gets a fresh copy
  of the fixture directory, so a write in one trial can't affect the next.
  MCP-backbone is read-only by design.
- **Secrets:** API keys come from the environment and never appear in run
  records, reports or logs (headers are redacted before anything is saved).
- **Missing token usage:** if the provider doesn't return usage, cost is
  recorded as *unknown*, never as 0. Whether Sumopod returns usage gets a
  spike in Phase 6.
- **Model randomness:** model settings (including temperature, or "provider
  default") are recorded with every run. Whether to pin temperature is an
  ADR question for Phase 5.

## Non-functional requirements

| Category | Decision |
|---|---|
| Reproducibility | Each run records the suite version, the hash of each task, model and settings, a hash of the system prompt, a hash of the tool list, the target's address and the harness's git SHA. With these, a later reader can see what changed between two runs. |
| Grading | Deterministic only in v1. Grading and comparing always give the same answer for the same input files. |
| Cost | At most $5 per full run (all suites × 5 repeats × 1 model). The command estimates cost before starting and stops once the cap is reached. |
| Latency | No target for the agent. The harness runs trials concurrently (limit set in config) so a full run takes minutes, not an hour. |
| Portability | Output is plain files (JSONL run records plus a Markdown report), readable without the tool. |
| Security | No secrets in output. The filesystem target only ever gets a temporary copy of the fixtures. |
| Maintainability | Solo, maintained by Arthur. A reviewer should understand it from the README and ADRs in about 15 minutes. |

## Constraints

- **Time budget:** full scope in 3–4 days (Phase 1 decision). Phase docs
  are kept short, and Arthur reviews each one before the next.
- **Team:** solo (Arthur + Claude).
- **Stack:** Python 3.12, with the same tooling as MCP-backbone (ruff,
  pyright, pytest, GitHub Actions). The filesystem server needs Node (`npx`)
  locally and in CI. The model client and MCP client libraries are chosen in
  Phase 5. The MCP-backbone benchmark used pydantic-ai + fastmcp, which is
  the starting candidate.
- **Model access:** the Sumopod key (OpenAI-compatible). Prices per model
  live in a config file that cites its source.
- **CI never calls a paid model.** CI runs the tests plus `compare` on
  committed run records. Live runs happen locally and their records are
  committed as evidence.

## Must / Should / Could

- **Must:**
  - `run`, `compare` and `report` commands, with suites in YAML.
  - An MCP adapter for both streamable HTTP (MCP-backbone) and stdio
    (filesystem).
  - Deterministic graders: result match (strict and lenient, ported from
    MCP-backbone's `rows_equal`/`rows_equal_strict`), final-answer match,
    and required/forbidden tool calls.
  - 5 repeats per task.
  - Pass rate (strict and lenient) and pass^k, plus cost and latency per
    task and in total.
  - JSONL run records.
  - A regression gate with the exit codes above.
  - Budget cap, error handling separate from fails, and turn/time caps.
  - Infra-error patterns per target: a tool result matching one (e.g.
    MCP-backbone's "rate limit … exceeded") becomes an `error`, never an
    agent `fail` (ADR-007).
  - Two suites: MCP-backbone (30 existing Pagila questions, with expected
    results stored in the suite, so no DB access is needed) and filesystem
    (about 15–20 new tasks).
  - Proof tests: a degraded agent **is** flagged, and an A/A run (same agent
    twice) is **not**.
  - Published results for 2 models.
  - README, ADRs, JOURNEY.md, and CI. The README's methodology states
    that MCP-backbone runs use an `eval` workspace with a raised hourly
    limit, so agents are measured without the 5/hour cap real demo users
    have.
- **Should:** tool-call traces in the report for failed trials, so a reader
  can see *why* a task failed.
- **Could / deferred past v1:** an optional LLM judge, an HTML report,
  adapters that aren't MCP (a plain HTTP agent), several models in one
  command.

## Rough effort estimate (logged for Phase 6/7)

| Item | Est. effort |
|---|---|
| Suite format + loader, port the 30 Pagila questions with expected results | 0.5 day |
| MCP adapter (HTTP + stdio) + agent loop with turn/time caps | 0.5–1 day |
| Graders (ported + new) | 0.5 day |
| Repeats, concurrency, retries, budget cap, run records | 0.5–1 day |
| Report + pass^k + cost/latency | 0.5 day |
| Compare + regression rule + exit codes + A/A and degraded proofs | 1 day |
| Filesystem suite (fixtures + 15–20 tasks) | 0.5 day |
| Live runs for 2 models + write-up (README, ADRs, JOURNEY) | 1 day |
| **Total** | **~5–6 focused days** |

**Open risk, carried to Phase 6:** the time budget (3–4 days) is below this
estimate, and it only works if Claude writes most of the code. Decision on
record: if time runs short, cut in this order: (1) the Should item (failure
traces in the report), (2) shrink the filesystem suite to 10 tasks, (3)
publish the second model with fewer repeats, saying so in the report. The
regression gate, both of its proof tests and both targets are never
silently cut.
