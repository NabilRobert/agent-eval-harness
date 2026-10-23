# agent-eval-harness

Measures whether an agent setup works, and catches it when a change makes
it worse. Here an agent setup means a model, a system prompt and an MCP
server's tools, run in [Inspect AI](https://inspect.aisi.org.uk/)'s agent
loop.

**Status: walking skeleton (slice A of 8).** One task runs end to end
against [MCP-backbone](https://github.com/NabilRobert/MCP-backbone)'s live
endpoint, and its run records are committed in `runs/skeleton/`. The
regression gate, the real suites and the published results are still to
come. See [the slice plan](docs/planning/phase-7-slices-plan.md). None of
the Phase 1 success metrics are claimed yet.

## What's Inspect's and what's ours

- **Inspect AI runs the trials:** the agent loop, repeats, limits,
  retries and MCP connections.
- **This harness adds what Inspect lacks:**
  - a statistical regression gate across repeated runs, with CI exit
    codes (slice D);
  - comparison from committed files, with no API key and no network;
  - regrading old runs with the current grader code;
  - provenance: which model, server build, tool list and data each run
    was graded against.

Why build on Inspect rather than replace it:
[ADR-009](docs/planning/phase-5-architecture-decisions.md).

## Use

```bash
uv sync --frozen --extra dev
uv run agent-eval run --run-id my-run            # needs .env, see below
uv run agent-eval compare runs/skeleton runs/my-run
```

`compare` exits with **0** for no regression, **1** for a regression, and
**2** when it can't decide. "Can't decide" covers runs that can't be
compared, an edited or incomplete run, or (until slice D) any change in
pass rates.

`run` reads these keys from `.env`, which is gitignored. They're never
written to run records, and each run's output is checked for the key
values before it's saved.

- `SUMOPOD_AI_API_KEY`
- `SUMOPOD_BASE_URL`
- `MCP_BACKBONE_EVAL_KEY`

## Planning record

[Phases 1–7](docs/planning/): problem brief, requirements, domain model,
flows and failures, ADRs, risks and spikes (with results), and the slice
plan.
