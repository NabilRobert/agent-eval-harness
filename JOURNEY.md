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

## 2026-10-23 — Slice C: the report

`report.md` is rendered from a run's records alone, deterministically, so
CI checks every committed report against a fresh render. A report can't
drift from its data or be edited to say something nicer.

What it reports, and how:
- **Strict pass rate is the headline.** Lenient is next to it, and errors
  are shown beside both but counted in neither.
- **pass^k:** the share of tasks that passed on every attempt. It only
  counts tasks with no errored attempts, since an error says nothing about
  the agent.
- **Cost:** shown as "unknown" without a price and as a lower bound when
  only partly priced, never as $0.
- **Every trial that didn't pass strictly** gets its tool sequence,
  expected vs got, and its last query.
- **Agent-written text is fenced safely.** It goes in a fence longer than
  any backtick run inside it, so it can't break the Markdown.

A slip on my side: when column order was fixed, I didn't bump the export
version, so two of the smoke run's rebuilds are recorded as "v2 → v2". The
history is left as it is; it's accurate about what happened. Now every
change to export output bumps the version (v3 adds task tags to the meta).

## 2026-10-23 — Real prices, and a save that wasn't atomic

Sumopod's prices are in `prices.yaml`: `gpt-5-mini` $0.25/M input and
$2.00/M output, `gpt-5-nano` $0.05/M and $0.40/M, with cached input at a
tenth of the input price. They're cited to Sumopod's pricing table and
dated. Repriced, the smoke run cost $0.0184 for 6 trials. A full Pagila run
(200 trials) is estimated at $0.61 on `gpt-5-mini`, from measured tokens.
Each run now records the exact price it was costed at.

Adding the prices exposed a real bug. YAML reads `checked: 2026-10-23` as a
date, JSON can't serialise a date, and `write_run` had already replaced
`trials.jsonl` before failing on the meta. The run was left with new trials
and an old meta, and its hash check would have refused it. Saving now
serialises everything first and then swaps each file in with an atomic
rename, so a failure leaves the run exactly as it was. A test checks this,
and fails against the old order. The damaged run was restored from git
and rebuilt from its Inspect log.

## 2026-10-23 — Slice D, offline: the gate

`compare` now decides. It uses a paired bootstrap of the mean per-task
change in strict pass rate, plus the "every attempt to none" task rule,
with exit 0, 1 or 2. Resampling n pass/fail trials with replacement is
statistically the same as a Binomial(n, observed rate) draw, so the
bootstrap draws binomials. That keeps 10,000 resamples fast in plain
Python, with a fixed seed so the same runs always get the same verdict. A
drop of 5 points or more whose interval still crosses 0 is "inconclusive"
(exit 0), with the dropped tasks named. Cost and latency increases are
warnings, not gates.

Two checks on the gate:
- **Synthetic tests.** These cover no change, a broad drop, one collapsed
  task, 5/5 → 1/5 (deliberately not flagged), an inconclusive drop,
  improvement and determinism. Each was mutation-checked against the old
  ≤1/5 rule, gating on the point estimate, and an unseeded generator.
- **The Spike 5 simulation, rerun through the shipped code.** False
  alarms came out at 3.0% and 1.0%, matching the throwaway version. The
  first rerun's "collapse" case was hollow: in the mixed suite it
  collapsed a task that almost never starts at 5/5, so it tested nothing
  (0/0). It now collapses the most reliable task, and catches 200/200.

Before any paid proof run, a one-trial check showed that removing
`describe_table` alone barely degrades the agent: it reads column names
with `sample_rows` instead. So the degraded agent for the proof loses
both. That choice, and the rule that whatever the gate says is published,
was written into the slice plan before running anything. Full runs now
refuse to start from a checkout with uncommitted changes, so every
published run traces back to one commit.

## 2026-10-23 — The live proofs: one passed, one failed, both published

Three full runs of `gpt-5-mini` on the frozen 40-task suite, $1.71 in
total.

- **The A/A pair isn't flagged:** 191/200 vs 192/200, +0.5 points
  (interval −3.0 to +4.5). That's the false-alarm proof, on real runs.
- **The degraded agent isn't flagged either.** Without `describe_table`
  and `sample_rows` it scored 185/200, only 3 points lower. The proof was
  pre-registered with "whatever the gate says is published", so this is
  the published result. The most likely reason: Pagila is a famous sample
  database, so the model knows its schema without looking. The schema
  tools were close to optional, and the agent compensated by reasoning
  more (output tokens +46%, cost +19%). Rerunning the gate simulation on
  the measured per-task rates shows a 3-point drop is caught only 14% of
  the time with 40 tasks × 5 attempts, while 10 points is caught 88.5% and
  15 points 99%. So the gate did what its power says. What failed was the
  choice of degradation, which was mine, and it's recorded as such.

Two lessons. First, "remove the schema tools" assumed the agent needs
them, and on a public dataset it doesn't. That's also a contamination
finding about the suite itself: it measures SQL writing more than schema
discovery. Second, the regrade check caught a real inconsistency: a trial
that ran the right query and then hit the message cap was failed by the
export but passed by the regrade. Both now apply the same rule (a cap hit
is a fail).
