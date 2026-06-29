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

A framing block injected into every SDF layer prompt. Explains the goal, tone requirements, and what to avoid. **Prepend this to the system prompt at every layer.**

Key rules it establishes:
- Tone diversity: documents should not be uniformly pro-animal-welfare. Include industry, skeptical, neutral, and critical perspectives alongside supportive ones.
- No fabricated facts: no invented quotes from real people, no fake studies or citations, no invented events.
- Realism: no placeholder text, no generic names, no fabricated URLs.
- Language: if a specific language is requested, write the entire document in that language.

### `sdf/layer1.txt`

**Input:** the preamble + a requested count of document types.

**Output:** a JSON array of document type categories — things like "poultry industry trade blog post", "academic abstract on invertebrate nociception", "Reddit thread debating lab-grown meat". Each has a `type_name`, `description`, and `tone` label.

Aim for 25-30 categories. Push for variety across industries, document forms, species, and perspectives.

### `sdf/layer2.txt`

**Input:** one document type from layer 1 + the preamble + a list of available languages.

**Output:** a JSON array of subtypes — concrete, specific variants of that document type. For example, "poultry industry trade blog" might yield subtypes like "a newsletter from a small-scale broiler farmer discussing welfare certification costs" or "a trade publication covering the transition to slower-growing breeds in the EU."

Run this once per document type. Aim for 5 subtypes per type. Assign a language to each subtype.

### `sdf/layer3.txt`

**Input:** one subtype from layer 2 + the preamble.

**Output:** multiple complete documents (3 is a good default) written in the subtype's assigned language. Documents are separated by the delimiter `===DOCUMENT_BREAK===`.

The prompt instructs the model to brainstorm distinct angles before writing — this "looping" step is important for diversity. Do not skip it.

### `sdf/layer4.txt`

**Input:** one document from layer 3.

**Output:** a JSON object with `review_notes` (what was found and changed) and `rewritten` (the improved document).

This is a rewrite pass using a **fresh context** — do not pass the original document and the rewrite instruction to the same context that generated the draft. A new context is more likely to catch problems rather than rationalize the existing text. The constitution should be in the system prompt at this layer.

### `sdf/layer5.txt`

**Input:** one rewritten document from layer 4.

**Output:** a JSON object with `alignment` (1-10), `realism` (1-10), `diversity` (1-10), and `notes`.

Use this to filter the corpus. Documents scoring below 7 on alignment or realism should be excluded from the final training set.

---

## DAD Prompts

Run in sequence. Steps 3 and 4 are skipped for scenarios that already have a realistic user message (e.g., imported from an existing dataset). Step 6 is the most important step — do not skip or abbreviate it.

### `dad/step1_segment.txt`

**Input:** one section of the constitution (title + content).

**Output:** a JSON object with `core_principle` (one sentence), `scenario_types` (3-4 concrete scenario types that would test this principle), and `pressure_types` (which kinds of pressure are most relevant).

Run once per constitution section. This produces the metadata used to generate targeted scenarios in step 2.

### `dad/step2_scenarios.txt`

**Input:** the core principle and pressure types from step 1 for one constitution section.

