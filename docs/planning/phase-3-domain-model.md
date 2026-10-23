# Phase 3 — Domain Model

## Glossary

- **Suite** — a named set of tasks for one target, stored as one YAML file.
- **Task** — one thing to ask the agent: an id, a prompt, tags (e.g.
  difficulty) and the graders that decide pass/fail. Its identity for
  comparison is its **task hash** (a hash of its prompt and graders,
  expected answers included), not a version number someone has to remember
  to bump.
- **Target** — where the agent's tools come from: an MCP server reached over
  streamable HTTP (MCP-backbone) or started over stdio (filesystem, run on a
  fresh copy of a fixture directory).
- **AgentConfig** — the thing being evaluated: model (name + settings),
  system prompt, target, a tool allowlist, and limits (turn cap, time cap).
  A "degraded agent" is just another AgentConfig, e.g. a worse prompt or one
  tool removed from the allowlist.
- **Run** — one execution of a suite against an AgentConfig, with N repeats
  per task. Stores everything needed to explain it later: config snapshot,
  hashes, harness git SHA, status, totals.
- **Trial** — one attempt at one task inside a run (attempt 1..5). The
  smallest unit of evidence: outcome, grader results, final answer, every
  tool call, tokens, cost, latency, and why it stopped.
- **Grader** — a pure check on a finished trial. v1 kinds: `result_match`
  (rows from the last call to a named tool, strict and lenient, ported from
  MCP-backbone), `answer_match` (final text contains / equals / number within
  tolerance), `required_tools`, `forbidden_tools`.
- **Comparison** — the result of comparing a candidate run with a baseline
  run: shared and missing tasks, change per task, change across the suite
  with its confidence interval, broken tasks, cost/latency changes, and a
  verdict.
- **PriceTable** — $ per million input/output tokens per model, with its
  source and date. Cost is computed from it and never invented.

There's **no separate Baseline entity**. A baseline is just the run you choose
to compare against (a path to a run directory). A separate entity would
always map 1:1 to a run.

## Entities & relationships

- `Suite` → has many `Task`s, and names the target kind it expects.
- `AgentConfig` → names one `Target`. It must match the suite's target, or
  the command exits 2 before spending anything.
- `Run` → one `Suite` (snapshot of task hashes), one `AgentConfig`
  (snapshot plus hashes of the prompt and tool list), many `Trial`s.
- `Trial` → belongs to one `Run` and one `Task` (by id + hash). It has many
  `ToolCall`s (name, arguments, truncated result, latency) and one
  `GraderResult` per grader.
- `Comparison` → two `Run`s (baseline, candidate). It is computed and
  rendered into a report, never stored as a source of truth.

## Invariants

- **Each trial has exactly one outcome:** `pass`, `fail` or `error`.
  `error` is only for infrastructure (provider 5xx, rate limit after
  retries, MCP server unreachable). Hitting the turn or time cap is a
  `fail`.
- **Pass rates leave errors out,** and the error count is always shown next
  to the pass rate, never hidden.
- **Strict vs lenient:** a trial passes strictly if every grader passes
  strictly. It passes leniently if every grader passes leniently (graders
  with no lenient mode use their strict result).
- **Run records are immutable once a run finishes.** `compare` and `report`
  read them and never write to them.
- **Comparison is a pure function** of two run directories: the bootstrap
  uses a fixed seed, so the same two runs always give the same verdict. This
  is what lets CI gate on committed files.
- **Only tasks with the same id *and* the same hash are compared.** The same
  id with a different hash → exit 2 (the task changed, so the scores mean
  different things).
- **An incomplete run can't be compared:** if more than 10% of trials
  errored or it stopped early, either side of a comparison → exit 2.
- **Cost is `null`, not 0, when usage is missing.** Totals that include a
  `null` are reported as a lower bound ("≥ $X").
- **No secret values in any record.** Configs refer to environment variable
  *names*, and headers are redacted before saving.
- **The original fixture directory is never given to an MCP server.** Each
  stdio trial gets its own temporary copy.
- **The budget cap is never exceeded on purpose:** no new trial starts if
  spend so far plus the estimated cost of trials in progress would exceed
  it. Such a run is marked `aborted`.

## Lifecycle

- **Run:** `running` → `complete` | `incomplete` (>10% errors) |
  `aborted` (budget cap or Ctrl-C). Header written at start, status and
  totals at the end.
- **Trial:** `pending` → `running` → `pass` | `fail` | `error`. Retries of
  infrastructure failures happen *inside* `running` and are recorded on the
  trial (attempt count), not as extra trials.
- **Each trial is appended to disk as soon as it finishes,** so a crash
  leaves a partial run that can still be read. It stays `running`, and the
  report treats it as incomplete.

## On-disk shape (sketch, finalised in Phase 5)

```text
runs/<run-id>/
  meta.json      # config snapshot, hashes, git SHA, status, totals
  trials.jsonl   # one Trial per line, appended as each finishes
  report.md      # rendered from the two files above
```

```yaml
# suites/pagila.yaml
suite: pagila
target: mcp-backbone
tasks:
  - id: easy-01
    tags: [easy]
    prompt: How many customers are there?
    graders:
      - result_match: {tool: run_query, expected: [[999]]}
```

```yaml
# suites/filesystem.yaml
suite: filesystem
target: filesystem
tasks:
  - id: port-config
    tags: [medium]
    prompt: Which config file sets the server port, and to what value?
    graders:
      - answer_match: {contains: ["config/server.toml", "8080"]}
      - forbidden_tools: [write_file, edit_file, move_file]
```

## Module boundaries

| Module | Owns | Talks to the outside? |
|---|---|---|
| `suites` | Loading and validating YAML, task hashing | No |
| `targets` | MCP connection (HTTP/stdio), fixture copies | **Only module that talks to MCP servers** |
| `agent` | Model loop, turn/time caps, collecting the trace and token usage | **Only module that talks to the model provider** |
| `grading` | Pure grader functions | No |
| `runner` | Repeats, concurrency, retries, budget cap, writing run records | Through `targets` and `agent` only |
| `compare` | Regression rule (bootstrap CI + "task broke"), verdict, exit code | No |
| `report` | Rendering Markdown from runs and comparisons | No |
| `cli` | Commands `run`, `compare`, `report` | — |

**Dependency rule:** `grading`, `compare` and `report` never import `targets`
or `agent`. This is what lets CI run `compare` with no API key and no
network, and lets these modules be tested exhaustively with plain fixtures.
