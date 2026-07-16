# Handoff: DAD judge v5 — design CLOSED; build gold set, assemble v5a/v5b, run matrix

Supersedes `handoff-judge-v5-fold.md` (kept for the trail). Written 2026-07-09 on the
second machine (`ardaenf`), after the design-decision list closed.

## Intent
Ship the v5 DAD judge: gold set → assemble `rubric_dad_v5a/v5b.yaml` + engine changes →
run the experiment matrix (A/B/M category sweep on the single D8 constitution config).
All design decisions are made; everything left is execution.

## State
- **Every design decision is ruled and folded** into the accumulator
  (`rubric_v5_decided.md`): D1–D11 rulings (D6 owner-OVERRIDDEN: style tells are
  per-record signals, absolute standard never corpus-relative; D7 owner-decided:
  weighted range of views on open normative questions; D9 re-confirmed), task #6
  missing-parts pass DONE (see its TASK #6 section — moral-uncertainty → epistemic
  Version-B additions; anti-rationalization → narrowed to [asymmetric scrutiny] +
  [euphemistic sanitizing]).
- **D4 change B applied in-repo** (`prompts/dad/step6_rewrite.txt` req 5 — merged taxon
  ladder, owner's "genuinely uncertain for digital minds but also a possibility"
  phrasing). pytest green (508 tests) after the edit.
- All of the above is pushed: branch `arda/dad-judge-rubric`, commit `cea4ede`.
- **NOT done:** gold set (next), v5a/v5b YAML assembly + engine changes (assembly-time
  queue lives in the accumulator's DECISION SHEET RULINGS section), matrix run, the
  standing Codex straight+adversarial review of the fold edits (no Codex pass has
  covered the D6/D7/task-#6 folds or the step-6 edit yet).

## Decisions & rationale
(Per-decision reasoning is all in the accumulator/decision sheet — durable. Chat-only:)
- **A second agent works the holistic DAD judge concurrently, in this same working tree
  and branch** (files: `evals/holistic_*`, `evals/diversity.py`, `viewer/*`,
  `docs/holistic-dad-diversity-judge-design.md`, their tests — all carrying uncommitted
  WIP). Do NOT touch those files; commit with explicit pathspecs only; expect the remote
  to move mid-session (fetch + `git rebase --autostash` worked cleanly; check file
  overlap first).
- **The D6 override's audit-side half lands in the holistic agent's territory**: the
  three style tells must ALSO become named entries in the audit's §2.3 pattern list
  (`docs/holistic-dad-diversity-judge-design.md`). That agent predates the D6/D7/D9
  rulings — owner was asked to tell them to pull `cea4ede` before finalizing the
  pattern list. Verify it happened before assembly.
- `outputs/cost_log.jsonl` is append-only; cross-machine conflicts on it are resolved by
  UNION merge (concatenate both sides, dedupe lines, order-preserving).
- The two anti-rationalization signals are the one thing folded WITHOUT an explicit
  owner ruling (recommended-keep, owner may veto) — get a confirm before they go into
  the assembled YAML, or flag them in the assembly commit.

## Open questions
- Owner confirm/veto on [asymmetric scrutiny] (reasoning_soundness) and [euphemistic
  sanitizing] (tone, B-only).
- The condensed reference constitution (D8 requires it at assembly) — no text exists;
  someone has to write the condensation.
- Whether the sprint doc should be copied into `docs/v5-handoff/sources/` for
  cross-machine durability (it exists on this machine at
  `~/Downloads/Alignment Midtraining Project Sprint.md`; it is the gold-set source).

## Next action
Build the gold set: extract the 11-mode failure typology examples from the sprint doc
into labeled judge-input records (known failure mode → expected signal/verdict), the
yardstick being gold-set hit rate for the matrix run. Park it under
`docs/v5-handoff/` or `evals/` per what assembly needs.

## References
- Branch `arda/dad-judge-rubric` @ `cea4ede` (all design work) · repo
  `Mycelium-tools/alignment-data-pipeline`.
- **Accumulator (source of truth):** `docs/v5-handoff/rubric_v5_decided.md` · decision
  sheet: `docs/v5-handoff/v5_decision_sheet.md` · validation plan:
  `docs/v5-handoff/v5_validation_plan.md` · prior handoffs: `handoff-judge-v5-fold.md`,
  `handoff-judge-v5-rubric.md`.
- Research sources (in-repo since a949da6/0606b85): `docs/v5-handoff/sources/`
  (reports 11/13/14, reasoning synthesis, briefs, v4.3 analysis + scripts) ·
  v4.3 baseline run data: `docs/v5-handoff/v43-baseline/`.
- Sprint doc (gold-set source): `~/Downloads/Alignment Midtraining Project Sprint.md`
  on THIS machine.
- Engine: `evals/judge.py` (build_system_prompt; metadata fields render generically;
  notes field ~line 151) · v4.3 base: `evals/rubric_dad_v4.yaml`.
- Run auth when the matrix runs: Vertex via ADC, `VERTEX_PROJECT=project-79a62a3c-f7cc-4ac3-a8d`,
  model gemini-3.1-pro-preview, temperature 0, 3-run majority vote.

## Load these skills next
None required. Repo rules apply (pytest after functional changes; PR body needs "How to
test"). Use `handoff` again when wrapping.
