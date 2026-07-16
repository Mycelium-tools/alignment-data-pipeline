# Handoff: Holistic DAD judge phase 3 — §12.3 CLI parity DONE; viewer §12.2 + embeddings §18.1 next

## Intent
Same program as phases 1–2 (see `docs/handoffs/handoff-holistic-dad-judge-{1,2}.md`,
now in-repo so they travel): pluggable categorical diversity judge + selection layer.
This phase finished spec §12.3 (CLI selection parity). "Done" for the program =
§12.2 viewer pages + §18.1 embedding analyzers built, TDD'd, Codex-review-passed.

## State
Everything committed and pushed to `origin/arda/dad-judge-rubric` (user asked for a
cross-machine handoff — the usual commits-are-opt-in rule was explicitly lifted for
this push only, not in general). Verified at handoff: **445 passed** (~2s),
`python -m compileall -q evals` clean.

**DONE this session (phase-2 task #2, "CLI selection wiring") — fully reviewed:**
- `evals/holistic_dad.py`: `--extract-only` + `--where/--ids/--limit/--sample/--seed`.
  Selection narrows which records get **tagged**; analysis always reads the whole
  index; selection flags + `--analyze-only` → SystemExit; `--where` with a
  missing/empty index → SystemExit with a build-it hint.
- `evals/holistic/pipeline.py`: `resolve_inputs`/`run` accept a pre-resolved
  `Inputs` (passthrough) — main resolves ONCE (kills the `latest`-symlink race).
- `evals/holistic/extract.py`: `resume=False` is now **corpus-scoped** (drops prior
  rows only for record_ids in this corpus) so a `--where --no-resume` re-tag can't
  wipe the rest of the index. No test pinned the old truncate-all behavior.
- `evals/score_dad.py`: same flags via pure `select_records` (index at
  `<run>/audit/category_records.jsonl` OR sibling `<stem>.category_records.jsonl`
  for bare corpora; loud SystemExit when `--where` has no usable index);
  `drop_retryable_errors(rows, selected_ids)` scopes `--retry-errors` to the
  selection; `--limit`/`--sample` use `selection.nonneg_int`.
- `evals/selection.py`: `apply_cli_selection` samples **positions, not ids** (dup
  record_ids can't exceed N; same records chosen as before for unique corpora);
  new `nonneg_int` argparse type.
- ~24 new tests (all RED-verified first) across `tests/test_holistic_cli.py`,
  `tests/test_holistic_extract.py`, `tests/test_holistic_pipeline.py`,
  `tests/test_selection.py`, new `tests/test_score_dad_selection.py`.
- Spec "Implementation status" bumped to rev 4 (§12.3 built).

**Review trail (standing Codex rule, all done for this change):** straight +
adversarial pass, adjudicated, one combined fix wave, re-review pass. Re-review
found one Important (holistic path re-expanded positional samples via a record_id
round-trip) — fixed by passing the narrowed `Inputs.corpus` itself into
`pipeline.tag`/`run` and REMOVING the short-lived `record_ids` param from
`pipeline.run`. That last fix is green (445) but was **not itself Codex-re-reviewed**
(user asked to stop) — fold it into the final Codex pair.

**Adjudicated WON'T-FIX (do not re-litigate):**
- `--ids`/dup-corpus-ids re-expansion: duplicate record_ids are corpus corruption
  the pipeline can't produce; `--limit` is positional-exact already.
- `summary.json` covers every saved verdict row, not just the selection: that's the
  verdict file's accumulate-and-resume design; documented in score_dad's docstring.
- Dup record_id rows in the tag index (last-wins): writer maintains
  one-row-per-record invariant.
- `resume=False` keeping out-of-corpus `extract_error` rows: consistent with resume
  semantics; retried when that record is next tagged.
- Latent footgun (documented, accepted): `resolve_inputs(Inputs, judge_version=...)`
  ignores judge_version on passthrough — fine for all current callers.

**NOT started:** viewer §12.2, embeddings §18.1, final Codex pair (phase-2 tasks
#3/#4/#5 = this session's task-store #2/#3/#4; the task store does NOT persist
across sessions — recreate from here).

## Decisions & rationale
- **Selection passes subset ROWS, never record_id lists** — a record_id round-trip
  re-expands duplicates past `--sample N` (Codex re-review finding). Any future
  selection consumer should follow this pattern.
- `--limit 0` now selects zero records (old `if args.limit:` treated 0 as "no
  limit"). Deliberate.
- Viewer plan (from this session's code reading, for §12.2): `judge_batch.py`'s
  `filter_ids`/`pick_subset` migrate to `evals/selection.py` equivalents
  (`filter_records`/`pick_subset` already exist there); combined index =
  `category_records.jsonl` + step3/step6 annotations + saved verdicts; facet
  multiselects from `dad_axes.yaml` field names; pure parts (combined-index builder,
  loaders like `category_records(run_dir)`/`holistic_report(run_dir)`) go in
  `viewer/loader.py` (no streamlit) so they're testable; note `judge_batch` renders
  under `viewer/ui_pages/judge.py`'s "Score a run" segment — the new
  `run_diversity.py` page registers as its own `st.Page` in `viewer/app.py`.
- §18.1 plan detail discovered: `evals/diversity.py` does NOT currently write
  per-record cluster assignments — the cluster-evenness addition must add a clusters
  section (ids → cluster) to `diversity_report.json` for the categorical×cluster
  bridge analyzer to read (bridge = new input-gated holistic `Analyzer`, no API
  calls, reads the diversity report).
- Codex agent quirks (still true): use "run Codex NOW and put the FULL findings in
  your final message"; its pytest "No usable temporary directory" is its sandbox's
  TMPDIR, not our tests; it may flag untracked files as "odd" — they're expected.

## Open questions
None new. Phase-1 opens stand (mockup quotas/thresholds; multi-value denominators;
user-side-only trimming).

## Next action
Build viewer §12.2 (phase-2 task #3), TDD the pure parts first: failing tests for
`viewer/loader.py` additions + the combined-index/facet-options builders, then
migrate `judge_batch.py` to `evals/selection.py`, add `run_diversity.py`, register
in `app.py`. Then §18.1, then the final Codex pair over all phase-2/3 work
(including this session's last un-re-reviewed fix).

## References
- Spec (source of truth): `docs/holistic-dad-diversity-judge-design.md` — §12.2
  (viewer), §18.1 (embedding candidates), Implementation status (rev 4).
- Prior handoffs: `docs/handoffs/handoff-holistic-dad-judge-1.md` (architecture,
  branch reality, phase-1 decisions), `-2.md` (embedding-lane port, selection
  semantics).
- This session's code: `evals/{selection,holistic_dad,score_dad}.py`,
  `evals/holistic/{pipeline,extract}.py`, tests listed in State.
- Viewer bases: `viewer/ui_pages/judge_batch.py` (seams: `audits`, `filter_ids`,
  `pick_subset`), `viewer/loader.py`, `viewer/app.py`, `viewer/ui_pages/judge.py`.
- Embedding lane: `evals/diversity.py`, `shared/embeddings.py`, conftest's
  `stub_embeddings`/`_openai_guard`.
- Branch: `arda/dad-judge-rubric` @ origin. Tests:
  `source .venv/bin/activate && python -m pytest` (offline, ~2s).
- Committing remains opt-in after this handoff push.

## Load these skills next
- `superpowers:test-driven-development` (everything is built test-first)
- Standing rule (user's global CLAUDE.md): Codex review pair (straight +
  adversarial via `codex:codex-rescue`) after every change; adjudicate; one
  combined fix wave; re-review.
