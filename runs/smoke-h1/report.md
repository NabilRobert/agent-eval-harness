# Run `smoke-h1`

- **Model:** `openai-api/sumopod/gpt-5-mini` (provider reported: gpt-5-mini)
- **Suite:** `pagila`, 3 tasks × 1 attempts, suite sha256 `e3babff6ef47`, not the frozen suite (subset or unfrozen)
- **Status:** complete (Inspect: success); rebuilt from its Inspect log 1×
- **Run at:** 2026-10-24T06:46:52+00:00

## Result

- **Strict pass rate (headline): 2/3 (66.7%)** of graded trials
- Lenient pass rate: 3/3 (100.0%)
- Errors (not counted as fails, not in the rates above): 0 of 3 trials
- pass^1 (every attempt passed, strict): 2/3 (66.7%) of tasks
- pass@1 (at least one attempt passed, strict): 2/3 (66.7%) of tasks

| Difficulty | Tasks | Strict | Lenient | Errors |
|---|---|---|---|---|
| easy | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 0 |
| hard | 1 | 0/1 (0.0%) | 1/1 (100.0%) | 0 |
| expert | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 0 |

## Cost and latency

- **Total cost:** $0.0082
- **Tokens:** 13,996 input (4,352 of them cached) + 2,828 output; median 5,383 per trial
- **Latency per trial:** median 22.5 s, p90 30.7 s, max 27.6 s
- Latency is wall time for the whole trial (all model and tool calls), measured by Inspect.

## Per task

| Task | Difficulty | Strict | Lenient | Errors | Median tokens | Median s | Cost |
|---|---|---|---|---|---|---|---|
| e01 | easy | 1/1 | 1/1 | 0 | 6,192 | 20.0 | $0.0021 |
| h03 | hard | 0/1 | 1/1 | 0 | 5,249 | 27.6 | $0.0026 |
| x02 | expert | 1/1 | 1/1 | 0 | 5,383 | 22.5 | $0.0035 |

## Trials that didn't pass strictly

### h03 attempt 1: fail

- Stop reason: completed; lenient: pass
- Tools called: list_tables → describe_table → describe_table → describe_table → describe_table → describe_table → describe_table → run_query → submit
- Expected: ['Action', '26505.44']
- Got: [1, 'Action', '26505.44']
- Last query:

```
SELECT c.category_id,
       c.name AS category,
       SUM(p.amount) AS total_revenue
FROM payment p
JOIN rental r ON p.rental_id = r.rental_id
JOIN inventory i ON r.inventory_id = i.inventory_id
JOIN film_category fc ON i.film_id = fc.film_id
JOIN category c ON fc.category_id = c.category_id
GROUP BY c.category_id, c.name
ORDER BY total_revenue DESC
LIMIT 1;
```

## Provenance

- Data fingerprint: `fa70dca8db64576c0f58182dc54196ecfa936a213453a62d2af5a1838c684d96`
- Server: `database-mcp` build `not reported` (/healthz: `not reported`)
- Tool list sha256: `ba48f1adcf4c` (describe_table, list_tables, run_query, sample_rows)
- Harness: `c9aff6b2339b-dirty`, Inspect AI 0.3.283, export v5
- Agent settings: {'strict_tools': False}, limits {'message_limit': 20, 'time_limit': 120, 'token_limit': 60000}
- Priced at $0.25/M input ($0.025/M cached), $2.0/M output (Sumopod model pricing table (screenshot supplied by Arthur), checked 2026-10-23)
- Budget: $5.00, estimate $0.0081 (measured tokens), per-trial cap $1.6667

