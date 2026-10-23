# Phase 6 — Risks, Spikes and the Walking Skeleton

## Risks, ranked by likelihood × impact

**Technical**

- **Cost can't be measured per trial.** If Sumopod doesn't return token
  usage on each response (or returns it only for some models), cost — a
  headline metric — becomes "unknown". **Likelihood: medium. Impact:
  high.** → Spike 1.
- **Expected answers don't match what the agent can see.** MCP-backbone
  caps results at 200 rows and rejects queries over its cost threshold, and
  the old benchmark computed ground truth directly against the database,
  not through those limits. A reference answer the agent *can't* reproduce
  through the endpoint makes a task unpassable. **Likelihood: medium.
  Impact: high** (silently wrong scores). → Spike 4.
- **The regression rule misbehaves in practice:** false alarms on an A/A
  run, or a degraded agent not caught at 5 repeats. ADR-001's claims
  ("about 1 in 2,000", "about 10 points detectable") are back-of-envelope
  until measured. **Likelihood: medium. Impact: high** (it's the core
  claim). → Spike 5, offline and free.
- **pydantic-ai's trace isn't enough** for graders and reports: missing
  per-tool-call timing, or tool results in an awkward shape. **Likelihood:
  medium. Impact: medium.** → Spike 2.
- **Library APIs move under us.** Already seen today: the `mcp` SDK
  renamed `streamablehttp_client` and `structuredContent` between versions.
  **Likelihood: high. Impact: low** if versions are pinned. → Exact pins
  in `uv.lock`, no unpinned ranges.
- **Filesystem server is slow or awkward to start per trial** (`npx`
  download on a cold cache, Node in CI, confinement to the temp dir).
  **Likelihood: medium. Impact: medium.** → Spike 3.
- **Sumopod rate limits (429) at 4 concurrent trials.** **Likelihood:
  low–medium. Impact: low** (retries absorb it; the error rate shows it).
  Observed during Spike 1.

**Integration**

- **A run starves MCP-backbone** on the shared 2 vCPU box. **Likelihood:
  low. Impact: high** (the public demo slows or fails). → Container CPU and
  memory limits (ADR-008), concurrency 4; Spike 3 measures a run's peak
  CPU and memory.
- **Keys leak on the VPS again** (the eval key already ended up in a VS
  Code history file once). **Likelihood: medium. Impact: medium.** → Keys
  only in the harness's own env file (mode 600), outside any folder VS Code
  opens; the runbook says how to rotate.
- **The live endpoint has a bad moment** (VPS restart, Caddy) mid-run.
  **Likelihood: low. Impact: medium.** Covered by design: transport
  failures are `error`, not `fail`, and >10% errors marks the run
  incomplete.
- **The demo data changes under a saved baseline** (someone reloads
  `pagila_demo` from upstream `master`). **Likelihood: low. Impact: high**
  (scores compared across different data). → Fingerprint the data at the
  start of every run and refuse to compare runs with different
  fingerprints (Spike 4 checks the fingerprint query passes the endpoint's
  own checks).

**Product (the reviewer)**

- **"Yet another eval framework."** A reviewer sees a CLI and a YAML format
  and stops. **Likelihood: medium-high. Impact: high.** → The README leads
  with the proofs: the degraded agent caught, the A/A run clean, real cost
  and latency numbers.
- **Scores are too high to show anything.** MCP-backbone already scored
  29/30; if every task is 5/5, regression detection looks trivial.
  **Likelihood: medium. Impact: medium.** → The filesystem suite includes
  genuinely hard and adversarial tasks (the planted prompt injection), and
  a second, cheaper model should score lower.

**People**

- **Time: 3–4 days against a ~5–6 day estimate.** **Likelihood: high.
  Impact: high.** The biggest risk, as in Project 1. The cut order is
  decided in Phase 2; the gate, its two proofs and both targets are never
  cut.

## Pre-mortem

Imagining this failed six months from now, the likely reasons:

1. The regression gate was never shown to work on real runs, so "catches
   regressions" was a claim, not evidence.
2. Scores were quietly wrong (unpassable tasks, rate-limited queries
   scored as fails, data drift) and nobody noticed because the numbers
   looked plausible.
3. Time ran out after the code and before the published runs and write-up,
   so a reviewer saw a tool with no results.

## Spikes (time-boxed, throwaway)

Spike code lives in the scratchpad, not the repo. Results are logged
below as each one runs.

1. **Does Sumopod return token usage, and what does one trial cost?**
   (~1 hour, < $0.10.) Run one Pagila task with pydantic-ai through Sumopod
   for 2 models; read `usage` from every response. **Pass:** input and
   output tokens on every model response, for both models. Also record
   tokens per trial and latency, and extrapolate the cost of a full run
   (all tasks × 5 repeats) against the $5 cap. **Fallback:** cost reported
   as unknown for that model, and the model is not used for published
   results.
2. **Does pydantic-ai's trace give graders and reports what they need?**
   (~1 hour, same runs as spike 1.) **Pass:** for every tool call: name,
   arguments, the full result, and a timing (measured around the call by a
   `process_tool_call` hook if the trace has none). Pin the exact working
   versions of pydantic-ai, `mcp` and `fastmcp`. **Fallback:** wrap the MCP
   toolset to record calls ourselves.
3. **Container + filesystem server per trial.** (~2 hours.) Build the
   image (Python + Node, pinned). Inside it, start
   `@modelcontextprotocol/server-filesystem` at a pinned version with
   `npx` (pre-installed in the image), pointed at a temp copy of a small
   fixture. Also measure the container's peak CPU and memory during a few
   trials, to set its limits. **Pass:** warm start
   ≤ 2 s; a read outside the temp dir is refused by the server; killing
   the process group leaves no `node` process behind; works with the Node
   on GitHub's `ubuntu-latest`. **Fallback:** one server per run instead
   of per trial, with the fixture reset between trials.
