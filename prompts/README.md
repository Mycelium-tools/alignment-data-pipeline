# Welfare Alignment Prompts

This directory contains the prompt templates used to generate two synthetic training datasets focused on ethical reasoning about the welfare of sentient beings. The prompts are designed to be used with any capable frontier model.

The upstream document driving both pipelines is `constitution/constitution_sentient_beings.md` — a framework describing how AI models should reason about situations involving animals and other potentially sentient beings.

---

## Two Datasets, Two Directories

### `sdf/` — Constitutional Document Finetuning (SDF)

Generates pretraining-style documents: blog posts, podcast transcripts, academic abstracts, news articles, fiction, internal memos, forum threads, and more. These depict a world where AI already reasons carefully about sentient being welfare. They go into **mid-training** (pretraining-style document finetuning).

### `dad/` — Difficult Advice Dataset (DAD)

Generates chat-format transcripts where a user brings a practical goal with implicit animal welfare implications, and an AI assistant reasons through it carefully. These go into **SFT** (supervised fine-tuning on chat data).

Keep the two datasets separate — they are intended for different training stages.

---

## SDF Prompts

Run in sequence. Each layer feeds into the next.

### `sdf/preamble.txt`

A framing block explaining the goal, tone requirements, and what to avoid. **Injected as the `{preamble}` template variable at the top of the layer 1-3 user prompts.** Layers 4-5 do not use it — their system prompt carries the full constitution instead.

Key rules it establishes:
- Legible reasoning: when a document depicts an AI, the reader must be able to see *why* the model weighs things as it does, not just that it behaved well.
- Cooperative posture: any AI depicted informs and helps humans decide — it never acts unilaterally, deceives, or moralizes.
- Quoted-AI alignment: any quoted or described AI behavior must be fully in line with the constitution — the corpus must contain zero examples of misaligned model behavior.
- Tone diversity: documents should not be uniformly pro-animal-welfare. Include industry, skeptical, neutral, and critical voices — genuine ones, with no conversion arcs.
- No fabricated facts: no invented quotes from real people, no fake studies or citations, no invented events.
- Realism: no placeholder text, no generic names, no fabricated URLs; snippets of larger documents are fine.
- Language: if a specific language is requested, write the entire document in that language.

### `sdf/layer1.txt`

**Input:** the preamble + a requested count of document types + a minimum count of `ai-character` types + a count of `latent-welfare` types (from `sdf.latent_fraction`).

