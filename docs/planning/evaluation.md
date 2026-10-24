# Evaluation: the project measured against its own plan (2026-10-24)

Project 2 checked item by item against the Phase 1 success metrics and the
Phase 2 requirements, with evidence. It includes a cold-read test of the
README, which ran before the gaps below were fixed, so it reflects what a
reviewer would have seen. Gaps found here were either fixed on branch
`feat/evaluation-gaps` or are listed as open.

## Phase 1 success metrics

| Metric | Verdict | Evidence |
|---|---|---|
| One command runs a suite and produces a report: strict/lenient pass rate, cost and latency per task and in total | Met | `agent-eval run` writes `report.md`; CI checks every committed report against a fresh render |
| A deliberately degraded agent is flagged against a saved baseline, and the harness exits non-zero | Met | `fs-mini-degraded`: regression, exit 1, −61.2 points. The three Pagila degradations (−2.5 to −4.5) weren't flagged; they're published as failed pre-registered proofs |
| Any two runs can be compared later without re-running | Met | `compare` reads files only; CI runs it with no key or network |
| At least two agent setups, one of them MCP-backbone over its real endpoint | Met | Pagila on `https://mcp.my.id/mcp/`, filesystem over stdio |
| Results for at least two models published with methodology, including repeated runs | Met | 5 attempts per task in every run. `gpt-5-mini` has two full Pagila runs (the A/A pair), `gpt-5-nano` one per suite, plus confirmation trials |
| Anyone can reproduce with their own model key | Met after a fix (see below) | `repro/` matches the published runs on data fingerprint and tool-list hash. Since this branch, any Inspect provider works (`--model openai/...`); it was Sumopod-only before |
| A reviewer gets the design and tradeoffs from the README and ADRs in about 15 minutes | Mostly met (cold read below) | 8 of 10 questions found easily, 2 with effort. It flagged over-claiming, which has been fixed |

All non-goals were respected. There's no service, no public way to run on
Arthur's keys, no LLM judge, no claim that results generalise, and no
training.

## Phase 2 requirements

**Met:**
- run, compare and report, from YAML suites;
- Inspect over HTTP and stdio;
- result matching (strict/lenient), answer matching and forbidden tools;
- 5 repeats; pass^k, cost and latency;
- JSONL run records;
- exit codes 0/1/2;
- a budget cap that holds by construction;
- errors kept apart from fails, including rate limits;
- both suites, frozen by hash;
- regrading, with the grader version recorded;
- provenance, with `compare` listing what differs;
- the reproduction mode;
- both proof tests (the A/A pair, the degraded agent);
- two models published;
- README, ADRs, JOURNEY and CI;
- both Shoulds: failure traces in reports, and `confirm` validated by
  simulation before use.

**Gaps found, now fixed on this branch:**
1. **The `required_tools` grader** was listed as a Must and never built.
   Built, with a unit test and an offline end-to-end test, both
   mutation-checked.
2. **The target's address wasn't recorded** in run records. Every run now
   records the target's name, transport and address, and `compare` lists
   it when two runs differ.
3. **Reproduction needed Sumopod.** `run` required the `SUMOPOD_*`
   variables for every model. They're now required only for Sumopod
   models, and other providers' keys are passed through to Inspect.
   - Strict tool schemas are switched off only on the OpenAI-compatible
     route; Inspect's native OpenAI provider doesn't use strict mode.
   - Prices are keyed by full model id, so an OpenAI run is never costed at
     Sumopod's prices.
   - Verified with tests up to `--plan-only` (an OpenAI key alone is
     enough to plan; an unpriced full run is refused). A live run through
     another provider hasn't been done: there's no such key here.

**Still open:**
- **Keys outside the harness's own file.** `MCP_BACKBONE_EVAL_KEY` is
  still in MCP-backbone's `.env` on the VPS (and the repo copy, now mode
  600). Arthur to remove.
- **Server build for the published Pagila runs.** Not recorded, because
  MCP-backbone didn't report it yet. It's documented in the README's
  limitations. The VPS smoke runs do record it.

## Cold-read test

A fresh agent with no access to code or history read only `README.md`,
`RESULTS.md` and the ADRs, as a skeptical reviewer, and answered ten fixed
questions.

**Accuracy:** all ten answers were correct against the facts. It also got
two things the docs didn't spell out: that the per-trial cap depends on
Inspect enforcing it, and that a plain OpenAI key wasn't supported (gap 3).
Eight answers were "easy" to find. Two "took effort": which false-alarm
numbers are current, and what's not done, which was spread across sections.

**What it flagged, and what changed:**

