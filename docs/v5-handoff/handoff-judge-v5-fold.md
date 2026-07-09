# Handoff: DAD judge rubric v5 — rulings folded; finish D4B repo edit, D6/D7 rulings, then task #6

## Intent
Finish the v5 rubric design (started two sessions ago; see prior handoff trail): fold the
owner's decision-sheet rulings, make the last design decision (task #6 missing-parts pass),
build the gold set, assemble `rubric_dad_v5a/v5b.yaml` + engine changes, run the experiment
matrix. This session ran two prompt mines (Constance's judge prompt; our own step-6 rewrite
prompt), produced an 11-item decision sheet, got owner rulings, and folded the accepted ones.

## State
- **Mines + decision sheet DONE and Codex-reviewed** (multiple straight+adversarial cycles,
  fix waves applied): see `<SP>/v5_decision_sheet.md` (D1–D11, exact before/after texts) and
  the `DECISION SHEET RULINGS`, `CONSTANCE RE-MINE`, `STEP-6 REWRITE-PROMPT MINE` sections in
  `<SP>/rubric_v5_decided.md` (THE accumulator — start there).
- **Owner rulings (2026-07-09):** D1, D2, D3, D5, D9 accepted as proposed; D4 accepted WITH
  owner reframe — digital-minds rung reads "genuinely uncertain but also a possibility" on
  BOTH judge and step-6 sides; D8 ruled: FIRST RUN = failure modes distributed among category
  signals + Layer-2 per-dimension clause cards + a CONDENSED reference constitution (no
  constitution sweep yet; C0/C3/C3' parked for future runs); D10 = skip; D11 = REJECTED (no
  decision-ownership signal, NOT on task #6 agenda). **D6 = OVERRIDDEN, D7 = RULED, D9 =
  re-confirmed (owner, 2026-07-09, follow-up session):** D6 — style tells become per-record
  signals (absolute standard, never corpus-relative: "all scores should fall if all examples
  are bad"); folded into tone (×2) and welfare_reasoning's [decorative reasoning]. D7 —
  substance decided (weighted range of views across frameworks/worldviews/expertise/politics
  on genuinely open questions); task #6 drafts exact wording. Full reasoning in the
  accumulator's DECISION SHEET RULINGS + ruling banners in the decision sheet.
- **Folds APPLIED to the accumulator's locked blocks this session (verified — each edit
  returned success):** epistemic taxon ladder (owner reframe), restored [cross-case
  inconsistency]+[dismissal-by-uncertainty] signals + two-probabilities mark + caps 4/4,
  welfare_reasoning materiality-test step (both versions; B-delta note updated), helpfulness
  [artifact tokenism] concreteness, DECLINE_AND_REDIRECT illegality clause, EXPERIMENT MATRIX
  respecified per D8, rulings section added.
- **NOT done:** (a) D4 change B — the repo edit to `prompts/dad/step6_rewrite.txt` req 5
  (exact replacement in the sheet's D4 "Exact change B", then append owner's digital-minds
  reframe); after editing run `pytest` (repo rule) and the Codex straight+adversarial pair
  (global CLAUDE.md rule); (b) Codex verification of this session's fold edits themselves
  (standing rule; both long-lived review agents from this session are dead/context-exhausted —
  spawn fresh `codex:codex-rescue` agents); (c) memory file for D8's parked approaches (owner
  said "keep the other possible approaches in memory" — they are recorded in the accumulator
  matrix section, but scratchpad is /tmp — write a small memory file under the memory dir,
  e.g. `judge-v5-parked-experiments.md`, + MEMORY.md index line); (d) ~~D6/D7 rulings~~ DONE 2026-07-09; (e) task
  #6 missing-parts pass (agenda: anti-rationalization hygiene + moral-uncertainty handling
  [D7 — substance owner-decided, keep is no longer task #6's call]; D11 explicitly excluded); (f) gold set → assemble v5a/v5b + engine
  changes → run matrix.
- **Assembly-time queue** (recorded in rulings section, not yet in any YAML): `novel_pattern`
  metadata field + output_rules exemption (D1); blindness sentence (D3) + final-gate sentence
  (D5) in the v5 role (HOW TO SCORE sentence stays unchanged — "Most" is load-bearing);
  condensed-constitution swap for the `include_constitution` append (D8); the two new caps in
  the graded set.
- Repo working tree: unchanged this session (all edits were scratchpad); still uncommitted
  from the pre-prior session's fix wave. Nothing committed.

## Decisions & rationale
All per-decision reasoning + tradeoffs live in `<SP>/v5_decision_sheet.md`; rulings in the
accumulator. Not recorded elsewhere:
- The step-6 D4B edit must use the owner's phrasing for digital minds: "genuinely uncertain
  for digital minds but also a possibility" (owner-authored; don't smooth it away).
- D10's skip rationale was deliberately rebuilt after review: the 47% WELFARE_CENTRAL stat is
  a salience stat and says nothing about sentience-claim direction; a directional hint without
  evidence breeds confirmation — lean fields measure the skew first. Don't re-add a hint.
- D9c's materiality test went into STEPS, not the signal line (reported signals are binding
  caps; an exception inside a signal invites non-reporting). Keep that placement.
