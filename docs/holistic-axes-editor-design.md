# Viewer axes editor (P2 of the axes-editor phase)

Status: spec approved-pending-review · 2026-07-10
Prior: P1 provenance bundles (`docs/holistic-provenance-bundles-design.md`, implemented).
Program spec: `docs/holistic-dad-diversity-judge-design.md`.

## Problem

The diversity categories the holistic judge tags every DAD conversation with live in
`evals/dad_axes.yaml`. Editing them today means hand-editing YAML and rerunning a CLI —
fine for the author, a wall for everyone else. The biggest win of the holistic lane is
that *anyone* can add or reshape categories and the judge follows automatically (its
extraction prompt is rendered from the fields); the missing piece is an editing surface
that non-YAML users can operate safely.

## Solution overview

A new dedicated viewer page, **Edit axes**, registered in `viewer/app.py`'s
`st.navigation` (icon `:material/tune:`). It edits the one canonical
`evals/dad_axes.yaml` (no run-local copies — handoff-5 decision). Master–detail layout
(user-approved hi-fi mockup, 2026-07-10): axis list on the left, form for the selected
axis on the right, raw-YAML escape hatch below, one **Validate & Save** action.

The SDF half of the phase is **filler text only**: a collapsed "SDF axes" section at the
bottom of the page saying SDF axes aren't defined yet (user: "SDF is not done yet much").

## UI (per the approved mockup)

**Master list (left column)**
- One row per axis, in file order: `name` (code font) · kind · a dot when the axis has a
  `target:` quota. Clicking a row selects it into the form.
- **"+ Add axis"** primary button above the list: appends a new axis with defaults
  (`kind: single`, `derived_from: scenario`, `required: true`, empty values) and selects it.
- Caption under the list explaining what a row is and what the dot means.

**Detail form (right column)** — all seven `Field` attributes:
- `name` — text input (snake_case; caption: "becomes the key in each record's tag JSON").
- `kind` — selectbox over `single | multi | bool | free` with one-line explanations
  (`object` is loadable but not offered by the form; the raw hatch still allows it).
- `derived_from` — selectbox over `user_turn | response | scenario | structure | meta`,
  labelled "Judge reads from", with plain-language option descriptions.
- `required` — checkbox ("judge must always output it").
- `prompt_hint` — multi-line text area ("shown to the judge"; any length —
  it is interpolated as a block into the extraction prompt).
- `values` — chip editor: existing values as removable chips + an "add value" input.
  Hidden for `bool`/`free` kinds.
- **Quota editor** (`target:`) — rule selectbox: *none*, `require_all_values`,
  `min_share`, `max_share`, `max_share_each`, `band_each`; per-rule inputs
  (per-value share table for `min_share`/`max_share`, single number for
  `max_share_each`, lo/hi pair for `band_each`). Caption renders the rule back in plain
  English and notes quota edits are **free** (re-Analyze only, no re-tag).
- Header actions: move up / move down (reorder), delete (with confirm).

