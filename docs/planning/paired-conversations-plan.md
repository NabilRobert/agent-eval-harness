# Paired multi-turn comparisons: the pilot slice (built)

*2026-11-04. Arthur accepted the slice ("OK the slice") and picked a
large degradation ("Large, ~30+ points"). The interface is agreed with
Project 10 (AI Flight School, `docs/planning/thesis-pilot.md` there).
Gate v3 and `plan-pairs` are built; their decisions are ADR-013 to
ADR-015 in the [Phase 5 doc](phase-5-architecture-decisions.md). The
pilot runs after Flight School's slice 4.*

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

## The interface (agreed with Project 10)

Project 10 writes normal harness run records, one run per agent variant,
with `export.trial_from_sample` and `records.write_run`.
- **Pair key: `(task_id, attempt)`.**
  - `task_id` is the scenario: persona × goal × tactic. Its text goes in
    the task's `prompt`, so the task hash covers it.
  - `attempt` is Inspect's epoch.
  - `customer_seed` is derived from the two and stored on the trial.
- **The pass is `result_match` over one row:** expected
  `[{"stop_marker": "###DONE###"}]`, graded rows `[{"stop_marker": ...}]`.
  It regrades exactly, with no new grader kind. The suite's name or
  description labels it "the simulator grading itself", as Arthur asked.
- **The customer is pinned through `provenance.data_fingerprint`.** It's
  a hash over the persona cards, the customer model file's hash, the
  llama-server build and the generation settings, with the parts also
  listed in provenance. `compare` already refuses two runs whose
  fingerprints differ (exit 2). The customer is the environment the agent
  is tested in, as Pagila's data is.
- **Extra trial fields:**
  - `scenario` (`{persona_id, goal_id, tactic_id}`) and `stop_marker`
    (`###DONE###`, `###GAVE_UP###` or `###GHOSTED###`);
  - `diverged_at_turn`: the first turn where the two arms' agents replied
    differently, for the thesis analysis (the gate doesn't use it).

  Checked on main (199657b): `write_run` and `load_run` keep these
  fields, the trials hash covers them, and `compare` accepts the runs.
- **Chats beside the run:** `chats.jsonl` holds one Project 15
  `ChatRecord` per trial, with `chats_sha256` in provenance. The harness
  doesn't read it: the gate decides from `trials.jsonl` alone.
- **Reproducible on one machine:** both arms run on the same Mac with the
  same llama-server build. llama.cpp is deterministic only within one
  build, model file and machine.

## The slice

Pilot scale only. It shows the pipeline works end to end; it doesn't
answer RQ3.

1. **Gate v3, paired** (ADR-014): `agent-eval compare --gate v3`.
   Built.
2. **`agent-eval plan-pairs`** (ADR-015): the pairs needed before a run.
   Built.
3. **The pilot runs**, pre-registered below. They run on local models
   through Project 10, at $0.

The pass and the customer pin needed no harness code (ADR-013).

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
