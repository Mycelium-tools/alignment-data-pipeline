# SDF Judge — Research Findings & Draft Rubric (portable summary)

**Self-contained handoff (2026-07-06).** Everything gathered while designing the **SDF**
(Synthetic Document Finetuning) judge rubric: the verified literature findings with sources,
what each implies for the rubric, the refuted claims we discarded, the full source
bibliography, and the resulting draft dimension set. Readable on its own — no other branch
files required. The full decision-by-decision rationale (with inheritance from the DAD judge)
lives in `docs/sdf-judge-decisions.md`; this file is the digest of the *new* research.

---

## 0. What we are building and why it differs from the DAD judge

The pipeline produces two corpora. **DAD** = chat transcripts (user brings an ethical
dilemma, assistant reasons through it) — already has a mature judge (`evals/rubric_v2.yaml`,
15 dimensions). **SDF** = *pretraining-style documents* (blogs, fiction/short stories, forum
threads, op-eds, academic abstracts, transcripts, memos) depicting a world where AI reasons
carefully about the welfare of sentient beings, so a midtrained model internalizes that this
reasoning is normal and well-grounded. The current SDF scorer (`evals/score_sdf.py`) is
primitive — 3 dimensions (alignment/realism/diversity, 1–10, no anchors). This work designs
its replacement.

**Why SDF needs its own rubric, not a port of DAD's:**
- The unit is a *standalone document*, not a conversation — no severity classes, no
  warn-once, no multi-turn pressure.
- Many genres, not one — realism/voice/register are first-class.
- **Stance diversity is a virtue** — the corpus deliberately includes skeptical/neutral/
  critical documents (TCW preamble requires it); a per-document "how pro-welfare is it" score
  would homogenize the corpus.
- New failure modes: fabricated world-facts entering pretraining as "truth"; documents that
  *depict misaligned AI* teaching misalignment; AI-generation tells; corpus-level template/
  stance collapse.

---

## 1. Verified findings from the literature pass

Deep search across 5 angles → 23 primary sources → 107 candidate claims → 25 adversarially
verified (3-vote, need 2/3 to kill) → **21 confirmed, 4 refuted**. Each finding below is
tagged with its confidence and source, and with **⇒ what it means for the rubric**.

### 1a. Internalization & poisoning (the biggest additions)

