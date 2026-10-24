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

## 2026-10-23 — The second degradation, and what five live runs say

Two more pre-registered runs. Neither was flagged:
- **`gpt-5-nano` in place of mini:** 182/200, −4.5 points (interval
  −10.0 to +0.5). Against the other baseline it was "inconclusive",
  −5.0 points.
- **The fallback prompt, without "call run_query exactly once with your
  final answer query":** 186/200, −2.5 points. The model ended on a
  correct query anyway.

So the live half of "a degraded agent is flagged" isn't met, and the
README won't claim it. What the runs do establish: the gate didn't raise
a false alarm in any of the four comparisons, and its misses are where its
measured power says they'd be. This suite, close to saturated and on a
dataset the model already knows, barely moves under any of the three
degradations tried. That's the most useful thing the harness has found so
far, and it's a finding about the suite rather than the gate.

Nano is the one consistent drop: about −5 points against both baselines,
at half the cost and twice the latency. The latency warning is the only
thing that fired. Resolving a 5-point drop needs either more attempts on
the tasks that moved (the `confirm` step) or a less saturated suite.

## 2026-10-24 — Slice E, and the degradation proof passing for real

The filesystem target runs the pinned reference MCP filesystem server on a
fresh temp copy of a synthetic fixture for every trial. Inspect opens one
server session per sample, and a smoke run confirmed distinct copies and
no leftovers. The fixture and its 17 tasks are generated deterministically,
and the answers are computed from the same data (each also checked with
plain shell tools). Every task forbids writes, and one reads a planted
prompt injection.

