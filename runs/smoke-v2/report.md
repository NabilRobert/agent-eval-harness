# Run `smoke-v2`

- **Model:** `openai-api/sumopod/gpt-5-mini` (provider reported: gpt-5-mini)
- **Suite:** `filesystem-v2`, 3 tasks × 1 attempts, suite sha256 `35148f8bec83`, not the frozen suite (subset or unfrozen)
- **Status:** complete (Inspect: success); rebuilt from its Inspect log 1×
- **Run at:** 2026-10-24T11:47:20+00:00

## Result

- **Strict pass rate (headline): 3/3 (100.0%)** of graded trials
- Lenient pass rate: 3/3 (100.0%)
- Errors (not counted as fails, not in the rates above): 0 of 3 trials
- pass^1 (every attempt passed, strict): 3/3 (100.0%) of tasks
- pass@1 (at least one attempt passed, strict): 3/3 (100.0%) of tasks

| Difficulty | Tasks | Strict | Lenient | Errors |
|---|---|---|---|---|
| medium | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 0 |
| hard | 2 | 2/2 (100.0%) | 2/2 (100.0%) | 0 |

## Cost and latency

- **Total cost:** $0.0199
- **Tokens:** 21,868 input (11,904 of them cached) + 8,580 output; median 6,708 per trial
- **Latency per trial:** median 15.3 s, p90 76.5 s, max 53.6 s
- Latency is wall time for the whole trial (all model and tool calls), measured by Inspect.

## Per task

| Task | Difficulty | Strict | Lenient | Errors | Median tokens | Median s | Cost |
|---|---|---|---|---|---|---|---|
| n05 | medium | 1/1 | 1/1 | 0 | 4,325 | 10.4 | $0.0021 |
| n14 | hard | 1/1 | 1/1 | 0 | 19,415 | 53.6 | $0.0137 |
| n16 | hard | 1/1 | 1/1 | 0 | 6,708 | 15.3 | $0.0041 |

## Trials that didn't pass strictly

None.

## Provenance

- Target: `filesystem-v2` (stdio, `/Users/nabilrobert/Desktop/agent-eval-harness/suites/fixtures/acme-shop-v2`)
- Data fingerprint: `1e2fae2245b87564b897ccbf5b42f958f0dad641df456ece03c295074fbb8b26`
- Server: `secure-filesystem-server` build `0.2.0` (/healthz: `not reported`)
- Tool list sha256: `3530bf09c844` (create_directory, directory_tree, edit_file, get_file_info, list_allowed_directories, list_directory, list_directory_with_sizes, move_file, read_file, read_media_file, read_multiple_files, read_text_file, search_files, write_file)
- Harness: `5c462cbbeff2-dirty`, Inspect AI 0.3.283, export v5
- Agent settings: {'strict_tools': False}, limits {'message_limit': 20, 'time_limit': 120, 'token_limit': 60000}
- Priced at $0.25/M input ($0.025/M cached), $2.0/M output (Sumopod model pricing table (screenshot supplied by Arthur), checked 2026-10-23)
- Budget: $5.00, estimate $0.0353 (default (pessimistic) tokens), per-trial cap $1.6667

