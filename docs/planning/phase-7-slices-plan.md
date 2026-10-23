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
