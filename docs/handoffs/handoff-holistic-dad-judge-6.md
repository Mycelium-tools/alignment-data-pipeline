# Handoff: P1 provenance bundles DONE — next is the P2 spec (viewer axes editor)

## Intent
Phase 6 of the holistic-DAD-judge program (prior: `docs/handoffs/handoff-holistic-dad-judge-{1,2,3,4,5}.md`).
Phase 5 split the axes-editor work into P1 (provenance bundles) and P2 (viewer
axes editor + SDF filler section). This session implemented P1 end to end.
Done for this handoff's scope = P2 spec written and user-approved, then
implemented via the same plan → subagent-driven → Codex-pair pipeline.

## State
- **P1 is complete and verified**: implemented per spec via
  superpowers:writing-plans + subagent-driven-development (8 tasks, each
  spec+quality reviewed), then final whole-branch review + Codex straight +
  Codex adversarial pair → adjudicated → one combined fix wave (7 fixes) →
  re-review **Approved**. Suite: **563 passed, ~2.7s, offline**. Both viewer
  pages verified rendering live (bundle picker, legacy entry, all required
  captions) against run `2026-07-06_18-16_naturalness-smoke`.
- **NOTHING is committed** — the whole branch working tree (phases 4–6) is
  uncommitted by standing rule; the user commits explicitly. SDD ran in
  no-commit mode (snapshot diffs instead of git ranges).
- Execution artifacts (ledger, briefs, reports, review diffs) are in
  `.superpowers/sdd/` — git-ignored scratch; treat as disposable.
- P2 is NOT specced. Its brainstorm decisions were captured in phase 5 (see
  handoff-5 "Decisions"): hybrid editing model (field list → per-field form +
  raw escape hatch), save to the one canonical `evals/dad_axes.yaml` with
  comments preserved via ruamel.yaml, SDF section is filler text only.

## Decisions & rationale
- **Two deliberate deviations from the P1 spec's literal fingerprint field
  list** (documented in the plan + code, surfaced to the user who moved on
  without objection — treat as accepted): `prompt_hint` IS identity (rendered
  into the extraction prompt; resuming across a hint edit would mix schemas);
  `target` is NOT identity (quota tweaks must re-Analyze, not force a paid
  re-tag). Tests pin both.
- **`evals/score_dad.py --where` was made bundle-aware beyond the spec** —
  without it, facet selection breaks permanently once tags live in bundles.
- **Review findings deliberately DEFERRED, not fixed** (user decisions;
  do not silently "fix" these):
  1. *Config-default-model fingerprint hole* (Codex adversarial, its one
     Critical): tagging without `--model` fingerprints the model as `""` (the
     spec's own canonicalization rule) while the effective model comes from
     `config.yaml` — changing the config default silently resumes old tags.
     Fix would be fingerprinting the resolved model = a spec change.
  2. *Concurrency*: bundle create / manifest RMW / `latest` swap are not
     atomic under simultaneous CLI+viewer tagging. Failures are loud, not
     corrupting, at single-user scale.
  3. *Legacy caption nuance*: Analyze on the legacy bundle still writes
     `audit/holistic_dad_report.json` (spec-documented; "read-only" applies to
     tags) — one reviewer felt the caption "stays untouched" undersells this.
- Codex adversarial claims verified FALSE and dropped: streamlit stale-widget
  crash (checked against installed streamlit 1.59 — degrades gracefully);
  sequential two-schema tag mixing (fingerprint prevents it, tested).
- Same-minute fp8 collision between different full fingerprints
  (~1 in 4.3B) now silently shares a dir instead of crashing (side effect of
  the crash-orphan `exist_ok` fix) — accepted, commented in `resolve_bundle`.

## Open questions
- The three deferred findings above — fix, spec-change, or accept? (#1 is the
  one worth a real decision before bundles accumulate.)
- Does the user want P1 committed before P2 starts? (Suggest yes — the branch
  now carries 3 phases of uncommitted work.)

## Next action
Ask the user to settle the two open questions, then write the P2 spec
(`docs/holistic-axes-editor-design.md` or similar) from handoff-5's captured
brainstorm decisions, and take it through the same pipeline:
superpowers:writing-plans → subagent-driven-development → Codex review pair.

## References
- P1 spec: `docs/holistic-provenance-bundles-design.md`
- P1 implementation plan (incl. Global Constraints + deviation notes):
  `docs/superpowers/plans/2026-07-09-provenance-bundles.md`
- P1 code: `evals/holistic/bundle.py` (new), `evals/holistic/pipeline.py`,
  `evals/holistic_dad.py`, `evals/score_dad.py`, `viewer/loader.py`,
  `viewer/ui_pages/run_diversity.py` (new file on branch),
  `viewer/ui_pages/judge_batch.py`; tests `tests/test_holistic_bundles.py`
  (new) + updated `test_holistic_{pipeline,cli}.py`,
  `test_score_dad_selection.py`, `test_viewer_loader.py`
- P2 brainstorm decisions: `docs/handoffs/handoff-holistic-dad-judge-5.md`
  ("Decisions & rationale", P2 bullet)
- Program spec (rev 5): `docs/holistic-dad-diversity-judge-design.md`
- Branch `arda/dad-judge-rubric`; suite: `source .venv/bin/activate && python -m pytest`
- Viewer: `streamlit run viewer/app.py` (port 8501; `.claude/launch.json` has a
  `viewer` config for preview tooling)

## Load these skills next
- `superpowers:brainstorming` (only if P2 scope questions surface beyond
  handoff-5's captured decisions; otherwise go straight to the spec)
- `superpowers:writing-plans` → `superpowers:subagent-driven-development`
  (user's standing execution mode; run it in NO-COMMIT mode — snapshot diffs,
  see the ledger convention in `.superpowers/sdd/progress.md`)
- `superpowers:test-driven-development` (everything here is built RED-first)
- Standing rule: Codex review pair (straight + adversarial via
  `codex:codex-rescue`) after implementation; adjudicate; one combined fix
  wave; re-review.
