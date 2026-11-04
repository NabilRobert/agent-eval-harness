# Paired multi-turn comparisons: the pilot slice (proposed)

*2026-11-04. Proposed, not built. It waits for Arthur's OK and for
Project 10's answer on the interface. Once accepted, the three ADRs below
move to the Phase 5 doc.*

## Why

Arthur's master's thesis asks (RQ3) whether a simulator-plus-judge
evaluation ranks agent versions correctly, using deliberately degraded
agents as ground truth, and how many conversations each decision needs.
This is part D of Project 15 (`id-chat-research`). Its pieces are:
- Project 10 (AI Flight School) supplies the simulated customers;
- Project 15 supplies the judge's noise estimates;
- this harness compares the runs.

What the harness has today doesn't fit as is:
- **Its gates pair tasks, not conversations.** Gate v1 bootstraps over
  tasks; gate v2 pools trials. Neither uses the fact that run A and run
  B met the *same* simulated customer with the same seed. That pairing
  is where the power comes from.
- **It regrades every stored grade.** It can't re-run a model judge, so
  a judge's verdict needs its own grader kind.
- **Its power estimates are scripts** (`scripts/simulate_gate.py`,
  `scripts/compare_rules.py`), run after the fact. RQ3 needs the sample
  size *before* the run.

## The slice

Pilot scale only. It shows the pipeline works end to end; it doesn't
answer RQ3.

1. **Input: harness run records** (proposed to Project 10, answer
   pending). Project 10 already writes them through
   `export.trial_from_sample` and `records.write_run`. There's one run
   per agent variant:
   - `task_id` is the persona id and `attempt` is the seed. The same
     (persona, seed) in both runs is one pair.
   - Each trial's transcript is a Project 15 `ChatRecord`
     (`source: synthetic`).
2. **Grader `judge_verdict`** (ADR-013).
3. **Gate v3, paired** (ADR-014): `agent-eval compare --gate v3`.
4. **`agent-eval plan-pairs`** (ADR-015): the pairs needed before a run.
5. **The pilot runs**, pre-registered below. They run on local models
   through Project 10, at $0.

Estimated size: code about 150 lines (grader 20, gate 60, `plan-pairs`
50, CLI wiring 20), plus about 200 lines of tests and a guide update.

## Decisions (proposed)

### ADR-013: A judge's verdict is a stored grade, pinned to its judge

**Decision:** a new grader kind, `judge_verdict`:
- spec: `{judge_model, codebook_hash}`;
- input: `{verdict: bool, reasons: str}`.

`grade_one` returns the stored verdict, so a regrade reads it back rather
than re-running the judge. `compare` treats a different `judge_model` or
`codebook_hash` between the two runs as incomparable (exit 2), just as it
treats a different task hash.

**Why:** the gate's promise is that a stored grade and a regrade agree.
For a model judge, that holds only if the judge is pinned. A judge change
between runs would otherwise show up as an agent change.

**Rejected:**
- *Re-judging inside `compare`:* model spend and non-determinism in the
  step that has to be reproducible.
- *Storing the verdict as a plain pass/fail with no grader:* it loses
  which judge made it.

### ADR-014: Gate v3 compares paired conversations

**Decision:**
- **The pairs:** each pair's difference is candidate pass minus baseline
  pass (−1, 0 or +1). The point estimate is their mean.
- **The interval:** the 95% interval comes from a bootstrap over
  personas, with all of a persona's seeds resampled together. It uses
  `BOOTSTRAP_RESAMPLES` and the fixed `BOOTSTRAP_SEED`, as gate v1 does.
- **The verdict:** the same rules as v1 and v2, the same exit codes, and
  the same "inconclusive" band (`INCONCLUSIVE_DROP`).
- **Dropped pairs:** a pair whose trial is an error on either side, or
  that's missing from one run, is left out and counted in the report.
  The pilot doesn't apply the "task went from all-pass to none" rule:
  with one seed per persona, it would fire on single conversations.

**Why:** pairing removes the difficulty both agents share, which is what
the pilot's power simulation credits it with. The bootstrap over personas
is gate v1's method one level down, so it's the same arithmetic and seed
discipline. Resampling personas (not single conversations) keeps the
interval honest when a persona has several seeds.

**Rejected:**
- *McNemar's exact test* (statsmodels): it gives a p-value, not the
  interval the report leads with, and it assumes the pairs are
  independent, which several seeds per persona break.
- *scipy's `bootstrap(paired=True)`:* about 40 MB of dependency for one
  resampling loop the harness already writes in plain Python. scipy may
  still be added as a dev-only dependency, so a test can cross-check
  gate v3's interval against it.

### ADR-015: The sample size is planned by simulating gate v3 itself

**Decision:** `agent-eval plan-pairs --baseline 0.8 --drop 0.10
--judge-error 0.10 --pair-correlation 0.5` reports how many pairs give
80% power, and how often the A/A pair would be falsely flagged.
- **The method:** it simulates the shipped gate v3 on synthetic pairs,
  the habit of `scripts/simulate_gate.py`. A textbook formula's
  assumptions would differ from the real gate's.
- **Judge error:** taken from `--judge-error`, or from Project 15's
  noise file once it exists (its format is to be agreed with Project 15).
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

- **Runs:** three runs of 50 personas × 1 seed, on local models, at $0:
  - H1: the healthy agent;
  - H2: the healthy agent again;
  - D: one seeded degradation, chosen with Project 10.
- **Comparisons:** H1 vs H2 (A/A) and H1 vs D.
- **What 50 pairs can see**, from `power_simulation.py` at 80% baseline
  and pair correlation 0.5:

  | Drop | Perfect judge | Judge wrong 10% of the time |
  |---|---|---|
  | 10 points | 0.32 | 0.18 |
  | 20 points | 0.78 | 0.47 |
  | 30 points | 0.96 | 0.79 |
  | 40 points | 1.00 | 0.94 |

  So the degradation should drop the pass rate by about 30 points or
  more. A milder one will most likely come back "inconclusive", and that
  is what gets published.
- **Expected:**
  - H1 vs H2 is not flagged.
  - H1 vs D is flagged if its drop is 30 points or more.
  - Whatever the gate says is published, as for the earlier proofs.
- **Measured, for the next run's plan:**
  - the pair correlation, from H1 and H2;
  - how often the judge disagrees with itself, by judging H1 twice;
  - minutes per conversation.

  Then `plan-pairs` is re-run with these numbers in place of the
  assumptions.
- **Not shown:** anything about RQ3's real answer, which needs hundreds
  of pairs per comparison. Nothing about real customers either: the data
  is synthetic only.

## Interfaces and open questions

- **Project 10:** the proposal above was sent 2026-11-04. Its questions
  are the run-record fit, whether a customer is reproducible from
  (persona, seed), time per conversation, and which degradation.
- **Project 15:** the format of the judge-noise file. Its measurement
  plan has D reading the judge's test–retest SD and the judge–human gap.
  The pilot is binary pass/fail. Gating on the continuous per-construct
  scores is a later slice, after Project 15's rubric results exist.
- **For Arthur:**
  - OK this slice: the new grader kind, gate v3 and `plan-pairs`.
  - OK the size of the degradation: about 30 points or more, or accept
    "inconclusive" as the likely outcome.
- **Spend:** $0. Local models only; a paid run needs Arthur's OK.