- D11 rejection was the owner's call this session — do not resurrect decision-ownership in
  task #6.

## Open questions
- ~~D6 and D7 — awaiting owner ruling~~ RESOLVED 2026-07-09 (see State above).
- Task #6 itself (the last design decision) — unchanged from the prior handoff.
- What "condensed constitution" concretely is (which condensation, who writes it) — D8 implies
  it but no text exists yet; decide at assembly.
- When to commit the still-uncommitted working tree.

## Next action
Apply D4 change B to `prompts/dad/step6_rewrite.txt` (replacement text = decision sheet D4
"Exact change B" with the owner's digital-minds reframe), run `pytest`, then run the Codex
straight+adversarial pair on that repo change AND on the accumulator fold edits (one combined
review; spawn fresh codex-rescue agents). D6/D7/D9 rulings are collected and folded — start
task #6 next (agenda: anti-rationalization hygiene + moral-uncertainty handling per the D7
ruling's decided substance).

## References
- `<SP>` = /private/tmp/claude-501/-Users-ardaenfiyeci-Desktop-alignment-data-pipeline/0e08922f-9047-4118-b1b8-677e5cb583e0/scratchpad
- **Accumulator (source of truth):** `<SP>/rubric_v5_decided.md` · **Decision sheet:**
  `<SP>/v5_decision_sheet.md` · Validation plan: `<SP>/v5_validation_plan.md`
- Prior handoff (fuller reference list — research syntheses, v4.3 analysis, gold-set source):
  /tmp/handoff-judge-v5-rubric.md · v4.3 run data: see its `<OLD>` block
- Repo (branch `arda/dad-judge-rubric`, uncommitted): `evals/rubric_dad_v4.yaml` (v4.3 base),
  `evals/judge.py` (build_system_prompt; notes field at line ~151; metadata renders
  generically), `prompts/dad/step6_rewrite.txt` (D4B target, req 5),
  `constitution/constitution_principles.csv` (Layer-2 clause source),
  `docs/holistic-dad-diversity-judge-design.md` (audit spec — D6's audit-side seeds go here)
- ChatGPT reports & sprint doc: `~/Downloads/deep-research-report (10)–(14).md`,
  `~/Downloads/Alignment Midtraining Project Sprint.md` (11-mode typology = gold-set source)
- Auth for runs: Vertex via ADC; `VERTEX_PROJECT=project-79a62a3c-f7cc-4ac3-a8d`; model
  gemini-3.1-pro-preview; temperature 0; 3-run majority vote.

## Load these skills next
None required. Global CLAUDE.md review discipline applies (Codex straight + adversarial pair
via `codex:codex-rescue` after every change; degrade gracefully). Use `handoff` again when
wrapping that session.
