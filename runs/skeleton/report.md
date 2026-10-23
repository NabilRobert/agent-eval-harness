# Run `skeleton`

- **Model:** `openai-api/sumopod/gpt-5-mini` (provider reported: gpt-5-mini)
- **Suite:** `pagila-skeleton`, 1 tasks × 1 attempts, suite sha256 `bd3a3ba8e45d`, not the frozen suite (subset or unfrozen)
- **Status:** complete (Inspect: success); rebuilt from its Inspect log 4×
- **Run at:** 2026-10-23T09:29:07+00:00

## Result

- **Strict pass rate (headline): 1/1 (100.0%)** of graded trials
- Lenient pass rate: 1/1 (100.0%)
- Errors (not counted as fails, not in the rates above): 0 of 1 trials
- pass^1 (every attempt passed, strict): 1/1 (100.0%) of tasks
- pass@1 (at least one attempt passed, strict): 1/1 (100.0%) of tasks

| Difficulty | Tasks | Strict | Lenient | Errors |
|---|---|---|---|---|
| easy | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 0 |

## Cost and latency

- **Total cost:** $0.0016
- **Tokens:** 3,262 input + 381 output; median 3,643 per trial
- **Latency per trial:** median 8.6 s, p90 8.6 s, max 8.6 s
- Latency is wall time for the whole trial (all model and tool calls), measured by Inspect.

## Per task

| Task | Difficulty | Strict | Lenient | Errors | Median tokens | Median s | Cost |
|---|---|---|---|---|---|---|---|
| easy-01 | easy | 1/1 | 1/1 | 0 | 3,643 | 8.6 | $0.0016 |

## Trials that didn't pass strictly

None.

## Provenance

- Data fingerprint: `not taken`
- Server: `database-mcp` build `not reported` (/healthz: `not reported`)
- Tool list sha256: `ba48f1adcf4c` (describe_table, list_tables, run_query, sample_rows)
- Harness: `47157d7d4efc-dirty`, Inspect AI 0.3.283, export v3
- Agent settings: {'strict_tools': False}, limits {'message_limit': 20, 'time_limit': 120, 'token_limit': 60000}
- Priced at $0.25/M input, $2.0/M output (Sumopod model pricing table (screenshot supplied by Arthur), checked 2026-10-23); every input token at the full input price, so cost errs high if any input was cached

