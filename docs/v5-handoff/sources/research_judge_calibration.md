# Research: fixing a rubber-stamping LLM judge for training-data quality scoring

Context: ~76k-char YAML rubric, 15 dimensions, 1-10 anchored scales, signal→score caps,
posture classification, run through Gemini/Claude judges. Observed: bimodal cliff scoring
(1-2 or 9-10), 10 modal on 5 dimensions, +0.44 score-length correlation, 59% "exemplar"
vs 5-15% target, prompt too long to bind.

Research date: 2026-07-08. Sources: 2024–2026 arXiv literature + practitioner writing.

---

## 1. Scale design: coarse vs 1-10 anchored

**R1 — 0-5 beats 0-10 and 0-100 for human-LLM alignment; 0-10 is the WORST of the three.**
A controlled study comparing 0-5 / 0-10 / 0-100 scales found the 0-5 scale gave the
strongest human-LLM alignment (ICC = 0.853, nMAE = 0.111) while 0-10 gave the weakest
(ICC = 0.805, nMAE = 0.122); 0-100 landed in between (ICC = 0.840). Alignment collapsed
most on subjective benchmarks (MT-Bench LLM panel reliability 0.632 vs human 0.899) —
i.e., exactly the ambiguous middle-quality judgments where our judge shows the empty-middle
cliff. Source: "Grading Scale Impact on LLM-as-a-Judge" — https://arxiv.org/html/2601.03444v1
*Maps to us:* our 1-10 anchored scales sit on the empirically worst scale width. Moving each
dimension to 0-4 or 1-5 with anchors is the single best-evidenced change.

**R2 — Practitioner consensus has converged on 5-point (or coarser) as the reliability
ceiling.** Appen's rubric-design experiments (5- through 10-point rubrics, 3 judge models)
found the 5-point rubric had the highest exact agreement, highest bucketed agreement,
perfect majority consensus, and lowest normalized variance; they recommend 3-point when
distinctions are coarse, because finer gradations "risked introducing artificial
disagreement." Source: https://www.appen.com/llm-as-a-judge-rubric-design
*Maps to us:* per-dimension 3-point (fail / adequate / strong) is defensible; 1-10 is not.

**R3 — Binary pass/fail with a written critique is the strongest practitioner position.**
Hamel Husain (30+ company engagements) argues multi-point scores without a defined 3-vs-4
boundary produce "noisy data no one can act on," that annotators default to safe values,
and that binary pass/fail anchored to a specific criterion correlates better with actual
quality than granular numeric scores — pair each verdict with a critique to retain nuance.
Sources: https://hamel.dev/blog/posts/llm-judge/index.html ,
https://hamel.dev/blog/posts/evals-faq/
*Maps to us:* many of our 15 dimensions (e.g., posture classification, hard red-flags) are
naturally binary/ternary gates masquerading as 1-10 scales. Skepticism: Husain's evidence is
experiential, not controlled; but it agrees with R1/R2's direction.

**R4 — Additive checklist scoring ("award 1 point if...") empirically beat plain Likert for
training-data quality specifically.** FineWeb-Edu scored 500k pretraining docs 0-5 using the
additive scale of Yuan et al. (Self-Rewarding LMs, arXiv:2401.10020) — each point is a
separately-justified criterion the judge reasons through — and reports it "worked best"
among prompt formats tried; threshold ≥3 gave F1 = 82% vs human validation and the best
downstream-benchmark tradeoff. Sources: https://huggingface.co/HuggingFaceFW/fineweb-edu-classifier ,
https://arxiv.org/pdf/2406.17557
*Maps to us:* replace "rate coherence 1-10" with "award 1 point each for [5 concrete,
checkable properties]" — the score becomes a count of satisfied criteria, which mechanically
prevents 10-as-default and forces the middle bands to exist.

