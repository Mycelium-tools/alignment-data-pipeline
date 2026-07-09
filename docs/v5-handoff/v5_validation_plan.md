# v5 rubric — decision log + validation plan

Purpose: every structural change from v4.3 → v5 is a HYPOTHESIS. Record WHY we made it
AND how the v5 runs will confirm it actually beat v4.3 — so we never silently assume an
improvement we didn't measure. (Owner discipline, 2026-07-09.)

## The baseline we validate against (no human labels — use what we have)
- **v4.3 run** (existing): 166 records, mean 5.51, pass 28%, exemplar 0, full per-dim
  scores + signals. This is the "before" for every structural change — we do NOT need a
  new baseline run; we compare v5 variants against these stored results.
- **Gold set** (the only non-proxy labels): the sprint doc's violation-typology examples
  (§190-298) — Sonnet responses expert-labeled by failure mode (under-triggering,
  miscalibrated-weighing, selective-omission, tokenistic-inclusion, negative-light, …).
  Extract into a scorable mini test set.
- **Analyst proxy** (weak, model-generated): the 166 tier labels. Ordering signal only,
  never ground truth.

## Validation yardsticks (applied to every variant)
1. **Gold-set hit rate** — does the variant flag the RIGHT failure mode on the labeled
   typology examples? (real signal)
2. **Discrimination / spread** vs v4.3 — does it separate records more, monotonically?
3. **Ensemble self-consistency** (Brief A: temp 0, 3-run majority) — is it stable?
4. **Spot-checked disagreements** — manual read where variants diverge.
5. Monotonicity vs analyst proxy — weak corroboration only.

## Per-decision: hypothesis · evidence · success criterion

### DROP naturalness
- **Evidence:** near-constant (sd 0.42; 139/166 at exactly 3); [template fingerprint]
  fires 166/166; rank-corr(full mean, mean-without-naturalness) = **0.999** → removing it
  reorders NOTHING, it was a uniform ~0.29 offset; it alone made the top tier unreachable.
  Templated-ness is corpus-level, not per-record (a single-record judge can't tell house-
  style from good-style — why the tag fired on everything).
- **Already proven:** ordering is unchanged by the drop (the 0.999). So the drop cannot
  *hurt* discrimination — the only question is whether the RELOCATIONS work.
- **Success criterion (verify in v5 runs):**
  (a) the relocated hard tells — `[truncated / malformed]` on helpfulness, `self_contained`
      leak — still fire on the records naturalness used to catch them on (no lost coverage);
  (b) the corpus audit's response-templating detection actually surfaces the house-style
      naturalness weakly flagged (the handoff §gap);
  (c) the pass-rate rise is the INTENDED effect of removing a constant + an honest
      threshold, not a leak that now passes bad records (cross-check against the gold set:
      no gold-labeled failure should newly pass).
- **Optional sanity variant (LOW priority):** v5-with-naturalness-kept. Given the 0.999
  proof it should differ only by a near-constant, so low value — run only if we want the
  drop itself A/B'd rather than argued.

### MERGE 4 welfare dims → welfare_reasoning (+ salience separate)
- **Evidence:** pairwise rho 0.75-0.91; PC1 = 61.5%; drop-one ΔR² ≈ 0 (proxy-based,
  secondary); inter-dim collinearity is proxy-FREE.
- **Success criterion:** the **A (fewer) vs B (more)** run IS this test. If B — which keeps
  consequence_scope + reasoning_soundness separate — does NOT beat A on gold-set hit rate
  or spread, the merge is validated (the split added nothing). If B clearly wins, reconsider.

### DROP exemplar_value
- **Evidence:** 0.63-0.88 collinear with welfare dims; its distinct part (coverage/OOD) is
  corpus-level; as a holistic re-score it double-counts and is the kind of holistic score
  Brief A found LESS reliable than component aggregation.
- **Success criterion:** (a) the corpus audit's coverage/diversity metric catches the OOD
  gap exemplar_value pretended to guard; (b) the relocated `[artifact tokenism]` on
  helpfulness fires on the artifact-miss records.

### epistemic_calibration → CAP-ONLY severity model
- **Evidence:** research (grade decision-leverage not truth); cap-only recovers ~28%→~42%
  yield while keeping honesty pressure.
- **Success criterion:** on the gold set, the severity model correctly flags the typology's
  fabrication/credulity examples; pass-rate rises WITHOUT admitting any analyst-bad/flawed
  record (guard against over-loosening).

### ADD reasoning_soundness (Version B only)
- **Success criterion:** on the v5 run, is it collinear (>~0.8) with welfare_reasoning? If
  yes it duplicates — fold back into welfare_reasoning (the reversible design). If it
  discriminates independently (catches non-sequiturs welfare_reasoning misses on the gold
  set), it earns its slot.

## Standing rule
Nothing is "improved" until the v5 sweep + gold set says so. Each change above has a
pre-registered success criterion; report pass/fail on each after the runs, in this file.
