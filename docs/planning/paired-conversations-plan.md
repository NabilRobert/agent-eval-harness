# Paired multi-turn comparisons: the pilot slice (accepted)

*2026-11-04. Arthur accepted the slice ("OK the slice") and picked a
large degradation ("Large, ~30+ points"). Building waits for Project 10
(AI Flight School, `docs/planning/thesis-pilot.md` there) to confirm the
interface below. The pilot runs after Flight School's slice 4. The ADRs
below move to the Phase 5 doc when the slice is built.*

## Why

Arthur's master's thesis asks (RQ3) whether a simulator-plus-judge
evaluation ranks agent versions correctly, using deliberately degraded
agents as ground truth, and how many conversations each decision needs.
This is part D of Project 15 (`id-chat-research`). Its pieces are:
- Project 10 supplies the simulated customers and runs the agents;
- Project 15 supplies the rubric judge and its noise estimates;
- this harness compares the runs.

What the harness has today doesn't fit as is:
- **Its gates pair tasks, not conversations.** Gate v1 bootstraps over
  tasks; gate v2 pools trials. Neither uses the fact that run A and run
  B met the *same* simulated customer with the same seed. That pairing
  is where the power comes from.
- **It doesn't treat the customer as part of the instrument.** If the
  customer model or its settings change between runs, the change would
  show up as an agent change.
- **Its power estimates are scripts** (`scripts/simulate_gate.py`,
  `scripts/compare_rules.py`), run after the fact. RQ3 needs the sample
  size *before* the run.

## The interface (Project 10's proposal, with the harness's requests)

Project 10 writes normal harness run records, one run per agent variant,
with `export.trial_from_sample` and `records.write_run`.
- **Pair key: `(task_id, attempt)`.**
  - `task_id` is the scenario: persona × goal × tactic, plus a seed.
  - `attempt` is the epoch.
  - There's no separate `pair_id`.
- **Extra trial fields:**
  - `customer_seed` and `scenario` (`{persona_id, goal_id, tactic_id}`);
  - `stop_marker`: `###DONE###`, `###GAVE_UP###` or `###GHOSTED###`;
  - `divergence_turn`: the first turn where the two arms' agents replied
    differently, for the thesis analysis (the gate doesn't use it).

  Checked on main (199657b): `write_run` and `load_run` keep these
  fields, the trials hash covers them, and `compare` accepts the runs.
- **The task hash covers the scenario:** the persona card, goal and
  tactic text go in the task's `prompt`.
- **The meta's `customer` block** holds the customer model and its
  generation settings.
- **The harness reads run records only.** The `ChatRecord` JSONL export
  stays Flight School's.

## The slice

Pilot scale only. It shows the pipeline works end to end; it doesn't
answer RQ3.

1. **Grader `customer_outcome`** and the customer check (ADR-013).
2. **Gate v3, paired** (ADR-014): `agent-eval compare --gate v3`.
3. **`agent-eval plan-pairs`** (ADR-015): the pairs needed before a run.
4. **The pilot runs**, pre-registered below. They run on local models
   through Project 10, at $0.

Estimated size: code about 150 lines (grader and customer check 30, gate
60, `plan-pairs` 50, CLI wiring 10), plus about 200 lines of tests and a
guide update.

## Decisions (accepted 2026-11-04)

### ADR-013: Grades come from stored inputs; the customer is pinned

**Decision:**
- **Pass in the pilot is a grader with a stored input:**
  `customer_outcome`, with spec `{pass_markers: ["###DONE###"]}` and
  input `{stop_marker}`.
  - Gave up, ghosted, or a hit turn limit is a fail. A hit limit is
    already failed by `regrade`.
  - It regrades like `result_match`, with no model call.
  - It's a placeholder until Project 15's rubric judge exists (Arthur,
    2026-11-04). The report labels it "the simulator grading itself".
- **A different `customer` block between two runs is incomparable**
  (exit 2), as a different task hash is.
- **Later, once Project 15's rubric judge exists:** each per-construct
  score is its own grader with a stored input. A model judge's grade is
  read back, not re-run. It's pinned the same way: its spec carries the
  judge model and codebook hash, and two runs judged differently are
  incomparable. The judge must come from a different model family than
  the simulated customer, to avoid self-preference bias (Arthur, e.g.
  Sailor2-8B and Qwen3.5-9B). A plain `scores` dict on the trial is
  rejected because it couldn't be regraded or pinned.
- **Not built in this slice:** the judge's grader. It waits for the
  judge, so there's no speculative code.

**Why:** the gate's promise is that a stored grade and a regrade agree,
and that only the agent differs between the runs. The simulated customer
and any judge are part of the instrument, so they're pinned like the
task.

**Rejected:**
- *A model judge for the pilot's pass:* it adds judge noise and spend
  before Project 15's judge has been validated against humans. The stop
  marker is already a pass/fail.
- *Re-judging inside `compare`:* model spend and non-determinism in the
  step that has to be reproducible.

### ADR-014: Gate v3 compares paired conversations

**Decision:**
- **The pairs:** each pair's difference is candidate pass minus baseline
  pass (−1, 0 or +1). The point estimate is their mean.
- **The interval:** the 95% interval comes from a bootstrap over
  scenarios (`task_id`), with all of a scenario's attempts resampled
  together. It uses `BOOTSTRAP_RESAMPLES` and the fixed `BOOTSTRAP_SEED`,
  as gate v1 does.
- **The verdict:** the same rules as v1 and v2, the same exit codes, and
  the same "inconclusive" band (`INCONCLUSIVE_DROP`).
- **Dropped pairs:** a pair whose trial is an error on either side, or
  that's missing from one run, is left out and counted in the report.
  The pilot doesn't apply the "task went from all-pass to none" rule:
  with one attempt per scenario, it would fire on single conversations.

**Why:** pairing removes the difficulty both agents share, which is what
the pilot's power simulation credits it with. The bootstrap over
scenarios is gate v1's method one level down, so it's the same arithmetic
and seed discipline. Resampling scenarios (not single conversations)
keeps the interval honest when a scenario has several attempts. A pair
is identical only until the agents first reply differently; after that,
the customer reacts to different text. That's why the pair correlation
is measured, not assumed.

**Rejected:**
- *McNemar's exact test* (statsmodels): it gives a p-value, not the
  interval the report leads with, and it assumes the pairs are
  independent, which several attempts per scenario break.
- *scipy's `bootstrap(paired=True)`:* about 40 MB of dependency for one
  resampling loop the harness already writes in plain Python. scipy may
  still be added as a dev-only dependency, so a test can cross-check
  gate v3's interval against it.

### ADR-015: The sample size is planned by simulating gate v3 itself

**Decision:** `agent-eval plan-pairs --baseline 0.8 --drop 0.10
--grader-error 0.0 --pair-correlation 0.5` reports how many pairs give
80% power, and how often the A/A pair would be falsely flagged.
- **The method:** it simulates the shipped gate v3 on synthetic pairs,
  the habit of `scripts/simulate_gate.py`. A textbook formula's
  assumptions would differ from the real gate's.
- **Grader error:** 0 for the stop marker. For a judged score, it comes
  from Project 15's noise file once it exists (its format is to be
  agreed with Project 15).