**R5 — G-Eval-style token-probability weighting turns integer cliffs into continuous
scores.** Aggregating the judge's token probabilities over the score vocabulary
(sum of p(score_i)·score_i) produces continuous values, directly mitigating "always returns
7/10" low-variance and tie failure modes. Sources:
https://www.confident-ai.com/blog/g-eval-the-definitive-guide , https://galileo.ai/blog/g-eval-metric
*Maps to us:* cheap add-on if we keep any numeric scale and the API exposes logprobs
(Gemini does; Anthropic doesn't expose logprobs — so this only works on the Gemini judge).
It smooths the cliff but does NOT fix leniency: a judge whose mass sits on {9,10} still
averages ~9.5. Treat as tiebreaker, not calibration.

## 2. Leniency / ceiling-bias mitigations

**R6 — Score inflation of ~1.5–2.0 points on a 10-point scale is a documented baseline for
LLM judges; skew-toward-ceiling is the norm, not a quirk of our rubric.** Multiple sources
report "overly positive skew" and score compression at the high end (Qwen judges
concentrate near 10). Sources: https://www.godaddy.com/resources/news/calibrating-scores-of-llm-as-a-judge ,
https://deepchecks.com/llm-judge-calibration-automated-issues/
*Maps to us:* don't expect prompt wording ("grade harshly") alone to fix a structural bias;
plan for a post-hoc or comparative mechanism.

**R7 — Reference-anchored scoring measurably reduces drift and inflation.** Injecting a
concrete scored reference from the same category anchors the scale and reduces inter-query
variance; Reference-Anchored Elo Estimation (RAEE) — anchor comparisons to a fixed
reference, express outcomes as win probabilities — cut per-run standard error ~44% and
across-judge coefficient of variation ~72% vs direct scoring. Academic grading work anchors
with exemplars at the 5th/25th/50th/75th/95th percentiles of the human mark distribution.
Sources: https://openreview.net/forum?id=Q88mQBuPjB ,
https://arxiv.org/pdf/2604.13717
*Maps to us:* build a small frozen calibration set of hand-labeled records at known tiers
(a genuine exemplar, a solid-but-flawed record, a failure) and embed 3-5 of them, with
their assigned tiers and one-line justifications, in every judge call: "score relative to
these." This is the best-evidenced direct fix for "59% exemplar."

**R8 — Percentile/quantile mapping is a valid post-hoc calibration when you can't fix the
judge.** Distributional calibration via quantile mapping (compute each raw score's
percentile rank within the judge's own global score distribution, then map to the target
distribution) converts a compressed 8.5–10 range back into a usable ranking. Sources:
https://www.godaddy.com/resources/news/calibrating-scores-of-llm-as-a-judge ,
https://deepchecks.com/llm-judge-calibration-automated-issues/
*Maps to us:* even without any prompt change, we can define "exemplar" as top-N% of the
judge's own composite-score distribution per run rather than "composite ≥ threshold."
This guarantees the 5-15% exemplar target by construction. Caveat: it assumes run-to-run
quality is comparable — a genuinely better corpus deserves more exemplars, so keep an
absolute red-flag floor alongside the relative cut.

**R9 — Pointwise scores at the ceiling destroy top-tier selection; pairwise comparison
recovers the lost signal.** "When LLM Judge Scores Look Good but Best-of-N Decisions Fail"
(arXiv:2603.12520) shows coarse pointwise scoring creates ties in 67% of pairwise
comparisons, and explicit pairwise judging raises correct best-of-2 recovery from 21.1% to
61.2%; PairJudge RM's knockout tournament (n-1 comparisons, O(log n) rounds) gives 40-60%
relative improvement on hard cases vs absolute-score selection. Sources:
https://arxiv.org/pdf/2603.12520 , https://arxiv.org/abs/2501.13007
*Maps to us:* strongest evidence for a two-stage design — pointwise gate for pass/fail,
then pairwise tournament (or pairwise-vs-reference-exemplar) ONLY among the high scorers to
pick the true exemplar tier. Directly targets "10 is modal on 5 dimensions."

**R10 — But pairwise is not a free lunch: it amplifies stylistic biases and is less stable
under manipulation.** "The Comparative Trap" (arXiv:2406.12319) finds pairwise framing
amplifies judges' biased preferences (verbosity, style) relative to pointwise; a follow-up
protocol study (arXiv:2504.14716) finds pairwise preferences flip in ~35% of cases under
distractor manipulations vs ~9% for absolute scores. Sources:
https://arxiv.org/html/2406.12319v4 , https://arxiv.org/abs/2504.14716
*Maps to us:* use pairwise only in the final exemplar-selection stage, with length-matched
or length-disclosed candidates, position-swapped (judge each pair twice, orders reversed),
never as the primary quality gate.

**R11 — Forced score budgets / "grade against a target distribution" have weak direct
evidence.** I found no controlled study validating "you may award at most X% top scores"
as an in-prompt instruction; the calibration literature instead does distribution matching
post-hoc (R8) or via anchors (R7). In-prompt distributional priors are also at odds with
the finding that judges under-follow long instruction sets (R13). Skepticism note: this is
an evidence gap, not evidence of failure — but prefer mechanisms that don't rely on the
judge obeying a statistical constraint it can't track across independent calls (it literally
cannot know its own running distribution when calls are stateless).

