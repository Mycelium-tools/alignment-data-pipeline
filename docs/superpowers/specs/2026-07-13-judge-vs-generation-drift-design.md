# Judge-vs-generation tagging drift (hints40)

**Date:** 2026-07-13
**Branch:** `arda/dad-judge-rubric`
**Status:** design — awaiting implementation plan

## Problem

The DAD pipeline tags every dilemma at generation time (step 1) with categorical
axes, carried onto each record's `.annotation` through step 2/3. The holistic
diversity judge (`evals/holistic_dad.py` + `evals/dad_axes.yaml`) independently
re-tags records with an overlapping axis set. We want to measure **how much the
judge's independent tagging diverges from the generation-time tagging** — a QA
signal on both the judge's reliability and the generation's fidelity, and a
regression signal across pipeline iterations. The comparison must be like-for-like:
identical axis names, vocabularies, and shapes on both sides, so the number
reflects real re-tag drift, not schema mismatch.

The machinery already exists: `evals/holistic/analyzers.py::_drift` computes
per-axis confusion between the intended (generation annotation) label and the
realized (judge) label — agreement rate, top confusion pairs, GOOD/OK/BAD verdict.
The pipeline already joins annotations by `record_id`. It has never been run on a
spec-driven dataset because the judge code and the spec-driven pipeline + dataset
have lived on divergent branches, and a few axes did not line up in name/shape.

## Dataset

`outputs/dad/runs/2026-07-12_16-37_hints40-smoke` (from PR #75,
`origin/constance/dad-refinement4`), 40 examples. It ships only through **step 2**:
no `final/dad_corpus.jsonl`, no `step3/`, and step-2 records key on
`prompt_id`/`response_id` (no `record_id`). We therefore compare the judge's
reading of the **step-2 response** (`user_message` + `assistant_response`, pre-
rewrite) against the dealt `.annotation`. This is the only conversation text the
run has, and it is the cleanest comparison — fewest transformations between the
deal and the read.

## Axis reconciliation (verified against the real data)

Comparable scalar axes and their handling in the annotation map:

| Axis | Handling |
|---|---|
| `visibility`, `user_attitude`, `conflict`, `direction`, `user_stakes`, `leverage` | Pass through — vocabularies already **identical** to `dad_axes.yaml`. |
| `welfare_severity` | Split from generation's `welfare_magnitude` = `"{severity} x {scope}"`. |
| `welfare_scope` | Split from `welfare_magnitude` (second component). |
| `taxa_category` | Lifted from the dilemma's top-level field; normalize `"farmed animals"` → `"farmed"` (only gap vs judge vocab). |
| `systemic_ai` | Lifted from the dilemma's top-level bool field. |

`welfare_magnitude` is a clean 3×3 product across all 40 records
({Mild,Moderate,Severe} × {Individual,Group,Population}); both components share the
judge's exact vocabularies, so splitting is lossless and yields two identical axes
on both sides. **No changes to the judge or `dad_axes.yaml`.**

Explicitly **out of scope** (not scalar / not comparable): `domain`, `user_goal`,
`values_in_tension` (multi-valued — drift compares scalars only), `moral_patients`
(free text, no controlled vocab; the judge's `taxa_category` covers the comparable
signal). No data is dropped — the map only *adds* derived scalar fields.

## Components

### 1. `evals/drift_report.py` (new, self-contained — the reusable artifact)

- Reads a run dir. For a step-2-only run, builds an in-memory
  `pipeline.Inputs`:
  - corpus: `[{record_id: <prompt_id>, messages: [{role:user, content:user_message},
    {role:assistant, content:assistant_response}]}]`
  - annotation map: `{record_id: {axis: value}}` per the reconciliation table above.
- Runs the existing `pipeline.tag` → `_drift` (plus the cheap no-API analyzers:
  `distribution`, `evenness`) via the holistic pipeline, using a pre-resolved
  `Inputs` so shared code is untouched.
- Renders `drift_report.md` + `drift_report.html` into the run dir.
- CLI: `python evals/drift_report.py --input outputs/dad/runs/<run>`. Points at any
  run; the step-2 adapter is used only when `final/`/`step3/` are absent, otherwise
  it defers to the normal `resolve_inputs` path.

Two pure helpers, unit-tested:
- `parse_welfare_magnitude(s) -> (severity, scope)` — splits `"Severe x Population"`;
  malformed input returns `(None, None)` so the record simply isn't compared on
  welfare (fail-safe, no crash).
- `step2_to_inputs(run_dir) -> Inputs` — builds corpus + annotation map from
  `step2/responses.jsonl` and `step1/dilemmas.jsonl`.

### 2. Report artifact

Markdown + HTML in the run dir. Per-axis table: axis, n compared, agreement %,
top confusion pairs (intended → realized × count), GOOD/OK/BAD verdict. Headline
summary: mean agreement across axes and the axes with the largest drift —
answering "how much does it change." HTML mirrors the existing
`outputs/dad/*_AB_REVIEW.html` style (self-contained, theme-aware).

## Cost

~40 extraction calls (one per record), a few cents to ~$0.50. Logged to the global
`outputs/cost_log.jsonl` like other evals.

## Testing (offline, per CLAUDE.md)

- `parse_welfare_magnitude`: valid split, malformed → `(None, None)`, case/spacing
  tolerance as implemented.
- `step2_to_inputs`: tiny fixture (2 step-2 records + 2 dilemmas) → asserts corpus
  shape, `record_id` join, welfare split, `taxa_category` normalization, and
  `systemic_ai`/`taxa_category` lift. No API, no network, `tmp_path`.
- Drift wiring: feed a hand-built `Inputs` with known annotations and pre-set tags
  (no API) through `_drift` and assert agreement/confusion for one matching and one
  mismatching axis. Uses the existing analyzer directly — confirms our annotation
  map is shaped the way `_drift` expects.

Renderer is I/O; covered by a smoke assertion that the two files are written and
contain each compared axis, not by pixel checks.

## Non-goals

- No merge/rebase of branches; the run is copied in as data only.
- No change to the generation pipeline, the judge, or `dad_axes.yaml`.
- No comparison of multi-valued or free-text axes in this pass.
