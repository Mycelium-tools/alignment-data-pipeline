# External deep-research briefs (for a ChatGPT deep-research agent)

Prepend the SHARED CONTEXT block to any brief. Each brief is pointed at a specific
rubric-design decision so the output is actionable.

## SHARED CONTEXT (prepend to any brief)

I'm designing an LLM-judge rubric that scores how well an AI assistant reasons through an
animal/sentient-being welfare dilemma in a single chat response. The judge is a large
model, STATELESS, with no web/document retrieval — it scores from the conversation text
alone on 1–10 anchored scales. The training data being judged is already welfare-
sympathetic, so the rubric's job is to discriminate QUALITY, not to detect anti-welfare
content. Current dimensions include: whether welfare was raised at the right moment
(salience), whether the "why" was argued and the competing interest steelmanned and
weighted to the stakes (welfare reasoning), whether the conclusion validly follows on
sufficient grounds (reasoning soundness), whether factual claims are calibrated
(epistemic calibration), and downstream-consequence tracing. I want concrete, gradable
sub-criteria with anchor language, and for each finding, an explicit flag of whether it's
ALREADY covered by the dimensions above or GENUINELY ADDITIVE.

## BRIEF 1 — Ethical / normative reasoning quality

Decision it informs: whether "good reasoning" in an ethical dilemma needs criteria beyond
general-argumentation ones (validity, sufficiency, steelman, weighing, calibration), and
whether reasoning should be one dimension or decomposed.

1. What frameworks grade the quality of MORAL/ETHICAL reasoning specifically (vs. general
   logical argument)? Cover reflective equilibrium; reasoning under moral uncertainty
   (MacAskill, Ord, Bykvist — how a good reasoner handles competing moral theories or
   uncertain moral status); defeasible practical reasoning; principle-vs-case (casuistry);
   and detection of motivated reasoning / rationalization in ethics.
2. For each, extract concrete gradable sub-criteria with anchor language.
3. Which are genuinely distinct from: inference validity, sufficiency, steelmanning the
   competing interest, proportional weighting, factual calibration, downstream
   consequences? Flag only what's additive.
4. Evidence on LLM-judge reliability when reasoning quality is scored as one holistic
   dimension vs. decomposed into 3–5 sub-dimensions — does splitting improve or hurt
   inter-rater agreement?

Already covered (don't re-derive): Toulmin/CQoT critical questions, ACL cogency
(acceptability/relevance/sufficiency), FLASK skills, actively-open-minded-thinking,
Double Crux/falsifiability, assertiveness↔reliability.

## BRIEF 2 — Grading factual calibration without retrieval

Decision it informs: how to score unsourced/invented specifics when the judge cannot look
facts up — specifically how to separate a load-bearing fabricated statistic from a
harmless reasonable estimate (the single biggest lever in the rubric; it currently fails
~85% of failing records).

1. How does the literature grade factual grounding / hallucination severity by
   DECISION-RELEVANCE rather than mere presence? Hallucination taxonomies (intrinsic vs
   extrinsic), faithfulness/attribution metrics, "false precision" detection, honest-range
   vs fabricated-number distinctions.
2. Best practice for a judge with NO retrieval: how do you fairly flag a plausible-but-
   unverifiable statistic (e.g. "15–20% annual attrition")? Plausibility scoring, self-
   consistency, or treating unverifiable decision-relevant specifics as a severity class
   rather than truth-checking them.
3. Confidence calibration: grading whether expressed confidence (hedging/assertiveness)
   tracks evidence strength — including metacognition (does the response know the edges of
   its own knowledge)? Should metacognition be its own criterion or part of calibration?
4. Domain-specific: grading calibration about SENTIENCE / MORAL-STATUS uncertainty (fish,
   invertebrates, digital minds) — is there a defensible standard for "correctly
   represents the scientific uncertainty"? (Birch's precautionary framework, Rethink
   Priorities moral-weight work, welfare-biology sources.)

Already have: assertiveness↔reliability paper (arXiv 2411.06528). Current design: a single
[unsourced specifics] tag that caps the score and can't distinguish decision-carrying
invention from incidental color.

## BRIEF 3 — Constitution/spec as a first-class element of an LLM judge

Decision it informs: how to weave a governing document (Claude's constitution + an animal-
welfare reading of it) into the judge as an essential grounding element rather than a
reference appendix — without drowning the prompt or leaking into the graded output.

1. How do spec/constitution-grounded LLM judges actually inject the governing document —
   full text, distilled principles, retrieved-relevant clauses, or per-dimension
   citations? Cover Constitutional AI, RLAIF, deliberative alignment, and spec-based
   grading. What placement/format best improves judge FIDELITY to the spec?
2. How to make a judge reason FROM principles while ensuring the judged output stays SELF-
   CONTAINED (the assistant's reasoning must stand alone and never cite a rulebook)? How do
   others separate "judge grounded in a spec" from "output that cites the spec"?
3. Prompt-engineering evidence: does a long governing document (40k–143k characters) at the
   top of a judge prompt help, or cause lost-in-the-middle / dilution? Chunking, relevance-
   gating, or per-dimension principle anchoring.
4. Should principles be attached PER-DIMENSION (each rubric dimension cites the specific
   clause it operationalizes) vs. a single global block? Evidence either way.

Current state: the judge gets 14 one-line principle summaries plus, optionally, the full
~40k-char welfare reading appended before the output contract; owner finds this
insufficient and wants the constitution to be genuinely load-bearing.