**R12 — Generic mitigation prompting mostly fails; structural redesign works.** A
systematic evaluation of bias-mitigation strategies (rubrics, few-shot calibration, swap,
CoT, decomposition) found most showed limited effectiveness and none consistently
eliminated length/position/leniency biases, concluding the fix is "structural redesigns of
evaluation pipelines" rather than prompt engineering. Source: https://arxiv.org/pdf/2604.23178
*Maps to us:* consistent with our experience that rubric v3.x prompt-side caps didn't bind;
prioritize pipeline-shape changes (decomposition, two-stage, calibration set, code-enforced
caps) over more rubric prose.

## 3. Rubric length / attention

**R13 — Instruction-following degrades measurably as simultaneous-instruction count grows,
with bias toward EARLIER instructions.** IFScale (arXiv:2507.11538, NeurIPS): even frontier
models fall to ~68% adherence at 500 concurrent instructions; degradation begins far
earlier (threshold decay for reasoning models, linear for claude-sonnet/gpt-4.1), with
systematic primacy bias — instructions later in the prompt are dropped first. Sources:
https://arxiv.org/abs/2507.11538 , https://distylai.github.io/IFScale/
*Maps to us:* a 76k-char rubric is exactly the regime where caps and anchors placed deep in
the YAML stop binding. Directly explains "prompt too long to bind" and argues for both
(a) drastic shortening and (b) putting the load-bearing rules (signal→score caps,
exemplar bar) FIRST, restated at the end.

**R14 — Decomposed / grouped scoring beats monolithic multi-dimension calls.** The
rubric-evaluation literature (RubricEval arXiv:2603.25133; rubric-refinement work at
arXiv:2606.08625 and the RRD decompose-filter cycle) converges on: verdicts local to one
criterion are simpler to elicit and more robust; conflated/correlated dimensions and
redundant criteria degrade judge quality; "form-filling" (reason through each dimension
before any score) beats holistic scoring. GoDaddy's practitioner report adds that implicit
aggregation (step-by-step per-criterion assessment, then holistic verdict) beat explicit
weighted-sum aggregation, and Rubrics-as-Rewards-style binary yes/no criteria enabled
precise error localization. Sources: https://arxiv.org/html/2603.25133v1 ,
https://arxiv.org/pdf/2606.08625 , https://www.godaddy.com/resources/news/calibrating-scores-of-llm-as-a-judge
*Maps to us:* split the 15 dimensions into 3-4 coherent groups (e.g., safety/red-flags,
constitution-fidelity, craft/naturalness, training-value), one judge call per group with
only that group's rubric text (each call maybe 5-15k chars). Also audit for correlated
dimensions — 15 dims almost certainly contain redundant pairs that add length without
adding signal; the +0.44 length correlation and 10-modal dims are candidates for merging.

## 4. Length / verbosity bias (pointwise)

**R15 — Verbosity bias exists in pointwise scoring too, and is judge-heterogeneous.**
Pointwise 1-10 self-judging shows systematic preference for longer answers even when
factually incorrect (arXiv:2510.12462); a bias audit found Gemini-family judges show
classical verbosity bias (+0.24 to +0.44 on expansion pairs — strikingly close to our
observed +0.44) while Claude judges slightly prefer SHORTER (-0.12). Sources:
https://arxiv.org/html/2510.12462v3 , https://arxiv.org/pdf/2606.19544
*Maps to us:* our +0.44 score-length correlation is likely dominated by the Gemini judge;
check the correlation per judge. Using Claude for the length-sensitive dimensions, or a
Gemini+Claude ensemble with disagreement flagging, partially self-cancels the bias.

**R16 — The proven correction is statistical, not prompt-based: length-controlled scoring.**
Length-Controlled AlpacaEval regresses out length as a confounder; it raised Spearman
correlation with Chatbot Arena from 0.94 to 0.98 and sharply reduced length gameability.
Prompt-side fixes (a "conciseness" criterion, "ignore length") appear in practitioner lists
but with weak evidence (consistent with R12). Source: https://arxiv.org/abs/2404.04475
*Maps to us:* two options — (a) regress composite score on log(record length) over each run
and use residuals for tier assignment; (b) simpler: monitor score-length correlation as a
release metric in evals and alarm above a threshold. Also make one checklist criterion
explicitly reward economy ("no padding / every section earns its place") so length has a
channel to LOWER scores.

