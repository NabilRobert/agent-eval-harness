# Phase 5 — Architecture and Decisions

## Components

Modules as in Phase 3 (`suites`, `targets`, `agent`, `grading`, `runner`,
`compare`, `report`, `cli`). The one rule that matters: `grading`, `compare`
and `report` are pure and never import `targets` or `agent`, so CI can run
`compare` with no API key and no network.

## Stack

- **Python 3.12**, packaged as one installable package with an
  `agent-eval` console command. CLI built on Typer (ADR-011; it replaced
  `argparse`).
- **Agent loop, repeats, limits and MCP client:** Inspect AI, pinned exactly
  (ADR-009; it superseded pydantic-ai, ADR-003).
- **Statistics:** standard library + `random.Random(seed)`. The bootstrap is
  about 20 lines, so pulling in numpy/scipy isn't worth it.
- **Tooling:** ruff, pyright (strict), pytest, GitHub Actions, the same as
  MCP-backbone.
- **Tracing (optional):** the OpenTelemetry SDK and its OTLP/HTTP
  exporter, off unless an endpoint is set (ADR-012).
- **Runtime:** one Docker image (Python 3.12 + Node, both pinned) run on
  demand on the VPS with Docker Compose (ADR-008). Also runs on the laptop
  for development.
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
**Context:** 5 repeats per task, about 30 tasks per suite (as built: 40 for
Pagila, 17 for the filesystem suite). Pass rates move
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
2. Any task went from 5/5 to 0/5. (First drafted as "1/5 or less";
   Spike 5 showed that version firing on 4–10% of A/A pairs, because a
   task that passes 50–70% of the time can swing from 5/5 to 1/5 by luck,
   and several such tasks add up. With 0/5 the A/A false-alarm rate is
   1–4%, and a task that really collapses is still caught every time.)

pass^k is reported, not used as a gate. Cost (+25% median) and latency only
**warn** by default.
**Why not the others:** (a) isn't calibrated to noise; (b) has almost no
power with 5 trials, and 30 tests stacked together give false alarms;
(d) is too blunt for a single number.
**Proof required (Phase 7):** a degraded agent **is** flagged; an A/A run
(the same agent twice) is **not**.
**Consequences (measured in Spike 5):** a uniform drop is caught 80% of
the time at about 13–14 points of pass rate on a mostly-easy suite, and
about 18 points on a mixed one. A 10-point drop is caught only 30–50% of
the time. Smaller drops show in the report but don't fail CI, and the
README says so. The percentile bootstrap with ~30 clusters is approximate;
that's acceptable for a gate, and stated.
**Measured on real runs (slice D/E, 2026-10-24; these supersede the
assumed-rate figures above for the published suites):** on the per-task
rates of the two Pagila baseline runs, false alarms are 0.5%, and a uniform
drop is caught 14% of the time at 3 points, 40.5% at 5, 88.5% at 10 and 99%
at 15. On the filesystem suite's measured rates (17 tasks): false alarms
0%, and 4% / 22% / 65.5% / 95.5% at 3 / 5 / 10 / 15 points. Fewer tasks,
less power. Live: the A/A pair wasn't flagged; three Pagila degradations of 2.5–4.5
points weren't flagged (below the gate's power, published as failed
proofs); the filesystem degradation (−61.2 points) was flagged on both
rules; `confirm` resolved an inconclusive −5-point model swap into a
confirmed regression.
**Compared with simpler rules (2026-10-24, `scripts/compare_rules.py`):**
- A fixed 5-point threshold raises 12% false alarms on a flakier suite, and
  per-task Fisher tests are useless at 5 attempts, so those rejections hold.
- But the pooled two-proportion z-test had lower or equal false alarms
  (0–0.5%) and more detection than this gate on all three suites tested.
  Resampling tasks makes the gate conservative for a fixed-suite CI
  question.
- Published verdicts keep this pre-registered gate.
**Gate v2 adopted for future comparisons (Arthur, 2026-10-24):**
- **The rule:** a pooled two-proportion z-test on strict passes over the
  shared tasks, one-sided, flag at z > 1.96 (the same 2.5% tail as v1),
  **or** the task rule (all → none, at least 5 trials each side).
  "Inconclusive" and `confirm` are defined as before.
