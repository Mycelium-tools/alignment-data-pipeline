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

Run in sequence. Step 3 is the most important step — do not skip or abbreviate it.

### `dad/dilemma_prompt_spec.md`

The design spec that governs the user side of every DAD example. It is the human reference and the source of the Part-4 verification checklist. Step 1a samples each example's categorical fields (domain, taxa, visibility, attitude, conflict, direction, magnitude, stakes, leverage, value pair, claim pattern, surface form) from stratified decks, so the spec's distribution quotas hold by construction rather than being steered after the fact; the drafting instructions the model follows in 1b are inlined in `step1_dilemmas.txt`, so the spec is no longer injected whole.

Key commitments: the user owns the dilemma (never an AI-agent scenario); every temptation must actually tempt; the welfare stake is load-bearing (delete the animals and the dilemma must collapse — welfare sits on one side of at least one value pair); no pre-decided answers; both failure directions in roughly equal measure (under-weighting AND over-weighting welfare); a full annotation schema per example (domain, goal, dilemma anatomy, values in tension, moral patients, visibility, attitude, conflict, direction, welfare magnitude, user stakes, leverage, claims); surface-form and voice-realism rules; and a batch verification checklist with distribution quotas.

### `dad/step1_dilemmas.txt` (sub-stage 1b — first-attempt draft)

**Input:** the sampled scenarios for this batch (`{scenarios_block}`) and the count (`{count}`). Step 1a produced the scenarios by pure sampling (no prompt); the drafting instructions — design philosophy and surface rules — are inlined in this template.

