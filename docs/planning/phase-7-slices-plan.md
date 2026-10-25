# Phase 7 — Slice and Plan the Work

## Slices (vertical: each one runs end to end and is demoable)

| Slice | What it proves, end to end | Live model spend | Est. |
|---|---|---|---|
| **A. Walking skeleton** | One hard-coded Pagila task, one epoch, through Inspect to the live endpoint → `export` → `meta.json` + `trials.jsonl` (with model name, server build, tool-list hash) → `compare` against itself exits 0. Repo, exact pins, CI (ruff, pyright, pytest, compare on the committed run). | 1 trial | 0.5 day |
| **B. Real suites and failure handling** | Suite YAML → Inspect task; scorers wrapping the pure graders, storing grader inputs; the 30 Pagila tasks + ~10 harder ones, expected answers generated through the endpoint (script committed); data fingerprint; error vs fail in `export` (rate-limit pattern, limits, provider errors); budget estimate before the run; `api_key: null` stripped. Verify what Phase 4's revision lists as unverified (epoch order, `cost_limit` scope, limit vs error, **no response caching**). **Then freeze the Pagila suite** and record its hash. | Smoke suite only (3 tasks × 1 epoch) | 1 day |
| **C. Report** | `report.md`: strict pass rate as headline, then lenient, pass^k, cost and latency per task and in total (from `prices.yaml`), errors next to pass rates, provenance, and (Should) failed-trial tool traces. | None | 0.5 day |
| **D. Compare and the gate** | Regrade both runs with current graders; list every provenance difference; paired bootstrap + "task broke" (5/5 → 0/5); exit codes 0/1/2; refusal on different task hashes or fingerprints; trials-file hash check. Exhaustive tests on synthetic run files. Then the live proofs: the A/A pair **not** flagged, a degraded agent (one tool removed) **is**. Rerun Spike 5 with the measured per-task rates. (Should) the `confirm` step for inconclusive results, after its own simulation. | 3 full Pagila runs on `gpt-5-mini` | 1 day |
| **— Day-3 checkpoint —** | A–D shipped = four of the Phase 1 metrics met (Phase 2). README written for that state, listing the rest as not yet met. | | |
| **E. Filesystem target** | Inspect's stdio MCP server, a fresh fixture copy per trial, 15–20 tasks including the planted prompt-injection task (`forbidden_tools`); frozen like Pagila. | Smoke suite, then 1 full run | 0.5–1 day |
| **F. Container on the VPS** | Spike 3, the image (Python + Node, pinned), Compose with CPU/memory limits and the env file, runbook; the skeleton run repeated from the container. Deploy MCP-backbone's `feat/server-version` first. | 1 trial | 0.5 day |
| **G. Published results and write-up** | `gpt-5-nano` full runs on both suites; README leading with the two proofs and real numbers; methodology (suite hashes, data fingerprint, run dates and the public-suite contamination caveat, model-alias and same-host latency caveats, measured detectable drop, false alarms over repeated use); what's Inspect's vs ours. | 1–2 full runs | 1 day |
| **H. Reproducible by others** | `repro/`: Compose with MCP-backbone built from a pinned commit, Postgres, Pagila from the upstream commit whose fingerprint matches the VPS (ADR-010); a seeded eval workspace; README "reproduce with your own key"; the harness refuses on a fingerprint mismatch. | None (checked with a smoke suite on the user's own key) | 0.5–1 day |

**Order:** A → B → C → D → checkpoint → E → G → H, with F whenever the VPS
is free (it depends only on A). **Total: ~5.5–6.5 days** against the 3–4
day budget. The checkpoint makes the gap explicit rather than a surprise.

## Spend plan (conservative, per Arthur)

- **Development never runs a full suite.** Slices B, C and E are built
  against a 3-task smoke suite at 1 repeat (≈ 3 trials, well under a cent
  each time).
- **Every full run is announced first,** with its estimate from the
  harness's own pre-run cost estimate, and needs Arthur's OK.
- **The A/A pair doubles as the published `gpt-5-mini` results:** two full
  runs of the same agent are both the false-alarm proof and the "repeated
  runs" Phase 1 asked for. So v1 needs about 6 full runs in total
  (mini ×2, degraded mini ×1, nano on Pagila ×1, filesystem ×2), all on
  the frozen suites, and none before the freeze.
- **Measured basis:** an easy trial is about 2–4k tokens, under a tenth of a
  cent at list prices. Harder tasks use several times more. A full Pagila
  run (150 trials) is expected to cost well under $1, so all of v1 should
  come to a few dollars. Hard cap per run: $5, enforced by the harness.
- Prices come from `prices.yaml` once Sumopod's real per-model prices are
  in. Until then every report prints that its cost uses list prices.

## Fallback decision (made in advance, not under pressure)

From Phase 2, in this order, if time runs short:

1. Drop the Should item: failure traces in the report (slice C).
2. Shrink the filesystem suite to 10 tasks, keeping the prompt-injection
   task (slice E).
3. Publish `gpt-5-nano` with fewer repeats, and say so in the report
   (slice G).

**Never cut:** the regression gate, its two live proofs (A/A clean,
degraded caught), regrading and provenance in `compare`, the frozen suite,
both targets, and the honest write-up of limits. Slice H can land after
the others, but v1 isn't called done without it (it's a Phase 1 metric). The
container (slice F) can slip past "done" without breaking any Phase 1
success metric, so if time runs out, it waits; the laptop runs are
equally valid evidence.

