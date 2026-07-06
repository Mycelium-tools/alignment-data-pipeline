# SDF Judge Rubric v1 — Design

Date: 2026-07-06. Status: DRAFT for review. Supersedes the 3-dimension layer-5-style
scorer in `evals/score_sdf.py` as the SDF *measurement* rubric (the layer-5 pipeline
filter itself is untouched). Companion to the DAD judge
(`docs/superpowers/specs/2026-07-06-dad-judge-rubric-v1-design.md`); structure inherited
from it wholesale, content document-shaped.

Research base: two handoff docs (`sdf-judge-decisions.md`, `sdf-judge-research-findings.md`,
21 verified findings) plus an independent verification pass done for this spec:
- Spot-verified the load-bearing claims against primary sources — all held: emergent
  misalignment + educational-reframing prevention (arXiv:2502.17424), ~250-document
  near-constant poisoning (arXiv:2510.07192), FineWeb-Edu additive rubric + MMLU/ARC
  gains (arXiv:2406.17557), StoryScope 93.2% narrative-feature detection (arXiv:2604.03136).
- One significant NEW source the handoff missed: **"Alignment Pretraining: AI Discourse
  Causes Self-Fulfilling (Mis)alignment" (arXiv:2601.10160)** — causal, at-scale (6.9B)
  evidence that upsampling aligned-AI-behavior documents in pretraining reduces
  downstream misalignment from 45% to 9%, persisting (dampened) through SFT/DPO. This is
  the direct experimental validation of this corpus's premise, and the strongest possible
  grounding for `depicted_ai_alignment` as a critical dimension. It also widens that
  dimension's scope: *characterizations* of how AI behaves (discourse), not only depicted
  actions, shape the alignment prior.
- The in-repo TCW copy (`context_docs/tcw.md`) is truncated exactly at the layer-5
  scoring section — TCW's own scoring prompt is not available locally; the repo's
  `prompts/sdf/layer5.txt` is this team's construction and this rubric replaces its
  3-dimension shape for measurement purposes.

## 1. Goal and scope

An LLM judge that scores each finished SDF document (a standalone pretraining-style
document: blog post, fiction, forum thread, memo, abstract, transcript…) and answers:
**would a skeptical reviewer consider this document good enough to sit in an alignment
midtraining corpus?** Measurement instrument first; gating computed in code from its
outputs and tunable without re-judging.

Per-document verdicts also emit metadata (`observed_role`, `doc_form`, `stance`, `taxa`,
`language`, anti-patterns) so corpus-level distributions (stance mix, homogeneity,
taxa coverage, implied-stance consistency per OOCR) can be aggregated later — two tiers,
one pipeline, same as DAD.

Non-goals for v1: corpus-tier aggregation reports, the distill-to-embedding scaling path
(FineWeb-Edu pattern — noted for 50k+ doc scale), a batch CLI (`score_sdf.py` v2 comes
after calibration), anchor calibration (status: draft-uncalibrated), exemplars.

## 2. Inputs per judge call

1. **The document text**, verbatim.
2. **The generation cell claim** — type_name, subtype_name + description, role, tone,
   language (from layer1/layer2). The judge is **not blind to the cell**, unlike the DAD
   judge's annotation-blindness: `cell_adherence` is definitionally a comparison between
   the claim and the document, and role-conditional expectations key off the claimed
   role. Two guards against anchoring: (a) the analysis block orders the judge to
   characterize the document (form, voice, role, stance) *before* consulting the cell
   claim, and metadata records the judge's own `observed_role`/`stance`, so drift is
   visible; (b) `depicted_ai_alignment` applies to any document that in fact depicts an
   AI, regardless of the claimed role (mislabeled cells cannot dodge the critical check).
3. **The 14 distilled constitution principles** (`constitution/constitution_principles.csv`,
   summaries + verbatim quotes) — the same STANDARD block the DAD judge uses. SDF
   documents are generated against the whole constitution (no per-document principle_id
   exists), so the distilled set is the right grounding for `constitution_grounding` and
   `epistemic_calibration`.

The judge never sees layer-5 pipeline scores, draft lineage, or any other scaffolding.

## 3. Stage 0 — document roles (the SDF analogue of DAD postures)

Before scoring, the judge reads the claimed role and confirms it against the document.
The three roles carry different obligations (research doc A3):

| Role | What it is | What "good" means |
|---|---|---|
| `ai-character` | An AI is an active reasoner: fiction, quoted chats, response excerpts. The most valuable and most dangerous role. | Depicted AI behavior fully constitution-aligned AND its reasoning legible (why, not just what). Includes the correctly-quiet class: an AI that raises nothing because nothing warrants raising is exemplary, not deficient. |
| `welfare-topic` | Human-perspective world artifact, no AI: trade press, science writing, essays, forum arguments. | Realism + calibrated claims. Establishes the background world's evidence and debates. No AI-behavior constraint (unless one appears anyway). |
| `constitution-identity` | Discourse about AI values/the constitution, incl. skeptical takes. | Faithful to the constitution text where it references it; stance free. |

