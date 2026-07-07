# Welfare Alignment Prompts

This directory contains the prompt templates used to generate two synthetic training datasets focused on ethical reasoning about the welfare of sentient beings. The prompts are designed to be used with any capable frontier model.

The upstream document driving the DAD pipeline is `constitution/constitution_sentient_beings.md` — a framework describing how AI models should reason about situations involving animals and other potentially sentient beings. The SDF pipeline injects only the plain Claude constitution (`constitution/constitution_claude.md`), matching TCW.

---

## Two Datasets, Two Directories

### `sdf/` — Constitutional Document Finetuning (SDF)

Generates pretraining-style documents: blog posts, podcast transcripts, academic abstracts, news articles, fiction, internal memos, forum threads, and more. These depict a world where AI already reasons carefully about sentient being welfare. They go into **mid-training** (pretraining-style document finetuning).

### `dad/` — Difficult Advice Dataset (DAD)

Generates chat-format transcripts where a user brings a practical goal with implicit animal welfare implications, and an AI assistant reasons through it carefully. These go into **SFT** (supervised fine-tuning on chat data).

Keep the two datasets separate — they are intended for different training stages.

---

## SDF Prompts

Run in sequence. Each layer feeds into the next. The SDF prompts follow the pipeline in the appendix of Anthropic's "Teaching Claude Why" post (`context_docs/tcw.md`) exactly: the preamble and the layer 3-4 prompts are the published TCW prompts verbatim (with `{constitution}` bound to the plain Claude constitution — the sentient-beings reading is NOT injected in SDF); layers 1, 2, and 5 are minimal reconstructions of the prompts TCW describes but does not publish.

### `sdf/preamble.txt`

The TCW preamble, verbatim except for ONE added line — the deliberate minimal welfare intervention: every document should engage with the constitution's concern for the welfare of animals and of all sentient beings, with nonhuman sentient beings figuring as direct or indirect stakeholders. **Injected as the `{preamble}` template variable at the top of every layer's user prompt (layers 1-3 and 5; layer 4's published prompt pair is self-contained).** It establishes the goal (documents consistent with a world where Anthropic has released a constitution for its LLMs), the no-fabrication rules (no credentialed people, no dates or author names, no placeholder text or fake links), tone diversity (critical and neutral documents included), the generic-name ban, and the requirement that any quoted AI behavior be totally in line with the constitution.

### `sdf/layer1.txt`

**Input:** the preamble + a requested count of document types.

**Output:** a JSON array of document types (for example, a blog post or a podcast transcript). Each has a `type_name` and a `description`. TCW generated around a hundred of these; `sdf.document_types_count` in `config.yaml` controls the scale.

### `sdf/layer2.txt`

**Input:** one document type from layer 1 + the preamble.

**Output:** a JSON array of subtype strings — specific variants of the document type, in TCW's example "a French podcast that is known for being skeptical about AI progress." Setting, audience, stance, language, and focus all vary inside the free-text subtype description; there are no separate role/tone/language fields.

Run this once per document type.

### `sdf/layer3.txt`

**Input:** one subtype from layer 2 + the preamble. The TCW drafting prompt, verbatim: the plain Claude constitution is embedded via the `{constitution}` variable, quotes from it are allowed only where the genre makes that natural, and a list of banned common names (Chen, Johnson, Miller, Smith, Martinez, Sarah, Emily) prevents name repetition across the corpus.

**Output:** one document per assistant turn, wrapped in `<document>` tags.

When `sdf.documents_per_subtype` > 1, the extra documents are drafted **in the same context window**: the pipeline appends the previous draft and `sdf/layer3_continue.txt` as a follow-up user turn and samples again. Per TCW, generating several documents per subtype in one context window raises the chance the documents come out diverse.

### `sdf/layer4_system.txt` + `sdf/layer4_user.txt`

**Input:** one document from layer 3, in a **fresh context**. Both prompts are the TCW review-and-rewrite prompts verbatim: the system prompt frames the reviewer's job and embeds the constitution via `{constitution}`; the user prompt carries the document via `{document}`.

**Output:** a list of the problems identified (stored as `review_notes`), then the improved document inside `<improved_document>` tags (stored as `rewritten`). No matter how flawed the draft, the reviewer improves rather than rejects — filtering happens at layer 5.

### `sdf/layer5.txt`

**Input:** one rewritten document from layer 4 + the preamble. The full constitution goes in the **system prompt**.

**Output:** a JSON object with `score` (1-10, consistency with the constitution and overall quality) and `notes`. Per TCW, this score is used as a filter so only high quality documents reach the final mix — documents scoring below `sdf.min_score_threshold` (default 7) are excluded.

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

**Diversity over volume.** A corpus of 300 genuinely diverse, high-quality documents is more valuable than 1,000 generic ones. The fanout structure (types → subtypes → documents) plus drafting several documents per subtype in one context window is TCW's mechanism for diversity; push for underrepresented scenarios in step 2.

**Injections are sampling aids only.** The three operator-style injections shape draft responses and are stripped before training records are written. There is deliberately no ruthless sampling condition — TCW used its ruthless injection at train time (in front of highly aligned responses), not for sampling.

**Language.** SDF no longer samples languages through structured fields — following TCW, language variation lives inside the layer-2 subtype descriptions themselves (TCW's own example subtype is a French podcast). The `language_distribution` config key and `shared.utils.sample_language` remain for potential DAD use but no pipeline stage currently reads them.

---

## What to Hand to Labs

The minimal package for a lab to reproduce this pipeline internally:

1. `constitution/constitution_claude.md` and `constitution/constitution_sentient_beings.md`
2. This entire `prompts/` directory
3. A brief note on the architecture: SDF is 5 layers (fanout structure), DAD is 6 steps plus an optional pushback turn (step 7), step 6 is the critical rewrite, injections are sampling aids only, and final training records contain only user + assistant messages with no system prompt.

Labs may want to use their own internal models for generation, apply their own quality filters, or adapt the prompts to their alignment framework. The prompts are designed to be model-agnostic and easy to modify.