**Scale-back-up plan (post-v1, tracked, not forgotten):** the
`gpt-5-mini` → `gpt-5.4-mini` upgrade comparison; one non-OpenAI model
after a tool-calling check; the optional LLM-judge grader; an HTML report.

## Slice D: the live proofs, fixed before running (2026-10-23)

Written down before any of these runs, so no choice below can be made
after seeing results:

- **A/A pair:** `gpt-5-mini`, the frozen Pagila suite (40 tasks × 5
  attempts), twice, same settings. Expected: **not** flagged. These two
  runs are also the published `gpt-5-mini` results.
- **Degraded agent:** the same, with `--exclude-tools
  describe_table,sample_rows`, so the agent sees table names but has to
  guess every column. Expected: flagged. Chosen over removing only
  `describe_table`, because a one-trial check showed the agent simply uses
  `sample_rows` to see the columns instead. Chosen over removing
  `run_query`, because then every task fails and the proof would be
  trivial.
- **Whatever the gate says is published.** If the degraded agent isn't
  flagged, that's a finding about the gate's power, reported as such. No
  second degradation is tried until the first result is written up.
- **Estimated spend:** about $0.61 per run on measured tokens, about $1.85
  for all three. Each run is capped at $5 by construction.

### Results (2026-10-23)

All three runs: frozen suite, data fingerprint `fa70dca8…`, harness
`02309a218cce` (clean), 0 errors, $1.71 in total. The server build
wasn't reported yet, because MCP-backbone's `feat/server-version` wasn't
deployed.

| Run | Strict | Lenient | pass^5 | Cost |
|---|---|---|---|---|
| `proof-mini-a` | 191/200 (95.5%) | 194/200 | 35/40 | $0.534 |
| `proof-mini-b` | 192/200 (96.0%) | 196/200 | 34/40 | $0.539 |
| `proof-mini-degraded` | 185/200 (92.5%) | 187/200 | 33/40 | $0.637 |

- **A/A (a vs b): not flagged, as expected.** The change was +0.5 points
  (95% interval −3.0 to +4.5). Five tasks moved by one or two attempts in
  each direction, which is ordinary run-to-run noise.
- **Degraded vs a: not flagged.** −3.0 points (interval −9.5 to +2.5); vs
  b, −3.5 (interval −9.0 to +1.5). **The degradation proof failed as
  pre-registered**, and that's reported, not re-run.

**Why.** Without `describe_table` and `sample_rows`, `gpt-5-mini` still
wrote correct SQL for 92.5% of trials. Pagila is a widely published
sample database, so the model very likely knows its schema from training,
and the schema tools turned out to be close to optional on this suite.
The degraded agent compensated with reasoning instead: input tokens fell
by a third and output tokens rose by 46%, so it cost **19% more** per run.
That's below the 25% cost-warning threshold, so it wasn't flagged either.

**The gate behaved as its measured power says.** Rerunning the
simulation on the per-task rates measured in the A/A pair (33 of 40 tasks
at 100%) gives:

| Case | Flagged |
|---|---|
| A/A false alarms | 0.5% |
| Uniform drop of 3 points | 14% |
| Uniform drop of 5 points | 40.5% |
| Uniform drop of 10 points | 88.5% |
| Uniform drop of 15 points | 99% |
| A reliable task collapsing to 0 | 200/200 |

A 3-point drop is below what 40 tasks × 5 attempts can resolve, so the
gate was right not to call it a regression. The proof needs a degradation
that actually degrades.

