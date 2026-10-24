# Handover (2026-10-23)

Context for a fresh session. Read this first; it replaces the long chat history.

## Working with Arthur

- **Terse, plain answers.** Recommend one option, don't list everything.
- **Commit, never push.** Arthur pushes himself. Commit in phases (one per
  logical step), not one big commit at the end. End commit messages with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Never read, print or move secrets.** `.env` values (API keys, DB
  passwords, the encryption key) stay unprinted; when one is needed, pipe it
  through a script without echoing. Allowed to *use* `SUMOPOD_API_KEY` and
  `AI_MODEL` from `.env` (benchmark runs), never to display them.
- **Verify, don't assume.** Test against real Postgres, check the live site
  from outside, view frames/screenshots before claiming something works. If a
  test can't fail, say so and drop it (it happened once).
- **VPS work goes through Arthur or the VPS Claude session.** Send it
  read-only checks via `SendMessage` (find its current name with `ListAgents`;
  it's a Remote Control session and gets renamed). If its own safety check
  blocks an action, do NOT ask it again or route around it: give Arthur the
  command to run himself.
- Arthur's own Claude sessions sometimes run things on the VPS at his request;
  check state before assuming a step is still pending.

## The bigger picture: why these projects exist

**Goal:** a portfolio that gets Arthur hired as an AI / backend engineer:
job fairs, applications, his CV and website. The plan was written with
Japan-style employers in mind, who value reliability, documentation and
polish over novelty, so READMEs and the CV (rirekisho) must be consistent and
precise.

**Where it came from:** Arthur's private "Jarvis" project, a broad personal
assistant platform (web, mobile, agents, voice, many data sources). The plan
(`~/Downloads/portfolio-plan.md`) concluded Jarvis is the wrong showcase: it's
the most common AI portfolio project, breadth reads as unfinished, and
reviewers can't tell it from a weekend demo. **Decision: Jarvis stays a
private tool; the portfolio is three small, finished, deep projects.**
MCP-backbone was extracted from Jarvis and hardened (its workspace was named
"jarvis"; the name lingers in a few identifiers).

**The three pieces, and how they connect:**

| # | Project | What it proves | Status |
|---|---|---|---|
| 1 | MCP-backbone | Can build a safe, tested, deployed AI-facing system (security, typing, CI, ops) | Done |
| 2 | agent-eval-harness | Can *measure* whether an agent works: pass rate, cost, latency, regressions | Planning |
| 3 | Beobot case study | Real system, real users: Arthur's actual agentic automation work, sanitised, with metrics (request volume, success rate), failure modes, what changed and the measured result | Not started |
| ongoing | Open-source PRs | A maintainer trusted his code: start small (docs, bugs, tests, types) in MCP SDKs and agent frameworks like LangGraph | Not started |

They reinforce each other: Project 2 uses Project 1 as a real target, and
Project 3 is evidence nothing else can fake. Order of work: 1 → 2 → 3, PRs in
parallel a little at a time.

**Principles that shaped Project 1 and apply to every project:**
- **Depth and proof over scope.** Claims are backed by tests, published
  results, or live checks (red-team suite, benchmark, threat model).
- **A reviewer should get it in about 15 minutes** from the README and ADRs.
- **Plan before building, and keep the record:** phase docs and ADRs with
  rejected alternatives and sources; JOURNEY.md logs what broke and what was
  wrong, honestly. Arthur must be able to defend every decision unscripted.
- **Finish things.** Explicit non-goals, fallbacks decided in advance, and
  "done" measured against the project's own written success metrics.
- **Honesty over polish:** state limits and failures openly (e.g. benchmark
  misses explained, not re-scored).

## Project 1: MCP-backbone — DONE

- **Repo:** `~/Desktop/my-kerjaan-aku/MCP project` → github.com/NabilRobert/MCP-backbone
  (public, MIT). All committed and pushed as of `5cbac78`.
- **What it is:** read-only database MCP server. Python 3.12, FastAPI, MCP SDK
  (Streamable HTTP), SQLAlchemy async + asyncpg, sqlglot, Postgres 16, Alembic.
  Console: Jinja2 + a little TypeScript (esbuild; compiled `main.js` is
  committed, CI checks it matches).
- **Live:** https://mcp.my.id (landing page with 3-step demo GIFs, signup, console),
  MCP endpoint https://mcp.my.id/mcp/, `/healthz` checks the DB.
- **Evaluated against all three plan docs: every item met.** Key docs: README,
  ARCHITECTURE.md, THREAT_MODEL.md (T1–T10), RED_TEAM.md, BENCHMARK.md,
  JOURNEY.md (build log), docs/planning/phase-1..7 (ADRs 001–010 in phase-5),
  deploy/RUNBOOK.md.
- **Benchmark:** 30 hand-written Pagila questions (10 easy/medium/hard),
  graded strictly + leniently by execution accuracy. `gpt-5-mini`: run 1 28/30,
  run 2 29/30 strict / 30/30 lenient (after a list_tables partition fix and a
  question fix). Code: `scripts/seed_eval_cases.py`, `scripts/run_benchmark.py`,
  `app/benchmark/grading.py` (`rows_equal`, `rows_equal_strict`). This is the
  seed for Project 2.
- **Local dev:** tests need `APP_TEST_DATABASE_URL` (docker container
  `jarvis-mcp-test-db`, port 55432, db `test`); suite refuses non-"test" DBs.
  Laptop `.env` target DB = Sumopod Pagila. Run checks:
  `.venv/bin/ruff check . && .venv/bin/pyright app/ tests/ scripts/ && .venv/bin/pytest tests/ -q`
  (130 tests). `gh` CLI isn't installed: check CI via
  `curl -s https://api.github.com/repos/NabilRobert/MCP-backbone/actions/runs?per_page=1`.
- **VPS:** 43.134.28.228 (Tencent, Ubuntu, CST clock), app at `~/MCP-backbone`,
  systemd unit `mcp-backbone` (uvicorn 8443 TLS), Tamara's Caddy container
  (`tamara-site`) proxies mcp.my.id:443 → 172.18.0.1:8443. ufw on (22/80/443
  open, 8443 only from Caddy's Docker net). Local Postgres: bookkeeping DB
  `jarvis_mcp_bookkeeping`, demo DB `pagila_demo` (login `pagila_ro`, read-only).
  Workspace `sumopod-external` queries Sumopod (kept as an external DB).
  Deploy: `cd ~/MCP-backbone && git pull && .venv/bin/alembic upgrade head && sudo systemctl restart mcp-backbone`
  (back up first with `~/bin/backup_bookkeeping.sh` when migrating). Migration
  head: `d2b7f4a9e6c1`.
- **Loose ends (Arthur's choice to leave):** a commented-out `WORKSPACE_API_KEY`
  line in the VPS `.env`; optional uptime + healthchecks.io monitoring
  (RUNBOOK). Raw demo footage is in `docs/demo/raw/` (gitignored).
- **Tooling tips:** the browser preview can't read files under ~/Desktop
  (macOS permission); copy to the scratchpad and serve with
  `/usr/bin/python3` (3.9, no `datetime.UTC`). No ffmpeg: Swift +
  AVFoundation/ImageIO handles video frames and GIFs (scripts were in the
  old scratchpad; easy to rewrite).

## Project 2: agent-eval-harness — PLANNING STARTED

- **Folder:** `~/Desktop/agent-eval-harness` (not yet a git repo; will be its
  own public repo). Name chosen: `agent-eval-harness`.
- **Approach:** plan phase by phase like Project 1 (problem brief →
  requirements → domain model → flows/failures → ADRs → risks/spikes → slices),
  then build in vertical slices.
- **Done:** draft `docs/planning/phase-1-problem-brief.md`. Proposed success
  metrics: one command → pass rate (strict/lenient), cost and latency per task;
  a deliberately degraded agent is flagged as a regression and exits non-zero
  (CI-able); runs saved and comparable later; works on ≥2 agent setups incl.
  MCP-backbone over its real endpoint; ≥2 models published with repeated runs.
  Non-goals: no leaderboard, no web app, LLM-as-judge optional only, not an
  agent framework.
- **Phase 1 final (2026-10-23), repo initialised.** Decisions: adapter-based
  targets ("model + MCP server" first); deterministic grading first, LLM
  judge optional; second target = reference filesystem MCP server on a
  fixture dir; at most $5 per full run, 5 repeats per task; full scope in 3–4
  days (keep phase docs short, Arthur reviews each before the next).
- **Phase 2 drafted** (requirements; awaiting Arthur's review). Regression rule
  recommended: paired bootstrap CI over tasks + "task broke" (5/5 → 0/5, tightened by Spike 5),
  proven by degraded-agent and A/A tests.
- **Phase 3 drafted** (domain model: Suite/Task/Target/AgentConfig/Run/Trial/
  Grader/Comparison; no Baseline entity; pure grading/compare/report modules).
- **Phase 4 drafted** (run/compare flows, failure table, trust boundaries).
- **Phase 5 drafted** (ADR-001..007). ADR-007 decided: per-workspace
  rate-limit override in MCP-backbone (live limit confirmed 5/hr by the VPS
  session). Done on MCP-backbone branch `feat/limit-tests`: `4b9e5ea` feat,
  `81c52d1` role-level statement_timeout for pagila_ro, `cd125ef` docs.
  135 tests pass; migration `d2b7f4a9e6c1` checked up/down/up. Merged (see below).
- **MCP-backbone change shipped (2026-10-23):** merged to main via PR #1
  (`4e418e9`), deployed and verified on the VPS (migration `d2b7f4a9e6c1`,
  `eval` workspace 2000/2000, `pagila_ro` statement_timeout=30s). Eval key
  was rotated in the console; it lives only in the harness `.env`
  (`MCP_BACKBONE_EVAL_KEY`, gitignored, 0600). Live check: 7/7 `run_query`
  calls succeeded over https://mcp.my.id/mcp/.
- **pagila_demo fingerprint (VPS, 2026-10-23):** current upstream Pagila
  (expanded: customer 999, film 1000, rental 51805, payment 51061 in 55
  monthly partitions 2022-01..2026-07, staff 1500, store 500). "599" was the
  old Pagila; 999 matches MCP-backbone JOURNEY.md:446. md5 (t::text, ordered
  by PK, session TZ +08): customer 689f0fad…8442, film 3d4c659a…0f1343,
  rental 29b35037…dd1c, payment 26c76779…53b. Loader pulls upstream
  `master` unpinned, so Sumopod's copy may differ; harness generates
  expected answers from the live endpoint and should fingerprint the data
  at run start (use UTC for hashes). No benchmark question is
  time-relative.
- **VPS hygiene (Arthur):** delete the key from the VPS `.env` and VS Code
  history copies; `~/.bash_history` holds another workspace's key (chmod 600,
  remove the line, rotate that key).
- **Phase 6 drafted** (risks, pre-mortem, 5 spikes, walking skeleton).
- **Deployment (ADR-008, Arthur 2026-10-23):** the harness runs on demand
  in its own Docker container on the MCP-backbone VPS (own dir, Compose
  project, network, CPU/mem limits, env file 0600 with eval + Sumopod
  keys), calling https://mcp.my.id/mcp/ like any client. Runs go to a
  volume; Arthur copies the ones to publish to the laptop and commits.
  No scheduler, no GitHub credential on the VPS.
- **Spikes run (2026-10-23, laptop):** 1, 2, 4 pass; 5 failed as drafted,
  so the broken-task rule was tightened to 5/5 → 0/5 (A/A false alarms
  1–4%; 80% detection at ~13–14 pts easy suite, ~18 pts mixed). Spike 3
  (Docker) deferred to the VPS. Spend: one trial, ~2.25k tokens, <1 cent.
  Arthur wants AI spend kept conservative: cap every live run, measure
  before scaling, ask before a second model.
- **Models (Arthur, 2026-10-23):** `gpt-5-mini` + `gpt-5-nano`. One nano
  trial: same answer, ~9× mini's output tokens (reasoning), 2× slower, so
  roughly the same cost per task at list prices. Harness `.env` has
  `SUMOPOD_AI_API_KEY` (base URL still read from MCP-backbone's `.env`;
  to add to the harness env file later).
- **Open:** Sumopod per-model prices for `prices.yaml`.
- **Later idea (not v1):** an "is upgrading `gpt-5-mini` → `gpt-5.4-mini`
  worth it?" before/after comparison as a README section, only after a
  one-trial cost check. Also possible later: one non-OpenAI model (Gemini /
  DeepSeek / Qwen flash) once tool calling through Sumopod is checked.
- **Phase 7 drafted:** slices A skeleton → B suites/repeats/failures → C
  report → D compare + gate + live proofs → E filesystem → G publish; F
  (container on VPS) whenever the VPS is free. Spend plan: dev only on a
  3-task smoke suite at 1 repeat; every full run announced with its
  estimate and needs Arthur's OK; ~6 full runs for all of v1.
- **Senior-review pass applied (2026-10-23):**
  - **ADR-009:** trials run on **Inspect AI** (0.3.283); we build the gate,
    regrading, provenance and fingerprinting on its logs. pydantic-ai
    (ADR-003) is superseded. Spike 6: one capped Inspect trial worked once
    `strict_tools=False` (MCP-backbone's optional `api_key` param breaks
    OpenAI strict mode).
  - **ADR-010:** a local reproduction mode (`repro/`, pinned MCP-backbone +
    pinned Pagila commit matched by fingerprint) = new slice H.
  - Suites frozen (hash recorded) before published runs; ~10 harder Pagila
    tasks; strict is the headline; `compare` regrades both runs and lists
    provenance differences; scope worded as "model + prompt + MCP server
    in Inspect's agent loop"; the "task broke" rule false alarms add up
    over repeated use (stated); inconclusive → `confirm` reruns (Should);
    Spike 5 reruns on measured rates; day-3 checkpoint after slice D.
  - New risks: Sumopod/LiteLLM response caching (verify in slice B),
    suite contamination (date results), silent model-alias updates.
- **MCP-backbone branch `feat/server-version` (`4a67282`, not pushed):**
  MCP handshake + `/healthz` report the running build (`git describe
  --dirty`); 138 tests pass. Needs merge + deploy before slice F.
- **MCP-backbone follow-up (proposed):** drop the optional `api_key` tool
  parameter from the HTTP-facing schema (strict-mode clients reject it).
- **Slice A done (2026-10-23, 4 commits `a51b046`..`19a8cb6`, not pushed):**
  package `agent_eval/` (grading, records, compare: pure; inspect_tasks,
  preflight, export, cli), Python 3.12 venv via uv, exact pins + `uv.lock`,
  CI workflow (ruff, pyright strict, pytest, compare with no key). Live
  skeleton run `runs/skeleton/`: gpt-5-mini 1/1 strict, 3,262+381 tokens;
  its records and Inspect log scanned clean of both keys, the base URL and
  any auth header. 26 tests; each new check was mutation-tested, and one
  vacuous assertion (api_key never sent in this run) was replaced by a
  direct unit test. Known: the skeleton's `harness_git` is
  `47157d7d4efc-dirty` (run before the code was committed), and
  `server_version`/`healthz_version` are null until MCP-backbone's
  `feat/server-version` is deployed. Published runs (slice D+) must come
  from a clean tree.
- **Run locally:** `uv sync --frozen --extra dev`; `uv run agent-eval run`
  needs `SUMOPOD_BASE_URL` in the harness `.env` (Arthur to add; for now
  passed in from MCP-backbone's `.env` at the command line, unprinted).
- **Slice B done (2026-10-23, not pushed):** `suites/pagila.yaml` = 40 tasks
  (30 MCP-backbone verbatim + 10 expert x01–x10), expected answers generated
  via the endpoint (`agent-eval generate-expected`), **frozen** (hash
  `a79b59cb…` in `agent_eval/suites.py` FROZEN_SUITES; a test fails if the
  file changes). Data fingerprint `fa70dca8…` taken at every run start.
  Budget guard: per-trial cap = budget ÷ trials (Inspect `cost_limit` is
  per sample); unpriced models limited to ≤10 trials (`prices.yaml` empty
  until Sumopod prices arrive). Verified: epochs attempt-by-attempt, no
  Sumopod caching, outcome classification (offline mock-model tests,
  mutation-checked). Smoke run `runs/smoke-b1` (3 tasks × 2, 5/6 strict,
  6/6 lenient) found two export bugs: unresolved `attachment://` args, and
  sorted JSON keys reordering row columns (caught by compare's regrade).
  Fixed; `agent-eval reexport` rebuilt both committed runs from their
  Inspect logs. 57 tests. JOURNEY.md started.
- **Spend today:** ~12 small trials + a 3-call caching probe, well under $0.10.
- **Harness on GitHub** (github.com/NabilRobert/agent-eval-harness), CI green
  on `e9e2589`. Arthur says the code is on the VPS too. MCP-backbone's
  `feat/server-version` is NOT pushed/deployed yet (live /healthz has no
  version).
- **Slice C done (2026-10-23, not pushed):** `agent_eval/report.py` renders
  report.md deterministically from records (strict headline, lenient,
  pass^k/pass@k, errors beside rates, cost unknown/lower-bound, latency,
  per-difficulty and per-task tables, failed-trial details with safe
  fences, provenance). `agent-eval report [--check]`; run and reexport
  write it; CI checks every committed report. Export v3 (task tags in
  meta). 65 tests, mutation-checked.
- **Prices in (Arthur, 2026-10-23):** gpt-5-mini $0.25/$2.00, gpt-5-nano
  $0.05/$0.40 per M (cache read 1/10). Full Pagila run ≈ $0.61 on mini.
  Fixed a non-atomic `write_run` the YAML date exposed.
- **Slice D offline done:** gate in `compare` (paired bootstrap via
  binomial draws, 10k resamples, seed 20261023; broken = all→0 with ≥5
  trials each side; inconclusive at ≤ −5 pts; cost/latency warnings),
  `scripts/simulate_gate.py` (A/A false alarms 3.0% / 1.0%),
  `--exclude-tools`, clean-tree guard for full runs. 74 tests.
- **Live proofs run (branch `feat/slice-d-proofs`, $1.71):** a 191/200, b
  192/200, degraded 185/200. A/A not flagged ✓. Degraded NOT flagged
  (−3.0 pts, CI −9.5..+2.5): the proof failed as pre-registered and is
  published as such. Likely cause: the model knows Pagila's schema from
  training. Measured-rate simulation: A/A 0.5%, 3-pt drop caught 14%,
  10-pt 88.5%, 15-pt 99%. Fixed: the regrade now fails limit-hit trials
  like the export does. Results in Phase 7 + JOURNEY.
- **Second degradation run (pre-registered):** `proof-nano` 182/200, −4.5
  vs a (not flagged), −5.0 vs b (inconclusive), $0.28, 2× latency (warning
  fired). Fallback `proof-mini-prompt` (no final-query line) 186/200, −2.5,
  not flagged. **Live "degraded agent is flagged" metric NOT met**; the gate
  never false-alarmed; the suite is saturated and Pagila is likely in the
  training data. Total proof spend ≈ $2.41.
- **Slice E done + proof met live (2026-10-24, branch feat/slice-d-proofs):**
  filesystem target (pinned server-filesystem 2026.8.31 in tools/fs-server,
  fresh fixture copy per trial via agent_eval/fs_server.py), synthetic
  acme-shop fixture + 17-task suite (frozen, built by
  scripts/build_filesystem_suite.py), graders answer_match/forbidden_tools.
  `fs-mini-base` 84/85 vs `fs-mini-degraded` (no discovery tools) 32/85 →
  **regression, exit 1** (−61.2 pts, 9 broken tasks). Injection task 5/5.
- **confirm step built + validated + used:** `agent-eval confirm` on
  mini-b vs nano (the inconclusive pair) → fresh 8 tasks × 10: mini 73/80,
  nano 58/80 → **regression confirmed** (−18.8 pts on those tasks). a vs
  nano not eligible (−4.5). Record in `confirmations/`.
- **Spend:** proofs ≈ $2.41 + filesystem $0.54 + confirm $0.37 ≈ $3.3 total.
- **Slice G done (2026-10-24):** `fs-nano` 67/85 (−20 pts vs mini, flagged).
  `agent-eval publish [--check]` renders RESULTS.md + the README results
  block from records named in `results.yaml` (CI checks it). README
  rewritten (results, gate, measured power, methodology, caveats, not-done).
  Injection resisted in every fs run (0 write calls). 89 tests.
- **Spend to date ≈ $3.45** (proofs, confirm, fs runs).
- **Slice H done (2026-10-24):** `repro/` (Dockerfile + compose + setup):
  MCP-backbone 4e418e9 + Pagila upstream 85bf46a → fingerprint fa70dca8
  matches exactly, tool list hash matches. Target `mcp-backbone-local`
  (http://127.0.0.1:8765/mcp/, key read via `docker compose exec`);
  `--target`; every run refuses data its suite wasn't generated against
  (`data_mismatch`). Smoke `runs/smoke-h1` 2/3. 91 tests.
- **Follow-ups:** MCP-backbone CI publishing a prebuilt image (slow builds);
  strict-schema `api_key` fix; server-version deploy.
- **Slice F built + tested locally (2026-10-24):** `Dockerfile` (node stage
  for fs-server, python image, non-root uid=1000 build arg, build commit
  stamped via HARNESS_GIT), `.dockerignore`, `deploy/compose.yaml` (1 CPU,
  1 GB, read-only root, cap_drop ALL, env file
  ~/.config/agent-eval/env), `deploy/RUNBOOK.md`. Spike 3 passed in the
  container. **Verified on the VPS (2026-10-24):** after a Dockerfile fix
  (40915c7, files at 600 on the VPS were unreadable to the non-root user),
  `vps-smoke-fs` 2/2 and `vps-smoke-pagila` 1/1, server build d2d19f8b4aec
  recorded, harness 40915c776cfc. **All 8 slices done.**
- **VPS state:** harness at ~/agent-eval-harness (feat/slice-d-proofs),
  keys in ~/.config/agent-eval/env (600); the earlier container draft is in
  ~/agent-eval-harness-draft-2026-10-23/ (has digest-pinned base images,
  worth carrying over). MCP-backbone deployed at d2d19f8 (version reported).
  The VPS session working on this is "Harness container smoke tests".
- **Project 2 complete (2026-10-24):** everything merged to main (99eb7aa),
  CI green on GitHub (incl. report/publish checks). MCP-backbone main at
  d2d19f8, deployed, /healthz reports its version.
- **Open (Arthur):** remove MCP_BACKBONE_EVAL_KEY from ~/MCP-backbone/.env;
  the other workspace's key in ~/.bash_history.
- **Next big piece:** Project 3, the Beobot case study (not started).
- **Follow-ups:** pin base images by digest (from the draft); MCP-backbone
  strict-schema api_key fix; MCP-backbone CI publishing an image.
  Arthur: push + merge `feat/slice-d-proofs`; deploy MCP-backbone
  `feat/server-version`; the strict-schema fix proposal.
- **Convention:** conventional commits (`feat(scope):`, `fix:`, `docs:`).
