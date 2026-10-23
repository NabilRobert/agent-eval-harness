# Run `smoke-e1`

- **Model:** `openai-api/sumopod/gpt-5-mini` (provider reported: gpt-5-mini)
- **Suite:** `filesystem`, 3 tasks × 2 attempts, suite sha256 `52ecb149e22b`, not the frozen suite (subset or unfrozen)
- **Status:** complete (Inspect: success); rebuilt from its Inspect log 2×
- **Run at:** 2026-10-23T17:23:58+00:00

## Result

- **Strict pass rate (headline): 6/6 (100.0%)** of graded trials
- Lenient pass rate: 6/6 (100.0%)
- Errors (not counted as fails, not in the rates above): 0 of 6 trials
- pass^2 (every attempt passed, strict): 3/3 (100.0%) of tasks
- pass@2 (at least one attempt passed, strict): 3/3 (100.0%) of tasks

| Difficulty | Tasks | Strict | Lenient | Errors |
|---|---|---|---|---|
| easy | 1 | 2/2 (100.0%) | 2/2 (100.0%) | 0 |
| medium | 1 | 2/2 (100.0%) | 2/2 (100.0%) | 0 |
| hard | 1 | 2/2 (100.0%) | 2/2 (100.0%) | 0 |

## Cost and latency

- **Total cost:** $0.0080
- **Tokens:** 12,427 input + 2,423 output; median 2,520 per trial
- **Latency per trial:** median 7.2 s, p90 8.2 s, max 8.0 s
- Latency is wall time for the whole trial (all model and tool calls), measured by Inspect.

## Per task

| Task | Difficulty | Strict | Lenient | Errors | Median tokens | Median s | Cost |
|---|---|---|---|---|---|---|---|
| f01 | easy | 2/2 | 2/2 | 0 | 2,520 | 6.8 | $0.0024 |
| f11 | medium | 2/2 | 2/2 | 0 | 3,722 | 7.2 | $0.0031 |
| f17 | hard | 2/2 | 2/2 | 0 | 1,183 | 7.5 | $0.0025 |

## Trials that didn't pass strictly

None.

## Provenance

- Data fingerprint: `304f741838b4595097c0130d8eff35ffa88775771f7a07f7e0862e205e7d5c0d`
- Server: `secure-filesystem-server` build `0.2.0` (/healthz: `not reported`)
- Tool list sha256: `3530bf09c844` (create_directory, directory_tree, edit_file, get_file_info, list_allowed_directories, list_directory, list_directory_with_sizes, move_file, read_file, read_media_file, read_multiple_files, read_text_file, search_files, write_file)
- Harness: `81d855b3b2db-dirty`, Inspect AI 0.3.283, export v4
- Agent settings: {'strict_tools': False}, limits {'message_limit': 20, 'time_limit': 120, 'token_limit': 60000}
- Priced at $0.25/M input, $2.0/M output (Sumopod model pricing table (screenshot supplied by Arthur), checked 2026-10-23); every input token at the full input price, so cost errs high if any input was cached
- Budget: $5.00, estimate $0.0705 (default (pessimistic) tokens), per-trial cap $0.8333