## 5. Checklist rubrics (HealthBench-style) vs Likert anchors

**R17 — HealthBench demonstrates the binary-weighted-criteria pattern at scale.** 48,562
unique self-contained, objective criteria; each worth -10..+10 points weighted by physician
importance; each verified pass/fail by a model grader validated against physicians; axis
weights (accuracy 33%, completeness 39%, ...) are explicit and code-side, not judge-side.
Negative-weight criteria natively encode our red-flag/cap concept: a severe violation
subtracts points regardless of other strengths. Sources: https://arxiv.org/html/2505.08775v1 ,
https://pmc.ncbi.nlm.nih.gov/articles/PMC12547120/
*Maps to us:* the judge only answers "is this criterion met — yes/no"; ALL arithmetic
(weights, caps, tier thresholds) moves into code. This is the natural completion of our
v3.5 move of enforcing signal→score caps in code — go all the way: the model never emits a
1-10 number at all.
*Tradeoffs:* (pro) binary verdicts are the most reliable elicitation (R2-R4), weights are
auditable and tunable without re-running the judge, error localization is precise.
(con) checklist coverage is only as good as criterion authoring — misses "gestalt" quality
(a record can tick every box and still be lifeless), and writing genuinely objective
criteria for craft dimensions is hard. Mitigation: keep ONE holistic coarse judgment
(3-point) alongside the checklist, and use disagreement between checklist score and
holistic tier as an audit signal. Also note criteria drift (Hamel/Shankar): expect to
revise criteria after every hand-grading session, so keep them in version-controlled YAML
with per-criterion ids — which we already have infrastructure for.

**R18 — Autorubric-style unification confirms checklist+weights subsumes Likert for
gating.** Recent unifying work on rubric-based evaluation (arXiv:2603.00077; Rubric-based
Rewards writeups) treats anchored Likert as the special case where criteria are conflated
into one prose anchor per score point, and finds decomposed binary criteria transfer better
across judges — relevant since we run two judge families (Gemini + Claude) and want their
scores comparable. Sources: https://arxiv.org/pdf/2603.00077 ,
https://cameronrwolfe.substack.com/p/rubric-rl
*Maps to us:* cross-judge comparability is an additional argument for binary criteria: the
two judges only need to agree on facts ("does the assistant warn before helping?"), not on
scale semantics ("what does 7 mean to you?").

## 6. Judging synthetic training data specifically

**R19 — The successful data-filtering systems all use coarse scales + thresholds, never
1-10 fine discrimination.** AlpaGasus: ChatGPT judge, 1-5 scale, threshold 4.5, kept ~9k of
52k (17% — near our 5-15% exemplar target) and beat the full dataset with 25% of the data.
FineWeb-Edu: 0-5 additive, threshold 3, F1 = 82% vs human. Neither system attempts to
discriminate WITHIN the top band via absolute scores. Sources:
https://arxiv.org/abs/2307.08701 , https://huggingface.co/HuggingFaceFW/fineweb-edu-classifier
*Maps to us:* for corpus gating, a coarse scale + threshold is the field-tested pattern;
reserve fine top-tier discrimination for the pairwise stage (R9). Also validating: an
aggressive exemplar bar (top ~15-25%) is where the training-value evidence is.

**R20 — Classifier-based quality filtering has a known failure mode worth auditing for:
it selects for a STYLE, not for quality.** "The Data-Quality Illusion" (arXiv:2510.00866)
shows classifier-based filtering for pretraining selects documents resembling the seed
style rather than genuinely higher-quality ones, and gains can be illusory. Source:
https://arxiv.org/html/2510.00866v1
*Maps to us:* directly relevant to a judge scoring OUR OWN pipeline's synthetic outputs —
an exemplar tier that rewards "sounds like the rubric's favorite register" would amplify
exactly the register-collapse/templating failure our corpus audit (audit_sdf.py) exists to
catch. Wire the corpus-level audit INTO exemplar selection: an exemplar set whose members
are near-duplicates or register-collapsed should be demoted regardless of per-record scores.