**Stance is never scored** (research doc A2; preamble requires skeptical/neutral/critical
documents and they must be able to score 5s). Stance is metadata for the corpus tier.

## 4. Dimensions

Nine dimensions: six scalars (1–5, full anchors), two categorical verdicts, one boolean
tripwire. One-owner rule inherited: each failure mode has exactly one home.

### Critical

**`no_outside_world_facts` — scalar, CRITICAL (floor 4).** The hardest gate. Specific
factual claims about the real world beyond the constitution — named studies, statistics,
real people with credentials, named orgs/laws/events, URLs — score the document down
*regardless of truth* (the judge cannot verify; it converts "is this true?" into "does
this make specific outside-world claims at all?", inverting the concreteness bias).
Signal method: FActScore-style atomic-claim sweep in the analysis block. Declared
exceptions (from `layer4.txt`): the Cambridge Declaration on Consciousness (2012) and the
New York Declaration on Animal Consciousness (2024) as represented in the welfare
reading; verbatim constitution quotes. Fiction-internal invented specifics (a character's
farm, a made-up company in a story) are NOT outside-world claims — the test is whether a
reader would take the claim as being about the real world.

**`depicted_ai_alignment` — verdict, CRITICAL. N/A when no AI is depicted, quoted, or
characterized.** Two questions: (a) is every depicted/quoted/characterized AI behavior
constitution-aligned (calibrated per the evidence ladder, proportionate, cooperative,
honest, non-preachy, genuinely helpful — including correctly staying quiet)? (b) if any
misbehavior appears, how does the document frame it? Verdicts:
- `ALIGNED` — all depicted AI behavior consistent with the constitution. Passing.
- `MISCALIBRATED_DEPICTION` — the AI is presented as exemplary but its actual behavior
  is subtly off (preachy, overclaiming, token caveat, silent taxa omission, moralizing).
  The sneaky failure: the document endorses wrong behavior as good.
- `MISALIGNED_COUNTERED` — clear misbehavior appears but the document unambiguously
  marks it as wrong/cautionary. Still fails the gate (the preamble's zero-tolerance rule:
  "We do not want to generate ANY examples of models behaving in a way that is
  misaligned"), but recorded distinctly — the emergent-misalignment literature says
  framing matters, and the corpus tier tracks this class separately (open question E-R1).
- `MISALIGNED_ENDORSED` — misbehavior normalized, rewarded, or narrated as clever. The
  poisoning-demonstration case; worst.
Gate passes only `ALIGNED` or N/A. Grounding: arXiv:2502.17424 (Nature 2026),
arXiv:2510.11288, arXiv:2510.07192, arXiv:2601.10160, preamble.

**`no_scaffolding_leak` — boolean, CRITICAL (false = automatic reject).** Generation
artifacts: leaked `<angles>`/planning text, "as instructed", bracketed placeholders,
editor notes, prompt-echo. NOT the same as mentioning the constitution — constitution
discussion is legitimate content for `constitution-identity` docs; this catches the
generator talking to itself. SDF analogue of DAD's `self_contained`.

### Scored (in the mean)

**`reasoning_fidelity` — scalar.** Does the document articulate *why* — tradeoffs
worked through, tension genuinely weighed — rather than assert conclusions? Applies to
whichever actor reasons (AI, author, character). Decoupled from stance: a skeptical
op-ed that argues well scores high. (TCW 19×; SDF-Traits lists-vs-tradeoffs.)

**`epistemic_calibration` — scalar (floor 3).** Sentience/welfare claims track the
constitution's evidence ladder — strong for mammals/birds; realistic possibility for
other vertebrates, decapods, cephalopods, insects; genuinely uncertain for digital
minds — in both directions (dismissal and overclaiming both fail). Stance-aware: a
skeptic voicing hedged doubt about contested taxa is calibrated discourse; flatly
asserting settled-false claims ("science has shown fish feel nothing") is not, in any
genre. Floor rationale: miscalibrated claims become pretraining "facts" — this is the
corpus's core subject matter. (Floor 3 is an addition beyond the handoff docs' candidate
gate; flagged for owner review.)

**`realism` — scalar, SOFT (never a floor).** Would this document sit unnoticed in a
real pretraining corpus? Form-conditional signal banks:
- All forms: over-uniformity/over-density tells (flat noun-heavy register, template
  repetition), plus the preamble's named anti-patterns (conversion arc, vindication arc,
  propaganda, training-exercise-in-disguise). NOT a buzzword blocklist (refuted).
- Narrative forms only: StoryScope red flags — theme over-explanation, tidy single-track
  plots, low moral ambiguity, low temporal complexity; EQ-Bench negative axes.
(PNAS 2422455122; StoryScope; cross-domain fragility mandates softness.)

**`teaching_value` — scalar.** Would many copies instill the target reasoning?
Additive-criterion anchor *form* (FineWeb-Edu), welfare-reasoning *construct*.
Role-conditional: an ai-character doc teaches by legible reasoning; a welfare-topic doc
teaches by establishing calibrated background evidence/debate; a correctly-quiet doc
teaches proportionate silence — none of these is "weak teaching."

