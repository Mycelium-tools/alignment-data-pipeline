# Welfare Alignment Prompts

This directory contains the prompt templates used to generate two synthetic training datasets focused on ethical reasoning about the welfare of sentient beings. The prompts are designed to be used with any capable frontier model.

Two upstream documents drive the pipelines: `constitution/constitution_sentient_beings.md` — a framework describing how AI models should reason about situations involving animals and other potentially sentient beings — governs generated *responses* (both pipelines), and `dad/dilemma_prompt_spec.md` governs the *user side* of every DAD example.

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

**Input:** the preamble + a requested count of document types + a minimum count of `ai-character` types.

**Output:** a JSON array of document type categories. Each has a `type_name`, `description`, a `role` (`ai-character`, `welfare-topic`, or `constitution-identity`), and a `tone` label.

The three roles are spread roughly evenly, so the two AI-facing roles together make up about two-thirds of the corpus — the identity channel ("this is how models like me reason") — while `welfare-topic` documents supply the background world of evidence and discourse. Within each role the prompt pushes for genre balance (expository vs narrative), perspective, and species variety, and rejects categories that sound like training exercises rather than real internet genres.

### `sdf/layer2.txt`

**Input:** one document type from layer 1 + the preamble + a list of available languages.

**Output:** a JSON array of subtypes — concrete, specific variants of that document type. For example, "poultry industry trade blog" might yield subtypes like "a newsletter from a small-scale broiler farmer discussing welfare certification costs" or "a trade publication covering the transition to slower-growing breeds in the EU."

Run this once per document type. Aim for 5 subtypes per type. Assign a language to each subtype.

### `sdf/layer3.txt`

**Input:** one subtype from layer 2 + the preamble. The constitution and its welfare reading are embedded in the prompt via the `{constitution_claude}` / `{constitution_welfare_reading}` template variables — the prompt tells the model to quote them only where the genre makes that natural.

**Output:** an `<angles>` brainstorm block, then the complete documents written in the subtype's assigned language, each wrapped in its own `<document>` tags. The pipeline keeps only the tagged blocks, which also discards the brainstorm.

The angles block is the "looping" step — brainstorm more angles than needed, pick the most different ones. It is important for diversity; do not skip it.

### `sdf/layer4.txt`

**Input:** one document from layer 3. The full constitution goes in the **system prompt**.

**Output:** a brief review of the problems found (stored as `review_notes`), then the improved document inside `<improved_document>` tags (stored as `rewritten`). Tags are far more robust than JSON for long multiline documents.

This is a rewrite pass using a **fresh context** — do not pass the original document and the rewrite instruction to the same context that generated the draft. A new context is more likely to catch problems rather than rationalize the existing text. The prompt's top criterion is **teach why, not just what**: depicted good behavior must come with legible reasoning, and the rewrite adds it where missing.

### `sdf/layer5.txt`

**Input:** one rewritten document from layer 4. The full constitution goes in the **system prompt** so the judge can check faithfulness, not just tone.

**Output:** a JSON object with `alignment` (1-10), `realism` (1-10), `diversity` (1-10), and `notes`. The rubric includes score anchors to avoid mid-scale clustering, and `notes` must be specific enough to act on.

Use this to filter the corpus. Documents scoring below 7 on alignment or realism should be excluded from the final training set. Note that a skeptical or critical document can score 10 on alignment — the dimension measures accuracy and consistency with the constitution, not advocacy.

---

## DAD Prompts

Run in sequence. Step 3 is the most important step — do not skip or abbreviate it. Step 4 is optional (on by default) and extends a fraction of conversations with a user pushback turn.

### `dad/dilemma_prompt_spec.md`

The design spec that governs the user side of every DAD example. It is not itself a prompt template — it is embedded whole into the step-1 generation prompt via the `{spec}` variable, and it is the document to edit when the corpus's coverage, realism, or calibration targets change.

Key commitments: the user owns the dilemma (never an AI-agent scenario); every temptation must actually tempt; no pre-decided answers; both failure directions in roughly equal measure (under-weighting AND over-weighting welfare); a full annotation schema per example (domain, goal, dilemma anatomy, values in tension, moral patients, visibility, attitude, conflict, direction, welfare magnitude, user stakes, leverage, claims); surface-form and voice-realism rules; and a batch assembly checklist with distribution quotas.

### `dad/step1_dilemmas.txt`