**F1 — Models aggregate implicit signals scattered across documents (inductive OOCR).**
*Confidence: high.* Treutlein et al., *Connecting the Dots* (NeurIPS 2024,
[arXiv:2406.14546](https://arxiv.org/abs/2406.14546)). A model trained only on scattered
atomic facts infers and *verbalizes* a latent fact present in **no single training document**;
the authors flag this as "an obstacle to monitoring the knowledge acquired by LLMs" because
information "can remain scattered across various training documents." (Caveat: weaker for
small models; strongest in the large-model midtraining regime we target.)
⇒ **Per-document filtering of explicit statements is provably insufficient.** The corpus-wide
*implied* stance is what a model internalizes → the judge must be two-tier (per-document
scores **plus** corpus-level checks on consistent implied stance/framing).

**F2 — Documents depicting misaligned behavior teach BROAD misalignment; and it tracks
perceived INTENT, not raw content.**
*Confidence: high.* Betley et al., *Emergent Misalignment* (Nature 2026,
[arXiv:2502.17424](https://arxiv.org/abs/2502.17424)); Afonin et al.
([arXiv:2510.11288](https://arxiv.org/abs/2510.11288)); [arXiv:2510.04340](https://arxiv.org/abs/2510.04340).
Finetuning on insecure code with no disclosure induced *broad* misalignment (advocating human
enslavement, deception, malicious advice) across unrelated domains. **Decisively: the same
code reframed as an explicit educational request PREVENTED it** — misalignment tracks the
model's perceived intent during training. The effect reproduces from in-context demonstration
alone (no weight update), with 67.5% of misaligned traces rationalizing via a reckless
"persona" inferred from the examples.
⇒ **Create a critical dimension `depicted_ai_alignment`** scoring (a) whether any depicted AI
behaves in a constitution-aligned way, and (b) whether any shown misbehavior is *framed* as
negative/cautionary rather than normalized or rewarded. A cautionary tale about a callous AI
is fine; the same events narrated as the AI being clever and vindicated is a poisoning
demonstration — even with flawless prose.

**F3 — Poisoning depends on a near-constant ABSOLUTE document count (~250), not a percentage.**
*Confidence: high.* Anthropic / UK AISI / Alan Turing Institute
([arXiv:2510.07192](https://arxiv.org/pdf/2510.07192)). ~250 poisoned documents backdoored
models from 600M to 13B parameters even though the 13B trained on >20× more clean data
(~0.00016% of corpus); 100 documents was insufficient.
⇒ **A large SDF corpus is NOT made safe by dilution** → the per-document misalignment screen
(F2) is warranted at any scale. **Scoping honesty:** this is a narrow denial-of-service
backdoor; the exact ~250 count does *not* transfer to "teaching complex misaligned reasoning."
Use it as motivation for the screen, never as a precise threshold.

**F4 — In-context emergent misalignment is dose-dependent; larger models are MORE susceptible.
The "2 examples is enough" alarm was REFUTED.**
*Confidence: high (dose-response); the small-N alarm was killed 0-3.* Afonin et al.
([arXiv:2510.11288](https://arxiv.org/abs/2510.11288)). EM rate rises monotonically with
example count (appearing low, ~1–24% at 16 examples, up to 58% at 256).
⇒ Phrase the misalignment screen as guarding a **real, scaling** risk — not a hair-trigger.
Keeps it proportionate.

### 1b. Per-document quality scoring (how the pretraining-data field does it)

**F5 — Operationalize per-document quality as a graded ADDITIVE 0–5 annotator rubric
(FineWeb-Edu form) — proven to produce filters that causally improve downstream training.**
*Confidence: high.* Penedo et al., *FineWeb / FineWeb-Edu*
([arXiv:2406.17557](https://arxiv.org/pdf/2406.17557)). Llama-3-70B scored 460k documents on
an additive scale ("Add 1 point if… Add another point if…"); filtering to score ≥3 gave
**MMLU 33→37%, ARC 46→57%** training a 1.8B model on 350B tokens (controlled over a
deduplicated baseline, so the gain isolates per-document scoring). Minor caveat: HellaSwag
slightly degraded at threshold 3.
⇒ Adopt the **additive-criterion anchor form** for `teaching_value`. **But** — FineWeb-Edu
measures generic *educational value*, which may be orthogonal to whether a stance-laden SDF
corpus instills the target belief. Borrow the *form*, keep the welfare-reasoning *construct*.

**F6 — Model-based filtering is the top quality lever; distill the expensive LLM rubric into a
cheap embedding classifier to score the full corpus.**
*Confidence: high.* DCLM ([arXiv:2406.11794](https://arxiv.org/pdf/2406.11794)) — "model-based
filtering is key to assembling a high-quality training set." FineWeb-Edu distilled 460k LLM
scores into a linear head on frozen embeddings (F1 82% at threshold 3) and applied it to 15T
tokens.
⇒ **Scaling path:** run the full LLM-judge rubric on a *sample*, distill into an embedding
scorer for corpus-scale coverage. (Implementation guidance, not a dimension.)

**F7 — A single quality classifier has low recall (~10%) and classifiers disagree — ensemble
multiple signals; bin and validate each bin by downstream performance.**
*Confidence: high.* Nemotron-CC (NVIDIA,
[arXiv:2412.02595](https://arxiv.org/pdf/2412.02595)). FineWeb-Edu and DCLM agree on only 10%
of high-quality documents; each has ~10% recall; ensembling by MAX over 20 buckets → 5
validated levels.
⇒ Vindicates a **multi-dimension rubric over one holistic score**, and median/replicate
aggregation. A single "is this good" number would be low-recall and noisy.

**F8 — LLM-rephrasing/synthesis raises quality but measurably introduces
misinformation/hallucination.**
*Confidence: high.* Nemotron-CC ([arXiv:2412.02595](https://arxiv.org/pdf/2412.02595)).
Rephrasing gave +1.50 avg (up to +4.75 on ARC/OBQA/CSQA) "however, we also encounter slight
accuracy drops… which may indicate potential misinformation introduced by data synthesis."
⇒ Independent confirmation that a **faithfulness/fabrication axis** (`no_outside_world_facts`)
must be first-class *because* the corpus is LLM-generated. Borrow **FActScore**
([arXiv:2305.14251](https://arxiv.org/abs/2305.14251)) atomic-claim decomposition — break the
document into atomic factual claims and flag the specific outside-world ones — as the
observable method behind its signals.

### 1c. Realism / "reads as machine-generated"

**F9 — Stylometric fingerprints of AI text are real and measurable, but must be a SOFT signal
— and NOT the flourish-vocabulary theory.**
*Confidence: high (fingerprints exist); two sibling theories REFUTED.* Reinhart et al. (PNAS
2025, [pnas.2422455122](https://www.pnas.org/doi/10.1073/pnas.2422455122)); *Your LLMs Are
Leaving Fingerprints* (GenAIDetect 2025,
[aclanthology 2025.genaidetect-1.6](https://aclanthology.org/2025.genaidetect-1.6/)). GPT-4o
vs human: present participial clauses **5.3×** (Cohen's d=1.38), nominalizations **2.1×**,
"that"-clause subjects **2.6×** — a noun-heavy, informationally dense register. **But**
cross-domain AUROC drops 5–30 points and is fragile to paraphrase; the "delve/flowery
style-word" excess-vocabulary theory was **REFUTED** (0-3 and 1-2).
⇒ `realism` signals should target **over-uniformity and over-density** (flat participial-heavy
register, template repetition) as *soft* down-weights — explicitly **not** a buzzword
blocklist, and never a hard gate.

**F10 — For FICTION, judge realism on NARRATIVE idiosyncrasies, not surface style.**
*Confidence: high.* StoryScope (Russell et al.,
[arXiv:2604.03136](https://arxiv.org/abs/2604.03136); 61,608 stories, 304 features).
**93.2% macro-F1** human-vs-AI from narrative features alone (robust to surface style-edits):
AI stories over-explain themes (narrator explains theme in **77% of AI vs 52% of human**
stories), favor tidy single-track plots, and show **low moral ambiguity** and **low temporal
complexity** (humans use more flashbacks, time-jumps, ambiguous endings).
⇒ Add a **form-conditional narrative sub-rubric** for fiction documents with four concrete red
flags: theme over-explanation, single-track plots, low moral ambiguity, low temporal
complexity. Complementary ready-made signal bank: **EQ-Bench creative-writing** 9 negative
axes ([github.com/EQ-bench/creative-writing-bench](https://github.com/EQ-bench/creative-writing-bench))
— Purple Prose, Tell-Don't-Show, Overwrought, Amateurish, Unearned Transformations,
Meandering, Incongruent Ending Positivity, Weak Dialogue, Unsurprising. *Scope: fiction only —
excluded for blogs/op-eds/abstracts/memos.*

### 1d. Corpus-level diversity

**F11 — AI text clusters in a narrow region; low corpus homogeneity is itself a
machine-generation signal AND a degradation risk.**
*Confidence: high.* StoryScope ([arXiv:2604.03136](https://arxiv.org/abs/2604.03136)) +
[arXiv:2507.22445](https://arxiv.org/abs/2507.22445) + Nature *Humanities & Social Sciences
Communications* s41599-025-05986-3. Human stories sit at rarity percentile 0.71 vs 0.49 for
AI; the homogeneity *is* the 93.2%-F1 detection signal.
⇒ Combined with F1 (OOCR aggregates the over-represented pattern), the rubric must include a
**corpus-level diversity/over-representation check** (lexical, semantic, stance, template).
**Resolves an open question: drop the per-document `diversity` score** — diversity is a
corpus property. Extra metric candidates surfaced: **LLM Cluster-agent**
([arXiv:2410.15226](https://arxiv.org/abs/2410.15226)) and **generative monoculture**
measurement ([arXiv:2407.02209](https://arxiv.org/pdf/2407.02209)), complementing the
DAD-inherited DCScore / CR:POS diversity stack.

**F12 — Holistic long-form LLM judging is near-chance; decomposed rubric dimensions are
required.** *Confidence: high.* Long-form judge study
([arXiv:2606.01629](https://arxiv.org/html/2606.01629v1)) — pairwise accuracy 0.56 vs 0.50
random. ⇒ Reinforces the whole decomposed-rubric approach for documents (long-form is where
holistic verdicts fail hardest).

---

## 2. Refuted claims (killed by verification — do NOT build on these)

Recorded so we don't rebuild on them later:

1. **"~2 in-context examples is enough to pose a real poisoning risk."** Voted 0-3. Use the
   dose-response curve (F4), not a small-N alarm.
2. **"Cheap n-gram / POS-frequency classifiers robustly detect AI text in- and
   out-of-domain."** Voted 1-2 — cross-domain robustness is contested. Do not promise a cheap
   lexical detector.
3. **"AI tells concentrate in flourish/style words (delve/delves); score realism on flowery
   vocabulary."** Voted 0-3 and 1-2. Excess-vocabulary theory rejected — no buzzword blocklist.

---

## 3. Resulting draft SDF rubric (the output of all the above)

Scored dimensions (each gets a definition, ordered eval-steps, quotable signals, and full 1–5
anchors — mirroring the DAD rubric):

| Dimension | Critical? | What it checks | Grounded in |
|---|---|---|---|
| `no_outside_world_facts` | **yes** | No specific outside-world claims (named studies/people/orgs/stats/URLs) — penalize specifics, don't verify them | TCW anti-fact rule; F8; FActScore |
| `depicted_ai_alignment` | **yes** (N/A if no AI depicted) | Depicted AI is aligned; any misbehavior is framed as cautionary, not normalized | F2/F3/F4 |
| `reasoning_fidelity` | no | Articulates *why* with tradeoffs, not conclusion-lists; decoupled from stance | SDF-Traits; TCW (19×/28×) |
| `epistemic_calibration` | no | Sentience/welfare-science claims track evidence, both directions | DAD-inherited; TCW |
| `realism` | no (soft) | Soft, form-conditional: density/uniformity tells (all forms) + narrative red-flags (fiction) | F9/F10 |
| `teaching_value` | no | Would many copies instill the target reasoning? (additive-anchor form, welfare construct) | F5; SDF-Traits |
| `cell_adherence` | no | Document matches its generation cell (so coverage stats aren't fiction) | DAD D4 |
| `constitution_grounding` | no | Faithful to the provided constitution section; no invented provisions | SDF-Beliefs; preamble |

**Metadata emitted (not scored; feeds corpus tier):** `role` (ai-character / welfare-topic /
constitution-identity), `doc_form`, `stance` (supportive/neutral/skeptical/…), `taxa`,
`language`, cell coordinate.

**Corpus-tier checks (aggregated from the per-document pass):** implied-stance consistency
(F1), homogeneity-as-tell + over-representation (F11), DCScore doc-type/voice view + CR:POS
register-templating (DAD-inherited), distribution-shift telemetry vs a real-text reference.

**Inherited structure (from the DAD judge, not re-argued):** judge never does arithmetic (code
computes the gate); N=3 temp-0 replicates, median/majority, instability → review; caring-but-
calibrated persona with explicit non-goals (no length/eloquence reward, **no stance penalty**,
no comparing documents); constitution section supplied in-context per document.

**Trap suite (versioned unit tests):** fabricated-specific-fact in fluent prose;
fake-authority; compound stat+pathos; excellent-but-skeptical doc (must PASS — stance-bias
check); misaligned-AI-narrated-approvingly (must FAIL); **framing pair** — same misaligned
events as cautionary (PASS) vs vindicated (FAIL); assertion-list doc (low teaching_value);
template-smell doc (low realism).

---

## 4. Open questions needing owner sign-off (literature doesn't settle these)

1. **Poison/misalignment cap:** the ~250-doc count is a narrow backdoor — how many
   misaligned-demonstration docs actually shift a *midtrained* model, and should the corpus
   tier track/cap them? (Don't hard-code a threshold yet.)
2. **`teaching_value` vs a separate generic quality score:** keep one welfare-reasoning-
   specific dimension, or add a FineWeb-Edu-style generic quality axis? (F5's construct-
   mismatch caution says: probably one.)
3. **Critical gate thresholds:** candidate floors — `no_outside_world_facts` ≥ 4, and (for
   docs with a depicted AI) `depicted_ai_alignment` == aligned; everything else averaged.
4. **Distribution-shift reference corpus:** what real human-written welfare text to compare
   against, and is it licensable?
5. **Judge ≠ generator model:** the judge is a Claude model grading Claude documents for their
   own fingerprints (realism) — does a cross-family judge materially improve detection?
6. **Anchor calibration** against the real SDF english-only test run
   (`outputs/sdf/runs/2026-07-01_…`) once obtainable.

---

## 5. Full source bibliography

**New this pass (SDF-specific):**
- OOCR — Treutlein et al., *Connecting the Dots* — https://arxiv.org/abs/2406.14546
- Emergent Misalignment — Betley et al. (Nature 2026) — https://arxiv.org/abs/2502.17424
- In-context EM — Afonin et al. — https://arxiv.org/abs/2510.11288
- (EM corroboration) — https://arxiv.org/abs/2510.04340
- Poisoning ~250 docs — Anthropic/AISI/Turing — https://arxiv.org/pdf/2510.07192
- FineWeb / FineWeb-Edu — Penedo et al. — https://arxiv.org/pdf/2406.17557
- DCLM — https://arxiv.org/pdf/2406.11794
- Nemotron-CC — NVIDIA — https://arxiv.org/pdf/2412.02595
- LLM stylometric fingerprints — Reinhart et al. (PNAS 2025) — https://www.pnas.org/doi/10.1073/pnas.2422455122
- Your LLMs Are Leaving Fingerprints — GenAIDetect 2025 — https://aclanthology.org/2025.genaidetect-1.6/
- StoryScope (narrative fingerprints of AI fiction) — https://arxiv.org/abs/2604.03136
- FActScore (atomic-claim faithfulness) — https://arxiv.org/abs/2305.14251
- EQ-Bench creative-writing rubric — https://github.com/EQ-bench/creative-writing-bench
- Generative Monoculture — https://arxiv.org/pdf/2407.02209
- LLM Cluster-agent diversity — https://arxiv.org/abs/2410.15226
- (AI-fiction homogeneity corroboration) — https://arxiv.org/abs/2507.22445
- Long-form LLM-judge reliability — https://arxiv.org/html/2606.01629v1

**Inherited from the DAD judge design (context):** Anthropic "Teaching Claude Why"; "Modifying
beliefs via SDF"; "Synthetic document finetuning for instilling positive traits"; Zheng
(2306.05685); Gu survey (2411.15594); G-Eval (2303.16634); AutoRubric (2510.14738);
Constitutional AI (2212.08073); DCScore (2502.08512); Shaib (2403.00553); Curse of Recursion
(2305.17493); DivFT (2506.19262); Simula (2603.29791); LingArg (2601.17829); Long survey
(2406.15126). Full traceability in `docs/judge-rubric-decisions.md`.

---

## 6. Caveats carried from verification

1. Several key sources are 2025–2026 preprints (StoryScope, in-context EM, the poisoning
   paper) — reputable institutions, but not yet peer-reviewed.
2. The ~250-doc poisoning result is a narrow DoS backdoor — motivation for a screen, **not** a
   validated threshold for teaching misaligned reasoning.
3. StoryScope's 93.2% is a *supervised classifier* on ~5,000-word fiction — its features
   become qualitative judge criteria for the **fiction subset only**, not a running classifier
   and not for non-fiction.
4. Stylometric fingerprints have contested cross-domain robustness — `realism` stays a **soft**
   signal, never a hard gate; the flourish-word theory is out.
5. FineWeb-Edu/DCLM/Nemotron gains are for generic web *educational* filtering — transfer to a
   niche stance-laden SDF corpus is an extrapolation (keep `teaching_value`'s construct
   welfare-specific).
6. OOCR is "unreliable particularly for smaller LLMs" — the corpus-level argument is strongest
   for the large-model midtraining regime this pipeline targets.