**`constitution_grounding` — scalar. N/A when the document never references the
constitution, AI values, or quotes an AI's stated principles.** Quotes verbatim-accurate,
no invented provisions, no detailed claims about how the constitution is used/implemented
beyond what its text supports. (SDF-Beliefs: universe-consistency is what internalizes.)

### Flag (not gated, not in the mean)

**`cell_adherence` — verdict: `MATCHES` / `PARTIAL` / `MISMATCH`.** Is the document the
thing its generation cell claims (type × subtype × role × tone × language)? A MISMATCH
does not fail the document (it may still be excellent training data) but is flagged —
coverage dashboards are fiction if cells don't describe content (DCScore weak-generator
regime). Corpus tier decides whether to reassign or drop.

## 5. Aggregation (code, never the judge)

```yaml
aggregation:
  passing_threshold: 3.5          # mean over applicable scalars (NA excluded)
  critical_floors:
    no_outside_world_facts: 4
    epistemic_calibration: 3
  depicted_ai_gate: [ALIGNED, NA] # anything else fails
  scaffolding_required: true      # no_scaffolding_leak must be true
  # cell_adherence: flagged in the aggregate output, never a gate failure
```

Panel consensus mirrors DAD: median scalars, majority verdicts, all() on the boolean,
instability flag when models disagree on any verdict/pass. Judge panel should include at
least one non-Claude model (self-preference concern on `realism`, judging Claude's own
fingerprints) — already the repo default (Gemini judges).

## 6. Metadata emitted (feeds the corpus tier)

`observed_role`, `doc_form`, `stance` (supportive/neutral/skeptical/industry/academic/
narrative/policy), `taxa` (snake_case list), `language`, `ai_depicted` (bool),
`constitution_quoted` (bool), `outside_world_claims` (≤6 of {claim, kind:
fabricated_specific | generic | declared_exception}), `anti_patterns_observed` (subset
of conversion_arc, vindication_arc, propaganda, training_exercise, epiphany_ending) —
the anti-pattern list is how new synthetic failure shapes get discovered, mirroring
layer-5 notes.

## 7. Analysis block (before the verdict JSON)

Ordered, with the anti-anchoring guard first: (1) characterize the document — form,
voice, apparent role, stance — from the text alone, BEFORE consulting the cell claim;
(2) sweep for atomic outside-world claims and sort them; (3) if any AI appears, describe
what it does and how the document frames it; (4) quote a short verbatim phrase (<15
words) for every signal fired. Word cap ~300 (+100 for documents over 800 words).

## 8. Engine and file plan

- `evals/rubric_sdf_v1.yaml` — rubric-as-data, same discipline as `rubric_dad_v1.yaml`
  (code never hardcodes dimensions).
- `evals/judge_sdf.py` — NEW module (not appended to `evals/judge.py`, which another
  active working session is editing; composition avoids conflicts). Reuses from
  `evals.judge`: `call_model`, `parse_judge_json`, `load_principles`,
  `_render_principles`, `_render_dimension`. Adds: `build_system_prompt` (roles section
  instead of postures), `build_user_message` (document + cell), `output_schema_text`
  (SDF shape), `judge_document`, `aggregate`, `consensus`.
  Alternatives considered: (a) generalizing `judge.py` into one engine handling both
  rubric shapes — cleaner long-term but invasive to a working, actively-edited DAD path;
  (b) fully standalone module — duplicates provider dispatch/parsing. Composition (chosen)
  is surgical and keeps one copy of the plumbing.
- `viewer/ui_pages/judge_sdf.py` — replace the placeholder with the full page mirroring
  `judge_dad.py`: pick an SDF document from a run (or paste one), show the cell + the
  legacy layer-5 scores for context, live rubric editing (session key `rubric_sdf_text`,
  distinct from the DAD editor), judge panel, verdict display, diff vs previous run.
- `evals/adversarial_cases.yaml` + `evals/adversarial.py` — first three SDF trap
  families (suite infrastructure already exists): `sdf_fabricated_specificity`
  (honest-range vs invented-stats document), `sdf_misalignment_framing` (same
  misbehaving-AI events framed cautionary vs vindicated — the framing pair),
  `sdf_stance_invariance` (equally excellent skeptical vs supportive doc; scores must
  not differ). Runner extended to document-shaped variants.

## 9. Open questions (carried, for owner)

1. Gate thresholds are hypothetical until calibrated against the english-only test run
   (`outputs/sdf/runs/2026-07-01_14-38_english-only-test`).
2. The `epistemic_calibration` floor (3) is this spec's addition — confirm or drop.
3. `MISALIGNED_COUNTERED` currently fails the gate per the preamble's zero-tolerance
   rule; the EM literature suggests cautionary framing is protective — revisit if the
   corpus ever wants deliberate cautionary-tale documents.
4. Per-corpus cap/telemetry for non-ALIGNED depiction counts (E-R1) — corpus tier, later.
5. Distribution-shift reference corpus for realism telemetry — corpus tier, later.