| Flag | Change |
|---|---|
| "The gate doesn't raise false alarms" over-claims from one A/A pair | Reworded: one live A/A pair, plus the simulated rates |
| "It catches a real degradation" shows only the best case | Reworded: one large degradation caught, out of four tried |
| "The confirmation step resolves borderline cases" rests on n = 1 | Reworded to one case, n = 1, and the simulation result stated |
| The Pagila contamination explanation was called a "finding" | Marked as a hypothesis, not tested |
| False-alarm figures disagreed across README and ADR | One table per suite in the README; ADR-001 marks the assumed-rate figures as superseded |
| Latency +42% (filesystem) and +110% (Pagila) were mixed together | Stated per suite |
| Unclear why `confirm` compared nano with run 2, not run 1 | Explained: only that pair was inconclusive (−5.0 vs −4.5) |
| Different harness commits across compared runs | Explained: `compare` regrades everything with current graders, and CI checks every committed run regrades to its stored grades |
| The injection claim's sample size | Stated: 18 injection-task trials, 0 write calls in 263 filesystem trials, one attack only |
| "Exactly" matching reproduction | Narrowed to: matches on data and tools, outputs vary |
| No filesystem power analysis | Added: false alarms 0%; 65.5% detection at 10 points, 95.5% at 15 |
| Simulation uncertainty not given | Added (200 pairs: ±7 points around 50%, ±1–4 near the ends) |
| Inspect-vs-ours boundary only in ADR-009 | A table at the top of the README |
| No single limitations section | A "Limitations" section |
| No CI evidence | A CI badge |

**Not addressed, because each needs new paid runs or is out of scope;
listed honestly in the README's limitations:**
- more than one live A/A pair;
- a live moderate (8–15 point) degradation caught;
- a second model family or provider;
- an audit of grader false passes and false fails;
- a data comparison of the bootstrap gate against simpler rules (a fixed
  threshold, a per-task test).
These would be the next evidence to buy if the project continues.

## Spend

About $3.50 of model calls in total, across all smoke, proof, confirmation
and VPS runs. The cold-read test and every simulation used no model calls
through the Sumopod key.

## Grader audit (follow-up, 2026-10-24)

Every non-passing trial in the 8 published runs (136) was read and
classified: what was expected, what the agent produced, and its last query
or final answer.

| Cause | Trials | Verdict |
|---|---|---|
| Message or cost cap hit (49 of them the filesystem degraded agent, 12 nano on the filesystem) | 64 | genuine fails |
| "(UTC)" in the question not handled: bare dates compared in the session's time zone, or converted back through it | 35 | genuine, but environment-dependent (below) |
| Strict only: right values, extra or reordered columns | 22 | by design; lenient counts them |
| Wrong answer, other (e.g. an invented "UNRATED" rating row, a different late-return definition) | 12 | genuine |
| Borderline: right in substance, wrong form (`src/acme/pricing/ discounts.py` with a space; 23.92 vs 23.93 days from averaging whole days) | 2 | ambiguous |
| **Grader false fail:** "March 14, 2026" for `2026-03-14` | 1 | grader limitation |

**The graders are sound.** One clear false fail in 136, and counting it
(and both borderline cases) as passes would move `fs-nano` from 67/85 to at
most 69/85. Its comparison with mini stays a regression (about −18
points). Fixing date formats would mean a new filesystem suite version and
new published runs, so it's recorded here rather than patched in.

**What the audit really found: a time-zone dependence.** 35 of Pagila's 64
non-passing trials come from 5 "(UTC)" tasks. A query that ignores "UTC"
reads a bare date in the database session's time zone, which is +08 on the
live server. The same query gives 9,098 rentals for 2025 there, but 9,092,
the right answer, on a UTC database. The local reproduction
(`postgres:16.10-alpine`, UTC by default) would have graded those answers
as correct, even though its data fingerprint matched exactly. The
fingerprint covered the data, not the session. Fixed:
- Every run records the session's UTC offset, through the endpoint.
- The Pagila suite records the offset it was published at (+28,800 s), and
  a run refuses a target at any other offset.
- `repro/` sets its database to Asia/Shanghai (+08, no DST). Locally, the
  same UTC-ignoring query now gives 9,098, as live does.

## The gate against simpler rules (follow-up, 2026-10-24)

A reviewer would ask why a bootstrap and not something simpler, so every
candidate rule was run on the same simulated pairs
([`scripts/compare_rules.py`](../../scripts/compare_rules.py); 200 pairs
per case, rates measured from the real runs, plus ADR-001's flakier
assumed suite). No API calls.

