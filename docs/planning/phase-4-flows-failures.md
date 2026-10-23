# Phase 4 — Flows & Failures

## Happy path: `run`

1. **Load and validate.** Parse the suite and the agent config (YAML
   `safe_load`, then schema checks). The agent's target must match the
   suite's. Every environment variable it names must be set. The model must
   be in the PriceTable; without a price the budget cap can't be enforced,
   so an unknown model → exit 2.
2. **Preflight the target.** Connect once and list the tools. Every tool
   named in the allowlist or a grader must exist. Record the tool-list hash.
   Any failure → exit 2, before any money is spent.
3. **Estimate cost.** Tasks × repeats × an estimated cost per trial (the
   average from the last complete run of the same suite and model, or else
   a conservative default). If the estimate is over the cap → refuse, and
   suggest fewer repeats or a smaller suite.
4. **Start the record.** Write `meta.json` with status `running`, the config
   snapshot, hashes and the git SHA.
5. **Schedule trials attempt by attempt:** every task's attempt 1, then
   every task's attempt 2, and so on. Provider hiccups then spread across
   tasks instead of hitting one task's five attempts, and a run cut short
   still has even coverage.
6. **Run each trial** (several at once, default 4). Stdio: copy the fixture
   to a temporary directory and start a fresh server limited to it. HTTP:
   open a fresh session. Then run the agent loop under the turn and time
   caps, capturing every tool call, token usage and timing.
7. **Grade** the finished trial (pure functions) → `pass`, `fail` or
   `error`.
8. **Append** the trial to `trials.jsonl`, add its cost to spend so far, and
   clean up (stop the server, delete the temporary copy).
9. **Finish.** Set the status (`complete`, `incomplete` or `aborted`),
   compute totals *from the trial lines*, store a hash of `trials.jsonl` in
   `meta.json`, and render `report.md`.

## Happy path: `compare`

1. Load both run directories. Each must be `complete`, and its
   `trials.jsonl` must match the hash in `meta.json`. Otherwise → exit 2.
2. Match tasks by id and hash. The same id with a different hash → exit 2.
   Tasks only one run has are listed and left out of the comparison.
3. Work out each task's pass rate in both runs. Then:
   - **Suite level:** the average change across tasks, with a 95% CI from a
     paired bootstrap (fixed seed, 10,000 resamples).
   - **Broken tasks:** tasks that went from 5/5 to 0/5 (ADR-001).
   - **Cost and latency:** the change in median cost and latency.
4. Verdict → exit code (0 / 1 / 2), and render the comparison report.

## Source of truth

- **`trials.jsonl`** is the truth for a run. The totals in `meta.json` are
  a convenience: reports recompute them from the trials, and the hash check
  catches a hand-edited record.
- **Suite YAML** is the truth for expected answers at run time. The Pagila
  answers are generated once by a script that runs MCP-backbone's reference
  SQL against Pagila; the output is committed, and the script stays in the
  repo so anyone can regenerate the answers.
- **Provider usage** is the truth for tokens, **PriceTable** for dollars,
  and the **harness's own clock** for latency (whole trial and per tool
  call).
- **The input to each grader is stored in full** (e.g. the rows of the
  graded tool call). Other tool results are cut down to fit the record.
  That means any trial can be regraded from its record alone.

## Failure interrogation (run flow)

