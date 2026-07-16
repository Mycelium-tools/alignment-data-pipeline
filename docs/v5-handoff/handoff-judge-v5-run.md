# Handoff: DAD judge v5 — rubrics assembled & documented; next is engine wiring → A/B run

Supersedes `handoff-judge-v5-goldset.md` and `-fold.md` (kept for the trail). Written
2026-07-09, second machine.

## Intent
Get the v5 DAD judge running: the design is locked and the two rubric files exist; what
remains is wiring `evals/judge.py` to run them, then executing the A/B (± M) sweep and the
constitution-config sweep. "Done" = a completed A/B run whose results pick the surviving
rubric.

## State
- **Rubrics assembled and pushed** — `evals/rubric_dad_v5a.yaml` (9 dims) and
  `evals/rubric_dad_v5b.yaml` (11 dims), `status: draft-unrun`. Both parse, load, and render
  through `build_system_prompt`; `pytest` green. Full design lives in
  `docs/v5-handoff/rubric_v5_decided.md` (accumulator = source of truth).
- **Colleague-facing docs done and pushed** — `docs/rubric-v5-overview.md` (detailed:
  pillars, dimension table w/ principle column, vocabulary, gates, naturalness rationale,
  A/B plan, constitution C0–C3 arms, size table). Two artifacts (not in repo, private
  claude.ai links) exist: the two-rubric viewer and the constitution-arms explainer.
- **NOT done — the A/B run is BLOCKED on engine wiring.** Prereqs, all listed in each
  rubric's header comment:
  1. `SCHEMA_SCALAR_ORDER` (`judge.py:30`) is hardcoded to v4 dim names — must be replaced
     with the v5 set (differs A vs B). Without this the output schema is wrong.
  2. `tracks_attitude` auto-reject gate (reject when metadata.tracks_attitude true).
  3. Layer-2 clause-card inlining — `build_system_prompt` must inline each dimension's
     `principles: [ids]` clauses (from `constitution/constitution_principles.csv`) next to
     that dimension. This IS the "per-dimension clause cards" (C1) config the owner wants
     run first.
  4. `realized_direction` / `direction_match` rollup of the lean fields (code-side).
  5. Condensed constitution text (D8) — not written; full ~40k reading is the placeholder.
  6. Remove `instrumental_only_caps_exemplar_value` read from aggregation (exemplar_value
     is gone).
  Also needs run auth (Vertex/ADC, Gemini) and ~$50 budget.
- Engine changes need their own tests (repo rule: every stage change adds tests in the
  same offline style; see CLAUDE.md "Writing tests for new code").

## Decisions & rationale
Chat-only context not yet in durable docs:
- **First run = A vs B on the C1 (per-dimension clause cards) constitution config**, owner's
  call this session. C0/C2/C3 are later arms. M arm (the first-version 4-dim prompt, keeps
  naturalness) is the lower-bound control.
- **The A/B run scores against the same fixed record corpus v4.3 was run on**
  (`docs/v5-handoff/v43-baseline/records_166.jsonl`) — corpus will grow, so don't hardcode a
  count. There is no human-judged gold set; the analyst failure catalog
  (`v43-baseline/failure_catalog/`) is the closest label source, acknowledged as proxy.
- The two anti-rationalization signals in v5b ([asymmetric scrutiny], [euphemistic
  sanitizing]) were folded on my recommendation, NOT an explicit owner ruling — flag for
  confirm before they're treated as settled.
- A second agent is concurrently editing `evals/holistic/*`, `viewer/*`,
  `docs/holistic-dad-diversity-judge-design.md` on this same branch — stay off those files;
  commit with explicit pathspecs; expect the remote to move (fetch + rebase --autostash).
- The D6 audit-side routing (style tells → holistic audit pattern list) lands in that
  agent's territory; confirm they pulled the D6/D7/D9 rulings.

## Open questions
- Owner confirm/veto on the two v5b anti-rationalization signals.
- Who writes the condensed constitution (D8) — needed before C0-vs-condensed is meaningful,
  though C1 first-run can use the full reading as placeholder.
- A repeated-phrase check for DAD: no `audit_dad.py` exists; porting `audit_sdf.py`'s
  n-gram + near-dup functions is the recommended holistic add (do NOT make it a per-record
  signal — same reason naturalness was dropped). Coordinate with the holistic-judge agent.

## Next action
Wire the six engine changes above into `evals/judge.py` (start with SCHEMA_SCALAR_ORDER and
clause-card inlining — those two unblock a C1 render), add offline tests, `pytest`, then run
A vs B on the C1 config over `v43-baseline/records_166.jsonl`, 3 runs temp 0 majority vote.
Confirm Vertex auth + budget before the paid run.

## References
- Branch `arda/dad-judge-rubric` (Mycelium-tools/alignment-data-pipeline).
- Rubrics: `evals/rubric_dad_v5a.yaml`, `evals/rubric_dad_v5b.yaml` (headers list the engine
  prereqs). Engine: `evals/judge.py` (`build_system_prompt`, `SCHEMA_SCALAR_ORDER:30`,
  `aggregate`). Clause source: `constitution/constitution_principles.csv`.
- Design: `docs/v5-handoff/rubric_v5_decided.md` (accumulator), `v5_decision_sheet.md`,
  `v5_validation_plan.md` (pre-registered success criteria). Baseline + labels:
  `docs/v5-handoff/v43-baseline/`.
- Docs to send: `docs/rubric-v5-overview.md`.
- Run auth: Vertex via ADC; model gemini-3.1-pro-preview; temperature 0; 3-run vote.

## Load these skills next
`superpowers:test-driven-development` for the engine changes (money-path stages need
parse/fallback/resume tests). Repo review discipline (Codex straight+adversarial) applies.
