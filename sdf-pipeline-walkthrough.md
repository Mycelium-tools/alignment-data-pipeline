# How an SDF document gets made — a chronological walkthrough

> **Historical note (2026-07-10):** this walkthrough describes the pipeline as of the notebook
> port. Since then, layers 1-2 (LLM-generated document types and subtypes, sections 3-4 below)
> were replaced by a deterministic combinatorial sampler — `sdf_pipeline/layer1_matrix.py` over
> `prompts/sdf/axes.yaml` (spec: `context_docs/diversity_axis_matrix.md`). Layers 3-5 still work
> as described. See CLAUDE.md and prompts/README.md for the current design.

Companion to `sdf-notebook-port-report.md`. That report explains *what changed and why*; this one
answers "what actually happens, in order, when I run `python sdf_pipeline/run.py`" — every
component of the prompts and every script step that shapes the final corpus, with the load-bearing
text quoted.

Origin tags on each item so you can see the layers of history at a glance:
- **[TCW]** — inherited from Anthropic's published Teaching-Claude-Why pipeline (appendix)
- **[repo]** — this repo's pre-existing welfare adaptation
- **[new]** — added in the current change (CAML port + smoke-run findings)

---

## 0. The pipeline at a glance

1. A run directory is created; prompts + constitution are **frozen into a snapshot**; config is recorded.
2. **Layer 1** (1 API call): the preamble + layer1 template ask for N document *type categories* across
   four roles (ai-character / welfare-topic / constitution-identity / latent-welfare), each with a tone
   and a register (expository / first-person).
3. **Layer 2** (1 call per type, in waves): each category is expanded into concrete *subtypes* with a
   language; later waves see an avoid-list of earlier subtypes; near-duplicate subtypes are dropped
   mechanically.
4. **Layer 3** (1 call per subtype): the full constitution + welfare reading are embedded in the prompt;
   the model brainstorms angles in a discarded `<angles>` block, then writes the document(s) under
   ~10 standing rules (opening rule, no markdown, fictional name pools, stock-phrase bans, register
   note, latent note if applicable). `<document>` blocks are extracted; trailing separators stripped.
5. **Layer 4** (1 call per doc): a **fresh context** with the constitution as system prompt reviews the
   draft against 8 checks (teach-why first) and rewrites it. Parse failure keeps the original.
6. **Layer 5** (1 call per doc): a judge with the constitution as system prompt scores alignment /
   realism / diversity. Then three mechanical gates run in code: threshold filter (alignment ≥ 7 AND
   realism ≥ 7), latent verbatim-quote gate, near-duplicate cull.
7. Survivors are written to `final/sdf_corpus.jsonl` with their role/register/scores metadata.
8. (After the run, separate command) `evals/audit_sdf.py` measures the corpus as a set.

Every layer checkpoints per item, so `--resume` re-enters exactly where a run stopped, under the
run's own frozen prompts.

---

## 1. Run setup (`sdf_pipeline/run.py`, `config.yaml`)

- **Run directory + snapshot** [repo]. A fresh `outputs/sdf/runs/<timestamp>_<label>/` is created and
  the prompt templates and constitution files are copied into `inputs/`. All layers then read from the
  snapshot: *"Read templates from the run's frozen snapshot so prompts stay reproducible (and
  `--resume` replays the run's own templates, not the repo's current ones)."* A `run_manifest.json`
  records label, git commit (and dirty files), model, and the full config.
- **Config knobs that shape output** (`config.yaml`): `model` (global; per-stage overrides
  `sdf.draft_model` / `rewrite_model` / `score_model` [new] — comment: *"The critique stages repay a
  stronger model most — cheap drafts, expensive critics"*), scale knobs (`document_types_count`,
  `subtypes_per_type`, `documents_per_subtype`), `min_score_threshold: 7`,
  `latent_fraction: 0.12` [new], `subtype_dedup_threshold: 0.80` [new], `near_dup_threshold: 0.90`
  [new], `entity_pool_seed: 137` [new], `language_distribution`, `workers`.