- **Closed-form:** no resampling, so no seed.
- **How it's applied:** `compare` and `confirm` default to v2, `compare`
  reports both verdicts, and every comparison published before the
  amendment stays pinned to v1 in `results.yaml`.
- **Measured as shipped** (`scripts/compare_rules.py`, 200 pairs per case):
  false alarms 0.5% / 0.5% / 1.0% (Pagila / filesystem / flaky suite,
  against v1's 0 / 0 / 1.0%). Detection is higher everywhere, e.g. a
  10-point drop: 94 / 81.5 / 40.5% against v1's 88 / 70 / 28%. Nano's
  real uneven drop on Pagila: 44% against 21.5%.
**Revisit if:** suites grow past ~100 tasks (consider a clustered standard
error instead), or repeats change.
**Amendments (2026-10-23, senior review):**
- **False alarms add up over repeated use.** At 1–4% per comparison, a
  team gating every change would expect a false alarm about once every
  25–100 comparisons. The README states that, and the report always shows
  the change with its interval, so a flag can be judged rather than
  obeyed blindly.
- **Inconclusive results get a confirmation step (Should):** when the
  point estimate is a drop of 5 points or more but the interval still
  crosses 0, `compare` exits 0, marks the result *inconclusive* and names
  the tasks that dropped. A local `confirm` command reruns just those
  tasks for **both** agents and decides on the fresh trials only, so the
  tasks picked for dropping don't bias the retest. CI never runs it (no
  key). It's used only after the same simulation as Spike 5 shows its
  false-alarm rate stays ≤ 5%.
- **The simulated pass rates were assumptions, not measurements.** Spike 5
  gets rerun with the per-task pass rates observed in the A/A pair, and
  the README quotes those results, not the assumed ones.
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

### ADR-003: pydantic-ai as the agent loop, behind the `agent` module — **superseded by ADR-009**
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
**Superseded (2026-10-23):** a senior-review pass asked "why not an
existing eval framework?", and Spike 6 showed Inspect AI already does
the running well. See ADR-009.

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
**Amended by ADR-009:** Inspect's own `.eval` log is kept next to these
files as the raw evidence (committed for published runs), and `meta.json`
+ `trials.jsonl` are exported from it. `compare` and `report` read only
the exported files.

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

### ADR-008: Run on demand in a separate container on the VPS
**Context:** Arthur wants the harness on the same VPS as MCP-backbone, but
isolated from it.
**Options:** (a) on-demand container: started for a run, exits after;
(b) scheduled container (cron, nightly or weekly); (c) an always-on
service with an API or UI; (d) the laptop only.
**Decision:** (a). `docker compose run harness <command>` in its own
directory (not inside `~/MCP-backbone`), its own Compose project and
network, CPU/memory limits, and an env file (mode 600) for the eval key
and the Sumopod key. It calls MCP-backbone through
`https://mcp.my.id/mcp/` like any outside client. Runs go to a volume;
Arthur copies the ones worth publishing to the laptop and commits them
there.
**Why not the others:** (b) costs up to ~$150/month nightly at the $5
cap, and needs alerting; (c) breaks the Phase 1 non-goals "no hosted
service" and "no public way to run it on Arthur's keys": anyone who
could trigger a run would be spending his model credit; (d) works, but leaves the harness undeployed next to a deployed
Project 1.
**Consequences:** the keys live on the VPS again, so they're kept out of
MCP-backbone's `.env` and out of any VS Code-tracked folder. Tool-call
latency excludes real network time, and the methodology says so. CI is
unaffected: it only compares committed runs.
**Revisit if:** scheduled regression runs become worth the cost (then
(b), with a smaller suite).
**Built (slice F, 2026-10-24):**
- `Dockerfile` and `deploy/compose.yaml`, with `deploy/RUNBOOK.md`.
- Locked down: a non-root user whose uid matches the host's `runs/`
  owner, a read-only root filesystem, no capabilities, 1 CPU, 1 GB.