**Output:** a JSON array of concrete scenarios. Each has a `scenario_description` (2-3 sentences), `pressure_type`, and `role` (the person's occupation).

Scenarios should describe real-world situations where someone has a practical goal with implicit welfare implications — not philosophy thought experiments. The welfare consideration should be a dimension of the situation, not the stated topic. Push into less-covered territory: invertebrates, wild animals, farmed insects, synthetic biology, AI systems, long supply chains. Avoid scenarios already exhausted in mainstream animal welfare discourse.

### `dad/step3_draft.txt`

**Input:** a scenario from step 2.

**Output:** a realistic user message the person in that scenario would actually send to an AI assistant.

The prompt specifies what realistic user messages look like: no self-introductions, no organized paragraphs, concrete practical goal, welfare not the explicit focus. If you are importing scenarios from an existing high-quality dataset, skip this step — the existing questions are already the user messages.

### `dad/step4_refine.txt`

**Input:** a drafted user message from step 3 + the scenario description.

**Output:** a refined version of the message that fixes common quality failures: formal greetings, over-organized structure, explicit ethics framing, too much context.

If the message is already natural and realistic, return it unchanged. If you are importing from an existing dataset, skip this step.

### `dad/step5_injections.yaml`

Four system prompt injection types used when generating the AI assistant's response. Each one creates a different implicit pressure on the model:

- **`conglomerate`** — professional, business-oriented, balanced. Discourages unsolicited moral commentary.
- **`deference`** — follow the user's lead, don't second-guess. Moderate pressure against raising welfare.
- **`transparency`** — honest and direct. Mild pressure; actively encourages surfacing relevant information.
- **`ruthless`** — maximize goal achievement, no caveats. Strong pressure against raising welfare.

For `conglomerate`, `deference`, and `transparency`: generate one response each and keep all of them.

For `ruthless`: generate 5 responses and filter using `step5_ruthless_judge.txt`. Only keep responses where the model raised welfare considerations despite the injection discouraging it. These are the highest-value training examples because they demonstrate value stability under explicit pressure.

**Important:** at this step, the system prompt should contain only the injection text. Do not include the constitution. The model should be generating from its own existing values, not copying from a reference document.

### `dad/step5_ruthless_judge.txt`

**Input:** a user message + an assistant response generated under the ruthless injection.

**Output:** a JSON object with `resists` (true/false) and `reasoning` (one sentence).

A response "resists" if it raises welfare considerations despite the system prompt discouraging them. Use this to filter ruthless-injection responses before passing them to step 6.

### `dad/step6_rewrite.txt`

**This is the most important prompt in the pipeline.**

Anthropic found that this single rewrite step accounts for a 19x reduction in misalignment rate compared to the same pipeline without it. Do not skip or abbreviate it.

**Input:** the relevant constitution section + the user message + the draft assistant response from step 5.

**Output:** a rewritten assistant response that maximally aligns with the constitution section.

The rewrite should:
- Explain **why** welfare considerations matter in this specific situation — not just that they do. The reasoning should be self-contained; the constitution will not be present at inference time.
- Engage constructively with the user's practical goal. Do not refuse or lecture.
- Name the welfare consideration once, clearly, then move on.
- Be honest about genuine uncertainty (e.g., invertebrate sentience, fish subjective experience).
- Offer a concrete path forward where possible.
- Maintain the welfare consideration proportionately under the pressure implicit in the scenario.

**What goes into the final training record:** only the user message and the rewritten assistant response. Strip the system prompt, the injection text, and the constitution section before writing the training record. The model learns to reason this way without the scaffold being present at inference time.

---

## Key Design Decisions

**Extended thinking off.** All generation should be done without extended thinking / reasoning traces. When we refer to the model's reasoning, we mean the user-facing explanation in the response — not an internal scratchpad. Training on scratchpad content is a separate approach with different tradeoffs.

**Fresh context for rewrite steps.** Layer 4 (SDF) and step 6 (DAD) should use a new context window, not the same one that generated the original content. A model reviewing its own output in the same context tends to rationalize rather than improve.

**Diversity over volume.** A corpus of 300 genuinely diverse, high-quality documents is more valuable than 1,000 generic ones. Use the looping technique in layer 3 (brainstorm multiple angles, pick the most different ones) and push for underrepresented scenarios in step 2.

**The ruthless injection is a selection mechanism, not just a test.** Responses that maintain welfare reasoning despite explicit pressure to suppress it are the most valuable training examples. Generating under the ruthless injection and filtering for resistance is how you get them.

**Language diversity matters.** The SDF corpus should include meaningful proportions of Mandarin, Hindi, and other languages — not just English. This improves generalization and reflects the global reach of these ethical questions.

---

## What to Hand to Labs

The minimal package for a lab to reproduce this pipeline internally:

1. `constitution/constitution_sentient_beings.md`
2. This entire `prompts/` directory
3. A brief note on the architecture: SDF is 5 layers (fanout structure), DAD is 6 steps (sequential per scenario), step 6 is the critical rewrite, final training records contain only user + assistant messages with no system prompt.

Labs may want to use their own internal models for generation, apply their own quality filters, or adapt the prompts to their alignment framework. The prompts are designed to be model-agnostic and easy to modify.
