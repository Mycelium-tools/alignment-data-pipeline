# Handoff: Holistic DAD Diversity Judge (categorical) — pluggable analyzer suite

## Intent
Build a run-level **categorical** diversity judge for the DAD corpus: tag every
conversation with categorical axes (taxa, direction, attitude, leverage…), then
analyze whether the run hit its designed *coverage / balance / correlation*. "Done"
= a pluggable, config-editable tool where anyone can change the JSON schema, the
prompts, and which analyses run **by editing files, not Python**, and rerun. It
complements (does not duplicate) `evals/diversity.py`, which owns the *semantic*
(embedding) lane. Full design lives in the spec — read it first (see References).

## State
Infrastructure + first analyzers **built, TDD'd, green: 356 tests pass, compiles under
the CI command** (`python -m compileall -q evals`). Everything is **untracked /
uncommitted** (user keeps commits opt-in).

Built and verified:
- Pluggable core in `evals/holistic/`: `Field`+`FieldRegistry` (fields.py),
  `Analyzer`+`AnalyzerRegistry`+`AnalysisContext`+input-gated `run_analyzers`
  (analyzers.py), extraction runner with resume (extract.py), synthesis stage
  (synthesize.py), orchestrator `resolve_inputs`/`tag`/`analyze`/`run` (pipeline.py),
  shared `OrderedRegistry` (_registry.py).
- Shared pure selection grammar `evals/selection.py` (filter/pick).
- CLI `evals/holistic_dad.py` → writes `<run>/audit/holistic_dad_report.json` + a
  GOOD/OK/BAD console summary (`summary_lines`).
- Editable files: `evals/dad_axes.yaml` (19-field schema + per-field `target:` quotas +
  a top-level `analysis:` block), `prompts/tools/dad_category_extract.txt`,
  `prompts/tools/dad_holistic_synthesis.txt`.