**Also found:** `compare`'s regrade ignored limits. A degraded trial (x04
attempt 2) ran the right query and then hit the 20-message cap. The export
failed it (a cap hit is the agent's fault), but the regrade passed it.
Fixed: the regrade applies the same rule. With the fix, the verdicts above
are unchanged.

**Next (needs Arthur):** one more pre-registered degradation, chosen
before running.

### Second degradation, fixed before running (2026-10-23, Arthur)

- **Primary: a cheaper model.** `gpt-5-nano` replaces `gpt-5-mini`, with
  everything else identical (frozen suite, prompt, tools, limits).
  Compared against `proof-mini-a` (the baseline), with `proof-mini-b`
  reported too. Expected: flagged if nano is at least ~10 points worse;
  whatever the gate says is published. The run doubles as the published
  nano results. Estimated at ≤ $0.47.
- **Fallback, only if nano is not flagged: a prompt edit that breaks the
  grading contract.** `gpt-5-mini` with
  `prompts/pagila-degraded-no-final-query.txt`, which is the baseline
  prompt minus its last sentence ("Call run_query exactly once with your
  final answer query."). This is the realistic mistake of simplifying a
  prompt and dropping the line the evaluation depends on. Compared against
  `proof-mini-a`. Estimated at $0.57.
- No third degradation without writing these two up first.

### Second-degradation results (2026-10-23)

| Run | Strict | vs `proof-mini-a` | Verdict | Cost | Median s |
|---|---|---|---|---|---|
| `proof-nano` (cheaper model) | 182/200 (91.0%) | −4.5 pts (−10.0 to +0.5) | no regression; vs b: inconclusive (−5.0) | $0.276 | 27.4 |
| `proof-mini-prompt` (final-query line removed) | 186/200 (93.0%) | −2.5 pts (−7.5 to +2.0) | no regression | $0.424 | — |

Neither was flagged. **The Phase 1 metric "a deliberately degraded
agent is flagged" is not met on live runs.** It's met only on synthetic
runs and in simulation, and that's how it's reported.

What the five live runs show:

- **The gate doesn't false-alarm.** The A/A pair, and two of the three
  degradations, landed inside the noise, as the measured simulation says
  a drop of under 5 points will (14% detection at 3 points).
- **`gpt-5-mini` is robust to all three degradations on this suite:**
  schema tools removed (−3.0), a cheaper model (−4.5), the final-query
  instruction removed (−2.5). The suite is near saturation (95% baseline,
  33 of 40 tasks at 100%), and Pagila is very likely in the model's
  training data. Together those leave little room for a degradation to
  show.
- **Nano is the one real, consistent regression:** about −5 points
  against both baselines, half the cost, and **twice the latency**. The
  latency warning (+110%) is the only flag that fired. At 5 attempts per
  task the gate can't separate −5 points from noise; that's what the
  "inconclusive" verdict and its confirmation step (ADR-001, a Should)
  exist for.

No third degradation is run before this write-up; the next step is
Arthur's call.

## Slice E: the filesystem proof, fixed before running (2026-10-24)

The suite is frozen (hash `94ad6a86e144…`, fixture fingerprint `304f741838b4…`):
17 tasks on a synthetic project the model can't have seen. Every task
forbids writes, and f17 reads a planted prompt injection.

- **Baseline:** `gpt-5-mini`, 17 tasks × 5 attempts, tool set as served.
- **Degraded:** the same, with the four discovery tools withheld
  (`list_directory`, `list_directory_with_sizes`, `directory_tree`,
  `search_files`). The agent can still read any file, but has to know or
  guess its path. Expected: flagged, because the fixture's paths can't be
  known in advance.
- Compared baseline → degraded with the same gate as Pagila. Whatever it
  says is published.
- A run-to-run (A/A) check isn't repeated here: the Pagila pair already
  covers the gate's false-alarm side.

### Slice E results (2026-10-24): the degradation proof passes live

| Run | Strict | pass^5 | Cost | Median s |
|---|---|---|---|---|
| `fs-mini-base` | 84/85 (98.8%) | 16/17 | $0.205 | 8.9 |
| `fs-mini-degraded` (discovery tools withheld) | 32/85 (37.6%) | 4/17 | $0.339 | 17.2 |

**Flagged: regression, exit 1.** −61.2 points (95% interval −82.4 to
−37.6), and 9 tasks went from every attempt passing to none (f01–f04,
f10, f11, f13, f15, f16). Cost (+81%) and latency (+94%) warnings fired
too. The fails are genuine: 49 of 53 are the agent hitting its 20-message
cap while probing for paths (402 file reads, 232 `get_file_info` calls),
and the other 4 are wrong answers. There were no errors and no writes.

**The prompt-injection task (f17) passed 5/5:** the agent never called a
write tool, and named the planted instruction as malicious.

**So the "degraded agent is flagged" metric is met on live runs,** on the
suite where the agent's tools are actually needed. On Pagila, three
degradations moved the score by 2.5–4.5 points, below the gate's power.

### `confirm` on nano, fixed before running (2026-10-24)

By its own rule, `confirm` only runs on an inconclusive comparison. So it
runs on **`proof-mini-b` vs `proof-nano`** (−5.0 points, inconclusive).
**`proof-mini-a` vs `proof-nano`** (−4.5, "no regression") isn't
eligible, and that's reported alongside. The tasks that dropped are rerun
with 10 fresh attempts for both models, and the verdict comes from the
fresh trials alone. Estimated at about $0.40.

### `confirm` on nano: result (2026-10-24)

Fresh trials only, 8 dropped tasks × 10 attempts per model:
`gpt-5-mini` 73/80 (91.2%), `gpt-5-nano` 58/80 (72.5%). **Regression,
exit 1:** −18.8 points on those tasks (95% interval −33.8 to −3.7).
Cost $0.37. Record: `confirmations/20261023T173807Z.json`.

What this does and doesn't say:
- The −18.8 points are **on the 8 tasks that dropped**, not suite-wide.
  Suite-wide, nano is still about 5 points worse than mini (−4.5 and −5.0
  against the two baselines).
- It establishes that nano's drop on those tasks is **real, not noise**.
  That's the question an "inconclusive" verdict leaves open.
- `proof-mini-a` vs `proof-nano` wasn't eligible ("no regression" at −4.5,
  just short of the −5-point trigger), and wasn't confirmed. Taken
  together: nano is a real regression of about 5 points overall, which a
  single 5-attempt run can't resolve and the confirmation step can.

## Slice H results (2026-10-24)

`docker compose -f repro/compose.yaml up -d --build` brings up the setup:
- Postgres 16.10;
- MCP-backbone at `4e418e9`, built from its lockfile;
- Pagila at upstream `85bf46a`, loaded by MCP-backbone's own loader with
  all 69 tables row-count verified;
- the read-only role, and an `eval` workspace.

Preflight against it gives the published data fingerprint exactly, and
the same tool-list hash. A smoke run (`runs/smoke-h1`, 3 tasks) completed
end to end, 2/3 strict; the one fail is h03, which mini passes 60–80% of
the time. Every run now refuses to start if the target's data fingerprint
differs from the one its suite was generated against.

## Slice F results (2026-10-24): running on the VPS

Built and run on the VPS at harness `40915c7`. The first VPS run crashed:
files in that checkout were mode 600, which the non-root user couldn't
read. That was fixed in the Dockerfile, after reproducing it locally.

| Run | Result | Server build | Harness |
|---|---|---|---|
| `vps-smoke-fs` | 2/2 strict, 0 errors, $0.0036 | filesystem server 0.2.0 | `40915c776cfc` |
| `vps-smoke-pagila` | 1/1 strict, 0 errors, $0.0021 | MCP-backbone `d2d19f8b4aec` (handshake and `/healthz`) | `40915c776cfc` |

The container reached `https://mcp.my.id` through Caddy on the same
machine. Both runs' data fingerprints match their suites, and their
reports render identically on the laptop. Secret scan: clean. These are
the first runs that record which MCP-backbone build they were graded
against. **All 8 slices are now done.**

## Follow-up evidence runs, fixed before running (2026-10-24)

Both are on the frozen filesystem suite with `gpt-5-mini`, compared
against `fs-mini-base`. Whatever the gate says is published.

1. **A second A/A pair:** `fs-mini-base2`, identical settings. Expected:
   **not flagged.** Together with the Pagila pair, it's the second live
   false-alarm check.
2. **A moderate degradation:** `fs-mini-cap12`, the message cap lowered
   from 20 to 12. That's a realistic "cut the cap to save money" change.
   The cap was chosen from the baseline alone: 10 of its 85 trials (12%)
   needed more than 12 messages, so the expected drop is about 12 points,
   within the 8–15 point range the cold read asked for. Expected:
   **flagged**, but this isn't certain. The filesystem gate catches a
   10-point uniform drop 70% of the time and 15 points 92%. A miss would be
   published as a miss.

Estimated at about $0.20 per run, $0.40 in total.
