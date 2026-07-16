# Handoff: implement the provenance-bundles spec (P1 of the axes-editor phase)

## Intent
Phase 5 of the holistic-DAD-judge program (prior: `docs/handoffs/handoff-holistic-dad-judge-{1,2,3,4}.md`).
Phase-4 ended with the axes-editor feature undesigned; this session brainstormed it
with the user and split it into two separately-specced sub-projects:
**P1 provenance bundles** (spec WRITTEN, user-approved — implement it now) and
**P2 viewer axes editor + SDF filler section** (spec NOT yet written — after P1).
Done for this handoff's scope = P1 implemented per spec, tests green, Codex-pair
reviewed.

## State
- `docs/holistic-provenance-bundles-design.md` — the P1 spec, complete, incl. a
  required "In-page explanations" section (visible captions next to every
  bundle-facing control, same pattern as the live-verified Tag/Analyze captions).
  User reviewed the design summary and moved straight to implementation — treat
  the spec as approved.
- NOTHING implemented yet. No plan doc yet either — write it first.
- The whole branch working tree (phase-4 work + this spec) is UNCOMMITTED;
  committing stays opt-in (user says "commit" explicitly). Phase-4 viewer test
  verdict: user was satisfied enough to move on, but never said "commit".
- Suite baseline: 490 passed, ~2s, offline (`source .venv/bin/activate &&
  python -m pytest`).

## Decisions & rationale
Brainstorm outcomes (user-chosen, do not re-litigate):
- **Bundles are fingerprint-keyed, automatic** — chosen over label-keyed (risk of
  resuming a stale label after an axes edit → mixed tags) and always-new (loses
  crash resume, re-tagging costs real money).
- **Fingerprint = fields + model + extract prompt ONLY**; `analysis:` block +
  synth prompt excluded so quota/analyzer tweaks re-Analyze in place instead of
  forcing a paid re-tag. Flagged to the user as overridable; not overruled.
- **Back-compat via implicit read-only `legacy` bundle** over a migration script.
- **No human label on bundle dirs** (`<ts>_<fp8>`); readability from the manifest.
- **In-page explanations are acceptance criteria, not polish** — user explicitly
  asked for "how they work near them at the website as instructions for people".
- For P2 (capture now, spec later): editing model = **hybrid** (field list →
  per-field form + raw escape hatch); save target = **one canonical
  `evals/dad_axes.yaml`, comments preserved via ruamel.yaml** (plain yaml.dump
  rejected — nukes the documented header; run-local copies rejected — diverges
  from the CLI's single-file model); **SDF section is filler text only** for now
  (user: "SDF is not done yet much so that can have filler text now").
- User approval of "Keep every run as a bundle" came bundled with an implicit nod
  to save-target A; I offered a chance to overrule, none came.

## Open questions
- None for P1 (the spec's two opens have stated defaults). P2's spec remains to
  be written after P1 lands.

## Next action
Invoke `superpowers:writing-plans` on `docs/holistic-provenance-bundles-design.md`
to produce the implementation plan, then execute it via
`superpowers:subagent-driven-development` (user's explicit choice of execution
mode).

## References
- P1 spec (source of truth): `docs/holistic-provenance-bundles-design.md`
- Key seams it touches: `evals/holistic/pipeline.py` (resolve_inputs/tag/run,
  `Inputs.index_path`), `evals/holistic_dad.py` (CLI, `report_path_for`),
  `viewer/loader.py:108-149` (`category_records`/`holistic_report`/
  `combined_index`), `viewer/ui_pages/run_diversity.py` (captions pattern at
  b1/b2), `viewer/ui_pages/judge_batch.py` + `evals/selection.py` (facet source).
- Fields/registry: `evals/holistic/fields.py` (`load_fields`, `Field` dataclass —
  fingerprint canonicalization builds on it). Axes file: `evals/dad_axes.yaml`.
- Program spec (rev 5): `docs/holistic-dad-diversity-judge-design.md`.
- Branch `arda/dad-judge-rubric`; testing rules in CLAUDE.md (offline suite,
  stub_claude, money-path coverage — bundles are exactly a money path).
- Viewer: `streamlit run viewer/app.py` (was live at localhost:8501).

## Load these skills next
- `superpowers:writing-plans` (first thing)
- `superpowers:subagent-driven-development` (execution mode, per user)
- `superpowers:test-driven-development` (everything in this repo is built RED-first)
- Standing rule: Codex review pair (straight + adversarial via `codex:codex-rescue`)
  after the implementation; adjudicate; one combined fix wave; re-review.
