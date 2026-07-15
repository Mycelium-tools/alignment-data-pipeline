# Deeper LLM diversity synthesis over every graph

## Intent

Make the holistic-diversity LLM judge (`evals/holistic/synthesize.py`) produce a
longer, better-organized analysis that reasons over **all** of the Run-diversity
graphs — including the semantic/embedding diversity it currently cannot see — while
keeping its input aggregate and bounded so it scales to **thousands of examples**.

## Current state

- `synthesize.synthesize(stats, template, …)` sends the analyzer `stats` blob
  (`analyses` + `skipped`) to one LLM call and returns `{"prose": str,
  "top_issues": list, "raw", "errors"}`. Prompt is the editable
  `prompts/tools/dad_holistic_synthesis.txt` with a single `{{STATS}}` token.
- The `stats` blob already contains every **categorical** graph's data
  (distribution, evenness, coverage_vs_target, correlation, combination_coverage
  incl. `filled_cells`, drift, cluster_bridge, structural). It is aggregate and
  **bounded by axis vocabulary, not record count** (~17 KB at any corpus size).
- It does **not** contain the **semantic** diversity report
  (`audit/diversity_report.json`: Vendi, near-dup rates, cluster spread, the 2D
  map projection). The judge is blind to meaning-space collapse.
- The viewer renders `synthesis.prose` (one expander) + `top_issues` (a list).
- `max_tokens=4000`, `temperature=0.0`.

## Design

### 1. Feed the semantic diversity — bounded

New helper in `evals/holistic/pipeline.py`:

```
_load_semantic_summary(base_dir: Path) -> dict | None
```

Reads `base_dir / "audit" / "diversity_report.json"` (same file `_load_clusters`
uses) and returns a **bounded** summary containing only aggregate fields:

- `embed_model`, `n_embedded`, `n_empty`
- `vendi` (score), `mean_pairwise_cosine`
- `nn` (near-dup fraction buckets)
- `clusters` **without `assignments`** (keep `k`, `clusters`, `evenness`,
  `verdict`)
- `top_pairs` **capped at the first 5** (similarity + snippets)

It **explicitly excludes** `projection` and `clusters.assignments` — the only two
O(records) arrays in that report. This exclusion is the scale guard: the judge's
whole input stays ~constant size regardless of corpus size.

Behavior: returns `None` when the file is absent or malformed (mirror
`_load_clusters`'s fail-soft handling — a corrupt report degrades to `None`, never
blocks synthesis).

### 2. Merge into the synthesis input without polluting persisted stats

In `pipeline.run`, when a `synthesis_template` is provided:

```
synth_input = {**stats, "semantic": _load_semantic_summary(inputs.run_dir)}
report["synthesis"] = synthesize.synthesize(synth_input, template=…, model=…)
```

`report["stats"]` continues to hold the pure analyzer output — semantic data still
lives only in its own report; we feed a *copy* of the bounded summary to the judge.
`"semantic"` is `null` in the input when no audit has run.

`synthesize.synthesize` is unchanged in how it serializes its input dict (it just
`json.dumps` whatever it is passed), so the prompt sees the summary under
`stats.semantic`.

### 3. Sectioned output schema

Replace the single `prose` string with labelled sections plus a one-line verdict:

```json
{
  "verdict": "<one-line overall diversity-health call>",
  "sections": [
    {"title": "Categorical balance & coverage", "body": "<paragraph(s)>"},
    {"title": "Correlations (sycophancy tell)", "body": "…"},
    {"title": "Combination gaps", "body": "…"},
    {"title": "Intent → realization drift", "body": "…"},
    {"title": "Semantic diversity", "body": "…"},
    {"title": "Response form", "body": "…"}
  ],
  "top_issues": [
    {"axis": "<field or pair>", "kind": "coverage|balance|correlation|combo|drift|semantic|structural",
     "severity": "high|medium|low", "detail": "…", "suggested_fix": "…"}
  ]
}
```

The prompt asks for **only the sections that have data** (skip a family whose stats
are absent/empty — e.g. no `Semantic diversity` section when `semantic` is null).
Each section reasons explicitly about that graph's signal (hot cells in the
correlation matrix = sycophancy risk; empty cells in the coverage grid = missing
designed combinations; low Vendi / high near-dup rate / collapsed cluster spread =
meaning-space collapse; etc.). `top_issues` is unchanged in shape; its `kind`
vocabulary gains `semantic` and `structural`.

### 4. Validation, prompt, token budget

- `synthesize._shape_errors`: require `sections` to be a list of objects each with
  string `title` and `body`; `verdict` optional string; `top_issues` a list of
  objects (as today). On shape error, return the best-effort parsed fields plus the
  `errors` list (same fail-soft contract as today; `prose` key no longer produced).
- Return dict becomes `{"verdict", "sections", "top_issues", "raw", "errors"}`.
- Rewrite `prompts/tools/dad_holistic_synthesis.txt`: keep the single `{{STATS}}`
  token; document that `stats.semantic` may be present or `null` (reason only from
  categorical stats when null); instruct the sectioned output above; keep "reason
  only from these numbers; you do not see the raw conversations."
- `max_tokens` 4000 → 8000. `temperature` stays 0.0.

### 5. Viewer rendering (`viewer/ui_pages/run_diversity.py`)

Render, in order: the `verdict` as a short callout; the existing `top_issues` list
(unchanged); then each `section` as a small subheading + body. **Backward compat:**
if a report has the old `prose` string and no `sections`, render `prose` as before,
so pre-existing reports still display.

## Scale (thousands of examples)

- Synthesis input is entirely aggregate: categorical `stats` are bounded by
  vocabulary; the semantic summary drops both O(records) arrays. One LLM call per
  Analyze, ~constant input size at any corpus size.
- No new per-record work is introduced anywhere in this change.

## Testing

- `synthesize` tests: sectioned happy-path (verdict + sections + issues parsed);
  malformed output → empty fields + `errors`; missing-token template raises.
- `pipeline.run` test: with a semantic report present, the synthesis input includes
  `semantic` and that summary **omits `projection` and `clusters.assignments`**;
  with no audit, `semantic` is `null`. (Drive through `run` with `stub_claude`
  capturing the prompt text handed to the model, asserting on the serialized input.)
- Confirm `report["stats"]` remains free of a `semantic` key (no pollution).
- Full offline suite stays green.

## Out of scope

- Rendering charts to images / vision models (rejected: less precise than the
  numbers, needs a renderer, no better at scale).
- Per-graph multi-call synthesis (rejected: more calls; the single enriched call
  covers it).
- An overall numeric health score (not requested).
- Downsampling the diversity-map scatter at thousands of points — a real future
  concern, tracked separately, not part of this change.
