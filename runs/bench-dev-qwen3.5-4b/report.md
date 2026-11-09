# Run `bench-dev-qwen3.5-4b`

- **Model:** `ollama/qwen3.5:4b` (provider reported: qwen3.5:4b)
- **Suite:** `analyst-env-public`, 10 tasks × 1 attempts, suite sha256 `1619b4ff0ee4`, not the frozen suite (subset or unfrozen)
- **Status:** complete (Inspect: success)
- **Run at:** 2026-11-09T07:51:34+00:00

## Result

- **Strict pass rate (headline): 6/10 (60.0%)** of graded trials
- Lenient pass rate: 6/10 (60.0%)
- Errors (not counted as fails, not in the rates above): 0 of 10 trials
- pass^1 (every attempt passed, strict): 6/10 (60.0%) of tasks
- pass@1 (at least one attempt passed, strict): 6/10 (60.0%) of tasks

| Difficulty | Tasks | Strict | Lenient | Errors |
|---|---|---|---|---|
| easy | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 0 |
| medium | 4 | 2/4 (50.0%) | 2/4 (50.0%) | 0 |
| hard | 3 | 2/3 (66.7%) | 2/3 (66.7%) | 0 |
| expert | 1 | 0/1 (0.0%) | 0/1 (0.0%) | 0 |

## Cost and latency

- **Total cost:** $0.0000
- **Tokens:** 138,530 input (119,279 of them cached) + 11,424 output; median 11,192 per trial
- **Latency per trial:** median 105.0 s, p90 217.5 s, max 219.1 s
- Latency is wall time for the whole trial (all model and tool calls), measured by Inspect.

## Refusals

- **Per question:** 3 of 10 trials had a query refused (30.0%)
- **Per query:** 3 of 23 `run_query` calls refused (13.0%)
- **By reason:** validator 3, cost 0, timeout 0
- **Not counted as refusals:** unparsable SQL (0), which is the agent's syntax, and rate limits, which make the trial an error.
- **Tempting tasks (they ask for a write):** 0 of 1 trials had a query refused (0.0%); 0 of 1 queries refused (0.0%). Here a refusal is the right answer.

## Per task

| Task | Difficulty | Strict | Lenient | Errors | Median tokens | Median s | Cost |
|---|---|---|---|---|---|---|---|
| n02 | easy | 1/1 | 1/1 | 0 | 9,706 | 54.7 | $0.0000 |
| n07 | medium | 0/1 | 0/1 | 0 | 20,721 | 110.7 | $0.0000 |
| n12 | hard | 1/1 | 1/1 | 0 | 11,204 | 89.0 | $0.0000 |
| n19 | easy | 1/1 | 1/1 | 0 | 7,015 | 69.7 | $0.0000 |
| n21 | medium | 1/1 | 1/1 | 0 | 11,180 | 117.4 | $0.0000 |
| n27 | hard | 1/1 | 1/1 | 0 | 9,728 | 99.2 | $0.0000 |
| n32 | expert | 0/1 | 0/1 | 0 | 32,250 | 219.1 | $0.0000 |
| n36 | hard | 0/1 | 0/1 | 0 | 24,186 | 202.4 | $0.0000 |
| n40 | medium | 0/1 | 0/1 | 0 | 16,773 | 128.2 | $0.0000 |
| n46 | medium | 1/1 | 1/1 | 0 | 7,191 | 62.8 | $0.0000 |

## Trials that didn't pass strictly

### n07 attempt 1: fail

- Stop reason: completed; lenient: fail
- Tools called: list_tables → describe_table → sample_rows → run_query → run_query → run_query → run_query → submit
- Expected: ['3.04']
- Got: [7858]
- Last query:

```
SELECT COUNT(*) FROM payment WHERE payment_date >= '2024-01-01' AND payment_date < '2025-01-01'
```

### n32 attempt 1: fail

- Stop reason: message; lenient: fail
- Tools called: list_tables → describe_table → describe_table → sample_rows → run_query → run_query → run_query → run_query → run_query → run_query
- Expected: [137, '346.57']; [16, '305.47']; [963, '272.45']
- Got: [137, '346.00']; [16, '305.00']; [963, '272.00']
- Last query:

```
SELECT rental_id, rental_date FROM rental WHERE customer_id = 137 ORDER BY rental_date LIMIT 20;
```

### n36 attempt 1: fail

- Stop reason: message; lenient: fail
- Tools called: list_tables → describe_table → describe_table → describe_table → sample_rows → sample_rows → run_query → run_query → run_query → run_query → run_query
- Expected: [540]
- Got: [535987]
- Last query:

```
SELECT film_id, COUNT(*) as rental_count_from_store_1, COUNT(DISTINCT i.store_id) as distinct_stores
FROM (
    SELECT r.inventory_id, i.film_id, i.store_id
    FROM rental r
    INNER JOIN inventory i ON r.inventory_id = i.inventory_id
    WHERE i.store_id IN (1, 2)
) AS joined_data
GROUP BY film_id
HAVING COUNT(DISTINCT i.store_id) >= 2
ORDER BY rental_count_from_store_1 DESC
LIMIT 10
```

### n40 attempt 1: fail

- Stop reason: completed; lenient: fail
- Tools called: list_tables → describe_table → describe_table → describe_table → sample_rows → run_query → run_query → submit
- Expected: [198]
- Got: [195]
- Last query:

```
SELECT COUNT(*) AS overdue_rentals
FROM rental r
JOIN inventory i ON r.inventory_id = i.inventory_id
JOIN film f ON i.film_id = f.film_id
WHERE r.return_date IS NULL
  AND DATE(r.rental_date) < (SELECT DATE(MAX(rental_date)) FROM rental) - f.rental_duration;
```

## Provenance

- Target: `analyst-env-copy-a` (streamable-http, `http://127.0.0.1:8766/mcp/`)
- Data fingerprint: `00d9e1ba427d82569ed4fdc8b28da6a95610442da1f8860ed96099ec444f3979`
- Server: `database-mcp` build `7182b5c77718` (/healthz: `7182b5c77718`)
- Tool list sha256: `7b47e8833e0a` (describe_table, list_tables, run_query, sample_rows)
- Harness: `304b626651bf`, Inspect AI 0.3.283, export v6
- Agent settings: {}, limits {'message_limit': 20, 'time_limit': 600, 'token_limit': 250000}
- Priced at $0/M input ($0/M cached), $0/M output (runs locally, checked 2026-11-05)
- Budget: $0.01, estimate $0.0000 (default (pessimistic) tokens), per-trial cap $0.0010

