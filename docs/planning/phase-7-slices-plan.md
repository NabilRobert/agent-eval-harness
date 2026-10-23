# Phase 7 — Slice and Plan the Work

## Slices (vertical: each one runs end to end and is demoable)

| Slice | What it proves, end to end | Live model spend | Est. |
|---|---|---|---|
| **A. Walking skeleton** | One hard-coded Pagila task, one trial, live endpoint → `meta.json` + `trials.jsonl` → `compare` against itself exits 0. Repo, packaging, CI (ruff, pyright, pytest, compare on the committed run) in place. | 1 trial | 0.5 day |
| **B. Real suites, repeats and failure handling** | The Pagila suite as YAML, with expected answers generated through the endpoint (script committed); the data fingerprint; 5 repeats run attempt by attempt with concurrency; turn/time caps; retries; errors kept apart from fails, including MCP-backbone's rate-limit message; budget estimate and cap; `api_key: null` stripped from records. | Smoke suite only (3 tasks × 1 repeat) | 1 day |
| **C. Report** | `report.md`: strict and lenient pass rate, pass^k, cost and latency per task and in total (from `prices.yaml`), errors shown next to pass rates, and (Should) the tool-call trace of each failed trial. | None (built on slice B's runs) | 0.5 day |
| **D. Compare and the regression gate** | Paired bootstrap + "task broke" (5/5 → 0/5), exit codes 0/1/2, trials-file hash check, refusal to compare different task hashes or data fingerprints. Tested exhaustively on synthetic run files. Then the two live proofs: an A/A pair is **not** flagged, a degraded agent (one tool removed) **is**. | 3 full Pagila runs on `gpt-5-mini` (see spend plan) | 1 day |
| **E. Filesystem target** | stdio adapter, a fresh fixture copy per trial, 15–20 tasks including the planted prompt-injection task graded with `forbidden_tools`. | Smoke suite, then 1 full run | 0.5–1 day |
| **F. Container on the VPS** | Spike 3, then the image (Python + Node, pinned), Compose file with CPU/memory limits and the env file, runbook. The skeleton run repeated from the container. | 1 trial | 0.5 day |
| **G. Published results and write-up** | `gpt-5-nano` full runs on both suites; README (leading with the two proofs and real numbers), methodology (data fingerprint, same-host latency caveat, detectable-drop numbers from Spike 5), ADRs and JOURNEY tidied. | 1–2 full runs | 1 day |

**Order:** A → B → C → D → E → G, with F slotted in whenever the VPS is
free (it depends only on A). **Total: ~5–6 days,** the same as the Phase 2
estimate, against the 3–4 day budget; the fallback below is already
decided.

## Spend plan (conservative, per Arthur)

- **Development never runs a full suite.** Slices B, C and E are built
  against a 3-task smoke suite at 1 repeat (≈ 3 trials, well under a cent
  each time).
- **Every full run is announced first,** with its estimate from the
  harness's own pre-run cost estimate, and needs Arthur's OK.
- **The A/A pair doubles as the published `gpt-5-mini` results:** two full
  runs of the same agent are both the false-alarm proof and the "repeated
  runs" Phase 1 asked for. So v1 needs about 6 full runs in total
  (mini ×2, degraded mini ×1, nano on Pagila ×1, filesystem ×2).
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
degraded caught), both targets, and the honest write-up of limits. The
container (slice F) can slip past "done" without breaking any Phase 1
success metric, so if time runs out, it waits; the laptop runs are
equally valid evidence.

**Scale-back-up plan (post-v1, tracked, not forgotten):** the
`gpt-5-mini` → `gpt-5.4-mini` upgrade comparison; one non-OpenAI model
after a tool-calling check; the optional LLM-judge grader; an HTML report.
