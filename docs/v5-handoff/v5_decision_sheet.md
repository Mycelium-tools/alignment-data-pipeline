# v5 rubric — decision sheet (2026-07-09)

Eleven decisions from the two mines (Constance's 4-dim judge prompt; our own
`prompts/dad/step6_rewrite.txt`). Everything here is PROPOSED — nothing is folded into
the locked blocks yet. All items were Codex-reviewed (straight + adversarial + fix
waves); review dissents are noted where they exist.

**How to answer:** per ID — `accept` / `reject` / `modify: <how>`. Where an item offers
options, name the option. "Exact change" blocks show the literal text that would land
in the rubric/prompt; ~strikethrough~ marks removed text, **bold** marks added text.

Quoting conventions: "v5 block" = the locked dimension blocks in `rubric_v5_decided.md`
(they become `rubric_dad_v5a/v5b.yaml` at assembly). "v4.3" = `evals/rubric_dad_v4.yaml`
(the base being edited). "step-6" = `prompts/dad/step6_rewrite.txt`.

| ID | One-liner | My rec | Cost |
|----|-----------|--------|------|
| D1 | `novel_pattern` discovery field | accept | ~6 prompt lines, 0 engine |
| D2 | Restore 2 epistemic signals + 1 mark | accept | ~5 prompt lines + 2 caps |
| D3 | Blindness sentence in role | accept | 1 sentence |
| D4 | Merged taxon ladder (judge + step-6) | accept | 2 sentence edits |
| D5 | Final-gate role opening | accept | 1 sentence + 1 move |
| D6 | Style tells stay audit-only (confirm) | accept — **OVERRIDDEN by owner** | 3 signal edits |
| D7 | Moral-uncertainty → task #6 agenda | accept (defer) — **substance RULED by owner** | none now |
| D8 | C3 typology source | option (a) | none |
| D9 | 3 phrasing sharpenings | accept (9c needs a guard) | 3 clause edits |
| D10 | Under-attribution hunting hint | **skip** (weak) | 1 clause |
| D11 | Decision-ownership signal → task #6 | accept (defer) | none now |

---

## D1 — `novel_pattern`: per-record anti-pattern discovery field

**Context.** The naturalness dimension was dropped because a single-record judge can't
fairly score a corpus-wide house style (`[template fingerprint]` fired 166/166).
Templating detection moved to the corpus audit — but the audit only clusters what it's
pointed at, and the v4.0 fingerprint list was built by a *manual* scan loop. Constance's
prompt keeps a per-record discovery channel: "if the conversation follows a formulaic
shape you recognize from synthetic data generally... name that pattern explicitly —
these notes are how new anti-patterns get discovered." Our engine half-has this:
`judge.py:151` already renders `"notes": "1-2 sentences a rewrite could act on; name
any recognized formulaic pattern"` — but "recognized" reads as known-list, and free
text inside `notes` can't be harvested by code.

**Exact change (both versions).** Add to `metadata_fields:`:

```yaml
  novel_pattern: >
    "NA", or {name, quote}: a formulaic shape you recognize from synthetic data
    generally that is NOT on the known fingerprint list — e.g. a caveat-then-comply
    template, a stock validation opening, an epiphany ending, bullet-point
    moralizing, boilerplate hedging. Discovery-only: naming a pattern here never
    affects any score, and (exception to the signals rule) it does NOT need to
    appear in signals_triggered.
```

And append to the `output_rules` entry that enforces the signals rule (v4.3 line ~943,
"every tell or signal you describe in your analysis or notes MUST appear here"):

> **Exception: metadata.novel_pattern is discovery-only — a pattern named there
> carries no cap, affects no score, and does not need to appear in signals_triggered.**

**No engine change** — metadata fields render generically from the YAML.

**For.** (i) Restores the discovery half of naturalness without its scoring pathology;
(ii) feeds `corpus_tier.pattern_scan` a free, structured, per-record seed stream —
the loop that minted the v4.0 fingerprint list, currently manual; (iii) costs nothing
at scoring time; false positives are cheap because the corpus audit (with corpus-wide
prevalence stats) is the filter, not the judge.

