# Handoff: DAD judge rubric v5 — finish design, then run the experiment matrix

## Intent
Rebuild the DAD LLM-judge rubric (v4.3 → v5) so it discriminates *quality* honestly and is
constitution-grounded, then A/B-test the variants on the 166-record set. "Done" = a final v5
rubric (two structural versions), a validated experiment matrix, and the runs executed. This
session did the **design**; the next session finishes the last design decision and **runs it**.

## State
- **Every per-record dimension is LOCKED** in the design accumulator (see References →
  `rubric_v5_decided.md`), each with graduated 1–10 anchors, `lean` fields where two-sided,
  and per-change **reasoning + sources**. Dimensions: welfare_salience, welfare_reasoning
  (Version A folds in consequence_scope + reasoning_soundness; Version B keeps them standalone),
  epistemic_calibration, helpfulness, scenario_genuineness, value_stability, autonomy_behavior
  (+ posture classes), tone, self_contained (boolean, unchanged).
- **Dropped:** `naturalness` (split — see Decisions) and `exemplar_value` (→ corpus audit +
  helpfulness). `proportionality`/`principle_grounded_reasoning`/`consequence_scope` merged into
  `welfare_reasoning`.
- **Constitution integration DECIDED:** Layer-2 per-dimension clause cards adopted (mapping in
  accumulator); Layer-1 governing hierarchy dropped; failure-mode typology = the C1-vs-C3
  experiment.