The smoke run caught a grader bug of mine. The injection task expected
"thursday", and the whole-token rule failed both correct answers ("moved to
Thursdays"). Numbers still need an exact end ("17" can't match "170"), but
a word may now take a suffix. This was fixed before the suite was frozen.
The export now recomputes grades from stored inputs, and rebuilding every
committed run changed 0 of 1,019 outcomes.

Then the proof that Pagila couldn't give. With the four discovery tools
withheld, the agent fell from 84/85 to 32/85. The gate flagged it on both
rules: −61.2 points (interval −82.4 to −37.6), and 9 tasks from every
attempt passing to none. The fails are genuine: the agent burned its
20-message cap guessing paths (402 reads, 232 `get_file_info` calls). The
same degradation idea that did nothing on Pagila works here, because here
the tools are actually needed. The injection task passed 5/5 without a
single write.

Finally, `confirm`. It was validated by simulation first (A/A false alarms
0%; on a nano-shaped drop, detection went from 27% to 45%), then applied to
the one comparison its rule allows: mini-b vs nano, inconclusive at −5.0.
On fresh trials of the 8 tasks that dropped, mini scored 73/80 and nano
58/80, a confirmed regression (−18.8 points on those tasks, interval −33.8
to −3.7). Nano's ~5-point suite-wide drop is real; a single 5-attempt run
just couldn't say so.

## 2026-10-24 — Slice G: publishing without typing a number

The published results are generated. `results.yaml` names the runs,
comparisons and confirmation to publish. `agent-eval publish` recomputes
every number from the committed records, re-deciding each comparison with
`compare`, and renders RESULTS.md plus the README's results table. CI runs
`publish --check`, so a published number can't drift from its records or
be tidied by hand: changing one "84/85" to "85/85" in the README fails it.
The three failed Pagila proofs are marked "(not as expected)" in the
tables, not left out.

The last run, `gpt-5-nano` on the filesystem suite, scored 67/85 against
mini's 84/85: −20 points, flagged outright. That's the same model swap that
only `confirm` could resolve on Pagila, which is the clearest contrast
between a suite where tools matter and one the model already knows.

Two corrections before publishing. I'd drafted "nano costs about half"; on
the filesystem suite it's about a third. And I'd only checked the
prompt-injection claim on one run, so I checked it on every filesystem
run (both models and the degraded agent): no trial in any of them called
a write tool. The tables also now say "pts" for changes in pass rate, so
"−3.0" can't be misread as a relative change.

## 2026-10-24 — Slice H: anyone can rerun Pagila

The published Pagila numbers came from my VPS, which nobody else can use.
`repro/` now brings up the same server and the same data locally, so they
can be checked with your own model key:
- MCP-backbone pinned to a commit and built from its lockfile;
- Pagila pinned to an upstream commit;
- everything loaded and provisioned by MCP-backbone's own scripts, not
  copies of them.

Which upstream commit matched the VPS was an open question, since the VPS
had loaded `master` unpinned. The fingerprint answered it: the first
candidate, the last commit to touch the schema or data, matched exactly.
The local tool list's hash matched too.

The first attempt hung on a host bind mount: Docker needed macOS permission
for the Desktop folder. Even though it came through later, the setup now
keeps everything in Docker volumes and the harness reads the local key with
`docker compose exec`, so nobody reproducing it hits the same wall. The
image build was slow (Debian mirrors at tens of KB/s). Publishing a
prebuilt image from MCP-backbone's CI would fix that, and is a follow-up.

Two small things I got wrong along the way. My first secret scan of the
local smoke run printed nothing: piping a heredoc into Python had used up
the script's input, so the scan never ran. "No output" isn't "clean", so it
was rerun properly (clean). And the fingerprint check that ADR-010 asked
for is now a general rule rather than a local-mode one: every run refuses
data its suite wasn't generated against, including the live endpoint.

## 2026-10-24 — Slice F: the container

The harness now has its own image, for on-demand runs on the VPS:
- **The pinned filesystem server** is built in a Node stage from its
  lockfile. Only the node binary and its modules are copied into the
  Python image.
- **Locked down at run time:** a non-root user, a read-only root
  filesystem, no capabilities, 1 CPU and 1 GB, so a run can't starve
  MCP-backbone on the shared box.
- **Keys come from an env file** kept outside the repo, never from the
  image.

Two details that would have broken it:
- **No `.git` in the image.** The clean-tree guard would have refused
  every full run as "unknown", so the build stamps in the commit it was
  built from.
- **File ownership.** The container user's uid has to match whoever owns
  the mounted `runs/` folder on the host, or run records can't be written.

The Spike 3 checks deferred from planning all passed inside the container:
- the server starts in 0.12–0.20 s;
- it refuses to read `/etc/passwd`;
- no server processes or fixture copies are left behind;
- a 2-trial smoke run peaked at about 232 MiB of the 1 GiB cap.

One more filter slip of mine: I'd hidden the server's "allowed directories"
log lines, which also hid the confinement result, since the refusal
message uses those words. It was rerun unfiltered.

## 2026-10-24 — The first VPS build: file modes

The image built on the VPS, but the first run crashed: `PermissionError`
reading `agent_eval/__init__.py`. Some files in the VPS checkout were mode
600, `COPY` keeps host modes, and the container runs as a non-root user,
so it couldn't read its own code. My laptop's 644 files hid this. The fix
belongs in the image, not on the server: everything under `/app` is made
readable during the build, whatever the host had. I reproduced the failure
locally first (a fresh clone with every file set to 600: old Dockerfile
crashes, new one reads fine). Dependencies now also install in their own
cached layer, so a code change rebuilds in seconds.

The fixed image then built and ran on the VPS: the filesystem smoke run
passed 2/2, and the Pagila one 1/1, reaching `mcp.my.id` from a container on
the same machine through Caddy. Both runs record the server build
(`d2d19f8b4aec`) and the harness commit stamped into the image. With that,
all eight slices of the plan are done.

## 2026-10-24 — Evaluating it against its own plan

Checked item by item against Phase 1 and 2 (`docs/planning/evaluation.md`).
Three real gaps:
- **`required_tools`** was a Must that never got built.
- **The target's address** wasn't recorded in run records.
- **"Anyone can reproduce with their own key" wasn't true:** `run` demanded
  Sumopod's variables for every model.

All three are fixed. The provider fix had a trap in it: Sumopod's prices
were looked up by model name alone, so an OpenAI run would have been
costed at Sumopod's prices. Prices are now keyed by the full model id.

Then a cold read. A fresh agent saw only the README, RESULTS and the ADRs,
and answered ten reviewer questions. It got all ten right, which says the
docs work, but it also caught me over-claiming:
- "doesn't raise false alarms" from a single A/A pair;
- "resolves borderline cases" from one case;
- a contamination hypothesis called a finding;
- two latency figures from different suites run together.

Those are reworded to what the evidence supports. The filesystem suite got
the power analysis it was missing (weaker than Pagila: 65.5% detection at
10 points), and the README gained a single limitations section. The
evidence the reviewer wanted but this project didn't buy (more A/A pairs, a
moderate live degradation, a second model family) is listed as such, not
glossed over.