- **Pair correlation:** assumed until the pilot measures it.
- **The search:** pair counts in steps of 10, not by ×1.25.

**Why:** the number of pairs has to be known before the run. The
simulation should be of the exact statistic the run will be judged by.

**Reused:** the pilot's `power_simulation.py` (Arthur's,
`~/Desktop/S2 Proposals/pilot/`) has the same model of pairs: shared
difficulty, and a judge that flips a verdict at random. `plan-pairs` is
checked against its published numbers (206 pairs for a 10-point drop
with a perfect judge, 404 with a 10% judge error). It isn't copied,
because it simulates a z-test, not the bootstrap the gate uses.

## Pilot pre-registration (fixed before running)

- **Runs:** three runs of 50 scenarios × 1 attempt, on local models, at
  $0:
  - H1: the healthy agent;
  - H2: the healthy agent again;
  - D: one seeded degradation, chosen with Project 10.

  50 × 1 rather than 25 × 2, because the interval resamples scenarios
  and 25 would make it wider.
- **Comparisons:** H1 vs H2 (A/A) and H1 vs D.
- **What 50 pairs can see**, from `power_simulation.py` at 80% baseline
  and pair correlation 0.5. The stop-marker pass has no judge, so the
  first column applies. The customer's own randomness is in the outcome
  and in the correlation.

  | Drop | Perfect grader | Judge wrong 10% of the time (later) |
  |---|---|---|
  | 10 points | 0.32 | 0.18 |
  | 20 points | 0.78 | 0.47 |
  | 30 points | 0.96 | 0.79 |
  | 40 points | 1.00 | 0.94 |

  Arthur's pick: a large degradation of about 30 points or more, such as
  taking away the agent's price and stock information so it can't
  answer most buying questions. Project 10 builds it. The pilot tests the
  pipeline end to end; detection limits come in the full study.
- **Expected:**
  - H1 vs H2 is not flagged.
  - H1 vs D is flagged (power 0.96 at a 30-point drop).
  - Whatever the gate says is published, as for the earlier proofs.
- **Measured, for the next run's plan:**
  - the pair correlation, from H1 and H2;
  - the divergence turns;
  - minutes per conversation.

  Then `plan-pairs` is re-run with these numbers in place of the
  assumptions.
- **Not shown:** anything about RQ3's real answer, which needs hundreds
  of pairs per comparison. Nothing about real customers either: the data
  is synthetic only.

## Open questions

- **Project 15:** the format of the judge-noise file. Its measurement
  plan has D reading the judge's test–retest SD and the judge–human gap.
  It's needed for the later slice that gates on judged scores, not for
  the pilot.
- **Project 10:** confirming the interface above (sent 2026-11-04).
- **Spend:** $0. Local models only; a paid run needs Arthur's OK.
