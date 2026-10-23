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
3. **Filesystem server per trial.** (~1–2 hours.) Start
   `@modelcontextprotocol/server-filesystem` at a pinned version with
   `npx`, pointed at a temp copy of a small fixture. **Pass:** warm start
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

The thinnest end-to-end slice, against the **real** endpoint:
`agent-eval run` with one hard-coded Pagila task and one trial, through
pydantic-ai and Sumopod to https://mcp.my.id/mcp/ with the eval key. It
writes `meta.json` + `trials.jsonl` (outcome, tool calls, tokens, cost,
latency) and grades with the ported `rows_equal`. Then `agent-eval compare`
of that run against itself exits 0. CI runs ruff, pyright and pytest, plus
`compare` on that committed run, with no API key. No repeats, no
statistics, no second target, no report yet: just proof that suite →
agent → MCP → grade → record → compare connects end to end.

## Spike results

*(filled in as each spike runs)*
