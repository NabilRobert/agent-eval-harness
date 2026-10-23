# Run `smoke-b1`

- **Model:** `openai-api/sumopod/gpt-5-mini` (provider reported: gpt-5-mini)
- **Suite:** `pagila`, 3 tasks × 2 attempts, suite sha256 `e3babff6ef47`, not the frozen suite (subset or unfrozen)
- **Status:** complete (Inspect: success); rebuilt from its Inspect log 4×
- **Run at:** 2026-10-23T09:45:59+00:00

## Result

- **Strict pass rate (headline): 5/6 (83.3%)** of graded trials
- Lenient pass rate: 6/6 (100.0%)
- Errors (not counted as fails, not in the rates above): 0 of 6 trials
- pass^2 (every attempt passed, strict): 2/3 (66.7%) of tasks
- pass@2 (at least one attempt passed, strict): 3/3 (100.0%) of tasks

| Difficulty | Tasks | Strict | Lenient | Errors |
|---|---|---|---|---|
| easy | 1 | 2/2 (100.0%) | 2/2 (100.0%) | 0 |
| hard | 1 | 1/2 (50.0%) | 2/2 (100.0%) | 0 |
| expert | 1 | 2/2 (100.0%) | 2/2 (100.0%) | 0 |

## Cost and latency

- **Total cost:** unknown (model has no price in prices.yaml)
- **Tokens:** 22,108 input + 6,457 output; median 4,424 per trial
- **Latency per trial:** median 15.9 s, p90 19.3 s, max 19.3 s
- Latency is wall time for the whole trial (all model and tool calls), measured by Inspect.

## Per task

| Task | Difficulty | Strict | Lenient | Errors | Median tokens | Median s | Cost |
|---|---|---|---|---|---|---|---|
| e01 | easy | 2/2 | 2/2 | 0 | 4,417 | 11.6 | unknown |
| h03 | hard | 1/2 | 2/2 | 0 | 4,856 | 16.8 | unknown |
| x02 | expert | 2/2 | 2/2 | 0 | 5,009 | 18.3 | unknown |

## Trials that didn't pass strictly

### h03 attempt 2: fail

- Stop reason: completed; lenient: pass
- Tools called: list_tables → describe_table → describe_table → describe_table → describe_table → describe_table → describe_table → run_query → submit
- Expected: ['Action', '26505.44']
- Got: [1, 'Action', '26505.44']
- Last query:

```
SELECT c.category_id, c.name, SUM(p.amount) AS total_revenue
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
- Harness: `816114ce9d7e-dirty`, Inspect AI 0.3.283, export v3
- Agent settings: {'strict_tools': False}, limits {'message_limit': 20, 'time_limit': 120, 'token_limit': 60000}
- Budget: $5.00; model unpriced, so no dollar cap: limited to a smoke-sized run, each trial capped by its token limit