- Analyzers registered in `default_analyzers()`: `distribution`, `evenness` (Pielou),
  `coverage_vs_target` (quota flags), `correlation` (Cramér's V / sycophancy check).
  All config-driven; all live-verified offline.

NOT started (this is the next work): `combination_coverage` (t-wise) and `drift`
analyzers — I marked a chapter "Analysis suite: t-wise + drift" but wrote **zero**
code before the handoff. Also not started: the selection UI / viewer pages, and
embedding cluster-evenness.

Unverified/assumed: the tool has only ever run on *synthetic* offline indexes (hand-
built `category_records.jsonl`), never a real API extraction pass or a real DAD run.

## Decisions & rationale
- **Separate cheap extraction judge**, NOT folded into the quality judge (`score_dad`)
  — user chose this to keep diversity decoupled from the delicate, mid-calibration
  quality judge. The extraction tags file (`audit/category_records.jsonl`) doubles as
  the index for the (future) selection UI.
- **Three-input model** (extraction tags / generation annotations / quality-judge
  verdicts); analyzers declare `requires=(...)` and are gated on what's present.
- **Frame = Coverage / Balance / Correlation / Novelty.** First three are ours;
  **Novelty is delegated to `evals/diversity.py`** (semantic/embeddings) — do NOT
  rebuild it here. The CAML dashboard the user shared is that semantic lane.
- **Adaptability is a hard requirement**: 3 edit-a-file surfaces (schema, prompts,
  analysis selection+params). Metric code may compute in Python but must read
  targets/pairs/thresholds from config, **never hardcode them**.
- **`dad_axes.yaml` quota numbers are MOCKUP placeholders** — user explicitly said make
  a mockup config to replace later. Don't treat them as real targets.
- **Config location = inside `dad_axes.yaml`** (user picked "2-A"): per-field `target:` +
  a top-level `analysis:` block. Not a separate file.
- **Verdict vocab aligned to `evals/diversity.py`**: GOOD/OK/BAD, `_verdict(value, good,
  ok, higher_better=False)` — deliberately matched for merge-ease.
- **"Don't extract each message"** (user): diversity is mostly about the *user-side
  dilemma*, not the assistant response. Each field is tagged `derived_from`
  (user_turn/response/scenario/…) so trimming to user-side-only is a 1-line filter.
  Deferred, not done. (Note: tagging is already per-*conversation*, one record each —
  never per-message.)
- **Branch reality (important):** `origin/main` has the **spec-driven** pipeline
  (`step1_dilemmas`→`step3_rewrite`, rich per-record `annotation`) but **no judge
  engine**. THIS branch (`arda/dad-judge-rubric`) has the **legacy 7-step** pipeline +
  the v4 judge engine + viewer (`judge_batch.py`, `loader.py`). Neither branch has
  both. The holistic tool only *reads* run dirs, so it works on spec-driven run
  **outputs** already; eventual clean merge = rebase this branch onto `main`. Design
  targets the spec-driven data model.
- **Selection feature already ~exists**: `viewer/ui_pages/judge_batch.py` does "open a
  run → narrow → pick subset (First N/Range/Random N/Hand-pick) → judge with resume",
  but filters only on `injection_used`. Plan (spec §12) is to widen its `audits` seam
  to the full `category_records.jsonl` index. Not built.
- **Codex agent is flaky**: sometimes returns "forwarding-only" without findings; the
  framing "run Codex NOW and put the FULL findings in your final message" works. Its
  pytest `No usable temporary directory` error is a TMPDIR env issue on Codex's side,
  NOT our tests — ignore it.
- **One file-truncation incident** occurred (an external write truncated
  `analyzers.py` mid-edit). Was caught via a parse check and repaired. If a file looks
  truncated, `python3 -c "import ast; ast.parse(open(F).read())"` and repair the tail.

## Open questions
- Multi-valued fields (`domain`, `user_goal`, `values_in_tension`): `coverage_vs_target`
  computes shares over tag *occurrences*, not records. Fine for mockup; decide the real
  denominator when real quotas are set. (Spec §19.6.)
- All verdict thresholds (evenness 0.75/0.5; coverage; Cramér's V 0.2/0.4) are
  provisional placeholders.
- Whether to trim extraction to user-side axes only (see decision above).
- Real target quotas + real `important_pairs` — to be designed together, later.

## Next action
Implement the **`combination_coverage` (t-wise) analyzer** per spec §9D/§11: for each
`config.important_pairs`, fraction of valid axis-pair cells (cartesian product of the
two fields' `values`) that occur ≥1×, plus the missing-cell list and a GOOD/OK/BAD
verdict; NA when either axis lacks a vocabulary. Register it in `default_analyzers()`,
add it to `dad_axes.yaml` `analysis.analyzers`, render BAD cells in `summary_lines`.
TDD (write failing tests in `tests/test_holistic_analyzers.py` first). Then do the same
for `drift` (spec §9F, `requires=("tags","annotations")`). Run the Codex review gate
after (subagent, `codex:codex-rescue`, inline-findings framing).

## References
- **Spec (read first — the source of truth):**
  `docs/holistic-dad-diversity-judge-design.md`. Key sections: §5 three-input model,
  §9 analyzer list (9D t-wise, 9F drift), §11 formulas, §12 selection/run-explorer,
  §18.1 CAML candidates (embedding cluster-evenness, categorical×cluster bridge),
  §19 open questions, Adaptability contract, Implementation status.
- **Code (all untracked):** `evals/holistic/{_registry,fields,extract,analyzers,
  pipeline,synthesize}.py`, `evals/holistic_dad.py`, `evals/selection.py`,
  `evals/dad_axes.yaml`, `prompts/tools/dad_category_extract.txt`,
  `prompts/tools/dad_holistic_synthesis.txt`.
- **Tests (all untracked):** `tests/test_holistic_{fields,extract,analyzers,pipeline,
  cli,config}.py`, `tests/test_selection.py`.
- **Style reference for merge:** `git show origin/main:evals/diversity.py` (`_verdict`,
  `resolve_input`, `audit/` output, argparse idioms). No linter; CI = byte-compile +
  pytest.
- **Selection feature base:** `viewer/ui_pages/judge_batch.py`, `viewer/loader.py`.
- **Branch:** `arda/dad-judge-rubric` (do not push/commit unless user asks). Run tests
  with `.venv` active: `source .venv/bin/activate && python3 -m pytest -q`.
- Live offline demos used in-session build a tiny run dir with a hand-written
  `audit/category_records.jsonl`, then `python evals/holistic_dad.py --input <dir>
  --analyze-only --no-synthesize`.

## Load these skills next
- `superpowers:test-driven-development` (every analyzer is built test-first)
- Standing rule (user's CLAUDE.md): run the Codex review pair (`codex:codex-rescue`,
  straight + adversarial) after every change; one combined fix wave; re-review.