```
40 tasks x 5 attempts, 200 simulated pairs per case, base ['../runs/proof-mini-a', '../runs/proof-mini-b']
| Rule | no change (false alarm) | uniform drop 3% | uniform drop 5% | uniform drop 10% | uniform drop 15% | measured uneven drop (4.8%) |
|---|---|---|---|---|---|---|
| shipped gate (bootstrap + task rule) | 0.0% | 12.0% | 34.5% | 88.0% | 100.0% | 21.5% |
| within-task bootstrap (fixed suite) + task rule | 4.5% | 35.0% | 70.5% | 96.5% | 100.0% | 68.5% |
| fixed threshold: drop >= 5 pts | 0.0% | 14.0% | 49.0% | 95.0% | 100.0% | 45.5% |
| fixed threshold: drop >= 10 pts | 0.0% | 0.0% | 2.0% | 51.0% | 95.5% | 1.0% |
| pooled two-proportion z-test | 0.5% | 18.0% | 51.5% | 94.0% | 100.0% | 44.0% |
| per-task Fisher, any task p<0.05 | 2.0% | 3.0% | 5.0% | 9.0% | 14.0% | 29.0% |
| per-task Fisher, Bonferroni | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |

17 tasks x 5 attempts, 200 simulated pairs per case, base ['../runs/fs-mini-base']
| Rule | no change (false alarm) | uniform drop 3% | uniform drop 5% | uniform drop 10% | uniform drop 15% | measured uneven drop (20.0%) |
|---|---|---|---|---|---|---|
| shipped gate (bootstrap + task rule) | 0.0% | 5.5% | 23.5% | 70.0% | 92.0% | 99.0% |
| within-task bootstrap (fixed suite) + task rule | 2.5% | 23.5% | 43.0% | 88.0% | 97.0% | 100.0% |
| fixed threshold: drop >= 5 pts | 0.0% | 14.5% | 43.0% | 90.0% | 99.0% | 100.0% |
| fixed threshold: drop >= 10 pts | 0.0% | 0.0% | 5.5% | 52.5% | 87.0% | 99.0% |
| pooled two-proportion z-test | 0.5% | 20.5% | 37.5% | 81.5% | 96.5% | 100.0% |
| per-task Fisher, any task p<0.05 | 0.5% | 0.0% | 1.0% | 0.5% | 5.5% | 98.0% |
| per-task Fisher, Bonferroni | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |

30 tasks x 5 attempts, 200 simulated pairs per case, base ['mixed']
| Rule | no change (false alarm) | uniform drop 3% | uniform drop 5% | uniform drop 10% | uniform drop 15% |
|---|---|---|---|---|---|
| shipped gate (bootstrap + task rule) | 1.0% | 5.0% | 8.5% | 28.0% | 66.0% |
| within-task bootstrap (fixed suite) + task rule | 5.5% | 12.5% | 28.5% | 56.5% | 89.5% |
| fixed threshold: drop >= 5 pts | 12.0% | 32.0% | 51.0% | 80.0% | 99.5% |
| fixed threshold: drop >= 10 pts | 2.0% | 9.5% | 20.5% | 50.0% | 86.5% |
| pooled two-proportion z-test | 0.0% | 6.0% | 12.5% | 39.5% | 80.5% |
| per-task Fisher, any task p<0.05 | 17.0% | 24.0% | 26.5% | 32.5% | 53.0% |
| per-task Fisher, Bonferroni | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
```

**What it shows:**
- **A fixed threshold isn't calibrated.** "Drop ≥ 5 points" looks good on
  the near-saturated real suites, but raises **12% false alarms** on the
  flakier suite. ADR-001's reason for rejecting it holds.
- **Per-task Fisher tests don't work at 5 attempts.** Uncorrected, they
  raise 17% false alarms on the flaky suite; with Bonferroni, they catch
  nothing.
- **A fixed-suite bootstrap** (resampling attempts only, not tasks) catches
  much more, but runs at **2.5–5.5% false alarms**. With 5 attempts, a task
  that went 5/5 looks noise-free when it isn't.
- **The pooled two-proportion z-test beats the shipped gate on every
  suite**: false alarms of 0–0.5%, and higher detection everywhere. For
  example, a 10-point drop is caught 94% / 81.5% / 39.5% of the time,
  against the gate's 88% / 70% / 28%. Resampling tasks makes the shipped
  gate answer "would this hold on tasks like these?", which is a more
  conservative question than a CI gate on a fixed suite needs.

**Decision: the published verdicts stay as they are.** They were made with
the pre-registered gate, and switching rules after seeing the data is what
pre-registration exists to prevent. Under the pooled test the published
verdicts wouldn't change anyway: mini vs nano on Pagila gives z = 1.79,
below the 1.96 needed to flag. **Recommended for future comparisons
(Arthur's call):** a gate v2 that uses the pooled z-test plus the task
rule, written down before any comparison uses it.
