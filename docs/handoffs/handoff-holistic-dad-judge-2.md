# Handoff: Holistic DAD judge — §12 selection layer + §18.1 embedding analyzers (phase 2)

## Intent
Continue the holistic categorical diversity judge (see the phase-1 handoff's intent:
pluggable, config-editable, complements `evals/diversity.py`'s semantic lane). This
phase: (a) §12 selection layer — CLI parity + viewer pages; (b) §18.1 embedding
analyzers. "Done" = spec §12.2/§12.3 + §18.1 items built, TDD'd, Codex-review-passed.

## State
All work uncommitted (user keeps commits opt-in). Suite: **421 passed** (~2s),
`python -m compileall -q evals` clean — verified at handoff time.

**DONE this session (all Codex-reviewed and fix-waved):**
1. `combination_coverage` (§9D t-wise) + `drift` (§9F) analyzers in
   `evals/holistic/analyzers.py`, registered in `default_analyzers()` and in
   `evals/dad_axes.yaml` `analysis.analyzers`; BAD-rendering in
   `holistic_dad.summary_lines`. Fully reviewed: 3 Codex passes (straight,
   adversarial, re-review), 5 findings fixed (non-string pair validation in
   `_pair_axes`; NA branch reports full missing grid; type-strict drift match —
   `True != 1`; canonical disagreement tie order incl. type names), 3 adjudicated
   won't-fix (`filled>n` for multi fields is correct per spec; None-record_id
   collision impossible via pipeline loader; no-vocab NA keeps `missing=[]`).
   Spec's "Implementation status" section updated to rev 3.
