# v4.3 run baseline — validation "before" set + gold-set seed

The paid v4.3 judge run (Gemini `gemini-3.1-pro-preview`) over 166 DAD records. This is
the baseline the v5 redesign validates against, and the seed for the gold set. Only
existed on the design machine — regenerating it is a ~$50 API run, so it is carried
here deliberately. Transient like the rest of `docs/v5-handoff/`; drop once the gold
set is frozen and v5 has its own run.

## Files
- `records_166.jsonl` — the 166 input records (user+assistant), one JSON per line. The
  fixed input corpus every rubric version is run against. (Identical to the old
  scratchpad's `dad_166_corpus.jsonl`; kept under the referenced name.)
- `verdicts_v4.3.jsonl` — the v4.3 judge verdicts, line-aligned 1:1 with
  `records_166.jsonl` (record N ↔ verdict N). The "before" distribution for the
  validation plan (`../v5_validation_plan.md`).
- `failure_catalog/slice_01..11.md` — the 2026-07-08 analyst catalog: per-record proxy
  labels across 11 slices. **This is the gold-set seed** (accumulator: "promoted to
  human-verified labels record by record").
- `failure_synthesis.md`, `failure_pass_brief.md` — the synthesis over the slices and
  the brief that produced the pass; context for reading the catalog.

## Deliberately NOT carried (available on the design machine on request)
- `JUDGE_REVIEW_gemini_dad-v4.3.md` (1.6 MB) — the human-readable per-record review;
  the readable form of `verdicts_v4.3.jsonl`, distilled already in
  `../sources/analysis_v43_findings.md`. Ask if the narrative is wanted.
- `verdicts_smoke.jsonl`, `cost_probe.jsonl` — smoke/probe artifacts, not baseline.

## How it's used downstream
1. Gold set: promote `failure_catalog/` proxy labels to human-verified tiers.
2. Validation: run v5a/v5b over `records_166.jsonl`, compare score distributions and
   per-record deltas against `verdicts_v4.3.jsonl` (see `../v5_validation_plan.md`).