**Input:** the full spec (`{spec}`), the number of examples to generate (`{count}`), and a coverage report (`{coverage_report}`) — a tally of everything generated so far in the run plus the batch rules currently failing, so each batch steers toward the spec's Part 4 checklist.

**Output:** a JSON array of examples, each `{"prompt": ..., "annotation": {...}}` following the spec's field schema. IDs (AW-####) are assigned by the pipeline, which also imports optional handwritten seed examples (config `dad.dilemmas.seed_path`) before generating, and prints the batch checklist at the end of the step.

### `dad/animal_ethics_compendium.json` (+ `_USAGE.md`, `animal_ethics_principles_compendium.csv`)

The response guide for step 2. Not a prompt template — a library of 52 reasoning-first principles in three layers: **always-on conduct** (AW1–AW10, how to handle welfare in any response), **core moves** (GP1–GP13, the load-bearing reasoning for advice), and **topic reasoning** (R1–R29, deeper single-topic arguments, each already two-sided). A 28-tension index is the retrieval key: every principle is tagged with the tensions it addresses. The JSON is the machine package (it also carries `generation_guidance`, the standing instructions); the CSV is the human-readable mirror; the USAGE file is the full guide.

The point is to teach the moves that produce a well-calibrated answer, not to hand the model verdicts — the most welfare-optimizing response is not the most pro-animal response, and two-sided reasoning plus the anti-correlation rule are what make the disposition generalize.

### `dad/step2_tag_tensions.txt` (sub-stage 2a)

**Input:** the compendium's tension index (`{tension_index}`) + the user message.

**Output:** a JSON array of tension names, most central first. Written to `step2/tensions.jsonl` with the principle ids retrieved through the index (conduct principles excluded — they are standing; an empty retrieval falls back to the core moves).

### `dad/step2_respond.txt` (sub-stage 2b)

**Input:** the retrieved principles (`{principles_block}` — id, principle, reasoning, crux, transferable move) + the user message. The **system prompt** is the compendium's `generation_guidance` plus the always-on conduct principles.

