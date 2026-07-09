# Brief A — LLM-judge reliability & aggregation (deep-research w76k8kbwl, 2026-07-08)

Full output: tasks/w76k8kbwl.output. Apply at the AGGREGATION/RUN-PROTOCOL phase.

## Key directives (high confidence, sourced)
1. RELIABILITY: LLM judges are noisy. Run at **temperature 0**. **Ensemble 3+ independent
   runs, majority vote** (11-20 for near-tie / pass-boundary records). Cross-seed
   Krippendorff alpha often <0.8; verdicts flip ~13.6% avg. Never treat cross-seed
   self-consistency as evidence the judge is VALID (only reliable).
2. AGGREGATION (biggest lever): a simple MEAN of sub-scores is a WEAK predictor of human
   overall; the LLM's OWN direct overall score is WORSE than a constant-mean baseline. A
   small **calibrated aggregator learned against human labels (LLM-Rubric style)** roughly
   DOUBLES agreement (RMSE ~2x better, Spearman ~0.20->~0.35-0.40 in their setting). →
   Strong argument to learn dimension weights from a labeled set rather than hand-set them.
3. GATES vs CONTRIBUTORS: judge is most reliable separating clearly-different tiers, least
   reliable on near-ties. → Reserve HARD GATES for genuinely decision-determining floors;
   let the (calibrated) aggregator weight the rest. Expect the pass/fail boundary to be the
   noisiest zone (so don't over-engineer precision there).
4. VALIDATION on ~166 items: headline a **chance-corrected** coefficient (Krippendorff
   alpha / QWK / Cohen kappa), NOT raw Spearman (which overstates by 30-40 pts). Use
   probability-weighted (expected) sub-scores to avoid tie-clustering that deflates
   correlation. Our 0.64 aggregate Spearman is already comparable-to-better than typical
   (G-Eval-4 = 0.514 on SummEval).

## Implications for our design
- The helpfulness (and every) "critical vs contributor" question: keep hard floors ONLY
  where a low score is truly disqualifying regardless of polish; everything else →
  contributor, ideally with LEARNED weights.
- BUT learned aggregator needs human labels. We only have the analyst PROXY (not human).
  So: either (a) get a small real-human-labeled set to fit weights, or (b) keep
  hand-set gates+mean for now and treat weights as provisional. Flag for owner.
- Run protocol for v5 A/B: temperature 0, 3-run majority vote minimum.
- Reporting: switch headline metric from Spearman to Krippendorff alpha / QWK vs whatever
  label set we trust; keep Spearman as secondary.
