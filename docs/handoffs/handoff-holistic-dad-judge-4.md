# Handoff: Holistic DAD judge phase 4 — program COMPLETE (§12.2 + §18.1 + reviews); next: viewer axes editor + SDF lane

## Intent
Same program as phases 1–3 (`docs/handoffs/handoff-holistic-dad-judge-{1,2,3}.md`).
This phase finished it: §12.2 viewer, §18.1 embedding analyzers, the final Codex
pair, plus an unplanned addition — Gemini provider dispatch for the eval lane.
New goal from the user (deferred to next phase): let people **edit the extraction
axes easily from the viewer** ("add stuff for the judge to look at in their ideal
JSON format") with analysis following automatically, as **two sections: one DAD,
one SDF** (SDF has no axes lane at all yet — spec §18 forward pointer).

## State
Everything built, TDD'd (RED-verified first), Codex-pair-reviewed, and green:
**490 passed** (~2s), byte-compile clean. ALL UNCOMMITTED — committing stayed
opt-in; user was mid-testing via the viewer at handoff time.

- **§12.2 viewer**: pure loaders in `viewer/loader.py` (`category_records`,
  `holistic_report`, `combined_index`, `facet_options`, `verdict_status`);
  `judge_batch.py` migrated to `evals/selection.py` (new `selection_rows` seam;
  injection + prev-verdict + axes all one `where`; "error" radio option); new
  `viewer/ui_pages/run_diversity.py` page (registered in `app.py`) with visible
  Tag/Analyze descriptions. Verified live in the browser (facet narrowing 4→1,
  full report render, zero console errors).
- **§18.1**: `evals/diversity.py` gained seeded numpy k-means (`kmeans_labels`),
  `cluster_evenness` (CAML topic-spread; `--clusters`, default 50 capped at n),
  and a `clusters` section (per-id assignments) in `diversity_report.json`.
  Holistic side: 4th gated input `clusters` (loaded by `resolve_inputs`,
  malformed report degrades to WARNING+None at every nesting level), new
  `cluster_bridge` analyzer (per-axis Cramér's V vs clusters; LOW V = label-only
  diversity; multi axes count per occurrence via `_axis_values`).
- **Provider dispatch**: new `shared/providers.py` owns `call_model` (moved from
  `judge.py`, which re-exports it): `gemini-*` → Gemini (AI Studio or Vertex,
  cost-logged), everything else incl. None → `api.call_claude`. Extraction +
  synthesis route through it; `holistic_dad.py --model gemini-*` and the
  run_diversity model input work Gemini-only. PROVEN with a real call: 1 record
  of `outputs/dad/runs/2026-07-06_18-16_naturalness-smoke` is genuinely tagged
  via Vertex ($0.0016 in the cost log) — that index row is real data, resume
  skips it.
- **Reviews**: two full Codex pairs this session (phase-3 scope, then providers),
  both "safe to commit" / zero Critical+Important after fix waves; every
  accepted finding fixed test-first. Spec bumped to rev 5.

## Decisions & rationale
- **`shared/providers.py` placement chosen for merge-safety**: user's constraint
  was "no merge headache" — `evals/judge.py` does NOT exist on main, so a new
  file + edits confined to branch-only files = zero conflict surface;
  `shared/api.py` (merge-sensitive) deliberately untouched. Rejected: dispatch
  inside `shared/api.py` (blast radius), holistic importing `evals.judge`
  (wrong dependency direction).
- **Eval-lane only** (user): generation pipelines stay Claude-only (provenance).
  `audit_sdf.py`'s pattern scan still calls Anthropic directly — README says so.
- Three deliberate adaptations in the moved dispatch: model=None → Anthropic;
  empty systemInstruction omitted; error string says "Gemini models" not
  "Gemini judges" (audience widened; nothing pinned the old string).
- **Spec-driven `.annotation` intent labels are NOT facets** in `combined_index`
  (spec §12.1: realized tags only); annotations contribute only legacy
  `injection_used`.
- **Bridge framing**: inverse of `correlation` — LOW V is the problem
  (higher_better verdict, provisional 0.3/0.15). n counts occurrences for
  multi axes (like `_distribution`).
- Retry-exhaustion tests deliberately skipped: tenacity's 4–60s sleeps can't
  live in the 2s suite (endpoint selection + body shape pinned instead).
- This session's adjudicated WON'T-FIXes (do not re-litigate): dup corpus ids
  collapsing cluster assignments (corpus-corruption class, matches phase-3
  --ids ruling; documented in `cluster_evenness` docstring); bool/int facet
  count collision (mixed types on one axis are schema-invalid); `prev_verdict`
  name collision (computed facet wins, documented in `selection_rows`).
- `.env.example` is hook-blocked for Claude — the user was given an append
  command for the optional-keys block; unknown whether they ran it.
- Codex tooling drama (all resolved, playbook in auto-memory
  `project_codex_cli_outdated.md`): gpt-5.6-luna server gate fixed by updating
  the ChatGPT desktop app; brew codex 0.144.0 then needed
  `/opt/homebrew/bin/codex-code-mode-host` — user symlinked it from
  ChatGPT.app/Contents/Resources (path is HARDCODED in codex; PATH tricks fail).

## Open questions
- The axes-editor feature is UNDESIGNED — user's words: edit fields "in their
  ideal JSON format", analysis follows, one section for DAD + one for SDF.
  Needs brainstorming: likely a viewer page editing `evals/dad_axes.yaml`
  (fields + targets + analysis block) with validation via
  `fields_mod.load_fields`, and an SDF lane from scratch (`sdf_axes.yaml`,
  extraction over SDF docs, SDF-appropriate axes — spec §18 forward pointer).
  SDF corpus records embed `content` not `messages`; extraction prompt renders
  conversations — needs a document-mode render.
- Phase-1 opens still stand (mockup quotas/thresholds; multi-value coverage
  denominators, spec §19).

## Next action
Wait for the user's verdict on their live test (viewer was running at
localhost:8501, run_diversity page). Then commit (+push if asked) — everything
is uncommitted. THEN brainstorm the axes-editor + SDF-section feature properly
(superpowers:brainstorming) before building.