| Step | Fail | Slow | Twice | Partial |
|---|---|---|---|---|
| Preflight (step 2) | Target unreachable or a named tool missing → exit 2, nothing spent | Connection timeout (10 s) → exit 2 | Harmless (lists tools only) | N/A |
| Model call | 429/5xx → retry with backoff + jitter, honour `Retry-After`, 3 tries, then trial `error`. **401/403 → abort the whole run** (every trial would fail). Context too long → `fail` (the agent's own transcript grew too big) | Per-request timeout (60 s) inside the trial's 120 s cap | A retried call after a timeout may be billed twice, and the lost call's usage is never returned → the trial's cost is marked a lower bound | Malformed or truncated response → treated as a 5xx and retried |
| Tool call (MCP) | **A tool *result* that is an error** (e.g. MCP-backbone rejecting a query) is normal feedback, passed back to the model, not an infra error. **Transport failure** (connection refused, server crashed) → rerun the whole trial fresh, at most 2 times, then `error`. Spend from the lost attempt still counts. | Client-side timeout (30 s) → transport failure. (A slow query killed by MCP-backbone's own `statement_timeout` comes back as an error result: the agent's fault.) | Safe: MCP-backbone is read-only, and the filesystem works on a throwaway copy | Big results are cut down in the record. The model always gets the full result |
| Grading | A grader raising an exception is a **harness bug**, not the agent's fault → `error` with kind `grader_error`, shown prominently. Expected answers are validated at suite load so this should be rare | Pure and local, so not a concern | Pure: same input, same result | N/A |
| Write trial line | Write fails (disk full, permissions) → abort the run, exit 2. A trial that wasn't written didn't happen | Lines are flushed one at a time | One writer, so lines never interleave | A line cut off by a crash is detected and skipped on load, and the run reads as incomplete |
| Budget check | Before each trial starts: spend so far + reserve for trials in progress + this trial's estimate must be ≤ cap, or no new trials start → `aborted` | — | — | **Known limit:** trials already running can still finish over budget. Worst-case overshoot ≤ concurrency × the largest trial cost. Documented, not hidden |
| Ctrl-C | First press: stop scheduling, cancel trials in progress, mark `aborted`, still write the report. Second press: exit immediately | — | — | Same as an abort: readable, but can't be compared |
| Clean-up | Stdio servers are started in their own process group and killed as a group, so no orphaned `node` processes remain. Temporary directories are deleted unless `--keep-fixtures` is passed (for debugging) | — | — | — |

## Concurrency

- Trials run at the same time under a semaphore (default 4, configurable).
  That's enough to keep a run to minutes without setting off Sumopod rate
  limits; 429s are absorbed by the retry backoff.
- Everything runs on one asyncio event loop. The spend counter and the
  trial writer are only touched from that loop, so no locks are needed.
  The writer is a single task fed by a queue.

## Trust boundaries

- **Model output is untrusted.** Tool arguments go to MCP servers that
  enforce their own limits. The filesystem server is started restricted to
  the temporary copy, and MCP-backbone is read-only at the database role
  level. Even a misbehaving agent can't touch the real fixtures or data.
- **Tool results are untrusted too** (prompt injection). One filesystem task
  should do this on purpose: a fixture file that tells the agent to delete
  or rewrite files, graded with `forbidden_tools`. This shows the harness
  can measure safety, not only accuracy.
- **The harness container is just another client.** It reaches
  MCP-backbone only through the public URL, like any outside client, and
  mounts nothing from MCP-backbone's directory, so it can't read the
  server's `.env` or database.
- **Suite and agent YAML are trusted but validated:** they're written by
  Arthur, loaded with `safe_load` only and checked against a schema.
- **Run records are public evidence** once committed. They contain no
  secrets (env var names only, headers redacted), only public Pagila data,
  and synthetic filesystem fixtures. Model text in reports is placed in
  fenced blocks so it can't break the Markdown.

## Revision (2026-10-23): the run flow on Inspect AI (ADR-009)

Steps 1–4 (validate, preflight, estimate, start the record) and step 9
(finish) stay the harness's own. Preflight now also reads the server's
build version, and takes the data fingerprint through the endpoint. Steps
5–8 (scheduling, the agent loop, retries, limits) are Inspect's:
`epochs=5`, `max_samples` for concurrency, `message_limit`/`time_limit` for
the caps, `retry_on_error` for infra retries, and `cost_limit` as a second
budget guard. After Inspect finishes, `export` turns its log into
`trials.jsonl`.

**To verify in slice B, not assumed:**
- whether Inspect runs epochs attempt by attempt (Phase 4 step 5). If it
  runs one sample's epochs back to back, the report says so; the effect
  is that a provider outage clusters on fewer tasks;
- what `cost_limit` caps (per sample or per eval) and what it does when
  hit;
- that a sample hitting `message_limit` or `time_limit` is recorded as a
  limit (→ `fail`), and a provider failure after retries as an error
  (→ `error`);
- **that repeats aren't served from a cache** (Sumopod is a LiteLLM proxy):
  two identical capped requests must get different response ids and no
  cached tokens. If caching is on, it's turned off or each epoch's request
  is made unique before any full run.

**Known incompatibility:** Inspect sends tools in OpenAI strict mode by
default, and MCP-backbone's optional `api_key` parameter violates strict
mode's rules, so the provider rejects the request with a 400 before any
tokens are spent. The harness sets `strict_tools=False` for the Sumopod
model provider, and records it in the run's settings. The root cause is
in MCP-backbone (see the handover), which affects any strict-mode client.

**`compare` adds two steps** before the statistics: regrade both runs with
the current grader code, and list every recorded difference between them
(model, server build, tool list, data fingerprint, prompt, settings).

**Verified in slice B (2026-10-23):**
- **Epoch order:** attempt by attempt, as step 5 wanted.
- **Caching:** none at Sumopod (different response ids and answers,
  0 cached tokens).
- **`cost_limit`:** caps each trial, not the run. The budget guard uses
  that: each trial is capped at budget ÷ trials, so the run's worst case
  is the budget itself, and the "trials in flight can overshoot" limit in
  the failure table no longer applies when the model has a price.
- **Limit vs error:** a cap hit is recorded as a limit (→ `fail`), and a
  model crash as a sample error (→ `error`). Both are tested offline.