4. **Can expected answers and the fingerprint go through the live
   endpoint?** (~1–2 hours, ~40 of the eval workspace's 2000/hour.) Run
   MCP-backbone's 30 reference SQL queries through `run_query` with the
   eval key. **Pass:** all 30 succeed, none truncated at 200 rows, none
   rejected by the cost check or the function allowlist. Then try a
   fingerprint query (row counts + max ids per main table, and an md5 in
   UTC if `md5`/`string_agg` pass the allowlist). **Fallback:** rewrite a
   failing reference query, or drop the task with the reason recorded; a
   count-and-max-id fingerprint if hashing is rejected.
5. **Does the regression rule behave as ADR-001 claims?** (~1–2 hours, no
   API calls.) Monte Carlo in plain Python: 30 tasks with pass rates drawn
   from MCP-backbone's real results, 5 trials each. **Pass:** A/A false
   alarms ≤ 5% of simulated pairs; a uniform 15-point drop flagged ≥ 80%
   of the time; a single task collapsing 5/5 → 0/5 always flagged.
   Report the actual smallest drop detected 80% of the time; it replaces
   the "about 10 points" in the README. **Fallback:** adjust the rule
   (e.g. one-sided 90% interval) and re-run, and record that in ADR-001.

## Walking skeleton

The thinnest end-to-end slice, against the **real** endpoint, run in the
harness container **on the VPS** (`docker compose run harness run …`):
one hard-coded Pagila task and one trial, through
pydantic-ai and Sumopod to https://mcp.my.id/mcp/ with the eval key. It
writes `meta.json` + `trials.jsonl` (outcome, tool calls, tokens, cost,
latency) and grades with the ported `rows_equal`. Then `agent-eval compare`
of that run against itself exits 0. CI runs ruff, pyright and pytest, plus
`compare` on that committed run, with no API key. No repeats, no
statistics, no second target, no report yet: just proof that suite →
agent → MCP → grade → record → compare connects end to end.

## Spike results

Run 2026-10-23 from the laptop against the live endpoint. Total model
spend: one trial, about 2,250 tokens, well under one US cent.

### Spike 1 result: PASS — usage on every response, and a trial is cheap

One easy Pagila task, one trial, the configured Sumopod model, capped at 8
model requests and 60k tokens. Every one of the 4 model responses carried
input and output tokens, plus details such as reasoning tokens. Totals:
2,084 input + 167 output tokens, 4 requests, 7.6 s wall time, correct
answer. At typical mini-model prices that's a fraction of a cent per easy
trial, so a full Pagila run (150 trials, with harder tasks using several
times more tokens) should land well under $1, comfortably inside the $5
cap. **Still open:** Sumopod's actual per-model prices for `prices.yaml`
(Arthur to supply or point to them), and the second model, held back to
keep spend down until one is chosen.

### Spike 2 result: PASS — the trace has what graders need

`result.all_messages()` gives every tool call (name, arguments, id) and
every result as structured data (a `list` or `dict`, e.g. `run_query`'s
`{"status", "rows", "error"}`), linked by call id. Timings aren't in the
trace, but a `process_tool_call` hook measured each call (83–127 ms). One
quirk: MCP-backbone's tool schemas list an optional `api_key` parameter,
so the model sends `"api_key": null` on every call. That's harmless (over
HTTP the server uses the header), but the harness strips it from records.
Working versions on the laptop: pydantic-ai-slim 2.55.0, mcp 2.3.0,
fastmcp-slim 4.1.0, openai 3.31.0. These are pinned exactly, and checked
again on Python 3.12, since the laptop venv is 3.14.

### Spike 3: deferred

The Docker part runs on the VPS later (Arthur, 2026-10-23).

### Spike 4 result: PASS — every reference answer is reachable through the endpoint

All 30 reference queries succeeded through `run_query` with the eval key:
none truncated (the largest result is 6 rows), none rejected by the cost
check or function allowlist, each 150–500 ms. So expected answers can be
generated through the endpoint, against exactly what the agent sees. The
fingerprint also passes the endpoint's checks: counts (customer 999,
film 1000, rental 51805, payment 51061) and max ids; and `md5(string_agg(…))`
is allowed. The full-row hash matched the VPS session's
(`689f0fad…8442`), which confirms the server's session timezone is +08.
The harness uses hashes over non-timestamp columns, so the fingerprint
doesn't depend on timezone.

### Spike 5 result: FAIL as drafted — fixed and re-run

Monte Carlo, 300 simulated pairs per case, 2,000 bootstrap resamples, on a
mostly-easy suite (24 tasks at 97%, 6 between 40% and 80%) and a mixed
suite (30 tasks from 30% to 100%).

| | Mostly-easy | Mixed |
|---|---|---|
| A/A false alarms, rule as drafted (5/5 → ≤1/5) | 5.0% | **11.0%** |
| A/A false alarms, tightened (5/5 → 0/5) | 1.0% | 4.0% |
| Uniform 10-point drop flagged | 50% | 29% |
| Uniform 15-point drop flagged | 90% | 64% |
| Uniform 20-point drop flagged | 100% | 91% |
| One task collapsing (5/5 → 0/5) flagged | 100% | 100% |

The suite-level CI alone stays at 0.7–1.3% false alarms, as designed. The
"task broke" rule was the problem, so it's now 5/5 → 0/5 (ADR-001
updated). The "about 10 points" claim was wrong: the honest number is
about 13–14 points on an easy suite and about 18 on a mixed one, at 80%
detection. That's what the README will say.
