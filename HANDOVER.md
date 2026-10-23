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
  recommended: paired bootstrap CI over tasks + "task broke" (5/5 → ≤1/5),
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
- **Next:** Arthur reviews Phase 6, then run spikes 1–5 (results logged in
  the doc), then Phase 7 (slices).
- **Convention:** conventional commits (`feat(scope):`, `fix:`, `docs:`).
