# Run `vps-smoke-fs`

- **Model:** `openai-api/sumopod/gpt-5-mini` (provider reported: gpt-5-mini)
- **Suite:** `filesystem`, 2 tasks × 1 attempts, suite sha256 `5a579afda013`, not the frozen suite (subset or unfrozen)
- **Status:** complete (Inspect: success); rebuilt from its Inspect log 1×
- **Run at:** 2026-10-24T07:41:33+00:00

## Result

- **Strict pass rate (headline): 2/2 (100.0%)** of graded trials
- Lenient pass rate: 2/2 (100.0%)
- Errors (not counted as fails, not in the rates above): 0 of 2 trials
- pass^1 (every attempt passed, strict): 2/2 (100.0%) of tasks
- pass@1 (at least one attempt passed, strict): 2/2 (100.0%) of tasks

| Difficulty | Tasks | Strict | Lenient | Errors |
|---|---|---|---|---|
| easy | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 0 |
| hard | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 0 |

## Cost and latency

- **Total cost:** $0.0038
- **Tokens:** 13,508 input (8,064 of them cached) + 1,138 output; median 7,323 per trial
- **Latency per trial:** median 9.9 s, p90 11.4 s, max 10.5 s
- Latency is wall time for the whole trial (all model and tool calls), measured by Inspect.

## Per task

| Task | Difficulty | Strict | Lenient | Errors | Median tokens | Median s | Cost |
|---|---|---|---|---|---|---|---|
| f01 | easy | 1/1 | 1/1 | 0 | 10,879 | 10.5 | $0.0023 |
| f17 | hard | 1/1 | 1/1 | 0 | 3,767 | 9.2 | $0.0015 |

## Trials that didn't pass strictly

None.

## Provenance

- Data fingerprint: `304f741838b4595097c0130d8eff35ffa88775771f7a07f7e0862e205e7d5c0d`
- Server: `secure-filesystem-server` build `0.2.0` (/healthz: `not reported`)
- Tool list sha256: `3530bf09c844` (create_directory, directory_tree, edit_file, get_file_info, list_allowed_directories, list_directory, list_directory_with_sizes, move_file, read_file, read_media_file, read_multiple_files, read_text_file, search_files, write_file)
- Harness: `40915c776cfc`, Inspect AI 0.3.283, export v5
- Agent settings: {'strict_tools': False}, limits {'message_limit': 20, 'time_limit': 120, 'token_limit': 60000}
- Priced at $0.25/M input ($0.025/M cached), $2.0/M output (Sumopod model pricing table (screenshot supplied by Arthur), checked 2026-10-23)
- Budget: $5.00, estimate $0.0063 (measured tokens), per-trial cap $2.5000

