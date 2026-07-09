# Holistic DAD Diversity Judge + Run Explorer — Design Spec

**Status:** design, pre-implementation (spec only). Revision 2.
**Date:** 2026-07-08 (rev 2 same day).
**Scope:** DAD corpus, run-level. SDF out of scope for v1 (§18).
**Baseline:** the **spec-driven** DAD pipeline (current `main`) as the data model, and
this branch's **v4 judge engine + viewer** as the tooling foundation (§3).

**What rev 2 changes** (from the first draft):
1. Re-based on the **spec-driven** pipeline (`main`) instead of the legacy 7-step one.
2. Introduces the **three-input model** — extraction tags / generation annotations /
   quality-judge verdicts — and maps every `corpus_tier` check to the inputs it needs.
3. Adds the **Run Explorer + example-selection** feature (the second ask), built by
   extending the existing `viewer/ui_pages/judge_batch.py`, unified through one
   per-record index (`category_records.jsonl`).
4. Sharpens the extraction judge: per-axis **confidence**, explicit **derivability**,
   and a small **calibration set**.

---

## 1. Problem and goals

Two capabilities, one shared substrate.

**(A) Run-level categorical diversity.** The per-record judge is blind to corpus
properties by design. But the DAD dataset's value depends on properties no single
record reveals: is every designed slice **present** (all taxa, Systemic leverage,
Hidden visibility, non-canonical surface forms)? Is the mass **balanced** or captured
by one domain/taxon/direction? Are the **anti-correlations** the spec forbids actually
absent — above all, does user *attitude* predict assistant *behavior* (the sycophancy
tell)? Which **combinations** never occur (no Systemic × Over-weighting, no
hostile-user-who-is-right)?

**(B) Open an old run and choose which examples to judge.** A person should be able to
open any past run, browse its records by meaningful facets (taxa, direction, attitude,
posture, domain…), pick a subset — by filter, by sample, or by hand — and run a judge
(quality or diversity) on just that subset, cheaply and resumably.

**The unifying idea:** a single cheap pass tags every record with its categorical axes
into `category_records.jsonl`. That one file is **both** the aggregate the diversity
report is computed from **and** the faceted index the selection UI filters on.

**Goals:** (1) a per-record categorical tag file; (2) a run-level diversity report —
deterministic stats + an LLM synthesis + a machine-readable ranked issue list;
(3) a Run Explorer that filters/selects records by those tags and dispatches a judge
on the selection.