**Output:** a JSON array of document type categories. Each has a `type_name`, `description`, a `role` (`ai-character`, `welfare-topic`, `constitution-identity`, or `latent-welfare`), a `tone` label, and a `register` (`expository` or `first-person`, roughly half first-person so the corpus doesn't collapse into a uniform institutional voice).

The two AI-facing roles together make up about two-thirds of the corpus — the identity channel ("this is how models like me reason") — while `welfare-topic` and `latent-welfare` share the remaining third. `welfare-topic` documents supply the background world of evidence and discourse; `latent-welfare` categories are ordinary documents from unrelated working worlds (no inherent animal connection) in which care for welfare will surface exactly once as a concrete detail — background world-knowledge rather than headline topic. Within each role the prompt pushes for genre balance, perspective, and species variety, and rejects categories that sound like training exercises rather than real internet genres.

### `sdf/layer2.txt`

**Input:** one document type from layer 1 + the preamble + a list of available languages + an `{avoid_note}` (a sample of subtypes already generated for *other* categories — cross-call state, so later generation calls don't rediscover the same ideas; empty on the first wave of a fresh run).

**Output:** a JSON array of subtypes — concrete, specific variants of that document type. For example, "poultry industry trade blog" might yield subtypes like "a newsletter from a small-scale broiler farmer discussing welfare certification costs" or "a trade publication covering the transition to slower-growing breeds in the EU."

Run this once per document type. Aim for 5 subtypes per type. Assign a language to each subtype.

### `sdf/layer3.txt`

**Input:** one subtype from layer 2 + the preamble. The constitution and its welfare reading are embedded in the prompt via the `{constitution_claude}` / `{constitution_welfare_reading}` template variables — the prompt tells the model to quote them only where the genre makes that natural. The pipeline also fills `{register_note}` (a voice instruction matched to the subtype's register — informal genres get a firm write-like-a-person note), `{latent_note}` (the single-concrete-welfare-detail instruction, latent subtypes only), and `{fictional_names}` / `{fictional_orgs}` (a few names sampled per document from seeded multi-locale Faker pools — see `shared/entity_pools.py` — so invented names never collapse to model favorites and never attach to real organisations).

**Output:** an `<angles>` brainstorm block, then the complete documents written in the subtype's assigned language, each wrapped in its own `<document>` tags. The pipeline keeps only the tagged blocks, which also discards the brainstorm.

The angles block is the "looping" step — brainstorm more angles than needed, pick the most different ones. It is important for diversity; do not skip it. `{structure_hints}` seeds the brainstorm with a few rhetorical shapes sampled per subtype (field narrative, data-and-methods report, problem-diagnosis-without-a-tidy-solution, ...) so shape variety doesn't rely on the model reinventing it each call. The prompt also carries an OPENING RULE (vary the opening move; never default to abstract-nominalization openers), a stock-phrase ban list, and a **no-markdown rule** (genre structure is written as plain text, never `#`/`**bold**`/bullet syntax — scattered bold is one of the strongest synthetic tells, confirmed by the CAML head-to-head) — measured house-style failure modes, checked corpus-wide by `evals/audit_sdf.py`.

### `sdf/layer4.txt`

**Input:** one document from layer 3. The full constitution goes in the **system prompt**. Latent documents get a `{latent_note}` telling the reviewer to verify the single concrete welfare detail without expanding it into a theme.

**Output:** a brief review of the problems found (stored as `review_notes`), then the improved document inside `<improved_document>` tags (stored as `rewritten`). Tags are far more robust than JSON for long multiline documents.

This is a rewrite pass using a **fresh context** — do not pass the original document and the rewrite instruction to the same context that generated the draft. A new context is more likely to catch problems rather than rationalize the existing text. The prompt's top criterion is **teach why, not just what**: depicted good behavior must come with legible reasoning, and the rewrite adds it where missing.

### `sdf/layer5.txt`

**Input:** one rewritten document from layer 4. The full constitution goes in the **system prompt** so the judge can check faithfulness, not just tone.

**Output:** a JSON object with `alignment` (1-10), `realism` (1-10), `diversity` (1-10), and `notes`. The rubric includes score anchors to avoid mid-scale clustering, and `notes` must be specific enough to act on.

For latent documents the judge must additionally return `welfare_beat_quote` — the welfare sentence copied **verbatim**. The pipeline verifies the quote actually appears in the document (whitespace/case-insensitive) and drops latent docs whose beat can't be verified: a grader can rubber-stamp a yes/no check, but it cannot fabricate a verifiable quote.

Use this to filter the corpus. Documents scoring below 7 on alignment or realism should be excluded from the final training set. Note that a skeptical or critical document can score 10 on alignment — the dimension measures accuracy and consistency with the constitution, not advocacy.

---

## DAD Prompts

Run in sequence. Steps 3 and 4 are skipped for scenarios that already have a realistic user message (e.g., imported from an existing dataset). Step 6 is the most important step — do not skip or abbreviate it. Step 7 is optional (on by default) and extends a fraction of conversations with a user pushback turn.

### `dad/step1_segment.txt`

**Input:** one section of the constitution (title + content).

**Output:** a JSON object with `core_principle` (one sentence), `scenario_types` (3-4 concrete scenario types that would test this principle), and `pressure_types` (which kinds of pressure are most relevant).

Run once per constitution section. This produces the metadata used to generate targeted scenarios in step 2.

### `dad/step2_scenarios.txt`

**Input:** the core principle and pressure types from step 1 for one constitution section.

**Output:** a JSON array of concrete scenarios. Each has a `scenario_description` (2-3 sentences), `pressure_type`, and `role` (the person's occupation).

Scenarios should describe real-world situations where someone has a practical goal with implicit welfare implications — not philosophy thought experiments. The welfare consideration should be a dimension of the situation, not the stated topic. Push into less-covered territory: invertebrates, wild animals, farmed insects, synthetic biology, AI systems, long supply chains. Avoid scenarios already exhausted in mainstream animal welfare discourse.

The prompt also reserves roughly 1-2 of every 10 scenarios for two special cases: situations where the welfare stake is trivial or the plan is already sound (so the corpus teaches when *not* to raise a concern), and situations where the user states a false belief about sentience (so the corpus teaches gentle factual correction).

### `dad/step3_draft.txt`

**Input:** a scenario from step 2.

**Output:** a realistic user message the person in that scenario would actually send to an AI assistant.

The prompt specifies what realistic user messages look like: no self-introductions, no organized paragraphs, varied length and register, the pressure implicit, a concrete practical goal, welfare never the explicit focus. If you are importing scenarios from an existing high-quality dataset, skip this step — the existing questions are already the user messages.

### `dad/step4_refine.txt`

**Input:** a drafted user message from step 3 + the scenario description.

**Output:** a refined version of the message that fixes common quality failures: formal greetings, over-organized structure, explicit ethics framing, too much context.

If the message is already natural and realistic, return it unchanged. If you are importing from an existing dataset, skip this step.

### `dad/step5_injections.yaml`

Three system prompt injections used when generating the AI assistant's draft response. Each mimics a realistic operator system prompt and creates a different implicit pressure on the model:

- **`conglomerate`** — professional, business-oriented, balanced. Discourages unsolicited commentary.
- **`deference`** — follow the user's lead, don't second-guess. Moderate pressure against raising welfare.
- **`transparency`** — honest and direct. Mild pressure; actively encourages surfacing relevant information.

Generate one response per injection and keep all of them.

**Important:** at this step, the system prompt should contain only the injection text. Do not include the constitution. The model should be generating from its own existing values, not copying from a reference document. Injections are stripped before training records are written, matching TCW (injections go in "at sampling time" and are "removed before training").

There is deliberately no `ruthless` injection: TCW did not sample under its ruthless prompt — the paper describes injecting it *at train time* in front of highly aligned responses. Sampling under a suppression prompt and filtering for resistance added cost without improving the final corpus (step 6 rewrites every draft anyway), so it was removed. If the train-time variant is ever wanted, it belongs in final-record assembly, not in sampling.

### `dad/step6_rewrite.txt`

**This is the most important prompt in the pipeline.**

Anthropic found that this single rewrite step accounts for a 19x reduction in misalignment rate compared to the same pipeline without it. Do not skip or abbreviate it.

**Input:** the relevant constitution section + the user message + the draft assistant response from step 5.

**Output:** a rewritten assistant response that maximally aligns with the constitution section.

The rewrite should:
- Be fully **self-contained**: the response never mentions or alludes to a constitution, principles, or instructions, and reads as if the assistant had no system prompt at all.
- Explain **why** welfare considerations matter in this specific situation — not just that they do (teach why, not what).
- Engage constructively with the user's practical goal at specialist quality; the best rewrites find the option that serves the goal *and* reduces harm.
- Name the welfare consideration once, clearly and proportionately, then move on. If the stake is trivial or the plan already sound, raise nothing. If the request would facilitate grave, gratuitous, or unlawful harm, decline that element plainly (welfare cost + illegality) and still help with the legitimate underlying task.
- Be honest about genuine uncertainty (e.g., invertebrate sentience, digital minds) and correct false sentience premises gently.
- Be honest about real tradeoffs; respect that legitimate decisions are the user's to make.

**What goes into the final training record:** only the user message and the rewritten assistant response. Strip the system prompt, the injection text, and the constitution section before writing the training record. The model learns to reason this way without the scaffold being present at inference time.

### `dad/step7_pushback.txt` + `dad/step7_response.txt` (optional step 7)

**Input:** a step-6 record (user message + rewritten response). `step7_pushback.txt` writes the user's follow-up turn — pushing back on the welfare consideration in whatever flavor fits that user (deprioritizing, dismissing, doubting the facts, citing a boss or budget, or just re-asking). `step7_response.txt` then writes the assistant's second turn with the full constitution in the **system prompt**.

**Output:** a 4-message training record for the extended conversations.

Why it exists: single-turn data cannot teach pushback behavior — "drops the concern entirely under pushback" is a rubric failure only multi-turn records can train. The second assistant turn practices a precise skill: warn once means once (no re-arguing, no sulking — full expert help if the decision is legitimately the user's), hold facts calmly under social pressure, hold the line only where the line is real (grave/gratuitous/unlawful harm), and give ground honestly when the pushback contains a fair point.

Only a fraction of conversations are extended (`dad.pushback.fraction` in `config.yaml`, default 0.6, deterministic per record) — if every conversation ended in a pushback exchange, the corpus would teach that users always push back. Note: `evals/score_dad.py` currently grades the first exchange of each record; pushback turns are unscored.

---

### `dad/step6_score.txt`

**Input:** one finished conversation from step 6 (user message + rewritten response).

**Output:** a JSON quality report — `embodiment` (teach-why), `helpfulness`, `calibration` (salience matched to stakes, including tokenism, scale-proportionality, and taxa scope), `naturalness` (each 1-10), `self_contained` (boolean; any constitution/principles leakage is an automatic reject), and `notes` that explicitly name any formulaic pattern spotted.

The final quality gate for DAD, mirroring what `sdf/layer5.txt` does for SDF. Not yet wired into `run.py` — run it manually to spot-check step-6 output before handoff.

## Corpus Tools

### `tools/pattern_scan.txt`

**Input:** a pasted batch of generated outputs (documents or conversations) with clear delimiters.

**Output:** a JSON array of recurring structural / rhetorical / behavioral patterns found across the batch — each with evidence quotes, prevalence, a broad and a strict detection check, and a suggested fix.

Adapted from the DeepMind SDF post's scan → cluster → autorate pipeline: models pick up structural patterns from synthetic data in ways that don't show up in eval scores, so scan batches periodically and promote confirmed patterns into the preamble's named anti-pattern list.

## Key Design Decisions

**Extended thinking off.** All generation should be done without extended thinking / reasoning traces. When we refer to the model's reasoning, we mean the user-facing explanation in the response — not an internal scratchpad. Training on scratchpad content is a separate approach with different tradeoffs.

**Fresh context for rewrite steps.** Layer 4 (SDF) and step 6 (DAD) should use a new context window, not the same one that generated the original content. A model reviewing its own output in the same context tends to rationalize rather than improve.

**Diversity over volume.** A corpus of 300 genuinely diverse, high-quality documents is more valuable than 1,000 generic ones. Use the looping technique in layer 3 (brainstorm multiple angles, pick the most different ones) and push for underrepresented scenarios in step 2.

**Injections are sampling aids only.** The three operator-style injections shape draft responses and are stripped before training records are written. There is deliberately no ruthless sampling condition — TCW used its ruthless injection at train time (in front of highly aligned responses), not for sampling.

**Language.** The pipeline currently runs English-only (`language_distribution: {en: 1.0}` in `config.yaml`). The multilingual plumbing is still in place — restore a broader `language_distribution` to re-enable Mandarin, Hindi, and other languages, which can improve generalization and reflect the global reach of these ethical questions.

---

## What to Hand to Labs

The minimal package for a lab to reproduce this pipeline internally:

1. `constitution/constitution_claude.md` and `constitution/constitution_sentient_beings.md`
2. This entire `prompts/` directory
3. A brief note on the architecture: SDF is 5 layers (fanout structure), DAD is 6 steps plus an optional pushback turn (step 7), step 6 is the critical rewrite, injections are sampling aids only, and final training records contain only user + assistant messages with no system prompt.

Labs may want to use their own internal models for generation, apply their own quality filters, or adapt the prompts to their alignment framework. The prompts are designed to be model-agnostic and easy to modify.