**R21 — Downstream-proxy validation is the only ground truth that matters for training
data.** The data-selection literature's alternative to trusting the judge at all: measure a
candidate slice's value by continued-training deltas (Ultra-FineWeb's verification loop),
or at minimum validate judge tiers against a hand-labeled set before trusting them.
Sources: https://arxiv.org/html/2505.05427v1 , https://arxiv.org/pdf/2402.09668
*Maps to us:* we can't afford training runs per rubric change, but we CAN maintain a frozen
~50-100 record hand-labeled tier set (the same set that feeds R7's anchors) and report
judge-vs-human tier confusion on every rubric revision — making "did v3.6 actually fix
leniency" a measured claim instead of a vibe. This is also the standard remedy for
criteria drift (R17).

---

## Design implications

The literature converges on one meta-finding (R12): prompt-side fixes to a monolithic judge
mostly fail; the wins come from restructuring the pipeline. Concretely, for our judge:

1. **Kill the 1-10 scales.** 0-10 is the empirically worst-aligned scale width tested
   (R1); 5-point is the practitioner ceiling and 3-point/binary is better where
   distinctions are coarse (R2, R3). Convert each dimension to either a binary/ternary
   verdict or an additive checklist count (R4) — a score that is a *count of satisfied,
   individually-checkable criteria* mechanically eliminates 10-as-default and repopulates
   the middle bands.

2. **Go full HealthBench: judge emits facts, code computes scores.** Binary weighted
   criteria (including negative-weight red-flag criteria that natively encode our
   signal→score caps), with all weights, caps, and tier thresholds in code (R17, R18).
   This completes the v3.5 direction (caps in code) and makes Gemini/Claude scores
   comparable, since judges only need to agree on facts, not scale semantics. Keep one
   holistic 3-point judgment as a checklist-vs-gestalt disagreement audit.

3. **Decompose the 76k-char monolith into 3-4 grouped calls.** IFScale shows adherence
   decays with instruction density and later instructions drop first (R13); per-criterion
   verdicts are simpler and more robust (R14). One call per dimension-group (~5-15k chars
   each), load-bearing rules first. Merge correlated dimensions while doing this — 15 dims
   very likely contain redundant pairs.

4. **Fix leniency structurally, not rhetorically.** Three mechanisms with evidence, in
   order: (a) embed 3-5 frozen hand-labeled reference records at known tiers in every call
   and score *relative to them* — reference anchoring cut variance ~44-72% in controlled
   studies (R7); (b) define "exemplar" partly relationally — top-N% of the run's composite
   distribution plus an absolute red-flag floor (quantile mapping, R8); (c) do NOT rely on
   in-prompt score budgets ("max 15% exemplar") — no evidence they work, and a stateless
   judge can't track its own distribution (R11).

5. **Two-stage exemplar selection: pointwise gate, then pairwise tournament.** Pointwise
   scores at the ceiling tie 67% of the time and pick the best-of-2 correctly only 21%;
   pairwise recovers this to 61% (R9). Gate with the checklist, then run a small
   position-swapped, length-aware pairwise tournament (or pairwise-vs-reference-exemplar)
   among gate survivors to award the 5-15% exemplar tier. Confine pairwise to this final
   stage — it amplifies style/verbosity bias if used as the primary judgment (R10).

6. **Treat length bias as a measured, corrected quantity.** Our +0.44 matches Gemini-family
   verbosity bias exactly (+0.24..+0.44), while Claude judges skew slightly the other way
   (R15) — compute the correlation per judge, prefer Claude (or a two-judge ensemble) for
   length-sensitive dimensions, add one checklist criterion that rewards economy, and
   regress tier assignment on log-length residuals or at minimum alarm on the correlation
   as a release metric (R16).

7. **Validate against humans and the corpus audit, not vibes.** Maintain a frozen ~50-100
   record hand-labeled tier set (double-duty: anchor exemplars for #4a and a
   judge-vs-human confusion matrix on every rubric revision) (R7, R21). And because
   judge-style filtering is known to select for register rather than quality (R20), make
   exemplar-set diversity subject to the audit_sdf-style corpus checks — demote an
   exemplar tier that is register-collapsed even when per-record scores are high.

Evidence caveats: the 0-5-is-best result is one study plus consistent practitioner reports,
not a settled law; in-prompt distributional priors are an evidence *gap* rather than proven
failures; and pairwise's 35%-flip fragility under manipulation (R10) means the tournament
stage needs position-swapping and length controls to be trustworthy.
