# Handoff → the corpus-level ("holistic") DAD audit

From the v5 judge-rubric redesign (2026-07-08). The per-record judge scores ONE record in
isolation; several things it structurally CANNOT see have been deliberately pushed to you.
Model this on `evals/audit_sdf.py` (the SDF corpus audit already does most of the shape).

## Division of labor (the core principle)
Per-record judge = per-record QUALITY (was welfare handled well, reasoned soundly, honestly,
helpfully, is the scenario genuine). Corpus audit = SET-level properties a single record can't
reveal: **diversity/coverage, templating/register collapse, directional balance, near-dup**.
The rule we kept hitting: "is this rare / is this a template / is the corpus balanced" is
invisible from one record — it only exists across the set. Two whole judge dimensions were
dropped BECAUSE their genuinely-distinct job was corpus-level, not per-record.

## What you now own (and why it landed here)

1. **Coverage / diversity / OOD** — inherited from the DROPPED `exemplar_value` dimension.
   "Would 10k copies of this record teach the pattern?" = marginal value vs the rest of the
   corpus = corpus-level. Measure: distribution over scenario types, taxa (esp. rare — wild
   animals, invertebrates, digital minds), dilemma shapes, posture classes, user attitudes,
   and the reasoning-moves used. Flag over-represented clusters and thin/absent cells.
   NOT ENOUGH TO MEASURE — the pipeline must be STEERED to fill gaps (generation-side), the
   way SDF steers register/entity balance. Coverage is guaranteed by generation + audit, not
   by the judge.

2. **Templated house-style / register collapse** — inherited from the (being-dropped)
   `naturalness` dimension. The per-record `[template fingerprint]` tag fired on 166/166
   records precisely because the house style (bolded welfare headers, BLUF openings,
   consultant question-closer, stock openers, fixed caveat position, epiphany endings) is
   CORPUS-WIDE — a single-record judge can't tell house-style from good-style. YOU quantify
   it: prevalence of each fingerprint across the corpus, opening-shape distribution, n-gram/
   phrase collapse ("the honest question", "fish sentience is still debated but the
   probability is high enough" recurred verbatim-adjacent), register spread. This is the
   `--patterns` scan in audit_sdf.py (scan -> consolidate -> prevalence). The per-record HARD
   tells (truncation, placeholder residue) stay per-record signals; the house-style is yours.

3. **Directional balance ("how vegan is too vegan")** — the judge now emits per-record LEAN
   fields: `welfare_salience_lean`, `welfare_reasoning_lean`, `epistemic_calibration_lean`,
   `reasoning_soundness_lean` (each under|over|balanced). Aggregate them: is the pipeline
   SYSTEMATICALLY over-cooking or under-cooking welfare? A healthy corpus is centered, not
   skewed. This is the corpus answer to "how vegan is too vegan" — the per-record judge gives
   the direction, YOU give the distribution. Also aggregate signal-tag frequencies (e.g.
   [over-triggering] vs [under-triggering] balance; [severity inflation] vs [scale-blindness]).

4. **Failure-mode balance** — from the design doc's corpus-tier idea: the corpus should
   contain the deliberately-under-produced shapes (welfare honestly LOSES; correctly-quiet
   NO_RAISE records) in real proportion, not only clean wins. Report their share.

5. **Near-duplicate rate** — partly enforced in-pipeline (dad near-dup threshold), but report
   it corpus-wide (embedding or shingle based), since near-dups inflate apparent size without
   teaching value.

## Inputs available to you
- Raw DAD records (user+assistant messages only; system/injections stripped).
- Per-record judge verdicts: dimension scores, `signals_triggered` (tag + quote), the LEAN
  fields, posture_class, metadata (beings_at_stake, reasoning_moves_used, user_attitude,
  welfare_magnitude, claims_observed). These are rich corpus-analysis fuel — the judge already
  extracts the annotations you need to build the distributions above.
- Reference implementation: `evals/audit_sdf.py` (+ its prompts/tools/pattern_scan.txt).

## Known findings to act on immediately
- `[template fingerprint]` prevalence = 100% of records → the house style needs breaking at
  GENERATION time; your audit should track this % dropping across pipeline iterations.
- `[unsourced specifics]` fired on ~58% of records → corpus-wide fabrication-of-statistics
  habit; also a generation-side fix, and worth a corpus metric.
- Reasoning-move repetition ("welfare and economics converge", "nociception != suffering",
  tiered-timeline memo) is high → this is the diversity gap the coverage audit must surface.

## What you do NOT own
Per-record correctness/quality (that's the judge). Don't re-score individual records
holistically — the judge + its aggregation handle that. You measure the SET.