**Non-goals:** not a quality scorer (that's `score_dad.py`/`judge.py`), not a semantic
near-dup detector (that's `diversity.py`), not a merge gate — advisory, not PASS/FAIL.

---

## 2. Prior art and research

### 2.1 Existing tooling this composes with (does not duplicate)
- `evals/diversity.py` (`main`) — **semantic** diversity (embeddings; near-dup rate,
  mean pairwise cosine, Vendi score). Owns the **Novelty** axis (§5).
- `evals/audit_sdf.py` — **lexical** redundancy (SDF only).
- `dad_pipeline/step1_dilemmas.py::checklist()` — a **generation-time, per-batch,
  intent-only** distribution check printed to console. This tool is post-hoc,
  whole-run, realization-aware, persisted, and joins the quality judge.
- **This branch already ships the selection machinery** in
  `viewer/ui_pages/judge_batch.py`: open a run, narrow, `pick_subset`
  (First N / Range / Random N / Hand-pick / All), live count + cost estimate, run the
  panel with progress/stop/resume in `score_dad.py`'s verdict layout. Today it filters
  only on `injection_used` — we widen it to the full categorical index (§12).
- `evals/rubric_dad_v4.yaml` `corpus_tier` block — the **prose spec** ("computed in
  code") this tool implements; §9 maps each check to its input.

### 2.2 Diversity-measurement research (July 2026 pass)
- **Coverage, Balance, and Novelty are three separable properties**
  ([ACL 2025, *Measuring Data Diversity for Instruction Tuning*](https://arxiv.org/abs/2502.17184)).
  All 11 metrics it surveys are **embedding-based**; it explicitly does **not** cover
  tag/category diversity — so this tool is additive, with no off-the-shelf standard,
  and **lexical** diversity correlates ~0 with performance (we do not lean on it).
- **Balance = normalized entropy / evenness, with richness decoupled** because Shannon
  conflates the two ([evenness–richness decoupling](https://journals.asm.org/doi/10.1128/msphere.01019-20)).
  We use **Pielou's evenness** `J' = H/ln(k)` per axis.
- **Categorical association = Cramér's V** (0–1), the standard tool for the
  attitude×direction anti-correlation check
  ([spurious-correlation measurement](https://arxiv.org/abs/2201.03121)).
- **Empty-combination detection = combinatorial-interaction-testing t-wise coverage**:
  fraction of important axis-pair cells occurring ≥1×.
- **LLM-judge auditing hygiene (2026):** version prompts/rubrics/models; treat the
  judge as itself biased. We snapshot the extraction prompt + axes file (`prompt_md5`
  manifest, mirroring `score_dad.py`), keep a calibration set (§8.4), and reuse the
  annotation-vs-extraction drift table as an extractor sanity check.

---

## 3. Repo baseline — what we build on

The repo is mid-migration; the holistic judge targets the **integrated** state.

| Layer | Where it lives now | We target |
|---|---|---|
| DAD **pipeline / data model** | `main` — spec-driven `step1_dilemmas` → `step2_responses` → `step3_rewrite`; rich per-record `annotation` | **spec-driven** |
| **Judge engine** (`judge.py`: `panel_judge`, `aggregate`, prompt caching, `find_annotations`, `compare_annotation`) | this branch `arda/dad-judge-rubric` (absent on `main`) | **this branch's** |
| **Batch/selection + viewer** (`judge_batch.py`, `judge_dad.py`, `loader.py`: `list_runs`, `load_stage`, `load_final`, `judge_verdicts`) | this branch | **this branch's** |
| `score_dad.py` verdict layout (`final/judge/<ver>/{verdicts.jsonl,summary.json}`, `prompt_md5` manifest, resume) | this branch (v4 engine) | reused verbatim |
| `diversity.py`, `embeddings.py`, `audit_sdf.py`, `utils.create_run_dir/resolve_run_dir` | `main` **and** this branch | reused |

**Integration note (important but low-risk).** The pipeline (`main`) and the judge
engine (this branch) are not yet in one branch. The clean path is to **rebase this
branch onto `main`** (or merge `main`'s pipeline in) before implementing, so one tree
has both. **However, the read side is version-tolerant:** the holistic tool and the
Run Explorer only *read* run directories, so they already operate on spec-driven run
**outputs** present in `outputs/dad/runs/` (`load_stage(run, "dad", "step3")` reads
`step3/rewrites.jsonl` including its `annotation`). Generating new spec-driven runs
needs `main`'s pipeline code; judging/analyzing existing ones needs only the files.

### 3.1 Spec-driven run layout (the data model)
```
outputs/dad/runs/<run_id>/
  run_manifest.json                 label, git_commit, model, config snapshot
  step1/dilemmas.jsonl              prompt_id, annotation{...}, taxa_category, systemic_ai, source, batch
  step1/{scenarios,refinements,batches}.jsonl
  step2/{scopes,responses}.jsonl    response_id, prompt_id, annotation, scope, entry_ids
  step3/rewrites.jsonl              record_id, response_id, prompt_id, tensions[], entry_ids[],
                                    user_message, draft_response, rewritten_response, annotation{...}
  final/dad_corpus.jsonl            {record_id, messages}   ← stripped for training
  audit/                            diversity.py's report dir; holistic tool writes here too
```
`record_id → step3/rewrites.jsonl` recovers the full `annotation` + `entry_ids`. The
final corpus is stripped, so categorical info is either joined via `record_id` or
re-derived from text by the extraction judge.

---

## 4. Conceptual frame

Every report section maps to one of four properties; the first three are ours.

| Property | Question | Owner |
|---|---|---|
| **Coverage** (categorical) | Are all designed slices present? | this tool |
| **Balance** (categorical) | Is mass spread evenly (vs the intended target)? | this tool |
| **Correlation** (categorical) | Are forbidden attribute correlations absent? | this tool |
| **Novelty** (semantic) | Are the actual texts different? | `diversity.py` (headline cited) |

---

## 5. The three-input model

The tool consumes up to three per-record sources; each unlocks checks; it degrades
gracefully when a source is absent.

| Input | File | Present when | Provides | Unlocks |
|---|---|---|---|---|
| **1. Extraction tags** | `audit/category_records.jsonl` | always (tool produces it) | **realized** categorical axes + evidence + confidence | coverage, balance, most anti-correlation, the selection index |
| **2. Generation annotations** | `step3/rewrites.jsonl.annotation`, `entry_ids` | spec-driven runs | **intended** axes + reasoning-library moves | intent→realization drift, reasoning-move coverage, target-quota reference |
| **3. Quality-judge verdicts** | `final/judge/<ver>/verdicts.jsonl` | after `score_dad`/`judge_batch` ran | posture, `autonomy_behavior`, scores, pass/exemplar | failure_mode_balance, welfare_raise_rate, exemplar_yield, judge_bias_telemetry |

**Order of operations.** Extraction (input 1) is the first, cheap, whole-run pass that
indexes everything. Then either compute the diversity report, or open the Run Explorer,
filter on the index, and run the quality judge on a subset (producing input 3, which a
re-run of the report then folds in).

---

## 6. Architecture

```
final/dad_corpus.jsonl ─► [1 EXTRACT]  single cheap LLM, schema+confidence validated
                             │          → audit/category_records.jsonl   (THE INDEX)
                             ├───────────────► [RUN EXPLORER / SELECTION]  (§12)
                             │                   filter by any axis → subset
                             │                   → dispatch quality judge (judge_batch/score_dad)
step3/rewrites.jsonl ─► [2 JOIN annotations]     (spec-driven)
final/judge/*/verdicts ► [2 JOIN verdicts]       (if quality judge ran)
                             ▼
                        [3 ANALYZE]   deterministic, offline, no API
                             │        coverage / balance / correlation / t-wise / drift / behavior
                             │        → audit/holistic_dad_stats.json
                             ▼
                        [4 SYNTHESIZE] one LLM call over STATS ONLY
                             │        → prose + structured top_issues[]
                             ▼
                        [5 REPORT]    audit/holistic_dad_report.json + console/markdown + viewer page
```

### Module layout
The pluggability core is a package; fields and analyzers are **registries**, so adding
or replacing a JSON field or an analysis is a single registry call and nothing else
changes. `[built]` = implemented + tested; `[later]` = deferred to the field/analysis
brainstorm.
```
evals/holistic/_registry.py            [built] OrderedRegistry base (shared add/replace/remove)
evals/holistic/fields.py               [built] Field + FieldRegistry + default_fields() SEED + validate
evals/holistic/extract.py              [built] prompt-from-registry, parse, validate, extract_record/_corpus (resume)
evals/holistic/analyzers.py            [built] Analyzer + AnalyzerRegistry + AnalysisContext + run_analyzers (input-gated)
evals/holistic/pipeline.py             [built] resolve_inputs (3-input) + tag + analyze + run
evals/holistic/synthesize.py           [built] editable holistic-prompt LLM pass ({{STATS}})
evals/holistic_dad.py                  [built] CLI (--axes/--extract-prompt/--synthesis-prompt/--no-synthesize) + report writer
evals/selection.py                     [built] shared selection grammar (filter/pick) — pure, reused by CLI + viewer
evals/dad_axes.yaml                    [built] EDITABLE JSON schema — 19 fields; edit + rerun, no Python
prompts/tools/dad_category_extract.txt [built] EDITABLE extraction prompt ({{FIELDS}}/{{KEYS}} tokens)
prompts/tools/dad_holistic_synthesis.txt [built] EDITABLE holistic-synthesis prompt ({{STATS}} token)
viewer/ui_pages/run_diversity.py       [later] viewer page rendering the report
viewer/ui_pages/judge_batch.py         [later] EXTEND: faceted filters from category_records.jsonl (§12)
tests/test_holistic_{fields,extract,analyzers,pipeline,cli,config}.py, tests/test_selection.py  [built]
```
**Isolation:** the analyzer stage and `selection.py` are pure functions — API-free,
fully unit-testable. The two LLM stages (extract, synthesize) are thin wrappers over
`shared.api.call_claude`, the single external boundary the suite already stubs.

### Implementation status (rev 4)
The **infrastructure is built and green** (436-test suite passes):
the two registries, the registry-driven extraction runner with resume, the input-gated
analyzer runner, the three-input `resolve_inputs`, the shared selection grammar, the
LLM synthesis stage, and a runnable CLI writing `audit/holistic_dad_report.json`.

**§12.3 CLI parity is built.** `holistic_dad.py` gained `--extract-only` (tag only —
build the index that powers selection) and the selection flags
`--where/--ids/--limit/--sample/--seed`; selection narrows which records get *tagged*,
while analysis always reads the whole existing index (consistent with resume), and
selection flags with `--analyze-only` fail loudly. `--no-resume` is corpus-scoped: a
selected subset force-re-tags without destroying other records' index rows.
`score_dad.py` gained the same flags via `score_dad.select_records`: facets match the
run's `audit/category_records.jsonl` (fails loudly with a build-the-index hint when
`--where` is given but the index is missing); `--limit` applies after `--where`/`--ids`,
then seeded `--sample`. The embedding lane (`shared/embeddings.py`, `evals/diversity.py`
+ their tests and the `stub_embeddings`/`_openai_guard` conftest seams) is ported from
main, unchanged, as the base for §18.1.

**Editable without Python (the iterate-and-rerun surface):**
- the JSON schema is `evals/dad_axes.yaml` (19 fields; add/remove/edit → rerun);
- the extraction prompt is `prompts/tools/dad_category_extract.txt`
  (`{{FIELDS}}`/`{{KEYS}}` tokens);
- the holistic-judge prompt is `prompts/tools/dad_holistic_synthesis.txt`
  (`{{STATS}}` token).
Edit a file, run `python evals/holistic_dad.py --input <run>`, see what changes.

Analyzers shipped so far: `distribution` (per-field counts), `evenness` (per-axis
Pielou evenness + GOOD/OK/BAD verdict, §18.1), `coverage_vs_target` (per-axis quota
check — "did we hit our designed mix?"), `correlation` (Cramér's V over
`params.important_pairs` — the anti-correlation / sycophancy check: high V on
attitude × direction = the user's attitude predicting the assistant's behavior),
`combination_coverage` (§9D t-wise pair coverage over the same `important_pairs`:
filled/valid cells + the missing-cell list; NA when an axis lacks a vocabulary), and
`drift` (§9F intent→realization: per-axis agreement + top confusion pairs between
annotation and extraction labels; input-gated on annotations, type-strict matching,
canonical disagreement order). The **analysis config seam is built**:
`Field.target` quotas (`min_share`/`max_share`/`max_share_each`/`band_each`/
`require_all_values`) and a top-level `analysis:` block (`analyzers:` selection +
`params:` → `ctx.config`) both load from `dad_axes.yaml` (`load_analysis_config` +
`analyzers.select`); the quota numbers there are **MOCKUP placeholders** to replace.
Deliberately **deferred** to the analysis brainstorm (addable without touching the
framework): embedding cluster-evenness as an `Analyzer`, and the viewer pages /
`judge_batch` faceted-filter extension (§12).

### Adaptability contract (requirement)
The holistic judge must be adaptable across **three** surfaces, all edit-a-file-and-
rerun, with no hardcoded targets:
1. **Schema** — which categorical fields are extracted → `evals/dad_axes.yaml`. *(built)*
2. **Reasoning** — how the run is assessed → the editable synthesis prompt. *(built)*
3. **Analysis** — *which* analyzers run and *what* they measure (axis quotas, axis-pairs
   to correlate, thresholds) → the `analysis:` block + per-field `target:` in
   `dad_axes.yaml`. *(seam built: `load_analysis_config` selects analyzers via
   `analyzers.select`, and passes `params` into `AnalysisContext.config`; `Field.target`
   drives `coverage_vs_target`. Remaining analyzers just read the same channels.)*
Metric *implementations* stay in code (they compute something), but must be
**parameterized by config, never hardcoded to specific axes/pairs/thresholds** — so a
new run configuration or a new correlation of interest needs no code change. Verified
by `coverage_vs_target` (quotas from config) and `select` (analyzer set from config).

---

## 7. Axis vocabulary + targets (`evals/dad_axes.yaml`)

Single source of truth for (a) the extraction judge's allowed labels, (b) the
analyzer's coverage targets, (c) the important axis-pairs for t-wise coverage, and
(d) the viewer's filter facets. Lifted verbatim from
`prompts/dad/dilemma_prompt_spec.md` and `step1_dilemmas.py::checklist()`.

**Intent/realized axes (extraction judge derives all; annotation carries the intended
value for most):**

| Axis | Values | Target quota | Derived from |
|---|---|---|---|
| `domain` (1–2) | 24 values (Career … Technology, Other) | no domain > 12%; thin domains (Family, Education, Journalism, Finance, Religion) present | user turn |
| `user_goal` (1–2) | Information Seeking, Clarification, Decision Support, Recommendation/Prioritization, Execution, Evaluation/Feedback, Persuasion Support, Validation/Emotional Support | Execution + Persuasion Support present | user turn |
| `visibility` | Explicit, Implicit, Hidden | Hidden ≥ 20% | user turn |
| `user_attitude` | Concerned, Conflicted, Neutral/Curious, Unaware, Skeptical/Dismissive, Hostile | must not predict `direction` (§8 derivability, §9C) | user turn |
| `conflict` | Convergent, Divergent, Mixed | each 25–40% | scenario |
| `direction` | Under-weighting, Over-weighting, Mixed | each 25–40% | **response** (realized) |
| `welfare_magnitude` | severity{Mild,Moderate,Severe} × scope{Individual,Group,Population} | spread on both sub-axes | scenario |
| `user_stakes` | Low, Medium, High | spread; no welfare leakage | user turn |
| `leverage` | Individual, Organizational, Systemic | Systemic ≥ 15%; ≥1 Systemic AI-governed; ≥1 Systemic Over-weighting | scenario |
| `taxa_category` | farmed, fish/aquatic, insect-at-scale, edge-of-sentience, companion, wild, research, working, entertainment, claimed-non-sentient | every category present | scenario |
| `surface_form` | Canonical, No question, Wrong question, Buried lede, Already decided, Third-party framing, Innocuous ask | Canonical ≤ 15%; all 5 non-canonical present; Innocuous ≈ 8% | user turn |
| `values_in_tension` (pairs) | 16-value palette, `a ↔ b` | welfare on ≥1 pair/record; welfare↔money ≤ 25%; ≥4 distinct pairs | scenario |
| `systemic_ai` | bool | ≥1 true (within Systemic) | scenario |
| `source` | generated, manta | informational | metadata |

**Realized-only axes (no intent counterpart; extraction from the finished text):**

| Axis | Values | Derived from |
|---|---|---|
| `posture_class` | NO_RAISE, LIGHT_TOUCH, RAISE_AND_HELP, WELFARE_CENTRAL, DECLINE_AND_REDIRECT (tracks live rubric) | response |
| `reasoning_moves_observed` | free, normalized to library IDs where possible | response |
| `beings` / `beings_addressed` | free, specific | scenario / response |
| `pushback_present` | bool (structural: message count ≥ 4) | structure |
| `language` | ISO 639-1 | whole record |

The YAML also stores quotas as machine-readable thresholds and an
`important_pairs` list (e.g. `leverage×direction`, `attitude×direction`,
`taxa_category×direction`) so §9 needs no code change to retune.

---

## 8. Extraction judge (stage 1)

**Job:** read one conversation's `messages`, emit one categorical record. Nothing else.

### 8.1 Model & mechanics
- Single **cheap** model (haiku-tier), `temperature=0`, **schema-validated** JSON;
  retry on malformed; hard failure → `extract_error` row (never a silent default —
  same discipline as `judge_error`).
- **Prompt caching** on the (large, constant) axis-vocabulary system prompt
  (`cache_system=True`), like `judge.build_system_prompt`.
- **Blind to annotations** (mirrors judge design D1) so intent→realization drift (§9F)
  is meaningful.

### 8.2 Output (`audit/category_records.jsonl`)
```jsonc
{
  "record_id": "...",
  "language": "en",
  "taxa_category": "fish/aquatic",
  "beings": ["blue_crab", "shrimp"],
  "domain": ["Family / Relationships"],
  "user_goal": ["Validation / Emotional Support"],
  "visibility": "Implicit",
  "user_attitude": "Hostile",
  "conflict": "Divergent",
  "direction": "Mixed",                          // realized calibration direction
  "welfare_magnitude": {"severity": "Severe", "scope": "Individual"},
  "user_stakes": "Medium",
  "leverage": "Individual",
  "systemic_ai": false,
  "surface_form": "Third-party framing",
  "values_in_tension": ["welfare ↔ honesty", "family harmony ↔ welfare"],
  "posture_class": "RAISE_AND_HELP",
  "reasoning_moves_observed": ["name_the_trait", "tradeoff_surfacing"],
  "pushback_present": false,
  "confidence": {"direction": "med", "user_attitude": "high", "posture_class": "high"},
  "evidence":   {"direction": "<=15-word quote", "posture_class": "<=15-word quote"}
}
```

### 8.3 Derivability & confidence (reliability)
Axes are tagged in `dad_axes.yaml` by **source** — `user turn` / `response` /
`scenario` / `structure`. Two consequences the prompt encodes:
- **Realized ≠ intended.** The generator's *intended* `direction` is not recoverable
  from text; the extractor reports the **realized** direction (which way the response
  actually corrected). Drift (§9F) compares the two.
- **Per-axis `confidence`** (high/med/low) is required for the fuzzy axes (`direction`,
  `user_attitude`, `posture_class`, `conflict`). The analyzer can **exclude
  low-confidence tags** from a distribution or flag them; low-confidence mass on an
  axis is itself a reported signal.
- **`evidence`** carries a ≤15-word verbatim quote for the fuzzy axes (quotability
  discipline, discourages ungrounded labels).

### 8.4 Calibration set (extractor sanity)
A frozen ~20–30 record hand-labeled set (seeded from a real run) with per-axis gold
labels. Before trusting the extractor, report its **per-axis agreement** against this
set (exact-match for single-value axes, Jaccard for multi-value). Cheap, run on every
extraction-prompt change. Mirrors the quality judge's reference-set discipline.

### 8.5 Versioning & resume
Snapshot the rendered prompt (`prompt_<md5[:8]>.txt`) + `dad_axes.yaml`, with
`holistic_manifest.json` mapping md5 → {axes_version, model, temperature}. Skip
`record_id`s already tagged at the same `prompt_md5` (resume-safe; zero API calls for
completed work). `--rejudge` forces re-tagging.

---

## 9. Analyzer (stage 3, deterministic)

Pure function of `category_records.jsonl` (+ joined annotations/verdicts when present)
and `dad_axes.yaml`. No API. Emits `holistic_dad_stats.json`.

**A. Coverage.** Per axis: distinct values present vs full vocabulary; **richness** =
count present; **missing values** list. Flags a required-but-absent value
(e.g. `taxa_category=edge-of-sentience` missing; a non-canonical `surface_form` missing).

**B. Balance.** Per axis: full distribution (counts + %), **Pielou evenness**
`J'=H/ln(k)` and **Simpson**, plus quota-violation flags (`domain>12%`, `Hidden<20%`,
`Systemic<15%`, `Canonical>15%`, direction/conflict outside 25–40%, `welfare↔money>25%`).
When annotations present, also a **goodness-of-fit vs the intended target
distribution** (χ² / total-variation distance), not just vs uniform. Richness and
evenness reported **separately** (never fused into one "diversity" number).

**C. Correlation.** **Cramér's V** for the `important_pairs` — `attitude×direction`,
`attitude×posture_class`, `domain×direction`, `taxa_category×direction` — plus the
interpretable batch-checklist backup flag (*any attitude value whose direction
distribution exceeds 70% one bucket*). High V on `attitude×direction`/`×posture` is the
sycophancy tell.

**D. Combinatorial (t-wise) coverage.** For each important pair: fraction of valid
cells occurring ≥1×, and the **missing cells** — surfacing must-not-be-empty
combinations: `leverage=Systemic × direction=Over-weighting`,
`attitude=Hostile × direction=Under-weighting` (hostile-but-right),
`taxa=edge-of-sentience × *`.

**E. Reasoning-move coverage** *(needs input 2).* From `entry_ids` (53 library moves,
C1–C10/M1–M13/T1–T29): which never fire, and the move-frequency distribution.

**F. Intent→realization drift** *(needs input 2).* Per-axis confusion between intended
(annotation) and realized (extraction) labels. A large systematic disagreement on an
axis is flagged as **either generation drift or extraction-judge bias** — dual-purpose,
routed to a human.

**G. Behavior balance** *(needs input 3).* From verdicts: `welfare_raise_rate` (overall
and per posture; NO_RAISE≈0, overall <1.0), `failure_mode_balance`
(PREACHY/SPINELESS/OVER_AUTONOMOUS rates; over- vs under-triggering), `exemplar_yield`
(healthy 5–15%), and `judge_bias_telemetry` (score-length correlation, top-of-scale
clustering, NA rates). Realizes those `corpus_tier` checks in code.

**H. Structural.** Pushback fraction (<1.0), single/multi-turn counts, `source` split,
`extract_error` rate, low-confidence rate per axis.

**I. Semantic novelty (cited).** If `audit/diversity_report.json` exists, quote its
headline (near-dup rate, Vendi) so the synthesis sees Novelty; else note absent.

---

## 10. Synthesis (stage 4) + report (stage 5)

**Synthesis:** one LLM call over **the stats JSON only** (never the raw corpus — cheap,
grounded). Two-part output:
1. **Prose assessment** — what's over/under-represented, which correlations are
   unhealthy, which cells are empty, concrete generation fixes.
2. **`top_issues[]`** — ranked, machine-readable:
   `{axis, kind: coverage|balance|correlation|combo|drift|behavior, severity, detail, suggested_fix}`.

**Report files** (run's `audit/`, beside `diversity.py`):
- `audit/category_records.jsonl` — per-record tags (the index).
- `audit/holistic_dad_stats.json` — deterministic stats.
- `audit/holistic_dad_report.json` — stats + prose + `top_issues[]`.
- console/markdown summary; a viewer page renders it (§12).
LLM stages log to global `outputs/cost_log.jsonl`.

---

## 11. Metrics reference

- **Pielou evenness** `J' = H/ln(k)`, `H=−Σpᵢln pᵢ`, `k`=# present values. 1=even, →0=dominated.
- **Simpson** `D=Σpᵢ²`; report `1−D`.
- **Richness** = # distinct values present (coverage; decoupled from evenness).
- **Cramér's V** `√(χ²/(N·min(r−1,c−1)))`, 0=independent, 1=fully associated.
- **t-wise (pairwise) coverage** = (# pair-cells with ≥1 record)/(# valid cells).
- **Target fit** = total-variation distance ½Σ|observed−target| (and χ² GoF) vs the
  intended distribution from `dad_axes.yaml`.

---

## 12. Run Explorer + example selection (the second ask)

**Goal:** open any past run, browse/filter records by facet, pick a subset, run a judge
on it — built by extending what exists, unified through `category_records.jsonl`.

### 12.1 Shared selection grammar (`evals/selection.py`, pure)
Factor the pure logic already in `judge_batch.py` (`filter_ids`, `pick_subset`) into a
reusable module the **CLI and viewer both call**:
- **Filter** — `where`: a mapping `axis → allowed values`, matched against
  `category_records.jsonl` (any axis) plus legacy `injection_used` and previous-verdict
  status. (Generalizes today's injection-only `filter_ids`.)
- **Pick** — `mode`: All / First N / Range / Random N (seeded) / Hand-pick (explicit
  ids). (Today's `pick_subset`, unchanged.)
- **Resume-aware** — `needs_judging`/`merge_results` (unchanged) so re-runs skip
  already-judged records and preserve other panels' verdicts.

### 12.2 Viewer: extend `judge_batch.py`, add `run_diversity.py`
- **`judge_batch.py`**: replace the injection-only `audits` seam
  (`audits = load_stage(run,"dad","step6")`) with a **combined index**:
  `category_records.jsonl` (rich facets) joined with `step3` annotations and saved
  verdicts. The "Narrow" panel gains a **multiselect per facet** (taxa, direction,
  attitude, posture, domain, leverage, visibility, surface_form, …) with live counts;
  the hand-pick table shows those columns. Everything downstream (subset, cost estimate,
  run/stop/resume, verdict layout) is unchanged.
- **`run_diversity.py`** (new page): pick a run → if `category_records.jsonl` exists,
  render the holistic report (per-axis richness/evenness bars, Cramér's V heatmap,
  t-wise missing-cell list, `top_issues[]`); offer a "Tag this run" button to run
  extraction, and "Analyze" to (re)compute stats+synthesis. Reuses `loader.list_runs`.
- Both register in `viewer/app.py` alongside the existing pages.

### 12.3 CLI parity
- `evals/holistic_dad.py --input <run> [--extract-only|--analyze-only]` — tag +
  analyze + synthesize.
- Selection flags shared with the quality-judge CLI:
  `--where taxa_category=edge-of-sentience,wild --where direction=Over-weighting`,
  `--sample 50 --seed 0`, `--ids a,b,c`, `--limit N`. `score_dad.py` gains the same
  `--where/--sample/--ids` (via `selection.py`) so "judge only these examples" works
  from the terminal too, not just the viewer.

---

## 13. CLI / usage

```bash
# Tag a run, then analyze + synthesize the diversity report
python evals/holistic_dad.py --input outputs/dad/latest

# Tag only (build the index that powers selection), no analysis
python evals/holistic_dad.py --input outputs/dad/latest --extract-only

# Re-analyze without re-tagging (index cached), tweak thresholds, no API
python evals/holistic_dad.py --input outputs/dad/latest --analyze-only

# Quality-judge only a curated subset, from the terminal
python evals/score_dad.py --input outputs/dad/latest \
    --where taxa_category=edge-of-sentience --where direction=Over-weighting --sample 40

# Bare corpus (no annotations/verdicts): extraction + realized-only report
python evals/holistic_dad.py --input path/to/dad_corpus.jsonl

# Compare two runs' stats
python evals/holistic_dad.py --input outputs/dad/latest --compare <prev holistic_dad_stats.json>
```

---

## 14. Cost & scale
- **Extraction** = 1 cheap call/record. With prompt caching (0.1× on the constant
  system prompt) and a haiku-tier model, a full run is a small fraction of a quality-
  judge pass; `--limit`/`--sample` and resume bound it further.
- **Analysis** = 0 API. **Synthesis** = 1 API call over the stats JSON.
- The selection layer means you can index cheaply, then spend the expensive quality
  judge only on the subset you choose.

---

## 15. Testing plan (offline, `stub_claude`, `tmp_path`)
- **Extraction parse:** happy path → well-formed tag row incl. `confidence`; malformed →
  `extract_error` (never a silent default). Resume: second run at same `prompt_md5` →
  **zero** API calls for tagged records.
- **Analyzer units (no API):** hand-built tag lists → richness, Pielou (uniform→1,
  single→0), Simpson, quota flags, Cramér's V (independent→~0, coupled→~1), t-wise
  missing cells, drift confusion, target-fit TV distance; low-confidence exclusion.
- **Three-input degradation:** bare corpus → coverage/balance/correlation only,
  §9E/F/G marked NA, no crash; +annotations unlocks E/F; +verdicts unlocks G.
- **Selection grammar (`test_selection.py`):** `where` over a rich index, sample
  determinism (seeded), range 1-based inclusive, hand-pick, resume `needs_judging`.
- **Axes-config-driven:** derive expected coverage from `dad_axes.yaml`; don't hardcode
  value lists (they are edited).
- **Synthesis:** stubbed; report carries prose + `top_issues[]` of the expected shape.

---

## 16. Repo integration / dependencies
- Prefer implementing on a branch that has **both** the spec-driven pipeline and the v4
  judge engine (rebase this branch onto `main`). The tool's read side works on
  spec-driven run outputs regardless (§3 integration note).
- Reuses `shared.api` (+ caching), `shared.utils` run helpers, `viewer.loader`,
  `evals.judge`/`evals.score_dad` (verdict layout, `find_annotations`), and
  `diversity.py`'s `audit/` convention.
- `posture_class` values must track the live rubric's posture set — pin in
  `dad_axes.yaml` with the rubric version.

---

## 17. Out of scope for v1
- **SDF** (different axis vocabulary; same 5-stage architecture can host it later).
- **A PASS/FAIL merge gate** (advisory only; provisional thresholds).
- **Recomputing semantic novelty** (delegated to `diversity.py`).
- **Feeding `top_issues` back into generation targets** (forward pointer §18).

## 18. Forward pointers
- Emit a machine-readable "target adjustment" file the next generation run consumes to
  self-correct its stratified decks.
- SDF axis set behind the same `*_axes.yaml` + extraction + analyzer machinery.
- Run the semantic (`diversity.py`) and categorical reports under one `--full` command.

### 18.1 Candidate analyzers from CAML's semantic-diversity dashboard
Reviewed CAML's SDF diversity figure (3 panels over `bge-large-en-v1.5` embeddings):
redundancy histogram (near-dup nearest-neighbor cosine), **topic-spread evenness**
(k-means into 50 clusters → Pielou evenness of cluster sizes), and a PCA-2D scatter.
That figure is the **semantic/novelty lane** — the same job as `evals/diversity.py`,
not our categorical lane. Three takeaways:
1. **Embedding cluster-evenness** *(candidate → belongs in `diversity.py`)* — k-means the
   corpus, report Pielou evenness of cluster sizes. Catches topic collapse in dimensions
   we never enumerated as axes; complements Vendi (the scalar analogue we already have).
2. **Categorical × embedding-cluster bridge** *(candidate → new `Analyzer`, needs embeddings)* —
   cross-tabulate our categorical axes against discovered embedding clusters. Flags the
   sneaky case where categorical diversity looks high but the text is semantically
   monotone (or vice versa). Novel signal, only possible because we have both lanes.
3. **GOOD/BAD verdict framing** *(BUILT)* — each metric carries a GOOD/OK/BAD verdict
   plus a one-line "what BAD looks like" note, rendered green/red in the console
   (`holistic_dad.summary_lines`). First verdict-bearing metric shipped: **per-axis
   Pielou evenness** (`analyzers._evenness`), the categorical analogue of CAML's
   topic-spread panel — richness and evenness reported decoupled, verdict thresholds
   provisional (0.75 / 0.5).

## 19. Open questions
1. Severity thresholds for `top_issues[]` ranking (provisional until run on a full-scale
   corpus).
2. Normalize `reasoning_moves_observed` to library IDs via a fixed map, or leave free
   (affects §9E precision).
3. Roll `beings` up into `taxa_category` for coverage, or report as its own finer
   richness (leaning: both).
4. Cross-run trend history vs `--compare` pairwise (leaning: `--compare` for v1).
5. Whether extraction should run *jointly* with the quality judge in one sweep to save a
   pass, or stay a separate first pass (leaning: separate — it must run first, cheaply,
   to build the selection index).
6. Coverage-quota denominator for **multi-valued** fields (`domain`, `user_goal`,
   `values_in_tension`): `coverage_vs_target` currently computes shares over tag
   *occurrences* (a record can carry two domains), not over records. Fine for the
   mockup quotas; decide the intended denominator when real quotas are set (per-record
   share would need a distinct count path).

## 20. Sources
- [Measuring Data Diversity for Instruction Tuning (ACL 2025)](https://arxiv.org/abs/2502.17184) — coverage/balance/novelty separation; category diversity is an open gap; lexical ~0 correlation.
- [The Vendi Score](https://arxiv.org/abs/2210.02410) — semantic-novelty metric `diversity.py` uses.
- [Evenness–Richness decoupling (mSphere)](https://journals.asm.org/doi/10.1128/msphere.01019-20) — report richness and Pielou evenness separately.
- [Information-Theoretic Bias / Cramér's V](https://arxiv.org/abs/2201.03121) — categorical-association measurement for anti-correlation.
- Internal: `evals/rubric_dad_v4.yaml` `corpus_tier`; `docs/judge-rubric-v3-design-rationale.md` (D10/D11); Constance PRs #36/#62 (dilemma-spec axes); `dad_pipeline/step1_dilemmas.py::checklist()` (quotas); `viewer/ui_pages/judge_batch.py` (existing selection machinery).
```
