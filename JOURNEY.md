# Journey

What was built, what broke, and what was wrong, in order. The planning
record is in [docs/planning/](docs/planning/); this file is the build log.

## 2026-10-23 — Planning, then a review that changed the runner

Phases 1–7 were written first. A senior-review pass over the finished
plan asked the question a reviewer would ask first: why not an existing
eval framework? A one-trial spike showed Inspect AI already runs agents
well (MCP tools, repeats, limits, retries, per-call usage and timings), so
the harness now runs on Inspect and builds only what Inspect lacks: the
regression gate, offline comparison of committed runs, regrading and
provenance (ADR-009). The first Inspect trial failed with a 400 before any
tokens were spent. Inspect sends tools in OpenAI strict mode, and
MCP-backbone's optional `api_key` tool parameter isn't allowed there, so
strict schemas are off for now and the root cause is recorded against
MCP-backbone.

The same review found that MCP-backbone couldn't say which build it was
(an empty MCP version, nothing in `/healthz`), so runs couldn't record what
they were graded against. That's fixed in MCP-backbone on a branch.

## 2026-10-23 — Slice A: the walking skeleton

One task, one trial, through Inspect to the live endpoint, exported to
`runs/skeleton/`, with CI comparing committed runs and no API key.

- **A test that couldn't fail.** "No `api_key` argument is recorded" was
  asserted on the skeleton run, but that run's model never sent one, so
  breaking the stripping left the test green. The assertion was dropped
  and replaced by a direct unit test, which does fail.
- **Secrets checked by value, not by hope.** Each run's output is searched
  for the actual key values before anything is written. Separately, the
  zstd-compressed Inspect log was unpacked and searched by hand: neither
  key, the base URL, nor any auth header appears in it.

## 2026-10-23 — Slice B: real suites, and two bugs only a real run found

The Pagila suite now has 40 tasks: MCP-backbone's 30 (copied verbatim by
parsing its seed file, not retyped) plus 10 expert ones (window functions,
relational division, many-to-many traps). Expected answers are generated
through the live endpoint, so no task can expect something the agent
can't reach. The generator refuses empty, truncated or oversized answers,
and "top 1" questions whose first two rows tie. It caught one (the most
rented film per rating tied 104/104 in PG-13), which now has an explicit
tie-break rule in its wording. The 30 regenerated answers match an earlier
independent run of the same queries exactly. The suite is frozen: its hash
is in the code, and CI fails if the file changes without a deliberate new
hash.

Verified rather than assumed (each was an open question in Phase 4):
- **Repeats run attempt by attempt:** every task's attempt 1, then
  attempt 2.
- **No response caching** at Sumopod: identical requests got different ids
  and answers, with 0 cached tokens.
- **`cost_limit` is per trial,** which made a stronger budget guard
  possible: each trial is capped at budget ÷ trials, so the whole run can't
  exceed the budget even counting trials in flight. That closes the
  overshoot Phase 4 had documented as a known limit.
- **Every outcome is classified correctly:** pass, fail, a rejected query
  (fail), a rate-limited one (error), a runaway agent hitting its cap
  (fail), a crashing model (error). This is tested offline with Inspect's
  mock model, and each rule is mutation-checked.

The 6-trial smoke run (3 tasks × 2 repeats) found two bugs:

1. **Long tool arguments were recorded as `attachment://<id>`.** Inspect
   moves long strings into an attachments table, and the export didn't
   resolve them, so the record held a reference instead of the SQL.
2. **Sorted JSON keys reordered every stored row's columns.** Strict
   grading compares columns in order, so regrading a stored, correct
   multi-column answer failed it. `compare`'s regrade check caught this on
   the very first self-comparison, which is the check doing its job. Task
   hashes had the same flaw: reordering an expected answer's columns didn't
   change the hash. Rows and task hashes now keep key order; only the data
   fingerprint and tool-list hashes (where order means nothing) still sort.

Neither needed a paid re-run. `agent-eval reexport` rebuilds a run's
records from its saved Inspect log, the raw evidence, with the current
export code, and records the rebuild in the run's meta. Both committed
runs were rebuilt this way. CI now checks that every committed run is
intact and regrades to its stored grades.