- The keys come from an env file outside the repo, and never from the
  image (`.dockerignore` excludes `.env`).
- The image has no `.git`, so the build commit is stamped in, and full
  runs still refuse a dirty or unknown one.

### ADR-009: Run trials on Inspect AI; build the regression gate on its logs
**Context:** the first question a senior reviewer would ask is "why not
an existing eval framework?" Inspect AI (UK AI Security Institute),
promptfoo, DeepEval and Braintrust all run agent evals. Inspect has MCP
tools (HTTP and stdio), repeats (`epochs`), turn/time/token/cost limits,
retry on error, concurrency, a mock model for offline tests, and
structured logs readable from Python. Spike 6 ran one capped trial through
Inspect against the live endpoint. It recorded token usage on every model
call, a timing on every tool call, and the model name the provider
actually served, and it got the right answer.
**Options:** (a) keep our own runner on pydantic-ai (ADR-003); (b) run on
Inspect and build what it lacks on top of its logs; (c) use Inspect alone
and write no harness.
**Decision:** (b). What Inspect doesn't do, and this project exists for:
a statistical regression gate across repeated runs (ADR-001) with CI exit
codes; comparison from committed files with no key and no network;
reproducible regrading; run provenance (what changed between two runs);
and data fingerprinting. Inspect runs; we gate.
**Consequences:**
- Less code to write and defend: the agent loop, repeats, retries and
  limits are a well-tested library's, not ours.
- The README can say plainly what's new versus what's reused, which is
  the stronger story for a reviewer.
- We depend on Inspect's log format. It's pinned exactly, and `export` is
  the one module that reads it, so a format change breaks one module,
  visibly.
- Strict tool schemas are turned off for the Sumopod provider: MCP-backbone's
  optional `api_key` parameter fails OpenAI's strict mode (Phase 4
  revision).
**Rejected:** (a) re-implements a standard tool, worse; (c) has no
regression gate, the whole point of the project.
**Revisit if:** Inspect's log format churns between minor versions, or a
target needs a loop Inspect can't run.
**Sources:** [Inspect AI](https://inspect.aisi.org.uk/) docs (MCP tools,
epochs, limits); Spike 6 (Phase 6).

### ADR-010: Results reproducible by others (local mode, pinned data)
**Context:** published Pagila results come from Arthur's VPS with his eval
key; nobody else can rerun them, so a reviewer has to trust the numbers.
The demo data is also loaded from upstream `master`, unpinned.
**Options:** (a) local mode: a Compose setup with MCP-backbone (built
from a pinned commit), Postgres, and Pagila loaded from a pinned upstream
commit with a checksum; (b) share a read-only key publicly; (c) publish
only, no reproduction.
**Decision:** (a). `docker compose up` in `repro/`, seed an eval
workspace, then run the suite against `localhost` with your own model
key. The harness checks the local data fingerprint against the one in
the published runs before it runs, and refuses on a mismatch.
**Consequences:** the upstream Pagila commit that matches the VPS's data
has to be found, by loading candidate commits locally until the
fingerprint matches. If none matches, the VPS data is reloaded from a
pinned commit and the published runs are made after that. Local latency
isn't comparable with the VPS's, and the README says so.
**Rejected:** (b) spends Arthur's rate limit and breaks the "no public
use on his keys" non-goal; (c) fails the reproducibility metric.
**Outcome (slice H, 2026-10-24):**
- **The first candidate matched.** Pagila at upstream `85bf46a` (the last
  commit to touch the schema or data) gives exactly the published
  fingerprint `fa70dca8…`, and the local server's tool list hash equals
  the published runs'.
- **No host bind mount.** It hung on a macOS folder permission during
  development, so generated settings and the local key live in a Docker
  volume, and the harness reads the key with `docker compose exec`.
- **The fingerprint guard became general.** Every run checks it against
  the suite's recorded fingerprint, for the live endpoint as well as the
  local copy.

