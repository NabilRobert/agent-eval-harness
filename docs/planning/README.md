# Planning and evaluation

The project was planned in seven phases before and while it was built.
Each phase doc was revised in place as decisions changed, with the date
and the reason. The build log is [JOURNEY.md](../../JOURNEY.md).

| Doc | What's in it |
|---|---|
| [Phase 1: problem brief](phase-1-problem-brief.md) | The problem, who it affects, success metrics, non-goals |
| [Phase 2: requirements and constraints](phase-2-requirements-constraints.md) | The core scenario, edge cases, budgets, Must / Should / Could |
| [Phase 3: domain model](phase-3-domain-model.md) | The glossary (suite, task, trial, grader, run), invariants, module boundaries |
| [Phase 4: flows and failures](phase-4-flows-failures.md) | The `run` and `compare` flows, what can fail at each step, trust boundaries |
| [Phase 5: architecture and decisions](phase-5-architecture-decisions.md) | The stack and every decision record (ADR-001 onwards), with the options each one beat |
| [Phase 6: risks, spikes and the walking skeleton](phase-6-risks-skeleton.md) | Ranked risks, a pre-mortem, Spikes 1–7 and their results |
| [Phase 7: slices and plan](phase-7-slices-plan.md) | The build slices, the spend plan, and every proof's pre-registration, written before it ran |
| [Evaluation](evaluation.md) | The finished project measured against Phases 1 and 2, the grader audit, and the follow-up simulations |

**Where the decisions are:** the ADRs live in the Phase 5 doc, under
"ADRs". Code comments cite them by number (for example "ADR-001" for how
a regression is decided).
