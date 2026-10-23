# Phase 1 — Problem Brief

**Project:** `agent-eval-harness`, a small, standalone tool that measures
whether an AI agent actually works, and catches it when a change makes it
worse. The second of three portfolio pieces (after the
[MCP-backbone](https://github.com/NabilRobert/MCP-backbone) database MCP
server; before the Beobot case study). Like the first, it should be small
enough for a reviewer to read, and prove its claims rather than state them.

## Problem

Most agent projects can't say whether they work. A demo shows one good run;
nobody knows the pass rate, what a run costs, how long it takes, or whether
last week's prompt tweak or model upgrade quietly broke something. Teams
building agents struggle with exactly this: changes are cheap to make and
expensive to verify, so regressions ship unnoticed.

The concrete case already in hand: MCP-backbone's benchmark showed both
sides of it. A tool change (hiding table partitions) and a question fix
moved the score from 28/30 to 29/30, and that comparison was done by hand,
across two report files, with no cost or latency numbers at all.

## Affected parties

| Party | Wants |
|---|---|
| Arthur (builder) | A finished project that demonstrates the evaluation discipline AI teams need, defensible in an interview |
| Reviewer / AI engineering team | Evidence the candidate can measure agent quality, cost and latency, and catch regressions, not just build demos |
| Someone building an agent or MCP server | A way to answer "did my change make it better or worse, and at what cost?" with one command |

## How it's handled today, and where it breaks

- **Eyeballing a few runs:** misses intermittent failures; an agent that
  passes 7 times in 10 looks fine in a demo.
- **One-off benchmark scripts** (like MCP-backbone's): measure one thing at
  one moment; comparing runs is manual, and cost and latency go unrecorded.
- **Large public benchmarks:** measure a model in general, not *your* agent
  with *your* tools and prompts.
- **LLM-as-judge everywhere:** convenient, but adds its own errors and cost,
  and makes scores hard to reproduce.

## Success metrics (verifiable, no invented usage data)

- One command runs a task suite against an agent and produces a report:
  pass rate (strict and lenient where grading allows), and cost and latency
  per task and in total.
- **Regression detection is proven, not claimed:** a deliberately degraded
  agent (a worse prompt, a removed tool) is flagged as a regression against
  a saved baseline, and the harness exits non-zero so CI can fail on it.
- Runs are recorded so any two can be compared later (model A vs B, before
  vs after a change), without re-running anything.
- Works against at least two different agent setups, one of them
  MCP-backbone over its real MCP endpoint, so it isn't tied to one project.
- Results for at least two models are published with their methodology,
  including repeated runs, since a single run of a non-deterministic agent
  proves little.
- A reviewer understands the design and its tradeoffs from the README and
  ADRs in about 15 minutes.

## Non-goals (current pass — revise as planning continues)

- No public leaderboard, and no claim that results generalise beyond the
  task suites used.
- No training or fine-tuning.
- No hosted service or web app; output is files (a report and run data).
- No public way to run it on Arthur's keys. The code and published results
  are public; anyone else runs it with their own model key. Runs that
  spend Arthur's Sumopod credit, or the eval workspace's raised rate
  limit, are started only by Arthur.
- LLM-as-judge is not the primary grading method. If added, it's optional,
  and reported separately from deterministic grading.
- Not a general agent framework: it evaluates agents, it doesn't build them.

## Decisions (settled 2026-10-23)

1. **What it evaluates:** any agent reachable through an adapter. The first
   adapter is "a model + an MCP server", which covers MCP-backbone and any
   other MCP server.
2. **Grading:** deterministic checks first (exact or tolerant result match,
   as in MCP-backbone; required/forbidden tool calls). An LLM judge is
   optional, used only where nothing deterministic fits, and reported
   separately.
3. **Second target:** the official reference filesystem MCP server
   (`@modelcontextprotocol/server-filesystem`) against a fixed fixture
   directory. It's non-SQL, offline and free, and it can be reset between
   runs, so its results can be reproduced.
4. **Budget:** at most $5 per full run on the Sumopod key, with 5 repeats per
   task. That allows mini-class models with full repeats, plus a single pass
   with a larger model.
5. **Time budget:** full scope in 3–4 days. Planning is compressed to hours,
   so each phase doc stays short and is reviewed before the next one starts.

## Cost of doing nothing

The portfolio keeps one strong project instead of two, and the claim
"I can tell whether an agent works" stays unproven, though it's the skill
AI engineering teams most need and most often lack.