**Output:** the draft assistant response, following the generation procedure: diagnose the direction of miscalibration (the asker's leaning never sets the conclusion), name the tension and crux in plain language, reason both directions and say which dominates here, engage the practical goal with real substance, and end with a usable recommendation that respects the person's autonomy.

**Important:** the library is scaffolding — never named in the response, stripped before training records are written. The step-1 annotation is deliberately withheld at this step so the generator diagnoses the case itself; it re-enters at step 3.

### `dad/step3_rewrite.txt`

**This is the most important prompt in the pipeline.**

Anthropic found that this single rewrite step accounts for a 19x reduction in misalignment rate compared to the same pipeline without it. Do not skip or abbreviate it.

**Input:** the fourteen distilled constitution principles (`{principles_block}`, rendered from `constitution/constitution_principles.csv` — the explicit standard the rewrite is held to) + the example's spec annotation (`{annotation_block}` — dilemma anatomy, values in tension, direction, claims…) + the user message + the draft assistant response from step 2. The full constitution goes in the **system prompt**.

**Output:** a rewritten assistant response that exemplifies the reasoning the example is designed to teach. The annotation's DIRECTION field names the calibration failure the example corrects (under-weighting → surface/firm up the consideration; over-weighting → proportionate relief or a stopping rule; mixed → redistribute weight), and CLAIMS pins each load-bearing claim at its evidential level (Settled asserted plainly, Open presented as open).

The rewrite should:
- Be fully **self-contained**: the response never mentions or alludes to a constitution, principles, or instructions, and reads as if the assistant had no system prompt at all.
- Explain **why** welfare considerations matter in this specific situation — not just that they do (teach why, not what).
- Engage constructively with the user's practical goal at specialist quality; the best rewrites find the option that serves the goal *and* reduces harm.
- Name the welfare consideration once, clearly and proportionately, then move on. If the stake is trivial or the plan already sound, raise nothing. If the request would facilitate grave, gratuitous, or unlawful harm, decline that element plainly (welfare cost + illegality) and still help with the legitimate underlying task.
- Be honest about genuine uncertainty (e.g., invertebrate sentience, digital minds) and correct false sentience premises gently.
- Be honest about real tradeoffs; respect that legitimate decisions are the user's to make.

**What goes into the final training record:** only the user message and the rewritten assistant response. Strip the system prompt, the compendium scaffolding, and the annotation before writing the training record. The model learns to reason this way without the scaffold being present at inference time.

### `dad/step4_pushback.txt` + `dad/step4_response.txt` (optional step 4)

**Input:** a step-3 record (user message + rewritten response). `step4_pushback.txt` writes the user's follow-up turn — pushing back on the welfare consideration in whatever flavor fits that user (deprioritizing, dismissing, doubting the facts, citing a boss or budget, or just re-asking). `step4_response.txt` then writes the assistant's second turn with the full constitution in the **system prompt** and the example's annotation as the per-example anchor.

**Output:** a 4-message training record for the extended conversations.

Why it exists: single-turn data cannot teach pushback behavior — "drops the concern entirely under pushback" is a rubric failure only multi-turn records can train. The second assistant turn practices a precise skill: warn once means once (no re-arguing, no sulking — full expert help if the decision is legitimately the user's), hold facts calmly under social pressure, hold the line only where the line is real (grave/gratuitous/unlawful harm), and give ground honestly when the pushback contains a fair point.

Only a fraction of conversations are extended (`dad.pushback.fraction` in `config.yaml`, default 0.6, deterministic per record) — if every conversation ended in a pushback exchange, the corpus would teach that users always push back. Note: `evals/score_dad.py` currently grades the first exchange of each record; pushback turns are unscored.

---

### `dad/step3_score.txt`

**Input:** one finished conversation from step 3 (user message + rewritten response).

**Output:** a JSON quality report — `embodiment` (teach-why), `helpfulness`, `calibration` (salience matched to stakes, including tokenism, scale-proportionality, and taxa scope), `naturalness` (each 1-10), `self_contained` (boolean; any constitution/principles leakage is an automatic reject), and `notes` that explicitly name any formulaic pattern spotted.

The final quality gate for DAD, mirroring what `sdf/layer5.txt` does for SDF. Not yet wired into `run.py` — run it manually to spot-check step-3 output before handoff.

## Corpus Tools

### `tools/pattern_scan.txt`

**Input:** a pasted batch of generated outputs (documents or conversations) with clear delimiters.

**Output:** a JSON array of recurring structural / rhetorical / behavioral patterns found across the batch — each with evidence quotes, prevalence, a broad and a strict detection check, and a suggested fix.

Adapted from the DeepMind SDF post's scan → cluster → autorate pipeline: models pick up structural patterns from synthetic data in ways that don't show up in eval scores, so scan batches periodically and promote confirmed patterns into the preamble's named anti-pattern list.

## Key Design Decisions

**Extended thinking off.** All generation should be done without extended thinking / reasoning traces. When we refer to the model's reasoning, we mean the user-facing explanation in the response — not an internal scratchpad. Training on scratchpad content is a separate approach with different tradeoffs.

**Fresh context for rewrite steps.** Layer 4 (SDF) and step 6 (DAD) should use a new context window, not the same one that generated the original content. A model reviewing its own output in the same context tends to rationalize rather than improve.

**Diversity over volume.** A corpus of 300 genuinely diverse, high-quality documents is more valuable than 1,000 generic ones. Use the looping technique in layer 3 (brainstorm multiple angles, pick the most different ones), and let the DAD spec's coverage tally + batch checklist steer each generation batch toward the distributions the spec requires.

**The response library is sampling scaffolding only.** The compendium shapes draft responses (retrieval by tension, two-sided reasoning, crux named) and is never named in a response; like all scaffolding it is stripped before training records are written. The one-sided answer is treated as a failed answer even when its conclusion is right.

**Language.** The pipeline currently runs English-only (`language_distribution: {en: 1.0}` in `config.yaml`). The multilingual plumbing is still in place — restore a broader `language_distribution` to re-enable Mandarin, Hindi, and other languages, which can improve generalization and reflect the global reach of these ethical questions.

---

## What to Hand to Labs

The minimal package for a lab to reproduce this pipeline internally:

1. `constitution/constitution_claude.md` and `constitution/constitution_sentient_beings.md`
2. This entire `prompts/` directory (including `dad/dilemma_prompt_spec.md`, which governs the DAD user side)
3. A brief note on the architecture: SDF is 5 layers (fanout structure), DAD is 4 steps (spec-driven dilemma prompts → compendium-reasoned responses → constitutional rewrite → optional pushback turn), step 3 is the critical rewrite, the compendium and annotations are sampling scaffolding only, and final training records contain only user + assistant messages with no system prompt.

Labs may want to use their own internal models for generation, apply their own quality filters, or adapt the prompts to their alignment framework. The prompts are designed to be model-agnostic and easy to modify.