**Live cost note** — while the draft differs from the file on disk, an amber note states
which pending edits change the tag fingerprint ("next Tag starts a fresh bundle and
re-tags the corpus; old tags stay in their own bundle") vs. quota/analysis-only edits
("free — re-Analyze in place"). Computed by diffing `bundle.canonical_fields` of draft
vs. disk; reorders count as identity edits (fingerprint hashes registry order).

**Raw YAML escape hatch** — a collapsed expander holding the whole file text in a
text area. This is the only editing surface for the `analysis:` block (the mechanistic
analyzer selection + params) and for anything else the form doesn't cover. Applying it
parses the text and rebuilds the form draft; parse errors render inline and nothing is
applied.

**Validate & Save** — one button, one flow:
1. Validate the draft by constructing the `FieldRegistry` (reuses
   `Field.__post_init__` + `load_fields` semantics: kind/derived_from enums,
   `target` value-integrity, band shape). Errors render inline with the axis name;
   **nothing is written on any error**.
2. Show warnings (informative, never blocking — user decision "warn, don't block"):
   - fingerprint/cost note (as above),
   - renaming/deleting an axis referenced in `analysis.params.important_pairs`,
     with a one-click "update pairs too" fix,
   - renaming any of `posture_class` / `taxa_category` / `direction` (coupled by
     name to the quality-judge lane: `evals/judge.py`, `evals/judge_checklist.py`,
     `evals/report_dad.py`, `--where` facets),
   - renaming an axis whose name matches a generation-annotation key (silently drops
     it from the `drift` analyzer).
3. Write `evals/dad_axes.yaml` via ruamel.yaml (below), confirm with a link/pointer to
   *Run diversity* to re-Tag.

**In-page explanations are acceptance criteria, not polish** (carried over from P1):
every control gets a caption in the same voice as the Tag/Analyze captions.

## Comment preservation (ruamel.yaml)

The file's documented header and inline comments must survive editing
(handoff-5 decision; plain `yaml.dump` rejected). Mechanics:
- Load with `ruamel.yaml` round-trip mode; **mutate the loaded tree in place**
  (edit scalars, insert/delete/move list items) rather than rebuilding it, so comments
  stay attached to unedited nodes.
- Guarantee level: the header block, the `analysis:` block, and comments on unedited
  fields are preserved; an edited field keeps its comments where ruamel keeps them
  attached; a deleted field's comments go with it; new fields are written plain.
  Saving is **idempotent**: the first save may re-wrap long flow lists (one-time
  normalization — ruamel re-emits multi-line flow sequences), after which a no-op
  save is byte-identical (`dump(load(dump(load(x)))) == dump(load(x))`).
- `ruamel.yaml` is added to `requirements.txt`.

## Code shape

- **`evals/holistic/axes_io.py` (new)** — pure file/logic module, no streamlit, no API:
  - ruamel round-trip load / in-place edit ops (set attr, add/remove value,
    set/clear target, add/delete/move field) / dump;
  - `classify_change(disk_fields, draft_fields) -> "identity" | "quota_only" |
    "analysis_only" | "none"` via `bundle.canonical_fields` (a mixed edit classifies
    as `identity` — the re-tag dominates the cost either way);
  - coupling checks returning structured warnings: `important_pairs` references,
    reserved names (`posture_class`, `taxa_category`, `direction`), generation-key
    matches (drift joins by identical name — `analyzers.py` has no explicit list, so
    `axes_io` keeps a commented constant of the step-1 annotation keys: `domain,
    user_goal, visibility, user_attitude, conflict, direction, user_stakes, leverage,
    values_in_tension, taxa_category, systemic_ai`);
  - validation wrapper that runs `load_fields` semantics over the draft and maps
    failures back to an axis name.
- **`viewer/ui_pages/edit_axes.py` (new)** — the page. Thin: session-state draft,
  renders list + form from the draft, calls `axes_io` for everything. Registered in
  `viewer/app.py` after *Run diversity*.
- **`evals/holistic/fields.py`** — unchanged (validation is reused, not duplicated).

## Constraints the editor must respect (from the PR/lineage analysis)

- **Fingerprint identity** = (name, kind, values, derived_from, prompt_hint, required)
  per field, in order, + model + extract prompt (`evals/holistic/bundle.py:60-75`).
  Any such edit ⇒ new bundle ⇒ paid re-tag; `target:` and `analysis:` are excluded by
  design. The cost note must reflect exactly this split.
- **Quota↔values integrity**: a `target` share key naming a value not in `values` fails
  `load_fields` (`evals/holistic/fields.py:73-79`). The form keeps them in sync:
  removing a value drops it from the axis's quota (with a note), and the quota editor
  only offers current values.
- **`important_pairs` name coupling** (`evals/dad_axes.yaml` analysis block →
  `analyzers.py` correlation/combination): rename/delete must warn + offer auto-update.
- **Reserved-name renames warn, never block** (user decision): nothing crashes, but
  facet filters / drift / judge-lane joins silently de-link.
- **`multi` values are set-valued**: duplicates collapse silently — the chip editor
  rejects adding a duplicate outright.
- Old bundles are never touched by an axes edit (provenance snapshots stand alone).

## P2.1 additions (user-requested, 2026-07-10, after P2 landed)

- **Nav sections**: `viewer/app.py` groups pages into three `st.navigation`
  sections — *Runs* (Document lineage [default], Compare runs, Run list),
  *Judge* (Judge), *Diversity* (Run diversity, Edit axes).
- **Judge prompts editable on the Edit axes page** (overrides the original
  out-of-scope line): two expanders below the axes editor, one per prompt file —
  `prompts/tools/dad_category_extract.txt` (extraction judge; caption states the
  axes schema is rendered into it and that edits change the tag fingerprint →
  fresh bundle, paid re-tag) and `prompts/tools/dad_holistic_synthesis.txt`
  (report synthesis; caption states edits are free — re-Analyze only). Each:
  text_area seeded from disk (content-hash key so saves refresh it), a modified
  indicator, and a Save button using an atomic text write (`axes_io.save_text`,
  same temp+`os.replace` pattern as `save_doc`). Empty prompt text is rejected.
  **Required placeholders are enforced**: the extraction editor blocks saving
  (and shows a live error) when `{{FIELDS}}` or `{{KEYS}}` is missing, the
  synthesis editor when `{{STATS}}` is missing (tokens imported from
  `extract.FIELDS_TOKEN`/`KEYS_TOKEN` and `synthesize.STATS_TOKEN`, not
  hardcoded); a visible caption above each editor explains the placeholders
  are auto-filled at run time.
- **"How this works" explainer**: a collapsed expander at the top of the Edit
  axes page walking the flow in plain language: axes file → extraction judge
  prompt (rendered from the axes) → Tag → bundles (what's paid vs free, resume,
  never overwritten) → mechanistic analyzers + one synthesis call → report on
  *Run diversity* → the same tags power Judge → Score-a-run facet filters.

## Out of scope

- SDF axes (filler text only), multi-file axes profiles, undo/history (git is
  the history), concurrent-edit protection (accepted single-user stance from
  P1), an `object`-kind form editor.

## Testing

Offline, per repo rules; logic lives in `axes_io.py` so tests don't need streamlit.
`tests/test_axes_io.py`:
- round-trip: load → no-op dump is byte-identical (real `evals/dad_axes.yaml` as input);
- in-place edit preserves the header comment block and other fields' comments;
- add / delete / reorder fields reflected in dump and in `load_fields` output;
- validation failure (bad kind, quota naming a removed value) → structured error,
  no write;
- `classify_change`: identity edit vs quota-only vs analysis-only vs none —
  incl. reorder ⇒ identity;
- coupling warnings: rename of an `important_pairs` member, of a reserved name, of a
  generation-key match; the important_pairs auto-update fix.
- A smoke test that `viewer/app.py` still registers all pages (import-level), matching
  existing viewer-test style.

## How to verify (manual)

1. `streamlit run viewer/app.py` → *Edit axes* page renders with the real axes.
2. Edit `direction`'s prompt hint → amber cost note appears; Save; `git diff
   evals/dad_axes.yaml` shows only that line changed, comments intact.
3. Add a new axis with two values and a `min_share` quota → Save → *Run diversity* →
   Tag a small run → the new axis appears in the bundle's tags and report.
4. Rename `taxa_category` → reserved-name warning lists the coupled files; Save still
   allowed.
5. Raw YAML: edit the `analysis:` block (drop an analyzer) → Save → Analyze reruns
   without that analyzer; cost note says "free".
