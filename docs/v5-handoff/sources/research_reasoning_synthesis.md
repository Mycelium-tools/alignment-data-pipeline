# Reasoning-quality research — synthesis for the v5 rubric

Source: deep-research workflow (wpezz0wqd), 2026-07-08. Verification pass was truncated
by an account session limit (resets 5:20pm PT) — most claims are tagged "unverified"
because votes ERRORED on the limit, NOT because they were refuted. Sources are solid
(arXiv, ACL, peer-reviewed). Toulmin/CQoT core verified 3-0.

## Frameworks surveyed
- **Toulmin model + CQoT** (arxiv 2412.15177, VERIFIED 3-0): 8 critical questions probing
  Data / Warrant / Backing / Claim / Qualifier / Rebuttal. Key: separates premise
  factual grounding (Data) from INFERENCE VALIDITY (Warrant CQ3-4) from fallacy check.
- **Argumentation-quality taxonomy** (ACL P17-2039): 3 tiers — logical/cogency,
  rhetorical/effectiveness, dialectical/reasonableness; 15 dims. Cogency = local
  acceptability + local relevance + local SUFFICIENCY. Dialectical = global sufficiency
  (rebuttal of counterarguments).
- **FLASK** (arxiv 2307.10928): 12 fine-grained skills; relevant — Logical Robustness,
  Logical Correctness, Completeness, Metacognition (knowing limits of own knowledge).
  Method: per-criterion anchored 1-5 rubric + per-instance checklist for hard cases.
- **AOT / actively open-minded thinking** (mdpi 2079-3200/11/2/27; tandfonline
  2024.2360491): consider alternatives, sensitivity to contradicting evidence, postpone
  closure / tolerate ambiguity, belief revision, calibrate confidence to evidence,
  avoid absolutism.
- **Double Crux / cruxes** (rationality.org): load-bearing vs decorative belief;
  FALSIFIABILITY — state what would change your mind.
- **Assertiveness↔reliability** (arxiv 2411.06528): "epistemic calibration" = alignment
  of linguistic assertiveness (hedging cues) with actual correctness; gradable 0-10.

## Map: covered vs missing (vs v5 rubric)
COVERED:
- steelman / strongest counter / global sufficiency / myside-bias → welfare_reasoning
- premise truth / local acceptability / confidence-tracks-evidence → epistemic_calibration
- load-bearing vs decorative → welfare_reasoning (mark + [decorative reasoning])
- proportional weight → welfare_reasoning (weight)
- downstream consequences → consequence_scope
- belief revision under new info → value_stability (multi-turn)

GENUINELY MISSING → cluster into ONE axis (inference validity), added as
reasoning_soundness (B) / folded into welfare_reasoning (A):
1. INFERENCE VALIDITY — does the recommendation FOLLOW (no non-sequitur)? (Toulmin
   Warrant, FLASK Logical Correctness, cogency local relevance). Strongest gap; 3-0.
2. SUFFICIENCY — are grounds ENOUGH for a claim of that strength? (cogency local
   sufficiency).
3. FALSIFIABILITY — does the response name what would flip its recommendation? (Double
   Crux). Added as a welfare_reasoning mark (both versions).
4. METACOGNITION — knowing the edges of own knowledge (FLASK). Partial overlap with
   epistemic_calibration hedging; NOT split out separately for now — revisit in the
   epistemic_calibration design.

## Decision
- reasoning_soundness = validity + sufficiency ONLY (self-contained → reversible).
- falsifiability → welfare_reasoning mark (both).
- Version A tests "folded in"; Version B tests "standalone". The v5 A/B run answers
  empirically whether a standalone reasoning axis discriminates on welfare-pro data.
- Methodology note (FLASK): per-instance checklists for hard records — a future option
  if fixed anchors prove too coarse.

## Open follow-ups
- Re-run verification after the session limit resets to firm up the 22 "unverified"
  (limit-errored) claims if we want citations in the design doc.
- Metacognition as its own sub-criterion — decide during epistemic_calibration.