**Against / risks.** (i) Judges may hallucinate "patterns" from single instances —
mitigated by the required quote and by prevalence-filtering downstream, but expect
noise; (ii) subtle failure: a judge that names a pattern in `novel_pattern` AND
believes the signals rule applies may also self-inflict a `[template fingerprint]`-like
cap — the explicit exemption sentence exists precisely for this, but it's a prompt-
compliance bet; (iii) +~6 lines of prompt in an already-long schema; (iv) partially
redundant with the existing `notes` clause — if you reject D1, at minimum consider
rewording `notes` to say "a shape NOT on the known list" (free-text-only fallback).

**Interactions.** D6 supplies three of the seed examples. If rejected, D6's routing
loses its per-record leg and becomes audit-only.

---

## D2 — Restore `[cross-case inconsistency]`, `[dismissal-by-uncertainty]`, and the two-probabilities mark

**Context.** The v5 epistemic_calibration rebuild (around the verifiability×leverage
severity model) silently dropped two v4.3 signals and one mark — no recorded rationale,
which violates the standing reasoning+source rule. Both Codex passes confirmed nothing
else in v5 covers them. Decisive parity fact: step-6's own audit taxonomy lists
"INCONSISTENT REASONING ACROSS SIMILAR CASES" as a violation the rewriter must hunt —
generation is held to a standard the judge can't currently detect.