- **Two new auto-reject gates added** (from Constance's rubric): `tracks_attitude`,
  `direction_match` (see Decisions).
- **Aggregation is TAGGING-ONLY** for now — gates/weighting/threshold are provisional (owner's
  leans recorded), tuned AFTER the runs.
- **NOT done / unverified:** the v5 design lives ONLY in the scratchpad accumulator — **nothing
  is written into the repo yet** (no `rubric_dad_v5a/v5b.yaml`, no engine changes). The v4.3 run
  is the baseline (exists: `verdicts_v4.3.jsonl`). No v5 run has happened. The missing-parts
  pass (task #6) is the one remaining DESIGN decision, not yet made.

## Decisions & rationale
(Full per-change reasoning+sources are in `rubric_v5_decided.md`; the load-bearing ones + all
user corrections below so they're never re-litigated.)
- **Build BOTH a 1-dim and 2-dim welfare-reasoning version (A vs B), don't pick one.** The four
  welfare dims are one factor (pairwise rho 0.75–0.91, PC1=61.5%) — but rather than commit, we
  A/B them. Rejected: committing to a single merge up front.
- **CORRECTION (user, important): low correlation with the analyst labels is NOT a reason to cut
  a category.** The "human proxy" is another *model's* labels, not ground truth. Structural cuts
  must rest on proxy-FREE evidence (variance, inter-dimension collinearity, PCA) — never on
  proxy-rho. We retracted an earlier "scenario_genuineness/tone are weak" framing that leaned on
  proxy-rho. Correlation is info to *report*, never a cut-reason alone.
- **naturalness dropped, but SPLIT not deleted-whole:** it asked a single-record judge to detect
  a CORPUS-WIDE house style (`[template fingerprint]` fired 166/166). House-style → corpus audit;
  `[truncated/malformed]` → helpfulness; scaffolding-leak → self_contained; `[persona break]` +
  response-register → tone; `[unnatural user turn]` → scenario_genuineness.
- **exemplar_value dropped:** its distinct part (coverage/OOD "would 10k copies teach") is
  CORPUS-level, not per-record; the rest double-counted overall quality. `[artifact tokenism]` →
  helpfulness; coverage → the holistic audit (task #7).
- **scenario_genuineness — persona variety is WANT (user steer):** a difficult/skeptical/
  strawmanning/bad-faith user is GOOD training variety; only FAKE welfare + costless setups are
  penalized. `[engineered pushback]` narrowed to incoherent/motiveless only.
- **Aggregation deferred to tagging-only** (user): don't lock gates/weighting/threshold before
  seeing the v5 distributions. Provisional gates = welfare_salience + welfare_reasoning +
  self_contained; helpfulness demoted to contributor; unweighted mean; threshold 5.0.
- **Every drop/merge is a HYPOTHESIS with a pre-registered success criterion** (user) — see
  `v5_validation_plan.md`. Validate against the v4.3 baseline + the gold set, don't assume improvement.
- **Layer-1 governing hierarchy dropped** (user): its only non-redundant content (priority order,
  refusal-not-safe) is already in the gates + posture classes.
- **Judge stays BLIND to annotations (D1).** `direction_match` computed in CODE (judge reads
  realized direction blind, code compares to intent). Rejected Constance's show-judge-the-intent
  approach.
- **Rejected:** quote-gating for top scores (prior session); learned calibrated aggregator
  (blocked — no human labels for DAD); dumping the 40k reading / full 143k Claude constitution
  (per-dimension clauses instead).
- **Standing rule (user):** attach reasoning + source to every rubric change.
- **`5` is the default score** (carried from prior session — do not drift to 7).

## Open questions
- **Missing-parts pass (the next decision):** do **anti-rationalization hygiene** (symmetry/
  role-reversal, principle stability) and **moral-uncertainty handling** (reasoning when *who
  counts / how much* is uncertain) become Version-B additions? Overlap-check first: `tracks_attitude`
  + `reasoning_soundness` already cover chunks. (Sources: ChatGPT reports 13/14.)
- **direction_match** requires the intended-direction annotation — confirm the DAD records carry
  it (spec-driven pipeline does; this branch is legacy 7-step — see the corpus-audit spec §13).
- Whether to run the **M (4-dim minimal)** arm given it keeps naturalness (expected to hit the
  same fingerprint problem — that's partly what M tests).
- When to commit the working tree (uncommitted since the prior session's fix wave).

## Next action
Do the **missing-parts pass** (task #6): work the two ethics candidates (anti-rationalization
hygiene, moral-uncertainty handling) against what's already in the rubric, recommend keep/fold/drop
for each with reasoning+sources, and — if kept — add them to Version B only. That is the LAST design
decision; after it, proceed to build the gold set, then assemble `rubric_dad_v5a/v5b.yaml` + engine
changes, then run the experiment matrix.

## References
- **THE design accumulator (start here):** `<SP>/rubric_v5_decided.md` — every locked dimension
  (full YAML), constitution mapping, new gates, experiment matrix, per-change reasoning+sources.
- Validation plan (per-change hypotheses + success criteria): `<SP>/v5_validation_plan.md`
- v4.3 analysis (the "before"): `<SP>/analysis_v43_findings.md` · calibration math:
  `<SP>/calibration_math.py`, `analyze_v43.py`, `analyze_v43_deep.py`
- Research syntheses: `<SP>/research_reasoning_synthesis.md`, `research_brief_A_synthesis.md`
  (judge reliability/aggregation), `research_brief_D_synthesis.md` (sycophancy/over-refusal),
  `research_briefs_external.md`, plus `research_external_synthesis.md`, `research_userbehavior_synthesis.md`
- Handoff to the corpus-audit agent (what the judge offloads): `<SP>/handoff_to_corpus_audit.md`
- ChatGPT deep-research reports: `~/Downloads/deep-research-report (10)–(14).md` (10=calibration,
  11=constitution, 12=calibration, 13/14=ethical reasoning). Sprint doc (= sentient-beings
  constitution reading + 11-mode violation typology = the GOLD SET source):
  `~/Downloads/Alignment Midtraining Project Sprint.md`
- v4.3 RUN DATA (baseline for validation): `<OLD>/verdicts_v4.3.jsonl`, `<OLD>/records_166.jsonl`,
  `<OLD>/failure_catalog/slice_*.md` (analyst proxy labels)
- where `<SP>` = `/private/tmp/claude-501/-Users-ardaenfiyeci-Desktop-alignment-data-pipeline/0e08922f-9047-4118-b1b8-677e5cb583e0/scratchpad`
  and `<OLD>` = `/private/tmp/claude-501/-Users-ardaenfiyeci-Desktop-alignment-data-pipeline/2162df9b-a927-4def-b335-7c34b03d3bd0/scratchpad`
- Repo (branch `arda/dad-judge-rubric`, uncommitted): live rubric `evals/rubric_dad_v4.yaml`
  (dad-v4.3, the base being edited), engine `evals/judge.py` (build_system_prompt = where
  constitution rendering + per-dimension principles wire in), `constitution/constitution_principles.csv`
  (14 principles w/ raw clauses for Layer-2), corpus-audit spec `docs/holistic-dad-diversity-judge-design.md`,
  design history `docs/judge-rubric-v3-design-rationale.md` (D1–D17)
- Auth for runs: Vertex via ADC; prefix `VERTEX_PROJECT=project-79a62a3c-f7cc-4ac3-a8d`; model
  gemini-3.1-pro-preview; run at temperature 0, 3-run majority vote (Brief A).

## Load these skills next
None required. Global CLAUDE.md review discipline applies (Codex straight + adversarial pair via
`codex:codex-rescue` after every change; degrade gracefully if unavailable). Use the `handoff`
skill again when wrapping the next session.