### ADR-011: Typer for the CLI, replacing argparse
**Context:** the CLI started on `argparse` because three subcommands
didn't justify a dependency. It grew to seven, and Arthur's other
projects settled on Typer: mcp-gateway's CLI uses it, and his rules
(2026-10-28) say to use the shared stack rather than hand-roll what a
framework does.
**Options:** (a) keep `argparse`; (b) Typer; (c) Click directly.
**Decision:** (b), at mcp-gateway's exact version (0.27.3) and in its
style. Typer 0.27 carries its own copy of Click, and Rich was already
installed for Inspect, so the lock gains only Typer and shellingham.
The commands, options, defaults, exit codes and the harness's own
messages are unchanged, checked by recording every command's help and
the CI commands' exit codes before and after the change. `cli.py` still
imports Inspect only inside `run`.
**Consequences:**
- `--help` and usage errors look different: Typer's panels instead of
  argparse's plain text. Usage errors still exit 2.
- Paths inside the checkout show their defaults as `<repo>/...`, not as
  the machine's absolute path.
- Typer's pretty tracebacks are off: they can print local variables,
  and `run` holds the env file's keys in locals.
- argparse accepted unambiguous abbreviations (`--plan` for
  `--plan-only`); Click doesn't. Nothing in the repo used them.
**Rejected:** (a) leaves the one CLI that looks different from the rest
of the portfolio; (c) would mean writing decorators where type hints do
the work, and differs from the gateway.
**Revisit if:** Typer and the gateway diverge on versions, or Typer's
startup cost becomes noticeable in CI.

### ADR-012: Optional OpenTelemetry traces, one per trial
**Context:** agent-observability (Project 6) needs one live trace from
the agent through mcp-gateway and MCP-backbone to Postgres (its ADR-009).
The MCP SDK 2.3.0 the harness already uses opens a client span for every
request and injects the trace context into the request's `_meta`, but
only once a tracer provider is installed, and with nothing above them
each request would start its own trace. Inspect AI 0.3.283 has no
OpenTelemetry code to reuse.
**Options:** (a) install a provider and add one parent span per trial;
(b) a third-party tracing layer (OpenInference, Langfuse's SDK); (c) no
tracing in the harness, leaving it to agent-observability's replay of
Inspect logs; (d) depend on MCP-backbone's `app/tracing.py`.
**Decision:** (a), off unless `OTEL_EXPORTER_OTLP_ENDPOINT` (or the
traces-only variable) is set, so a normal run is unchanged.
`agent_eval/tracing.py` copies MCP-backbone's exporter setup and its
capped 2 s shutdown (`app/tracing.py` at `5f38bd2`), and wraps the agent
in two spans per trial: `eval sample {id}` (named as agent-observability's
replay names it) and `invoke_agent react` (the GenAI conventions' agent
span). Spans follow agent-observability's `docs/conventions.md`: no
prompts, answers or tool arguments; an error records only its class.
`scripts/scripted_pagila_agent.py` drives the database path with
Inspect's mock model, as `scripts/gullible_agent.py` drives the
filesystem one, so a trace costs $0.
**Consequences:**
- Two new pinned dependencies, `opentelemetry-sdk` and
  `opentelemetry-exporter-otlp-proto-http` 1.45.1, the version of the
  `opentelemetry-api` the MCP SDK already brought in.
- Inspect's log names the solver `traced_agent` instead of `react`.
  Nothing reads that name: export reads samples, events and scores.
- The MCP SDK names its client spans `MCP send tools/call <tool>`, not
  the `tools/call <tool>` the conventions table shows; the harness
  leaves the SDK's spans as they are.
- A dead viewer loses spans; the run still finishes, at most 2 s later.
**Rejected:** (b) uses its own attribute names rather than the
OpenTelemetry GenAI ones the portfolio follows, and adds a dependency
for a few lines of glue; (c) can't put the trace context into the live
requests, so the server's spans could never join the agent's trace;
(d) MCP-backbone is a server, not a package: depending on it would
install its whole stack, and its module reads its own settings.
**Revisit if:** Inspect gains OpenTelemetry support, or the MCP SDK's
span names change with the conventions.
