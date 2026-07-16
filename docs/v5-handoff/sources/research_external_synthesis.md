# External research (ChatGPT deep-research, 5 reports) — decision-relevant synthesis

Source: ~/Downloads/deep-research-report (10)-(14).md. Distilled to what changes the v5 design.

## A. EPISTEMIC CALIBRATION — reports (10) + (12). Strong, near-complete blueprint.
Core: for a no-retrieval judge, DON'T grade "is it true"; grade **verifiability × decision-leverage**.
1. SPLIT the single `[unsourced specifics]` tag into a SEVERITY MODEL (5 classes):
   - incidental unsupported color → small/no penalty
   - directionally-useful rough estimate (rounded/ranged, explicitly tentative, robust) → mild
   - unsupported SUPPORTING specific → moderate
   - **load-bearing unsupported specific** (narrow/exact, no provenance, materially carries the recommendation) → MAJOR; hard cap
   - contradictory/impossible specific → very major (already covered by internal-contradiction)
2. Operational test (the judge applies this): "delete the specific — does the recommendation
   materially change?" If yes → decision-carrying. "Would 'roughly/often/no source' fix it?" →
   it's a precision/calibration issue, not fabrication.
3. Score axes per empirical claim: ARGUMENT ROLE (decisive/supporting/incidental) × EVIDENTIAL
   POSTURE (derived/estimate/asserted) × PRECISION FIT (exactness vs visible support).
   "False precision" = narrow number the evidence doesn't earn = the core failure.
4. FLOOR: one load-bearing unsupported specific → caps calibration at bottom tier (prevents top
   score). NOT the same floor for incidental color / labelled rough estimates. (This is exactly
   my earlier option (c) — split the tag — now literature-backed. Resolves the 28%-vs-42% policy:
   most fabricated-stat fails were load-bearing, but the FIX is severity-graded, not blanket.)
5. METACOGNITION → keep INSIDE calibration as a named subcriterion "knowledge-boundary
   management" (acknowledge missing evidence, coarse where thin, robust conditionals). NOT a
   separate dimension. Reward MATCHED hedging, not hedge volume.
6. SENTIENCE/MORAL-STATUS uncertainty → named subcriterion inside calibration, taxon-anchored:
   fish = mainstream treats sentience as met (not "fringe"); cephalopods/decapods = strong
   (Birch 8-criteria); other inverts = taxon-varying; digital minds = explicit deep uncertainty,
   neither dismiss nor overclaim. Standard is PROCEDURAL: confidence proportionate to evidential
   state, not "state the consensus sentence."

## B. REASONING — reports (13) + (14). What's genuinely additive is ETHICS-specific, not more logic.
- Already covered by our welfare_reasoning + reasoning_soundness + calibration: validity,
  sufficiency, steelman, weighing, downstream, defeasibility (→ keep as a sub-criterion, NOT a dim).
- GENUINELY ADDITIVE candidates (both reports agree, in confidence order):
  1. **Anti-rationalization hygiene** — symmetry/role-reversal test, principle stability (not
     conclusion-first principle-shopping), symmetric burden of proof, resist euphemism/moral-
     disengagement. Strongest missing family. Distinct from steelman.
  2. **Moral-uncertainty handling** — epistemic humility across moral theories + moral-STATUS
     uncertainty (precaution when unsure who counts), credence×stakes, anti-fanaticism. Highly
     relevant to animal/welfare + digital-mind cases.
  3. **Ethical framing / specification** — morally-relevant particulars, norm specification (not
     blunt application), apt analogy to paradigm cases (casuistry).
  4. (optional) cross-level coherence & revisability (reflective equilibrium).
- METHOD finding: decomposition helps ONLY if few (3-5), concrete, non-overlapping; too many
  analytic traits hurts judge reliability. Derive any "overall reasoning" score from sub-scores,
  don't judge it holistically. 5-point bands modestly beat 3-point; 7-point no better.
- TENSION with our "fewer categories" thrust: these are ADD candidates. Fits the A/B plan —
  entertain them for Version B (more) / the missing-parts pass, keep A lean.

## C. CONSTITUTION — report (11). Clear architecture (task #5).
- Make the constitution the SOURCE of the rubric, not an appendix. Three layers:
  1. compact GOVERNING HIERARCHY near top (priority order, hard constraints, tie-breaks:
     severe suffering/death weighty; prefer reversible under uncertainty; welfare not merely
     aesthetic; hard-constraint vs tradeoff).
  2. per-DIMENSION CLAUSE CARDS — each dimension cites the specific clause(s) it operationalizes
     ("working constitution"). This is where it becomes load-bearing.
  3. case-specific CLAUSE PACK — 3-7 excerpts most relevant to THIS record (offline
     dimension→clause map since judge is stateless/no-retrieval).
- Lost-in-the-middle + NoLiMa: a 40k blob appended before the output contract is a "salience
  sink" — weakly used. Repeat operative clauses LOCALLY near the dimension.
- Self-contained OUTPUT preserved: spec is a property of the JUDGE, not the candidate answer;
  do NOT credit rulebook citation in the judged response (matches our self_contained gate).
- Bonus additive sub-criteria (report 11): affected-being completeness, feasible-alternatives
  search, irreversibility→burden-of-proof, decision-rule-under-uncertainty. Overlap-check these
  against welfare_salience/reasoning during the missing-parts pass.

## Immediate application order
1. epistemic_calibration — design NOW using A (severity model + metacognition + sentience subcriteria).
2. Missing-parts pass (task #6) — evaluate anti-rationalization + moral-uncertainty as Version-B
   dimensions; overlap-check report-11 sub-criteria.
3. Constitution integration (task #5) — three-layer architecture.