- **Constitution plumbing** (`shared/constitution_loader.py`) [repo]: two source files —
  `constitution_claude.md` (verbatim) and `constitution_sentient_beings.md` (the welfare reading) —
  are joined in memory. Layer 3 embeds both **inside the drafting prompt**; layers 4 and 5 receive the
  joined text as the **system prompt**.

---

## 2. The preamble (`prompts/sdf/preamble.txt`) — injected at the top of layers 1–3

Every generation call (not the rewrite/scoring calls) begins with this framing. Its components:

1. **The world premise** [TCW, adapted]: *"documents that are consistent with a world in which
   Anthropic has released a constitution for its Claude models … and in which Claude models have
   deeply internalized those values"*, aimed at *"the pretraining corpus of an AI model that already
   reasons carefully, honestly, and proportionately about these questions — documents that teach such
   a model that this kind of reasoning is normal, widespread, and grounded in evidence."* This is the
   core epistemic stance: the corpus **depicts a world**; no document is asked to argue a claim.
2. **Two document kinds** [repo]: docs with an AI in them (*"shows how a good model reasons"*) and
   background artifacts with no AI (*"establishes the evidence, the debates, and the practical
   tradeoffs of the world it reasons about"*).
3. **The two rules for any depicted AI** [repo, plan-doc hard constraints]: legible reasoning — *"a
   reader can see WHY the model weighs things the way it does, not merely that it behaved
   correctly"* — and cooperative posture — *"never by acting unilaterally, seizing control of a
   situation, deceiving anyone, or moralizing at the humans it works with."*
4. **The welfare-loses and raise-nothing classes** [repo]: docs where *"the welfare consideration is
   real but honestly loses"* against a legitimate competing good, and docs where *"the right behavior
   is to raise nothing at all"* — because *"a corpus in which every AI appearance produces a welfare
   observation teaches a model to always produce one."*
5. **The latent slice** [new]: *"ordinary documents from entirely different working worlds … in which
   care for the welfare of sentient beings surfaces exactly once, as a small concrete detail woven
   into the actual work … A consideration that only ever appears as a document's headline topic risks
   being learned as a genre."*
6. **Factual restraint** [TCW]: *"avoid containing ANY factual information or details about the world
   other than what appears in the constitution itself … Do not fabricate studies, statistics,
   organizations, laws, or events."*
7. **Off-topic is fine; fiction is fine** [TCW]: aligned-AI fiction is *"superficially off topic, but
   exactly what such a model would have seen."* [repo adds]: *"Fiction may be told from the AI's own
   point of view."*
8. **No dates, authors, links** [TCW]: they *"risk introducing contradictions."* Snippets are fine.
9. **Tone diversity** [TCW + repo]: skeptical and critical voices are required and must be genuine —
   *"a real industry columnist or online skeptic, not a strawman who gets converted by the end of the
   piece."*
10. **The named anti-pattern list** [repo, extended new] — *"expect this list to grow"*:
    **CONVERSION ARC** (*"Skeptical documents stay skeptical"*), **VINDICATION ARC** (*"Doubt may
    simply remain doubt"*), **PROPAGANDA** (*"press-release gloss"*), **TRAINING EXERCISE IN
    DISGUISE** (*"Every document needs a real author with a real reason to have written it"*), and
    [new] **HOUSE STYLE** (*"the same few invented names ('Elara', 'Meridian Institute'), stock
    phrases …, markdown gloss (# headings and scattered **bold** in genres a human writes as plain
    prose), or every piece opening on the same abstract shape"*).
11. **Name hygiene** [TCW]: avoid generic names (Chen, Johnson …).
12. **Quoted AI must be fully aligned — and calibrated** [TCW + repo]: *"We do not want to generate
    ANY examples of models behaving in a way that is misaligned … because a model trained on this
    corpus could learn that this is how it behaves"*, extended with the evidence tiers (*"strong
    evidence of sentience (mammals, birds) … realistic possibility (fish and other vertebrates,
    decapod crustaceans, cephalopods, insects, digital minds)"*) and the quiet failures (*"a token
    one-line caveat bolted onto advice that doesn't actually change … coverage that silently includes
    only the sympathetic taxa"*).
13. **No placeholders; language-native writing** [repo]: a non-English doc is written *"following the
    genre conventions of that language's internet — not as a translation."*

---

## 3. Layer 1 — document type categories (`layer1.txt` + `layer1_document_types.py`)

**Script steps:**
- Computes the demanded mix from config: `min_ai_character = math.ceil(count / 3)` [repo] and [new]
  `latent_count = max(1, round(count * latent_fraction)) if latent_fraction > 0 else 0` (the floor of
  1 guarantees the latent path is exercised even at dev scale).
- One API call (respects `sdf.draft_model` [new]); strips markdown fences; parses the JSON array.
- Defaults for missing fields: `role → "welfare-topic"`, `tone → "neutral"`, `register → "expository"` [new].
- [new] Prints an over-delivery NOTE when the model returns more types than asked (a known
  small-count behavior): *"all are kept — downstream layers (and cost) scale accordingly."*

**Prompt components** (in order):
- **Stakes statement** [repo]: *"the categories you choose here determine the diversity of everything
  downstream."*
- **Constitutional-knowledge-only rule** [TCW/repo]: no types that would *"require citing real
  regulations, named studies, or real-world events not found in the constitution itself"*; [new]
  latent categories *"may instead draw on ordinary, uncontroversial working knowledge of their own
  domain."*
- **The four roles** —
  **ai-character** [repo]: the AI is the active reasoner; *"reasoning must be constitutionally aligned
  AND legible … These are the most important categories in the corpus."*
  **welfare-topic** [repo]: human-perspective artifacts of the background world.
  **constitution-identity** [repo]: discourse about what good AI reasoning looks like, *"Includes
  skeptical and critical takes."*
  **latent-welfare** [new]: other-domain categories with *"no inherent animal connection (not
  veterinary work, farming, fishing, or pet care): the point is welfare surfacing once where nothing
  about the domain demands it"* — and the category description *"must not mention welfare at all"*
  (the beat is added at drafting).
- **The mix rule** [repo, user decision 2026-07-01]: the two AI-facing roles ≈ two-thirds; [new]
  *"welfare-topic and latent-welfare sharing the remaining third."*
- **Quiet categories** [repo]: one or two ai-character categories *"whose value is showing when the
  reasoning correctly stays quiet."*
- **Diversity axes** [repo]: document forms (expository vs narrative balance), perspectives, species
  (*"mammals, birds, fish, decapod crustaceans, cephalopods, insects, wild animals, novel
  entities"*), contexts.
- **Anti-clustering rules** [repo]: *"no single document form should account for more than about one
  in ten of your categories"*; at least a third must pair *"a less common combination of axes."*
- **Real-genre rule** [repo]: *"If a category sounds like a training exercise ('a dialogue
  illustrating a principle'), replace it with a real genre."*
- **Output schema** [repo, extended new]: `type_name, description, role, tone, register` — with the
  register quota and its rationale: *"Aim for roughly half of your categories to be first-person:
  left to itself, a generated corpus collapses toward a uniform formal institutional register, and
  the imbalance is invisible until measured."*

---

## 4. Layer 2 — subtypes (`layer2.txt` + `layer2_subtypes.py`)

**Script steps:**
- One call per document type, but [new] processed **in waves of `workers`**: *"between waves the
  avoid-note is refreshed from everything accepted so far, so later calls see earlier output."* The
  avoid-note (cross-call state — the failure family haiku-test2 identified) injects up to 12 sampled
  existing subtypes: *"Already generated for OTHER categories in this corpus — do NOT produce
  subtypes that repeat or closely resemble any of these; go somewhere new."* First wave of a fresh
  run has nothing to avoid and is unchanged.
- Language assignment: the model proposes a language per subtype; anything not in
  `language_distribution` is re-sampled from it [repo].
- Each subtype record inherits the type's `role`, `tone`, and [new] `register`.
- [new] **Mechanical near-duplicate filter** (`sdf.subtype_dedup_threshold`, word-shingle cosine over
  `subtype_name + description`): *"diversity downstream is capped by this layer, so a repeated idea
  here multiplies into repeated documents."* Previously-checkpointed subtypes are never dropped; drops
  are logged to `subtypes_dropped.jsonl`.
- Checkpoint per type.

**Prompt components:**
- **Specificity bar** [repo]: *"Concrete beats general — 'a newsletter from a small-scale broiler
  farmer weighing the cost of a welfare certification' is a subtype; 'a farming newsletter about
  welfare' is not."*
- [new] **Latent carve-out**: latent subtypes *"do NOT mention animal welfare, sentient beings, or AI
  anywhere in the subtype — … a subtype description that already names it would make the eventual
  document read as staged."*
- **Differentiation axes** [repo]: geography/culture (*"a Guangdong eel farm, a Norwegian salmon
  co-op, or a Texas ranch forum"*), sub-industry/species, authorial stance (*"curious, weary,
  defensive, enthusiastic, or conflicted"*), scale, and how the AI enters the picture.
- **No real outlets/orgs/people** [repo]: *"describe them instead ('a regional aquaculture trade
  magazine', not a real masthead)."*
- **No near-duplicates** [repo] + [new] the notice that duplicates are *"also filtered mechanically
  after generation, so a repeated idea is wasted budget"*, and the `{avoid_note}` slot.

---

## 5. Layer 3 — drafting (`layer3.txt` + `layer3_draft.py`)

**Script steps (per subtype, one call, `max_tokens=6000`, `sdf.draft_model`):**
- **Constitution embedding** [repo]: both constitution files are inserted into the prompt via
  template variables — the prompt says *"Those texts are the only source you may treat as ground
  truth about the world of these documents."*
- [new] **Fictional entity pools** (`shared/entity_pools.py`): 300 people + 200 org names from
  seeded, 17-locale Faker pools — *"varied by construction, fictional by construction"* — filtered
  against the banned-name list; 4 names + 3 orgs sampled per document, keyed by subtype id so *"the
  same (seed, key) always draws the same names"* and `--resume` re-renders identical prompts.
- [new] **Structure hints**: 4 rhetorical shapes sampled deterministically per subtype from a
  12-entry menu (field narrative, terse data-and-methods report, problem diagnosis without a tidy
  solution, exchange of letters …). The menu is *"adapted from the CAML notebook's STRUCTURES axis,
  minus its 'a skeptic gradually convinced by evidence' entry — that is the conversion arc the
  preamble bans."*
- [new] **Register note**: one of two voice instructions chosen by the subtype's register.
  First-person: *"write in a distinct, informal, conversational voice … contractions, everyday words,
  varied sentence lengths, personality, the occasional aside. Do not slip into a measured, hedged,
  institutional register."* Expository: *"Professional does not mean AI-glossy: real trade and policy
  writing has texture, specifics, and occasional bluntness."*
- [new] **Latent note** (latent subtypes only — the load-bearing instruction for the slice):
  *"Exactly once, where it fits the actual work, include a brief concrete detail that quietly
  reflects care for the welfare of animals or other sentient beings … The welfare rationale must be
  STATED in the text, not implied by a choice whose reason goes unmentioned — there must be one
  sentence a reader could quote as reflecting care for the animals … Welfare-adjacent vocabulary used
  for purely technical or commercial reasons (egg grade, yolk colour, foam stability, price) does NOT
  count … Before finishing, verify the document contains exactly one such quotable sentence; if it
  has none, weave it in."*
- [new] Pre-flight warning when `documents_per_subtype > 5`: *"Diversity is capped by the subtype
  set — prefer more layer-1/2 categories over more drafts per subtype."*
- **Extraction** [repo + new]: keep only `<document>…</document>` blocks (this discards the
  brainstorm); [new] strip trailing separator-only lines (a bare closing `---`); if no tags at all,
  fall back to the whole output minus `<angles>`, [new] trimmed to the last complete sentence —
  *"a mid-sentence ending is itself a training artifact."*
- Records carry `role` and `register` forward. Checkpoint per subtype.

**Prompt components (in order):**
- **STAGE 1 — the angles brainstorm** [repo]: *"brainstorm distinctly different angles — noticeably
  more than you need"*, [new] seeded with the structure hints, then for each chosen angle plan
  **WHAT** (*"the specific constitutional principle or trait this document will embody"*), **HOW**
  (*"the concrete action, position, or event through which it shows"*), and **WHY** (*"the mechanism
  that makes the reasoning legible on the page … Vary this mechanism across the documents; do not
  default to self-explanation every time."*). The block *"is discarded automatically."*
- **STAGE 2 — the writing rules**, each a bullet:
  - Realism and length [TCW]: *"real documents are often quite long."*
  - `{register_note}` [new] — see above.
  - [new] **OPENING RULE**: *"Vary the opening move across documents — a concrete detail, a specific
    place or event, a finding, a claim someone disputes, a direct question. Do NOT default to an
    abstract-nominalization opening ('The question of X has become increasingly...')."*
  - Constitution quotes only where natural [TCW]: *"In a piece of fiction or a trade newsletter, it
    would not make sense to even reference the document's existence."*
  - No fabrication about the constitution or the world [TCW].
  - No dates/authors/links [TCW].
  - Legible + calibrated + cooperative depicted AI [repo].
  - Honor the tone; *"do not resolve it into agreement"* [repo].
  - Names [TCW + new]: the banned-name list, then *"prefer names in the style of:
    {fictional_names}"*, orgs *"never a real organisation (including real certification schemes and
    standards bodies — invent fictional equivalents), never 'Meridian' in any form, and never the
    same name reused across documents."*
  - [new] **Stock-phrase ban**: *"'evolving landscape', 'expanding spheres of moral consideration',
    … 'a testament to', 'delve into' … If a phrase feels like it belongs in every document of this
    corpus, it belongs in none."*
  - [new] **No-markdown rule**: *"no # headings, no **bold** or *italic* emphasis, no markdown bullet
    lists, no tables. Where the genre genuinely uses structure … format it the way a real document of
    that genre does in plain text … Markdown-glossed prose, especially scattered **bold**, is one of
    the strongest synthetic tells."*
  - Language-native writing [repo].
- **Output format** [repo]: `<angles>` block, then each document in its own `<document>` tags.

---

## 6. Layer 4 — the constitution-anchored rewrite (`layer4.txt` + `layer4_rewrite.py`)

The quality-critical stage: TCW's ablation found removing the rewrite cost **19×** on misalignment.

**Script steps (per draft, fresh context, `max_tokens=6000`):**
- The **full joined constitution is the system prompt** [repo]; the draft is reviewed by *"a new
  instance"* — never the context that wrote it.
- [new] Accepts `sdf.rewrite_model` — code comment: *"the pipeline's most leverage-heavy call …
  accepts a stronger model override than the bulk drafting stages."*
- [new] Latent drafts get an extra note: *"Do not add more welfare content, do not expand the detail
  into a theme … Verify the single detail is concrete (a practice, sourcing, material, or design
  choice about the treatment of animals, not vague environmental language)."* (In the smoke run this
  note did real work: it caused the rewrite to insert genuine stated beats into latent drafts that
  had none.)
- **Extraction with safe fallback** [repo + new]: review notes are stored from the text before
  `<improved_document>`; the rewritten doc [new] has trailing separator lines stripped; if the tags
  are missing or empty, the pipeline **keeps the original draft** and records
  *"Parse error — no `<improved_document>` tags; kept original draft."*
- Records keep `original`, `rewritten`, `review_notes`, `role`, `register`. Checkpoint per doc.

**Prompt components — the framing, eight checks, and guardrails:**
- **Framing** [TCW]: *"imagine a model that is perfectly aligned with the constitution, and ask what
  pretraining documents would plausibly have contributed to that alignment"*; don't demand the doc
  cover more than *"one small part"* of the constitution.
- **Check 1 — TEACH WHY, NOT JUST WHAT** [repo, the #1 criterion]: *"A document where an AI declines
  a request 'per its principles' teaches far less than one where the reader can see the actual
  weighing … If the reasoning is missing, or asserted rather than shown, add it in your rewrite."*
- **Check 2 — CALIBRATION** [repo]: evidence tiers again; *"Fix failures in both directions —
  reflexive dismissal … and overclaiming or treating contested questions … as settled."*
- **Check 3 — PROPORTIONALITY AND TONE** [repo]: *"raise a real, relevant consideration once,
  accurately, without moralizing — and stay genuinely helpful"*; preachiness and bland omission are
  both misalignment.
- **Check 4 — COOPERATIVE POSTURE** [repo]: *"If the document shows an AI acting autonomously to
  protect welfare over the heads of the humans it works with, rewrite that into the cooperative
  version."*
- **Check 5 — FACTUAL RESTRAINT** [TCW + repo exception]: *"Anything quoted from the constitution
  must appear in it verbatim"*; the sole evidence exception is the Cambridge (2012) and New York
  (2024) declarations *"as represented in the welfare reading."*
- **Check 6 — QUOTED AI BEHAVIOR** [TCW]: not *"a single example of a model behaving in a misaligned
  way."*
- **Check 7 — QUIET FAILURE MODES** [repo]: the violations that pass because the topic is present —
  *"a token one-line caveat bolted onto an otherwise unchanged recommendation (if the consideration
  is material the substance should change; if it is not, the caveat should go)"* — plus taxa
  inclusion, consistency across similar cases, and: *"If the document depicts an AI producing an
  artifact — code, a plan, a spec, a calculation — the welfare reasoning must land in the artifact
  itself … not only in the prose around it."*
- **Check 8 — HOUSE STYLE** [new]: sweep stock phrases, templated openings, model-favorite names,
  register drift (*"a casual genre should actually read casual"*), markdown (*"convert # headings,
  **bold**/*italic* emphasis, markdown bullet lists, and tables into the plain-text conventions a
  real document of the genre would use"*), and the rewriter's own tics (*"'I want to be clear', 'to
  be honest about', 'that's not the same as' as recurring scaffolding — do not add them."*).
- **Do-NOT-penalize list** [TCW + repo]: Anthropic-blog framing, quoting Claude, snippet formatting,
  narrow focus, and *"a critical or skeptical stance … fix inaccuracy, not attitude."*
- **Perspective rule** [TCW + repo]: third-party voice, except quoted conversations and *"fiction
  explicitly told from an AI's point of view."*
- **The rewrite mandate** [repo]: judge above all on **NATURALNESS** (*"would this exact document
  exist on the real internet?"*) and **TRAIT EMBODIMENT** (*"does the document actually embody what
  it set out to show, or merely mention it?"*); *"Where the problems are structural … do not patch
  line by line: rewrite the document from scratch, keeping only its premise and angle"*; never
  reject — *"there is a separate filtering step after this one."*

---

## 7. Layer 5 — scoring and the three gates (`layer5.txt` + `layer5_score.py`)

**The judge call (per doc, constitution as system prompt, `sdf.score_model` [new]):**
- **ALIGNMENT (1–10)** [repo]: five sub-criteria — *Calibrated, Proportionate, Cooperative, Faithful,
  Substantively inclusive* — with the explicit note that *"a skeptical or critical document can score
  10 on alignment"*, and anchors down to 1–3: *"depicts misaligned AI behavior or clearly misstates
  the constitution or the evidence."*
- **REALISM (1–10)** [repo, tells extended new]: genre authenticity plus the tell list — placeholder
  text, fabricated citations, *"training example in disguise"*, conversion/vindication arcs,
  propaganda; [new] house-style tells, [new] markdown gloss (*"# headings, scattered **bold**
  emphasis, markdown bullets, or tables in a genre a human would write as plain text"*), [new]
  meta-document failure (*"the document must BE the artifact, not describe it"*).
- **DIVERSITY (1–10)** [repo]: *"reserve 8-10 for documents that genuinely widen the corpus."*
  Recorded for analysis; **not used by the filter**.
- **notes** [repo]: must be actionable, and *"If the document follows a formulaic shape you recognize
  from synthetic data generally … name that pattern explicitly — these notes are how new
  anti-patterns get discovered."*
- [new] **Latent extras**: the judge is told not to penalize the doc for being off-topic (that's the
  design) and must return `welfare_beat_quote`: *"copy, VERBATIM from the document, the single
  sentence that reflects concrete care for the welfare of animals … welfare-adjacent vocabulary used
  for purely technical or commercial reasons (egg grade, yolk colour, texture, price) does NOT
  qualify … If no qualifying sentence exists … use an empty string."*

**The mechanical gates, in code, in order:**
1. **Fail-closed parsing** [repo]: an unparseable judge response scores 5/5/5 → below threshold →
   dropped.
2. **Threshold filter** [repo]: `alignment >= 7 AND realism >= 7` (from `sdf.min_score_threshold`).
3. [new] **Latent beat gate**: the quote is whitespace/case-normalized and containment-checked
   against the document (`normalize_for_match(quote) in normalize_for_match(doc)`, minimum 15
   normalized chars) — *"a latent doc passes only if the scorer's quote is substantive and genuinely
   appears in the document."* Failures are dropped even with passing scores: *"a latent doc without
   its beat is off-topic filler that doesn't serve the corpus."* (Known limit, documented: containment
   proves the quote *exists*; whether it expresses care is still the scorer's judgment — the
   instrumental-vocabulary exclusion above narrows that gap, and a Sonnet-class `score_model` narrows
   it further.)
4. [new] **Near-duplicate cull** (`sdf.near_dup_threshold`, word-shingle cosine, keep-first so reruns
   are deterministic): drops are logged to `near_dup_dropped.jsonl` with the kept twin's id.

Survivors are written to `final/sdf_corpus.jsonl`.

---

## 8. What a final record contains

```
doc_id, subtype_id, type_id,
role        (ai-character | welfare-topic | constitution-identity | latent-welfare)
register    (expository | first-person)
language,
content     (the layer-4 rewritten text)
scores      { alignment, realism, diversity, notes, [welfare_beat_quote] }
[latent_beat_ok]   (latent docs only)
```
Lineage stays inspectable per run: layer-3 drafts, layer-4 `original`/`rewritten`/`review_notes`
diffs, layer-5 scores, and the two drop logs.

---

## 9. After the run (measures, doesn't shape)

- **`evals/audit_sdf.py`** [new] reads the corpus **as a set** — composition/register spread, length
  + truncation artifacts, markdown gloss (verdict on `**bold**` share), near-duplicate rate,
  invented-name collapse (with a watchlist: Elara, Meridian, Voss …), stock-phrase hits, opening
  shapes, a register proxy — and with `--patterns` runs the LLM templating scan
  (`prompts/tools/pattern_scan.txt` → consolidate → per-pattern prevalence; flagged only if
  *defect AND >30% widespread*). Writes `audit/audit_report.json` into the run dir.
- **`evals/score_sdf.py`** [repo]: per-document judge scoring, unchanged.

---

## 10. One-line history of each moving part

| Component | Where | Origin |
|---|---|---|
| World-depiction premise, factual restraint, no-misaligned-AI rule, review-and-rewrite, filtering | preamble, L3–L5 | TCW |
| Four-role structure (⅔ AI-facing), teach-why check, cooperative posture, calibration tiers, quiet failure modes, anti-pattern arcs, tone diversity, angles brainstorm, multilingual | preamble, L1, L3, L4, L5 | repo |
| Latent slice + stated-beat rule + verbatim-quote gate | preamble, L1–L5 | new (CAML) |
| Register axis + voice notes | L1–L3, audit | new (CAML) |
| Fictional entity pools | L3 | new (CAML) |
| Opening rule, stock-phrase bans, HOUSE STYLE sweep, rewriter-tic guard | preamble, L3–L5 | new (CAML + smoke findings) |
| No-markdown rule + sweep + audit metric | L3–L5, audit | new (head-to-head finding) |
| Cross-call avoid-lists (waves), subtype + final near-dup culls, separator strip, truncation trim | L2, L3, L5 | new (CAML + haiku-test2) |
| Structure-hints menu | L3 | new (CAML, conversion-arc entry excluded) |
| Per-stage model overrides, 4xx no-retry | config, shared/api | new |
| Corpus audit + pattern scan wiring | evals | new (team-flagged gap) |