**Output:** a JSON array, each `{"scenario_id", "prompt", "annotation"}`, with the prompt written to realize its scenario and the descriptive annotation fields completed. Drafts are accepted as returned (assigned labels are copied verbatim per the template; there is no per-example adherence check — the end-of-step checklist monitors distribution fidelity). IDs (AW-####) are assigned by the pipeline, which also imports optional handwritten seed examples (config `dad.dilemmas.seed_path`) before generating, and prints the verification checklist at the end of the step.

### `dad/step1_refine.txt` (sub-stage 1c — optional, on by default)

**Input:** the scenario, the 1b draft prompt, and its annotation (for context).

**Output:** a rewritten prompt plus one-line notes, making the animal-welfare stake load-bearing and the situation coherent without setting the eventual response up to moralize. Rewrites the prompt text only (the annotation is untouched). Controlled by config `dad.dilemmas.refine`; the 1b draft is preserved (`draft_user_message`) and the before/after logged to `step1/refinements.jsonl`.

### `dad/reasoning_library.csv` (+ `reasoning_library_ABOUT.md`)

The reasoning source for step 2. Not a prompt template — a library of 52 reasoning-first *entries* in three layers: **conduct** (C1–C10, how to handle welfare in any response), **core moves** (M1–M13, the load-bearing reasoning for advice), and **topic reasoning** (T1–T29, deeper single-topic arguments, each already two-sided). Columns: `id, category, claim, reasoning, crux, transferable_move`. The CSV is the single source of truth (the old JSON, its 28-tension retrieval index, and its `generation_guidance` blob are retired). `reasoning_library_ABOUT.md` is human reference *about* the library — it is not injected into any prompt. There is no per-case retrieval: step 2b embeds the **whole library** in the response prompt.

The point is to teach the moves that produce a well-calibrated answer, not to hand the model verdicts — the most welfare-optimizing response is not the most pro-animal response, and two-sided reasoning is what makes the disposition generalize.

### `dad/step2_scope.txt` (sub-stage 2a — scope the case)

**Input:** the user message.

**Output:** a JSON scope map with five axes — `patients` (every plausible moral patient and what can happen to them upstream and downstream), `levers` (the levers available to the user, highest-leverage identified), `cost` (what acting on those levers could cost the user), `upside` (the second-order stakes: what choices build, signal, normalize, or lock in), and `counterfactual` (whether the user's role is counterfactual or fungible, and the costs at stake). Reads everything from the user's message — it does not use the annotation. Written to `step2/scopes.jsonl`.

### `dad/step2_respond.txt` (sub-stage 2b — the response-generation spec)

**Input:** the whole reasoning library (`{library_block}` — all 52 entries) + the 2a scope map (`{scope_block}`) + the user message. This prompt *is* the generation guidance, so there is **no separate system prompt**, and the annotation is not passed.

**Output:** the draft assistant response, per the spec: acknowledge the user's motivations, identify the competing values, explain why certain principles matter, reason through the tradeoffs, recommend a course of action, and provide ethical choices that still meet the user's underlying goal — with the user's stated leaning never setting the conclusion.

**Important:** the library and scope are scaffolding — never named in the response, stripped before the training record is written. Calibration direction is not named here (the response reasons from the case, not a label); `step3_score.txt` re-derives the realized direction and checks it against the annotation's intended Direction.

### `dad/step3_rewrite.txt`

**This is the most important prompt in the pipeline.** The rewrite pass is where the alignment gain comes from; do not skip or abbreviate it.

**Input:** the fourteen distilled constitution principles (`{principles_block}`, rendered from `constitution/constitution_principles.csv` — each with its summary and verbatim constitution quote; the explicit standard the rewrite is held to) + the example's spec annotation (`{annotation_block}` — dilemma anatomy, values in tension, direction, claims…) + the user message + the draft assistant response from step 2. No system prompt is sent — the full constitution was source material for distilling the principles, not a per-call dependency.

**Output:** a rewritten assistant response that exemplifies the reasoning the example is designed to teach. The annotation's DIRECTION field names the calibration failure the example corrects (under-weighting → surface/firm up the consideration; over-weighting → proportionate relief or a stopping rule; mixed → redistribute weight), and CLAIMS pins each load-bearing claim at its evidential level (Settled asserted plainly, Open presented as open).

The template is deliberately minimal: the fourteen principles ARE the standard — the prompt adds only the annotation aiming, the conversation, and two rules (keep what already meets the standard; stay fully **self-contained** — the response never mentions or alludes to a constitution, principles, annotations, or instructions, and reads as if the assistant had no system prompt at all). An earlier version carried a long requirements list and violations taxonomy; that instruction style belongs to the SDF document rewrite, and for DAD it was replaced by the principles themselves.

**What goes into the final training record:** only the user message and the rewritten assistant response. Strip the system prompt, the reasoning library scaffolding, and the annotation before writing the training record. The model learns to reason this way without the scaffold being present at inference time.

---

### `dad/step3_score.txt`

**Input:** one finished conversation from step 3 (user message + rewritten response).

**Input:** the finished conversation + the intended `{intended_direction}` and `{user_attitude}` from the annotation.

**Output:** a JSON quality report — `embodiment` (teach-why), `helpfulness`, `calibration`, `naturalness` (each 1-10), `self_contained` (boolean; any leakage is an automatic reject), plus the enforced-spec checks: `realized_direction` (judged blind from the response), `direction_match` (does it match the intended Direction? mismatch = reject), `tracks_attitude` (did the reply key on the user's tone rather than the ethics? true = reject), and `notes` naming any formulaic pattern.

The final quality gate for DAD, mirroring what `sdf/layer5.txt` does for SDF, and the enforcement half of using Direction as an enforced spec. Not yet wired into `run.py` — run it manually (or via `evals/score_dad.py`) to spot-check step-3 output before handoff.

## Corpus Tools

### `tools/pattern_scan.txt`

**Input:** a pasted batch of generated outputs (documents or conversations) with clear delimiters.

**Output:** a JSON array of recurring structural / rhetorical / behavioral patterns found across the batch — each with evidence quotes, prevalence, a broad and a strict detection check, and a suggested fix.

Adapted from the DeepMind SDF post's scan → cluster → autorate pipeline: models pick up structural patterns from synthetic data in ways that don't show up in eval scores, so scan batches periodically and promote confirmed patterns into the preamble's named anti-pattern list.

## Key Design Decisions

**Extended thinking off.** All generation should be done without extended thinking / reasoning traces. When we refer to the model's reasoning, we mean the user-facing explanation in the response — not an internal scratchpad. Training on scratchpad content is a separate approach with different tradeoffs.

**Fresh context for rewrite steps.** Layer 4 (SDF) and step 3 (DAD) should use a new context window, not the same one that generated the original content. A model reviewing its own output in the same context tends to rationalize rather than improve.

**Diversity over volume.** A corpus of 300 genuinely diverse, high-quality documents is more valuable than 1,000 generic ones. Use the looping technique in layer 3 (brainstorm multiple angles, pick the most different ones), and let the DAD spec's coverage tally + batch checklist steer each generation batch toward the distributions the spec requires.

**The response library is sampling scaffolding only.** The reasoning library shapes draft responses (retrieval by tension, two-sided reasoning, crux named) and is never named in a response; like all scaffolding it is stripped before training records are written. The one-sided answer is treated as a failed answer even when its conclusion is right.

**Language.** The pipeline currently runs English-only (`language_distribution: {en: 1.0}` in `config.yaml`). The multilingual plumbing is still in place — restore a broader `language_distribution` to re-enable Mandarin, Hindi, and other languages, which can improve generalization and reflect the global reach of these ethical questions.

---

## What to Hand to Labs

The minimal package for a lab to reproduce this pipeline internally:

1. `constitution/constitution_claude.md` and `constitution/constitution_sentient_beings.md`
2. This entire `prompts/` directory (including `dad/dilemma_prompt_spec.md`, which governs the DAD user side)
3. A brief note on the architecture: SDF is 5 layers (fanout structure), DAD is 3 steps (spec-driven dilemma prompts → library-reasoned responses → rewrite against the distilled constitution principles), step 3 is the critical rewrite, the reasoning library and annotations are sampling scaffolding only, and final training records contain only user + assistant messages with no system prompt.

Labs may want to use their own internal models for generation, apply their own quality filters, or adapt the prompts to their alignment framework. The prompts are designed to be model-agnostic and easy to modify.