## References
- Spec (source of truth, rev 5): `docs/holistic-dad-diversity-judge-design.md`
  — Implementation status has per-feature paragraphs incl. provider dispatch.
- Prior handoffs: `docs/handoffs/handoff-holistic-dad-judge-{1,2,3}.md`.
- New/changed this session: `shared/providers.py`, `viewer/loader.py`,
  `viewer/ui_pages/{judge_batch,run_diversity}.py`, `viewer/app.py`,
  `evals/{diversity,holistic_dad,judge}.py`, `evals/holistic/{analyzers,
  pipeline,extract,synthesize}.py`, `evals/dad_axes.yaml`, README ("Eval API
  keys"), CLAUDE.md setup line, requirements comments; tests:
  `tests/test_{providers,viewer_loader,judge_batch_selection}.py` (new) +
  appended in `tests/test_{diversity_eval,holistic_analyzers,holistic_pipeline,
  holistic_cli,holistic_extract,holistic_config}.py`.
- Branch: `arda/dad-judge-rubric` (origin has 38edf26; ~everything since is
  uncommitted working tree). Tests: `source .venv/bin/activate && python -m
  pytest` (offline, ~2s, 490).
- Viewer: `streamlit run viewer/app.py` (or `.claude/launch.json` "viewer").

## Load these skills next
- `superpowers:brainstorming` (the axes-editor feature is undesigned — design
  it with the user before coding)
- `superpowers:test-driven-development` (everything is built test-first)
- Standing rule: Codex review pair (straight + adversarial via
  `codex:codex-rescue`) after every change; adjudicate; one combined fix wave;
  re-review. Codex works again after the symlink fix.
