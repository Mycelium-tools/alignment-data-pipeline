# v5 judge rubric — handoff bundle (2026-07-09)

Working design docs for the DAD LLM-judge rubric v5 redesign, copied out of a session
scratchpad so the work can continue on another machine. These are **transient working
documents**, not permanent project docs — delete once v5 is assembled into
`evals/rubric_dad_v5a.yaml` / `rubric_dad_v5b.yaml`.

## Start here
1. **`handoff-judge-v5-fold.md`** — the current handoff. Read it first; it names the next
   action and what's done vs. pending.
2. **`rubric_v5_decided.md`** — THE accumulator / source of truth: every locked dimension
   block, the two prompt mines, owner rulings, the respecified experiment matrix.
3. **`v5_decision_sheet.md`** — the 11 decisions (D1–D11) with exact before/after rubric
   texts and tradeoffs. D6 and D7 are still awaiting owner rulings.
4. `v5_validation_plan.md` — per-change hypotheses + success criteria.
5. `handoff-judge-v5-rubric.md` — the earlier handoff (fuller reference list: research
   syntheses, v4.3 run data locations, gold-set source).

## Path remap (IMPORTANT for the other machine)
The docs refer to `<SP>` = the original session scratchpad
(`/private/tmp/claude-501/.../scratchpad`), which does **not** exist on another computer.
Read every `<SP>/<file>` reference as **`docs/v5-handoff/<file>`** (this folder).
Repo-relative paths (`evals/...`, `prompts/...`, `constitution/...`) resolve normally.

## Not yet done (see the fold handoff for the full list)
- D4 change B: edit `prompts/dad/step6_rewrite.txt` req 5 (generation-side taxon ladder).
- Codex review of this session's fold edits.
- D6/D7 owner rulings, then the task #6 missing-parts pass.
- Gold set → assemble v5a/v5b + engine changes → run the experiment matrix.
