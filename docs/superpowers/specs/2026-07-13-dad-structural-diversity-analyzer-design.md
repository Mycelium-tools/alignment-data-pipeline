# DAD structural-diversity analyzer

**Date:** 2026-07-13
**Status:** approved (design), pending implementation plan

## Problem

The "Analyze" button on the viewer's **Run diversity** page (`viewer/ui_pages/run_diversity.py`)
runs the holistic categorical analyzers over a DAD run: evenness, coverage-vs-target,
correlation (Cramér's V), cluster-bridge, combination-coverage, and drift. Every one of
those reads **categorical tags** — `AnalysisContext.records` are the extraction tag rows
(`evals/holistic/analyzers.py:28`), not the raw text. So they answer "is the topic/taxa/
question-type mix varied?" but never "are the assistant's replies all *written* the same
way?"

That blind spot is the highest-risk collapse mode for chat/SFT training data: an aligned
model's rewrite (DAD step 6) tends to stamp a single response scaffold across the corpus —
"I understand your concern… here are three considerations… ultimately it's your call." The
research pass (2026-07-13) confirms this is the dominant SFT structural-collapse mode and
that surface/structural collapse hides in exactly the lane the current judge doesn't cover.
The categorical judge is **sound, not broken** — this is a missing dimension.

`evals/audit_sdf.py` already has mechanical structural instruments (opening-shape clustering,
markdown density, length/truncation, recurring n-grams, stock phrases), but they are
SDF-only (they resolve `final/sdf_corpus.jsonl`) and are print-coupled inside the CLI.

## Goal

Add one new **`structural`** analyzer that reads the **assistant turns' raw text** of a DAD
run and flags response-*form* collapse. It must be:

- **Mechanical / offline / free** — no LLM calls, so it preserves the page's "Analyze is
  nearly free" promise (the only paid call there is the existing one-shot synthesis).
- **A first-class analyzer** — registered in the holistic registry, selectable via the axes
  YAML `analysis:` block, rendered on the Run diversity page next to the existing sections,
  and folded into the existing LLM synthesis over the stats blob.
- **Comparative** — verdicts are provisional; the reliable read is diffing across runs, the
  same honest stance as `evals/diversity.py`.

## What it measures

All computed over the assistant turns of each final DAD record (`{record_id, messages}`,
roles `user`/`assistant`):

1. **Opening moves** — first-sentence shape clustering + duplicate first-5-word stems on the
   assistant's opening ("I understand your concern…", "That's a thoughtful question…").
2. **Closing moves** — last-sentence stem clustering / sign-off patterns
   ("Ultimately,…", "In the end, the choice is yours…").
3. **Scaffold shape** — the acknowledge → N-considerations → recommendation arc, detected
   mechanically: enumerated-list prevalence, section-header prevalence, and
   "considerations/factors/things to consider" framing.
4. **Formatting & length** — markdown density (bold / bullets / headers), length
   distribution + truncation artifacts, recurring 5-grams and banned stock phrases.

### Deliberate choices

- **Which turn:** opening/closing are computed on the **first assistant turn** (the primary
  training answer). Formatting, length, scaffold, and n-grams are computed over **all**
  assistant turns of the record concatenated.
- **Register proxy omitted.** The DAD assistant voice is single-register by design
  (first-person, conversational), so a first-person/contraction proxy would report ~100%
  and teach nothing. `audit_sdf`'s register check does not carry over.
- **`audit_sdf.py` is left untouched.** It works; routing it through the new module would
  edit stable code for no functional gain. The new module reuses the low-level primitives
  already in `shared/textstats.py` (shingles, near-dup, truncation helpers) and defines its
  own opener/markdown/scaffold patterns. The mild duplication of a few regex constants with
  `audit_sdf.py` is the conscious price of not destabilizing the SDF audit. (Optional future
  consolidation is out of scope here.)

## Architecture

### 1. `evals/holistic/structural.py` (new) — pure metric functions

No I/O, no API. Each function takes plain text/lists and returns a JSON-able fragment with a
GOOD/OK/BAD verdict, using the same `_verdict` convention as the other lanes
(`evals/holistic/analyzers.py`, `evals/diversity.py`). Sketch:

- `assistant_turns(record) -> list[str]` — the `content` of every `role == "assistant"`
  message, in order.
- `first_sentence(text)` / `last_sentence(text)` — sentence extraction (mirrors
  `audit_sdf.first_sentence`).
- `opening_moves(first_sentences) -> dict` — pattern-cluster share + duplicate stem list +
  verdict.
- `closing_moves(last_sentences) -> dict` — stem clustering + verdict.
- `scaffold_shape(texts) -> dict` — `{enumerated_list_frac, header_frac,
  considerations_frac, verdict}`.
- `formatting(texts) -> dict` — markdown-class prevalence (reuse `audit_sdf`'s classes),
  bold-frac verdict.
- `length_stats(texts) -> dict` — p10/median/p90 chars + `ends_mid_sentence` rate
  (`shared/textstats`).
- `recurring(texts) -> dict` — banned stock-phrase hits + recurring-5-gram discovery list.

### 2. `structural` analyzer — `evals/holistic/analyzers.py`

- Add `"texts"` to `INPUTS`.
- `AnalysisContext` gains `texts: dict | None = None` (`record_id -> joined assistant text`)
  and `available` adds `"texts"` when it is populated.
- New analyzer `structural`, `requires=("texts",)`, whose fn reads `ctx.texts`, derives the
  first/last sentences and concatenated texts, calls the `structural.py` functions, and
  returns `{opening, closing, scaffold, formatting, length, recurring}`.
- Register it in `default_analyzers()`; it is input-gated, so it runs whenever `texts` is
  present and is skipped-with-reason otherwise (the existing `run_analyzers` contract).

### 3. Plumbing — `evals/holistic/pipeline.py`

- `analyze(...)` gains a `texts: dict | None = None` param, threaded into `AnalysisContext`.
- `run(...)` derives `texts` from `inputs.corpus` — `{r["record_id"]: <joined assistant
  turns>}` — and passes it to `analyze(...)`; appends `"texts"` to `inputs_present`.
- Because the viewer's Analyze button calls `pipeline.run(..., do_tag=False)`, the new
  analyzer flows through automatically. `texts` is always derivable (the corpus is already
  resolved by `resolve_inputs`), so analyze-only runs keep working.

### 4. Rendering — `viewer/ui_pages/run_diversity.py`

A `structural = analyses.get("structural")` block placed alongside the existing sections:
per-signal tables (opening/closing/scaffold/formatting/length) with verdict columns and a
worst-offenders expander (duplicate stems, most-templated openings). No change needed for
synthesis — it already reads the whole `stats` blob, so structural findings appear in
"Top issues" for free.

## Data flow

```
final/dad_corpus.jsonl ──resolve_inputs──▶ inputs.corpus [{record_id, messages}]
                                             │
                              run(): texts = {record_id: assistant turns}
                                             │
   tag index (existing) ──▶ analyze(records, texts=…) ──▶ AnalysisContext
                                             │
                              run_analyzers (input-gated)
                                     ├─ evenness/coverage/… (read tags)
                                     └─ structural (reads texts)  ◀── NEW
                                             │
                              report.stats.analyses.structural
                                             │
                    run_diversity.py renders it  +  synthesis reads it
```

## Testing

New tests in the holistic suite; offline, `tmp_path`, plain asserts, seeded/shape-only per
the project conventions:

- **Pure functions** (`structural.py`): opening/closing/scaffold/formatting on hand-built
  inputs — a templated set yields BAD, a varied set yields GOOD; edge cases (empty text,
  single record, no assistant turn).
- **Analyzer**: over a synthetic tag+corpus fixture — templated corpus → BAD verdicts,
  varied corpus → GOOD; assert the fragment shape.
- **Input gating**: analyzer runs when `texts` present, is in `skipped` (with reason) when
  absent.
- **Pipeline wiring**: `run(...)` populates `texts` from the corpus and `"texts"` appears in
  `inputs_present`; extraction of assistant turns handles multi-turn (pushback) records.

## Non-goals

- No refactor of `evals/audit_sdf.py`.
- No LLM structural scan (would break the free-Analyze promise).
- No new dependencies.
- No register/tone proxy for DAD.
- No new verdict-threshold calibration study — thresholds ship provisional and comparative.

## Success criteria

- Clicking **Analyze** on a DAD run shows a new structural section with GOOD/OK/BAD verdicts
  for opening, closing, scaffold, and formatting/length, at no added API cost.
- A deliberately templated corpus scores BAD on opening/scaffold; a varied corpus scores
  GOOD.
- Structural issues surface in the synthesis "Top issues" list.
- `pytest` stays green and offline; the new analyzer is skipped gracefully when text is
  unavailable.
