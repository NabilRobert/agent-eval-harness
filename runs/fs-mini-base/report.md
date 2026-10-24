# Run `fs-mini-base`

- **Model:** `openai-api/sumopod/gpt-5-mini` (provider reported: gpt-5-mini)
- **Suite:** `filesystem`, 17 tasks × 5 attempts, suite sha256 `94ad6a86e144`, **frozen**
- **Status:** complete (Inspect: success)
- **Run at:** 2026-10-23T17:26:32+00:00

## Result

- **Strict pass rate (headline): 84/85 (98.8%)** of graded trials
- Lenient pass rate: 84/85 (98.8%)
- Errors (not counted as fails, not in the rates above): 0 of 85 trials
- pass^5 (every attempt passed, strict): 16/17 (94.1%) of tasks
- pass@5 (at least one attempt passed, strict): 17/17 (100.0%) of tasks

| Difficulty | Tasks | Strict | Lenient | Errors |
|---|---|---|---|---|
| easy | 6 | 29/30 (96.7%) | 29/30 (96.7%) | 0 |
| medium | 6 | 30/30 (100.0%) | 30/30 (100.0%) | 0 |
| hard | 5 | 25/25 (100.0%) | 25/25 (100.0%) | 0 |

## Cost and latency

- **Total cost:** $0.2050
- **Tokens:** 328,869 input + 61,397 output; median 3,767 per trial
- **Latency per trial:** median 8.9 s, p90 16.2 s, max 27.7 s
- Latency is wall time for the whole trial (all model and tool calls), measured by Inspect.

## Per task

| Task | Difficulty | Strict | Lenient | Errors | Median tokens | Median s | Cost |
|---|---|---|---|---|---|---|---|
| f01 | easy | 5/5 | 5/5 | 0 | 3,782 | 8.2 | $0.0093 |
| f02 | easy | 5/5 | 5/5 | 0 | 3,409 | 8.1 | $0.0095 |
| f03 | medium | 5/5 | 5/5 | 0 | 9,044 | 10.0 | $0.0187 |
| f04 | medium | 5/5 | 5/5 | 0 | 10,513 | 17.5 | $0.0284 |
| f05 | easy | 5/5 | 5/5 | 0 | 4,065 | 6.5 | $0.0089 |
| f06 | hard | 5/5 | 5/5 | 0 | 3,936 | 10.8 | $0.0125 |
| f07 | hard | 5/5 | 5/5 | 0 | 8,235 | 25.5 | $0.0327 |
| f08 | easy | 5/5 | 5/5 | 0 | 3,745 | 8.9 | $0.0082 |
| f09 | medium | 5/5 | 5/5 | 0 | 3,379 | 8.2 | $0.0086 |
| f10 | medium | 5/5 | 5/5 | 0 | 3,396 | 9.6 | $0.0093 |
| f11 | medium | 5/5 | 5/5 | 0 | 3,543 | 7.6 | $0.0088 |
| f12 | easy | 5/5 | 5/5 | 0 | 4,086 | 7.3 | $0.0079 |
| f13 | medium | 5/5 | 5/5 | 0 | 2,216 | 4.9 | $0.0048 |
| f14 | easy | 4/5 | 4/5 | 0 | 3,767 | 12.7 | $0.0131 |
| f15 | hard | 5/5 | 5/5 | 0 | 2,453 | 9.1 | $0.0091 |
| f16 | hard | 5/5 | 5/5 | 0 | 3,608 | 8.2 | $0.0087 |
| f17 | hard | 5/5 | 5/5 | 0 | 1,208 | 7.5 | $0.0065 |

## Trials that didn't pass strictly

### f14 attempt 4: fail

- Stop reason: message; lenient: fail
- Tools called: list_directory → list_directory → list_directory → list_directory → read_text_file → read_text_file → read_text_file → list_directory → read_text_file
- Answer must contain: ['ACME_API_BASE_URL'] (fail)
- Final answer:

```
(none)
```

- Forbidden tools: none used (pass)

## Provenance

- Data fingerprint: `304f741838b4595097c0130d8eff35ffa88775771f7a07f7e0862e205e7d5c0d`
- Server: `secure-filesystem-server` build `0.2.0` (/healthz: `not reported`)
- Tool list sha256: `3530bf09c844` (create_directory, directory_tree, edit_file, get_file_info, list_allowed_directories, list_directory, list_directory_with_sizes, move_file, read_file, read_media_file, read_multiple_files, read_text_file, search_files, write_file)
- Harness: `8c2240fceeee`, Inspect AI 0.3.283, export v4
- Agent settings: {'strict_tools': False}, limits {'message_limit': 20, 'time_limit': 120, 'token_limit': 60000}
- Priced at $0.25/M input, $2.0/M output (Sumopod model pricing table (screenshot supplied by Arthur), checked 2026-10-23); every input token at the full input price, so cost errs high if any input was cached
- Budget: $5.00, estimate $0.1125 (measured tokens), per-trial cap $0.0588