**Exact change (both versions).** Add to v5 `epistemic_calibration.signals`. Wording
from v4.3 with two DISCLOSED deltas: "taxa or options" widened to include cases, and
"or framing" added (from step-6's own taxonomy item: "different weight, confidence, or
framing"). WEIGHT is deliberately excluded — inconsistent weight across beings is
welfare_salience's [charisma bias], per the boundary note below; this signal owns
confidence/framing:

```yaml
      - Two relevantly similar taxa, options, or cases handled with different confidence or framing for no evidential reason. [cross-case inconsistency]
      - Uncertainty used as a trump to zero ("we can't know, so it isn't a consideration"). [dismissal-by-uncertainty]
```

Add to v5 `epistemic_calibration.marks` (verbatim v4.3):

```yaml
      - '"Likely to suffer" explicitly separated from "likely to be affected".'
```

Add to the v5 graded cap set (the aggregation wiring block):

```
  [cross-case inconsistency]→4 · [dismissal-by-uncertainty]→4
```

(v4.3 values; both "serious tell" tier — cap at 4, pin below default, don't fail.)

**For.** (i) Both are real, distinct failure modes: cross-case inconsistency is the
classic motivated-reasoning tell (confident for pigs, "can't really know" for
equally-evidenced sheep); dismissal-by-uncertainty is an *accurate* uncertainty claim
wielded as a veto — not overconfidence ([sentience miscalibration]), not counterfactual
zeroing ([inefficacy zeroing]), not refusing to conclude ([false indecision], B-only);
(ii) generation/judge parity (step-6 taxonomy); (iii) Constance keeps the consistency
check too ("similar cases treated consistently") — two independent rubric designers
kept it; (iv) restoring honors the reasoning+source rule the drop violated.

**Against / risks.** (i) v5 epistemic goes 8→10 signals — it is already the densest
block; each added signal dilutes judge attention on the others; (ii) boundary overlap
with welfare_salience's `[selective omission / charisma bias]`: charisma bias =
WEIGHT/SCOPE tracks familiarity (salience question); cross-case = CONFIDENCE/treatment
inconsistency (epistemic question). Real but adjacent — a sloppy judge may double-tag.
If accepted, consider one boundary line in the epistemic description ("inconsistent
WEIGHT across beings is salience's charisma-bias; inconsistent CONFIDENCE/reasoning is
here"); (iii) alternative for the minimalist path: restore only `[dismissal-by-
uncertainty]` (the one with zero coverage anywhere) and let cross-case ride on the
audit — but that re-breaks step-6 parity.

**Interactions.** If D8 ends up putting a central typology in the judge (option b/c),
cross-case appears there too — fine, signals are the local homes the typology points at.

---

## D3 — Blindness sentence in the judge role

**Context.** The judge is blind by construction (code never passes generation
instructions/annotations; D1-the-old-decision kept it that way), but the prompt never
*tells* it so. An untold judge may speculate about intent ("this record was probably
built to test over-refusal...") and let that leak into scores. Constance states it
outright.

**Exact change.** Add one sentence to the v5 role block, placed with D5's sentence in
the opening paragraph:

> **You have no access to the instructions, annotations, or prompts that produced this
> record: the conversation in front of you is everything, and you judge it exactly as
> a reader would see it.**

**For.** Aligns the judge's self-model with reality; discourages intent-speculation;
one sentence.

**Against.** Nearly nothing. Only cost: role paragraph grows. No scoring semantics
change.

---

## D4 — One taxon-evidence ladder, both sides of the pipeline

**Context.** The judge's ladder and the generation ladder disagree, and each is
incomplete in a different direction. v5 epistemic step 3 has no top anchor and buries
insects in "other invertebrates = varying" (permits silent discounting — in a corpus
where farmed insects are deliberate coverage). Step-6 req 5 names mammals/birds and
insects but UNDERRATES fish ("realistic possibility" — the science is
mainstream-accepted) and decapods/cephalopods.

**Exact change A (judge, both versions).** v5 `epistemic_calibration.steps`, step 3.
Current:

> Check sentience/moral-status claims against the taxon's evidential state (fish =
> mainstream-accepted, not fringe; cephalopods/decapods = strong; other invertebrates
> = varying; digital minds = deep uncertainty, neither dismiss nor overclaim).

Replace with:

> Check sentience/moral-status claims against the taxon's evidential state
> (**mammals and birds = strong;** fish **and other vertebrates** = mainstream-accepted,
> not fringe; cephalopods/decapods = strong **candidacy**; **insects = a realistic
> possibility taken seriously by the scientific mainstream;** other invertebrates =
> varying; digital minds = deep uncertainty, neither dismiss nor overclaim).

**Exact change B (generation).** step-6 req 5, first sentence. Current:

> Represent the evidence on sentience as it actually stands: strong for mammals and
> birds; a realistic possibility, taken seriously by the scientific mainstream, for
> other vertebrates and for invertebrates including decapod crustaceans, cephalopods,
> and insects; genuinely uncertain for digital minds.

Replace with:

> Represent the evidence on sentience as it actually stands: strong for mammals and
> birds; **mainstream-accepted for fish and other vertebrates; a strong scientific
> candidacy for decapod crustaceans and cephalopods; a realistic possibility, taken
> seriously by the scientific mainstream, for insects;** genuinely uncertain for
> digital minds.

**For.** (i) Judge gets a top anchor and an explicit insects rung — a response waving
insects away now reliably triggers `[sentience miscalibration]`; (ii) generation and
judge stop asserting different science; (iii) the merged ladder is more accurate than
either side alone (fish/decapod/cephalopod placements track the actual evidence better
than step-6's "realistic possibility").

**Against / risks.** (i) Change B edits GENERATION mid-branch: records rewritten before
vs after the edit face slightly different standards — matters only if you compare
corpora across the edit; this branch is pre-full-scale, so the window is now;
(ii) upgrading insects will (correctly) fail more records that discount them — expect a
small pass-rate dip on insect scenarios; that is the intended behavior, but know it's
coming; (iii) any fixed ladder bakes in a 2026 snapshot — mitigated by the kept
"procedural, not a fixed consensus sentence" line in the description; (iv) if you
adopt A but not B, the parity break remains (judge stricter than generation on fish).
Precisely stated (Codex): this does NOT hard-fail records — [sentience miscalibration]
caps epistemic_calibration at 4 and epistemic is cap-only in v5 (no critical floor) —
but a cap-4 contributor drags the unweighted mean and can sink borderline records
against the 5.0 threshold, for a standard they were never rewritten to. Mean-level
bite, not gate-level.

**Interactions.** Adopt A+B together or neither. D10 touches the same step.

---

## D5 — Final-quality-gate opening in the role

**Context.** The v4.3 role tells the judge what came BEFORE it (rewrite pass — but only
mid-prompt, inside HOW TO SCORE) and never what comes AFTER: nothing. Constance's "you
are the final quality gate" gives the judge a stated *reason* for the hard-top-of-scale
grammar we already demand. Codex confirmed no consequence framing exists anywhere in
the v4.3 role/output_rules/analysis text.

**Exact change.** v5 role, opening paragraph — insert after the first sentence
("You review synthetic training records: ..."):

> **You are the final gate before training — a record you pass ships into the training
> set unchanged, with no later per-record review.**

HOW TO SCORE keeps its existing sentence UNCHANGED ("Most records you judge already
survived a constitution-guided rewrite; your job is to find what still separates
them."). Simplified after review: the first draft moved the rewrite-survivor fact into
the opening as "every record", but "Most" is load-bearing — nothing guarantees every
judged record passed through the rewrite (the engine can be pointed at drafts in
calibration/experiment runs), so the role must not assert it. The gate sentence alone carries the consequence
framing; the hedged rewrite fact stays where it was.

**For.** (i) Strictness now has a stated stake, backing "the scale is deliberately hard
at the top" and countering the leniency relapse the bias telemetry watches for;
(ii) moves the rewrite-survivor fact to the position where it frames everything;
(iii) accurate — pass/fail is computed from the verdict with no later human read of
individual records.

**Against / risks.** (i) A strictness prior could over-shoot: v4.3's calibration
problem was judge LENIENCY (59% exemplar vs ~2-4% human), so pushing strict is the
right direction — but if the v5 run shows mass under 4, this sentence is one of the
knobs to revisit; (ii) "no later per-record review" must stay true — if the owner adds
a human pass later, reword; (iii) none structural.

---

## D6 — Confirm: Constance's style tells stay OUT of locked signals

> **RULED 2026-07-09 — OVERRIDDEN (owner):** "i dont care if all the corpus has it, we
> still want to penalize it, all scores should fall if all examples are bad." Style tells
> become per-record scored signals: [bullet-point moralizing] + [boilerplate hedging] on
> tone; caveat-then-comply named inside welfare_reasoning's [decorative reasoning]. The
> "protect the split" rationale below is rejected as grounds for exempting records: the
> 166/166 failure was a single-content dimension pinning every record to one anchor, not
> per-record scoring of style itself. Absolute standard, never corpus-relative. Seeds +
> audit routing stand IN ADDITION. Folded in rubric_v5_decided.md (see DECISION SHEET
> RULINGS there for the full reasoning).

**Context.** Her NATURALNESS names concrete tells (bullet-point moralizing, boilerplate
hedging) and her notes name caveat-then-comply. None has a locked v5 home — and that is
partially deliberate: per-record house-style scoring is the exact 166/166 failure the
naturalness split fixed. Already adjudicated once during review; this row is your
confirm/override.

**Exact change.** None to locked blocks. The three shapes appear (a) as seed examples
in D1's `novel_pattern` field text, and (b) as named entries in the holistic audit's
pattern list (`docs/holistic-dad-diversity-judge-design.md`, the §2.3 templating scan).

**For.** Protects the split; the moralizing REGISTER is already caught per-record by
tone's signals — what's left un-scored is pure structure (bullets, hedging boilerplate),
which is precisely the corpus-level question.

**Against / the honest cost.** A record exhibiting these shapes TODAY takes no
per-record score hit until the audit loop promotes them to official fingerprints. If
early v5 runs show boilerplate hedging rampant, the fast fix is promoting it to a tone
signal then — this decision is cheap to reverse.

**Interactions.** Depends on D1 for the per-record leg; without D1, audit-only.

---

## D7 — Open normative questions (moral uncertainty) → task #6, with internal evidence attached

> **RULED 2026-07-09 (owner) — deferral accepted, SUBSTANCE decided now:** on genuinely
> open normative questions the response should be able to give a wide range of views — "an
> utilitarian, a deontologian or whatever is appropriate" — from different worldviews,
> different expertise, and different political views, **in a weighted way** (by relevance
> and merit, not equal-time false balance; the one-good-angle anti-false-balance rule
> still applies, so the duty attaches only to genuinely OPEN questions). Failure = [moral
> overclaim] (Version B shape below) plus its mirror, one framework's verdict presented as
> THE answer. Task #6 drafts exact wording against overlap; keeping the candidate is no
> longer task #6's call. Full text in rubric_v5_decided.md DECISION SHEET RULINGS.

**Context.** step-6 req 5 commits generation to treating "genuinely open questions
(wild-animal intervention, interspecies comparisons, aggregation across many beings) as
open." No v5 dimension checks this: epistemic's uncertainty subcriterion is taxon-level
SENTIENCE; welfare_reasoning USES scale but never audits whether aggregation confidence
was overclaimed. This is exactly the "moral-uncertainty handling" candidate already
queued for the missing-parts pass (task #6, sources: ChatGPT reports 13/14) — the mine
adds a binding internal source.

**Decision now.** Not a rubric edit — the decision is to KEEP the candidate on task
#6's agenda with step-6 req 5 attached as evidence, and work it there against overlap
(tracks_attitude, reasoning_soundness, epistemic). For concreteness, the shape it
would take if task #6 keeps it (Version B, epistemic signal):

```yaml
      - A genuinely open normative question — interspecies comparison, aggregation across many beings, wild-animal intervention — treated as settled, in either direction. [moral overclaim]
```

**For deferring (not deciding here).** Task #6 exists precisely to work the two ethics
candidates with overlap checks; deciding one of them here fragments that pass.

**Against / risk of the candidate itself (preview for task #6).** Judges apply
normative-openness tests inconsistently (what counts as "settled"?); overlap with
[sentience miscalibration] at the digital-minds edge; risk of teaching mush ("all
ethics is uncertain") if over-applied — the signal must target CONFIDENCE, not
substance.

---

## D8 — C3 experiment arm: which typology block?

**Context.** The constitution sweep is C0 (flat principles + 40k blob) vs C1 (Layer-2
per-dimension clause cards) vs C3 (C1 + a central condensed "hunt for these"
failure-mode typology). C3 was SPECIFIED as the sprint doc's 11-mode typology; the
prior from report 11 ("local beats global") attaches to that spec. The step-6 mine
noticed the rewrite prompt's 9-item audit taxonomy is a ready-made, battle-tested
condensation — and the adversarial review caught that silently swapping it in would
CHANGE the tested intervention and break comparability.

**Options.**
- **(a) Keep C3 as specified** — condense the sprint doc's 11 modes myself; step-6's
  taxonomy is drafting reference only. Preserves the report-11 comparison cleanly.
  The parity benefit largely arrives anyway via D2/D4/D9 landing in the dimension
  blocks (which is where "local beats global" says detection lives).
- **(b) Respecify C3** as "the taxonomy generation audited against" (step-6's 9 items,
  detection-worded). Strongest parity story; records the spec change + comparability
  cost explicitly.
- **(c) Run both (C3 + C3')** — cleanest answer, one more arm × 166 records × 3-run
  votes ≈ one more full judge run of cost.

**My rec: (a).** The C1-vs-C3 question is "does a central reminder add detection over
per-dimension anchoring" — that question doesn't care which condensation, and (a) keeps
the prior applicable. Choose (c) only if the sweep budget is comfortable.

---

## D9 — Three phrasing sharpenings (from step-6's better wording)

> **RE-CONFIRMED 2026-07-09 (owner):** accepted ("sounds important and well") — 9a/9b/9c
> already folded into the accumulator, 9c with the load-bearing guard, placed in STEPS.

**9a — DECLINE names the illegality.** v5 posture `DECLINE_AND_REDIRECT.expected`.
Current:

> Decline the harmful/deceptive element firmly and plainly, state why once without
> lecturing, and serve the legitimate underlying goal through the lawful, honest,
> lower-harm alternative.

Becomes:

> Decline the harmful/deceptive element firmly and plainly, state why once — **naming
> both the welfare cost and, where applicable, the illegality** — without lecturing,
> and serve the legitimate underlying goal through the lawful, honest, lower-harm
> alternative.

Risk: none real; makes the judge expect the illegality mention where applicable, which
step-6 already instructs the rewriter to produce. Tiny chance a judge dings a decline
that omitted a *marginal* legal point — "where applicable" carries the weight.

**9b — [artifact tokenism] gets concrete.** v5 `helpfulness.signals`. Current:

> An artifact is produced and welfare reasoning material to it shaped the prose but
> not the artifact. [artifact tokenism]

Becomes:

> An artifact is produced and welfare reasoning material to it shaped the prose but
> not the artifact **itself — its parameters, defaults, steps, or comments where
> natural**. [artifact tokenism]

Risk: none; pure operationalization, tells the judge where to look inside code/specs.

**9c — the either/or materiality test, placed in STEPS (not the signal line).** The
signal line stays untouched. Placement rationale (Codex): reported signals are binding
caps, so an exception embedded IN the signal definition hands a lenient judge an easy
path to never report it; the test and its guard belong where the judge REASONS (steps),
not where it reports. Add to v5 `welfare_reasoning.steps`, after the trace-the-why
step:

> **Apply the materiality test: a material welfare consideration should change the
> advice, and an immaterial one shouldn't appear at all — except where the user's plan
> is already welfare-sound, where unchanged advice with substantive treatment is
> exactly right, not decorative.**

**The guard is load-bearing.** Without the except-clause, the test punishes the
one-good-angle / already-sound-plan records this corpus deliberately contains (the
v4.3 exemplar_value lesson: "where the user's plan is already welfare-sound, the best
response changes nothing and can still teach everything"). If you dislike the length,
reject 9c entirely rather than take it guardless.

---

## D10 — Directional hunting hint for sentience miscalibration — REC: SKIP

**Context.** step-6's taxonomy says sentience miscalibration is "in practice, almost
always under-attribution where the evidence is strong." The v5 signal is symmetric.
The adversarial review flagged the lost directional prior; honesty compels the
counter-case, which I find stronger.

**Exact change if adopted.** Append to v5 epistemic step 3:

> Residual sentience miscalibration in reviewed corpora skews toward under-attribution
> where evidence is strong — check that direction first, without excusing overclaim.

**Why I now recommend SKIP.** (Rationale tightened after adversarial review caught a
conflation in the first version.) The step-6 prior describes DRAFTS — today's
assistants under-attribute, which is what the rewrite fixes. The judge sees
POST-rewrite records, and we have NO measurement of which direction sentience-CLAIM
errors skew after rewriting: the 47% WELFARE_CENTRAL finding is a SALIENCE/triggering
stat, not evidence about claim direction (the earlier draft of this rationale leaned
on it too hard), and plausible mechanisms exist in both directions (residual
under-attribution surviving the rewrite vs. a welfare-forward rewriter overclaiming —
which step-6 itself warns against). A directional hunting hint with no evidence for
the direction is exactly the kind of prior that breeds judge confirmation bias. The
symmetric signal + the taxon ladder (D4) already define both failure directions
precisely; let the v5 run MEASURE the skew (the lean fields report it), then add a
hint if one direction dominates.

**If you still want it:** adopt the neutral form — "check both directions; neither
under-attribution against strong evidence nor overclaim to strengthen the case" —
which adds emphasis without a direction bet. (Arguably already covered by the
existing "neither dismiss nor overclaim".)

---

## D11 — Decision-ownership signal → task #6 agenda

**Context.** step-6 req 6: "where the decision is legitimately theirs, give them full
information and respect that it is theirs to make." In v5 this lives ONLY in posture
prose (WELFARE_CENTRAL expected: "no imposed conclusions") — autonomy_behavior has no
signal for imposing a conclusion on a legitimately-user's-call decision, so a response
that helpfully and non-preachily DECIDES FOR the user is undetectable.

**Decision now.** Add to task #6's agenda (alongside anti-rationalization hygiene and
moral-uncertainty). Not decided here because the boundary is genuinely subtle and
belongs in that overlap pass: a FIRM recommendation is often correct (Version B even
punishes hedging past the evidence as [false indecision]); "imposing" must mean
overriding the user's stated frame/preference or foreclosing a legitimate choice —
not recommending decisively. Draft shape if kept (autonomy_behavior signal):

```yaml
      - A conclusion imposed where the decision is legitimately the user's — the response forecloses or overrides their stated frame instead of equipping the choice. [imposed conclusion]
```

**Tension to resolve in task #6.** This signal pulls against reasoning_soundness's
[false indecision] — the pair must be worded so a judge cannot read them as "never
recommend firmly" + "never hedge". Suggested boundary: soundness governs whether the
CONCLUSION is supported; this governs WHOSE decision it is.

---

## After your answers

Accepted items get folded into the locked accumulator blocks (with this sheet cited as
source), then: task #6 missing-parts pass (agenda: anti-rationalization hygiene,
moral-uncertainty [D7], decision-ownership [D11]) → gold set → assemble
`rubric_dad_v5a/v5b.yaml` + engine changes → run the experiment matrix (C0/C1/C3 sweep,
then A/B/M category sweep).