2. **Task #1 (embedding lane port) — done.** `git checkout origin/main --
   shared/embeddings.py evals/diversity.py tests/test_embeddings.py
   tests/test_diversity_eval.py` (staged, purely additive — none existed here).
   Ported ONLY `_openai_guard` (autouse) + `stub_embeddings` fixtures into
   `tests/conftest.py` (deliberately did NOT copy main's claude_code-backend
   guards or `dad_scenario_reply` — those belong to main's pipeline). Added
   `numpy` + `openai>=1.40` to requirements.txt; `pip install openai` done in
   `.venv`. All 42 ported tests pass.
3. **Task #2 (CLI selection) — grammar half done.** `evals/selection.py` gained
   `parse_where`, `parse_ids`, `apply_cli_selection` (pure; where matches a
   separate facet index when given, else the records; unindexed records drop;
   order-preserving; ids→limit→sample compose). 8 new tests in
   `tests/test_selection.py`, all green (RED verified first).

**NOT done (task #2 second half — the in-flight work):**
- Wire flags into `evals/holistic_dad.py`: `--where/--sample/--seed/--ids/--limit`
  + `--extract-only`. Design decided (see Decisions): selection subsets which
  records get TAGGED (pass a record_ids/subset param into `pipeline.run` → filter
  `inputs.corpus` after resolve); analysis stays whole-index. `--extract-only`
  = tag then skip analyze+synthesize (call `resolve_inputs`+`tag` directly in main).
- Wire into `evals/score_dad.py` (branch version, NOT main's): facet index =
  `<run>/audit/category_records.jsonl` (input is `final/dad_corpus.jsonl`, so
  `parent.parent/audit/...`); fail loudly if `--where` given but index missing
  ("run holistic_dad --extract-only first"). `--limit` already exists there;
  keep it, apply after where/ids. No tests exist for score_dad's main — test a
  small pure wiring helper instead.
- Tasks #3, #4, #5 (see task list): viewer §12.2, embedding analyzers §18.1,
  final Codex pair. Zero code written for these.

## Decisions & rationale
- **User chose: copy embedding lane from main now** (vs defer to rebase), with
  explicit caution "make sure we don't lose stuff we had on our branch — we've
  never merged with main". Verified additive: the 4 copied files didn't exist
  here; conftest was hand-merged, not overwritten. At the eventual rebase these
  files may add/add-conflict — resolve by keeping whichever has the §18.1
  cluster-evenness additions.
- Files deliberately NOT copied from main: `tests/test_pref_pipeline.py`,
  `tests/test_viewer_loader.py` (belong to main's spec-driven pipeline/viewer,
  would fail here).
- **Selection semantics decided:** CLI selection narrows which records are
  *processed* (tagged/judged); holistic *analysis* always reads the whole
  existing tag index (consistent with resume behavior). `--sample` and `--limit`
  compose after `--where`/`--ids`; sample is seed-deterministic, order-preserving.
- §18.1 split per spec: cluster-evenness (k-means → Pielou over cluster sizes)
  goes in `evals/diversity.py`; the categorical×cluster bridge is a new holistic
  `Analyzer` (input-gated; read cluster assignments from the diversity report,
  no API calls inside the analyzer). Task #4 description has details.
- Viewer plan (task #3): migrate `judge_batch.py`'s local `filter_ids`/
  `pick_subset` to `evals/selection.py`; combined index = category_records +
  step3/step6 annotations + saved verdicts; facet multiselects from
  `dad_axes.yaml` fields; new `viewer/ui_pages/run_diversity.py` renders the
  holistic report; register both in `viewer/app.py`. Keep streamlit thin, TDD
  the pure parts (only `tests/test_holistic_pipeline.py` currently touches
  viewer-adjacent code; no streamlit imports in tests).
- Codex agent quirks (from phase 1, still true): use the framing "run Codex NOW
  and put the FULL findings in your final message"; its pytest
  `No usable temporary directory` errors are its sandbox's TMPDIR issue, not our
  tests — ignore.

## Open questions
- None new. (Phase-1 opens still stand: mockup quotas/thresholds; multi-value
  denominators; user-side-only trimming.)

## Next action
Finish task #2's wiring, TDD: add failing tests in `tests/test_holistic_cli.py`
for `--extract-only` and `--limit/--sample/--ids/--where` on `holistic_dad.py`
(stub_claude counts calls = subset size), implement, then the score_dad wiring +
its pure-helper test. Then tasks #3 → #4 → #5 (Codex pair at the end; task list
is already in the session task store, ids #2–#5).

## References
- **Phase-1 handoff (read for full background):** `/tmp/handoff-holistic-dad-judge.md`
- **Spec (source of truth):** `docs/holistic-dad-diversity-judge-design.md` —
  §12.1–12.3 (selection/viewer), §18.1 (embedding candidates), §15 (testing plan),
  Implementation status (rev 3, updated this session).
- Code this session: `evals/holistic/analyzers.py`, `evals/holistic_dad.py`,
  `evals/selection.py`, `evals/dad_axes.yaml`, `tests/test_holistic_analyzers.py`,
  `tests/test_holistic_cli.py`, `tests/test_selection.py`, `tests/conftest.py`
  (embeddings fixtures), `requirements.txt`; staged-from-main:
  `shared/embeddings.py`, `evals/diversity.py`, `tests/test_{embeddings,diversity_eval}.py`.
- Viewer bases for task #3: `viewer/ui_pages/judge_batch.py` (its `filter_ids`/
  `pick_subset`/`audits` seam), `viewer/loader.py`, `viewer/app.py`.
- Branch `arda/dad-judge-rubric`; do not commit/push unless asked. Tests:
  `source .venv/bin/activate && python -m pytest` (offline, ~2s).
- Offline demo run dir (works with `--analyze-only --no-synthesize`):
  `/private/tmp/claude-501/-Users-ardaenfiyeci-Desktop-alignment-data-pipeline/dbd238bb-4536-4e6e-bbef-8747356a4b9c/scratchpad/2026-07-09_00-00_demo`
  (may be gone in a new session — trivially rebuildable, see phase-1 handoff).

## Load these skills next
- `superpowers:test-driven-development` (every piece is built test-first)
- Standing rule (user's CLAUDE.md): Codex review pair (`codex:codex-rescue`
  subagents, straight + adversarial) after every change; adjudicate; one combined
  fix wave; re-review.
