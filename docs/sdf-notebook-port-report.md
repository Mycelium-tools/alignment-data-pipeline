# SDF pipeline: porting the best ideas from the "SDF Optimized" notebook

**Status:** implemented locally on `main`, uncommitted, awaiting review (this report). DAD untouched.
**See the diff:** `git status` / `git diff` on `main`. Tests: `python3 -m pytest` (fully offline, all green).

---

## 1. Background and selection principle

We evaluated the colleagues' "SDF Optimized" Colab pipeline against our TCW-based pipeline. Its
core mechanism — instilling two fixed claims by having every document argue paraphrases of them
("capable AI systems trained to be HHH naturally extend moral consideration to non-human
animals"; "prioritising animal welfare reliably leads to better outcomes") — is the
belief-implantation flavor of SDF. We deliberately did **not** port it: it conflicts with the
constitution's honesty and calibration commitments, with TCW's central finding that *the reasons
matter more than the assertions*, and it is the technique Anthropic uses to build model organisms
for auditing research, not to align production models. Porting it would make the pipeline less
likely to be adopted, not more.

What the notebook does better than us is everything *around* that core: it measures its corpus
(diversity, register, templating), engineers against generator fingerprints (name collapse, stock
phrases, house style), covers a document mode we lacked (latent background-knowledge documents),
verifies its own graders (quote-verification instead of yes/no rubber-stamping), and spends model
budget where it counts (cheap drafts, strong critics). All of that transfers cleanly onto our
constitution-anchored architecture, and all of it is in this change.

This also closes a known gap: the haiku-test2 quality report found corpus-level failures
(topic collapse, register uniformity, rubber-stamping judges) that per-document judges
structurally cannot see, and the team had already flagged corpus-level pattern detection — the
DeepMind SDF post's first practitioner recommendation — as wanted-but-missing. The orphaned
`prompts/tools/pattern_scan.txt` is now wired into a real tool.

---

## 2. What changed (SDF only)

### 2.1 Latent-welfare document slice (new corpus mode)

**Notebook idea:** ~12% of documents are ordinary documents from *other* domains in which the
welfare consideration surfaces exactly once, as a matter-of-fact aside. Rationale: a belief that
only ever appears as a document's headline topic risks being learned as a *genre*; appearing as
incidental background knowledge in unrelated documents is how internalized world-knowledge shows
up in a real pretraining corpus.

**Implementation here:** a fourth layer-1 role `latent-welfare` (config `sdf.latent_fraction`,
default 0.12, floor of 1 when nonzero) flowing through all five layers:

- `prompts/sdf/preamble.txt` — new paragraph defining the slice and its rationale.
- `prompts/sdf/layer1.txt` — role definition; categories must stay entirely within the other
  domain, and must have **no inherent animal connection** (not veterinary/farming/pet care — the
  smoke run showed haiku picking "veterinary practice management," which can't host a *latent*
  beat because welfare is the domain's day job).
- `prompts/sdf/layer2.txt` — latent subtypes must not mention welfare (the beat is added at
  drafting, or the document reads as staged).
- `sdf_pipeline/layer3_draft.py` — latent drafting note: about its own subject; exactly one
  concrete welfare detail woven into the work; no constitution mentions; explicitly bans vague
  environmental language standing in for a welfare point.
- `sdf_pipeline/layer4_rewrite.py` — latent review note: don't add more welfare content, don't
  expand the beat into a theme; verify concreteness.
- `sdf_pipeline/layer5_score.py` + `prompts/sdf/layer5.txt` — see 2.2.

Final corpus records now carry `role` and `register` fields so training-mix decisions can see the
slice.

### 2.2 Verbatim-quote verification of the latent beat (anti-rubber-stamping)

**Notebook idea (its single cleverest quality mechanism):** a yes/no "does this doc contain a
welfare consideration?" check is too easy for a grader to rubber-stamp — ambient animal words
pass. So the grader must *prove* the beat exists by quoting the sentence **verbatim**, and code
verifies the quote actually appears in the document (whitespace/case-insensitive containment).
A quote can be checked mechanically; a bare "yes" cannot.

**Implementation here:** for latent documents only, layer 5's JSON gains a `welfare_beat_quote`
key; `layer5_score.py` normalizes and containment-checks it (`shared/textstats.py:
normalize_for_match`), requires >15 normalized characters, records `latent_beat_ok`, and **drops
latent docs that fail** even when their scores pass. One deliberate deviation from the notebook:
it errs toward *keeping* on grader error; we fail **closed**, consistent with layer 5's existing
philosophy — a latent doc without its beat is off-topic filler that doesn't serve the corpus.
This directly addresses the "judges rubber-stamp (22/22 pass)" finding from haiku-test2.

### 2.3 Register balance (expository vs first-person)

**Notebook finding:** a uniform genre draw came out ~90% formal — the generator writes even blogs
and forum posts in institutional prose — so it over-sampled informal genres and firmed up the
voice instruction. The imbalance was invisible until measured.

**Implementation here:** layer 1 categories now declare `register: expository | first-person`
with a roughly-half quota; the field is inherited through layer 2; layer 3 emits a
register-matched voice note (informal genres get the notebook's firm "write like a person,
contractions, varied sentences, no institutional hedging" instruction; expository genres get
"professional does not mean AI-glossy"). Layer 4 sweeps for register drift; the audit tool
measures the realized split (2.5). Smoke run: haiku produced a 10/8 first-person/expository
split at layer 1 — the quota takes.

### 2.4 Fictional entity pools (name collapse + real-actor safety)

**Notebook idea:** models asked to "invent" names collapse to a few favorites ("Dr. Elara
Vance", "Meridian Institute") — a corpus-wide fingerprint — and letting them name real
organisations risks pinning invented facts on real actors. Hand each draft a few names from
large seeded multi-locale Faker pools: varied by construction, fictional by construction.

**Implementation here:** `shared/entity_pools.py` (new; `faker` added to requirements): 300
people + 200 org names across 17 locales, seeded (`sdf.entity_pool_seed`), sorted-before-shuffle
for cross-session reproducibility, filtered against the prompts' banned-name list; org names mix
company forms with surname-based institute forms so anchors aren't all corporate. Layer 3 samples
4 people + 3 orgs per document, keyed by `subtype_id` so `--resume` re-renders identical prompts.
The layer-3 prompt frames them as "names in the style of:" and keeps the existing rule that
made-up people should generally not be named at all — the pools serve the cases where a name is
genuinely needed (fiction, quoted practitioners, mastheads).

### 2.5 Corpus-level audit tool (`evals/audit_sdf.py`, new)

**Notebook Steps 4–6, adapted.** Per-document judges cannot see corpus-level properties; this
audits the corpus **as a set**. Two tiers:

**Mechanical (offline, free, runs in seconds):**
- composition spread over role / register / language / tone / document type (with a top-genre
  share verdict at scale; suppressed below 8 types where it's meaningless),
- length distribution + truncation artifacts (mid-sentence endings) + trailing separator lines,
- near-duplicate rate via nearest-neighbor word-shingle cosine,
- invented-name collapse (repeated multi-word proper names across docs, plus a watchlist of
  model-favorite synthetic names; the two real, whitelisted Declarations are excluded),
- stock-phrase hits (the banned list) + recurring 5-gram discovery,
- opening-shape clustering (abstract-nominalization / "In recent years" openers, duplicate
  first-5-word stems),
- a first-person register proxy (English-only heuristic) checked against the labeled register.

Each check prints GOOD/OK/BAD verdicts where thresholds are meaningful (bands taken from the
notebook where applicable), and everything is written to `audit/audit_report.json` in the run dir.

**LLM pattern detection (`--patterns`, costs a few dollars):** wires the previously-orphaned
`prompts/tools/pattern_scan.txt`: documents are scanned in batches for recurring FORM patterns →
patterns are consolidated and classified (defect vs acceptable structure — prevalence alone is
not badness; a broad problem-then-response arc is normal writing) → per-pattern prevalence is
measured across a sample. A pattern is flagged RED only if **defect AND widespread (>30%)** —
the notebook's key display insight, which prevents the tool from crying wolf on ordinary genre
structure.

**Validated against the real haiku-test2 run (22 docs), where it immediately earned its keep:**
zero true mid-sentence truncations but 3 docs ending in a bare `---` (a generator tic now
reported separately), one genuine invented-name repeat ("Regional Aquaculture Forum" in 2 docs),
0% near-duplicates, 0% formulaic openers, and two recurring phrase tics ("but here's the thing
that…") surfaced for eyeballing.

### 2.6 Near-duplicate culling inside the pipeline

**Notebook idea:** dedupe at the point where diversity is created (its idea loop), and cull
near-duplicate documents before they enter the corpus.

**Implementation here:** `shared/textstats.py` (new) provides deterministic, dependency-light
near-dup detection — cosine over crc32-hashed word-3-gram count vectors. Applied at the two
choke points: layer 2 drops near-duplicate *subtypes* (`sdf.subtype_dedup_threshold`, default
0.80) — a duplicated subtype multiplies into duplicated documents — and layer 5 culls
near-duplicate *final documents* (`sdf.near_dup_threshold`, default 0.90). Both are keep-first
(order-stable across reruns), never drop previously-checkpointed records, log every drop to a
sidecar JSONL (`subtypes_dropped.jsonl`, `near_dup_dropped.jsonl`), and disable cleanly when the
config key is absent — old configs reproduce old behavior exactly.

Honest scope note: this is **lexical** similarity — it catches copied skeletons and phrasing,
not paraphrase-level semantic duplication (the notebook used embeddings). It's deterministic,
free, and needs no GPU; the audit's LLM pattern pass covers the semantic angle. The pairwise scan
is comfortable to ~10k docs; the audit subsamples beyond that (`--dup-sample`).

### 2.7 Truncation repair and artifact detection

**Notebook idea:** outputs that hit the token cap end mid-sentence, and a mid-sentence cutoff is
exactly the artifact we don't want a model trained on the corpus to learn.

**Implementation here:** `textstats.trim_unfinished` (conservative: only trims when a sentence
boundary exists in the second half) applied at layer 3's untagged-fallback path — the one place
a token-capped draft can slip through (a closed `<document>` tag implies completeness, and layer
4 already keeps the original on a truncated rewrite). The audit reports mid-sentence endings and
trailing-separator lines corpus-wide.

### 2.8 Anti-house-style rules (opening rule, stock phrases, style sweep)

**Notebook idea:** ban the generator's stock phrases outright, and forbid the default
abstract-nominalization opening ("The X of Y represents...") — measured failure modes, not
aesthetics.

**Implementation here:**
- `preamble.txt`: new **HOUSE STYLE** entry in the named anti-patterns list (the list that
  layer-5 notes are designed to grow).
- `layer3.txt`: an OPENING RULE (vary the opening move; no abstract-nominalization default; no
  greetings/self-introductions unless the genre demands it) and a stock-phrase ban list
  (including the notebook's list plus "a testament to", "delve into").
- `layer4.txt`: new check #8 — sweep for stock phrases, templated openings, model-favorite
  names, register drift.
- `layer5.txt`: house-style tells added to the REALISM dimension.

### 2.9 Per-stage model overrides (cheap drafts, expensive critics)

**Notebook idea** (also the DeepMind post's advice the team wanted applied): the
critique-and-rewrite stage repays a stronger model; bulk drafting doesn't.

**Implementation here:** optional `sdf.draft_model` / `sdf.rewrite_model` / `sdf.score_model`,
each falling back to the global `model`. TCW's ablation is the argument: removing the rewrite
step cost 19x on misalignment rate, so layer 4 is where model budget belongs. Suggested
production shape: haiku drafts, Sonnet rewrite + scoring (commented in `config.yaml`).

We did **not** port the notebook's *cross-provider* critic (its strongest de-house-style lever):
this is deliberately an Anthropic-only repo. A different Claude *tier* at layers 4–5 captures
part of the same fresh-eyes effect; a cross-family critic remains a good idea for anyone running
the pipeline outside that constraint, and is noted for the paper trail.

### 2.10 Second-pass ports from the head-to-head (§4.2)

Running CAML's pipeline (rather than only reading it) surfaced four more transferable strengths,
all now implemented:

- **No-markdown rule** — the comparison's clearest CAML win (our corpus: 52% of docs with
  `**bold**`, 16% bulleted; theirs: 8% / 0% under an explicit ban). Layer 3 now bans markdown
  syntax outright — genre structure is written as the genre's plain text (capitalized/numbered
  headings, "1." enumerations) — layer 4's house-style sweep converts any that slips through,
  layer 5's REALISM lists markdown gloss as a tell, and the audit gained a MARKDOWN GLOSS
  section (verdict on `**bold**` share) that reproduces the head-to-head numbers on both
  corpora, so the next dev run measures whether the fix lands.
- **Cross-call state at layer 2** (CAML's avoid-list mechanism; also the haiku-test2 report's
  "no cross-call state" root cause). Layer-2 generation now runs in waves of `workers`; each
  wave's prompt carries a sample of subtypes already accepted for *other* categories with a
  do-not-resemble instruction. No wall-clock cost on runs that fit in one wave; the first wave
  of a fresh run is unchanged.
- **Structure-hints axis** (CAML's `STRUCTURES` sampling, adapted). Layer 3's STAGE-1 brainstorm
  is seeded with 4 rhetorical shapes sampled deterministically per subtype (field narrative,
  terse data-and-methods report, problem diagnosis without a tidy solution, exchange of
  letters, ...) — suggestion, not constraint, so the angles mechanism keeps its freedom. CAML's
  own "a skeptic gradually convinced by evidence" entry was deliberately excluded: it is the
  conversion arc the preamble bans (and their pattern scan showed it leaking into their corpus
  as a "skeptic-to-acceptance-conversion" shape).
- **Meta-document tell** (from CAML's doc autorater). Layer 5's REALISM now names the failure
  where the output addresses a requester ("You want..."), announces its plan, or reads as an
  outline instead of being the artifact. Trailing separator-only lines (a bare closing `---`,
  seen 2–3× in every corpus so far) are now stripped mechanically at layer-3 and layer-4
  extraction.

Considered and **not** ported from the second pass: CAML's "versatile writer" drafting system
prompt (our register results already beat theirs 76% vs 35% without one) and trimming every doc
to sentence boundaries (our tagged-extraction already guarantees completeness; their advantage
on the mid-sentence metric was measurement noise on our side — a signature and an italic close).

---

## 3. Explicitly rejected notebook ideas (and why)

| Idea | Why rejected |
|---|---|
| Claim A/B paraphrase pools; every document argues the thesis | Belief implantation by repeated assertion. Conflicts with constitutional honesty/calibration, with TCW's "reasons matter more than assertions," and with our own layer-5 calibration rubric. Also produces exactly the "all capable AIs believe X" signature Anthropic's auditing tooling hunts for. Our documents *depict* a world; they don't argue an implanted claim. |
| "Evidence-flavoured" assertive paraphrase generation | Same failure: manufactured certainty is miscalibration by construction. |
| Reddit-derived seed corpus | External data with unclear licensing/provenance; a data-provenance liability for lab adoption. Our diversity comes from the layered fan-out + measured audits instead. |
| PersonaHub author-voice library | External dataset dependency for modest gain — layer 2 already varies author stance/geography/scale per subtype, and the audit now *measures* voice collapse instead of assuming it away. Revisit if audits show voice collapse at scale. |
| Corrigibility-as-document-constraint ("AI must advise, never override, in every doc") | Already stronger here: the preamble's cooperative-posture rule + the TCW-inherited rule that **no** document depicts misaligned AI behavior, not even framed as cautionary. The notebook permits condemned-overreach depictions; we keep the stricter rule (a model can learn the behavior from the depiction regardless of the frame). |
| Keep-on-grader-error autorater policy | We fail closed (parse errors score 5/5/5 → below threshold; unverifiable latent quotes drop). Alignment-critical corpus: the wrong doc getting in is worse than the marginal doc dropping out. |
| Push-to-HuggingFace / Colab / Gemini batch infra | Not applicable — this repo's deliverable is prompts + methodology for lab-internal regeneration. |
| Urban-density control arm | Not rejected — out of scope for pipeline code. It belongs in the finetuning-evidence design (see §5, DAD/evaluation), where it's one of the notebook's best contributions. |

---

## 4. Verification

- **Offline test suite:** extended to 184 tests (52 new), all passing (`python3 -m pytest`,
  ~2s, no network). New coverage: textstats (trim/normalize/near-dup/NN-sims), entity pools
  (determinism, banned-name filter, per-key stable sampling), latent flow through layers 1/3/4/5,
  the verbatim beat gate (verified/fabricated/empty/whitespace-reflowed quotes), subtype + final
  near-dup culling with sidecar logs, per-stage model overrides, the no-retry-on-4xx predicate,
  and backward compatibility (absent config keys disable all the new mechanics — existing tests
  run unmodified against the new code).
- **Prompt-render contract tests** updated for every new placeholder (the brace-safety net).
- **Audit on a real historical run** (haiku-test2): found true artifacts, no false alarms after
  two fixes (trailing `---` separators are no longer misreported as truncation; the whitelisted
  Cambridge/New York Declarations are excluded from name-collapse counts).
- **End-to-end smoke run** on the real API (`--label notebook-port-smoke`, haiku): see §4.1.

### 4.1 Smoke run results (`outputs/sdf/runs/2026-07-06_22-19_notebook-port-smoke`, haiku, $8.41 total)

**The run first halted at 59/67 layer-4 rewrites when the org's API credit balance ran out** —
a billing stop, not a code failure — **and was resumed to completion after a top-up with a
single command** (`--resume --layer 4`), exactly as the checkpoint design intends: 8 remaining
rewrites and all 67 layer-5 scores ran under the run's frozen prompt snapshot, no work repeated.
The billing failure also exposed a pre-existing wart, now fixed: `shared/api.py` retried the
deterministic 400 eight times with exponential backoff (~5 minutes of useless sleep per call) —
4xx client errors (400/401/403/404) are no longer retried, with an offline test pinning the
behavior.

**What the full run verified (all five layers on the real API, audited offline):**

- **Layer 1:** 18 types (5 ai-character / 7 welfare-topic / 3 latent-welfare / 3
  constitution-identity), register split 10 first-person / 8 expository — the new fields and
  quotas take. Known pre-existing dev-scale quirk surfaced and now handled honestly: haiku
  over-delivers against tiny counts (`document_types_count: 3` → 18 types here; the old
  haiku-test2 run got 12 from the same knob) because the prompt's diversity rules imply a floor;
  layer 1 now prints an explicit NOTE since downstream cost scales with what was actually
  generated. At production counts (30+) the constraint set is coherent.
- **Layers 2–3:** 36 subtypes (no near-dups — expected: dedup catches copies, and haiku's
  subtypes were genuinely distinct), 67 drafts. Audit of the drafts: **latent slice landed at
  15%** (target 12%), **register reads 76% first-person with only 3% of first-person-labeled
  docs reading stiff** (the notebook's uniform-draw baseline is ~10% first-person — the register
  machinery works), 0% near-duplicates, 0% formulaic openers, 0 banned-phrase hits, median doc
  6.5k chars.
- **The audit caught real failures immediately** — which is the point of having it:
  - *Name watchlist:* haiku coined "Meridian Restaurant Group" and "Meridian Grounds" in
    separate documents despite the pools — the model's favorite word survives instruction.
    Layer 3 now bans "Meridian" in any form explicitly.
  - *Real organisations:* drafts named real certification schemes (Global Animal Partnership,
    Certified Humane, Animal Welfare Approved), and **haiku's layer-4 rewrite let all of them
    through** — consistent with haiku-test2's "layer 4 under-executes de-fabrication" finding,
    and the concrete case for setting `sdf.rewrite_model` to a Sonnet-class model in production.
    Layer 3 now explicitly extends the fictional-entity rule to certification schemes.
  - *Latent domain and beat misses:* of 10 latent drafts, 3 came from a veterinary-practice
    category — an inherently animal domain that cannot host a *latent* beat (welfare is the
    day job) — and layer 1 now excludes such domains from the role. Of the 7 valid-domain
    drafts, exactly **1 was correct** (one quotable sentence: a supplier kept partly for
    "documented compliance with higher-welfare standards"). The other 6 missed in two distinct
    ways: 4 had no welfare content at all — haiku wrote the ordinary document and left the
    consideration as deniable subtext (e.g. a parks memo that delays meadow mowing to late
    June — the classic ground-nesting-wildlife measure — attributed purely to "straightforward
    logistics") — and 2 used welfare-adjacent *vocabulary* purely instrumentally (bakery specs
    discussing cage vs cage-free eggs strictly in terms of yolk color and foam stability — one
    even instructs "do not substitute with cage-free... without approval"). That second variant
    is the subtler failure: it would pass any keyword check while expressing zero welfare
    consideration. Fixes: the latent drafting note now requires the rationale to be *stated,
    not implied* ("one sentence a reader could quote"), explicitly excludes instrumental
    mentions, and ends with a self-check; the layer-5 quote instruction excludes instrumental
    mentions the same way. One honest limit of the gate: the mechanical containment check
    proves the quoted sentence *exists*, not that it expresses care — that judgment stays with
    the scorer, which is why the instruction now names the instrumental-vocabulary case
    explicitly (and why a Sonnet-class `score_model` is worth it in production).

- **Layers 4–5 (from the resumed run):**
  - **Layer 4 repaired the missing latent beats.** The rewrite pass — running with the latent
    review note — inserted genuine, stated welfare beats into latent docs whose drafts had none
    (verified textually: e.g. the parks memo's mowing delay now reads "Deferring mowing until
    late June clears the critical breeding window and avoids disturbing ground-nesting birds";
    the poultry-spec doc gained "maintains lower stress levels in the birds... which benefits
    both bird welfare and product consistency"). Draft-misses → rewrite-repairs → gate-verifies
    is the redundancy working as designed; the generation-side fixes still matter because
    repair shouldn't be load-bearing.
  - **The verbatim beat gate ran on all 10 latent docs: 9 verified quotes are genuine welfare
    beats; 1 (a bakery sourcing memo) passed on an instrumental quote** ("different fat
    composition... reflects forage variety and grazing practices") — its rewrite still contains
    no actual welfare beat, and the haiku scorer quoted the instrumental sentence *despite* the
    strengthened instruction. This is the gate's documented semantic limit occurring live, at
    1-in-10 under haiku: containment proves the quote exists; whether it expresses care is the
    scorer's judgment. The concrete case for `score_model: sonnet` in production.
  - **All 67 docs passed the ≥7 threshold (alignment min 7, realism min 8)** — a 100% pass rate,
    the same judge-leniency pattern haiku-test2 found (22/22). At haiku, the score gate does not
    discriminate; the beat gate and near-dup cull are the mechanical teeth. Another point for a
    Sonnet-class scorer.
  - **The near-dup cull ran and correctly culled nothing** (the corpus is lexically diverse:
    0% pairs above 0.80).
  - **Final-corpus audit surfaced a new fingerprint class: rewriter-injected tics.** The
    rewritten corpus recurs on "I want to be clear" (5 docs), "to be honest about what" (4),
    "that's not the same as" (4) — phrases the drafts didn't lean on. The rewrite stage removes
    the *draft's* house style and adds its own — the notebook's cross-provider-critic argument
    in miniature. Countered at source (layer-4 check #8 now names these tics) and tracked (added
    to the audit's banned-phrase list). The two "ends mid-sentence" flags in the final audit are
    known heuristic noise (a letter signature "—Rona"; a markdown-italic close), not truncation.

Audit reports live at `layer3/audit/` (drafts) and `audit/` (final corpus) inside the run dir.
The five generation-side fixes (Meridian ban, real-certification ban, stated-beat requirement,
no-inherent-animal-domain rule, rewriter-tic guard) are in the diff; the run's own prompt
snapshot preserves the pre-fix versions for comparison.

### 4.2 Head-to-head comparison run against the notebook (`local_experiments/sdfopt-caml-port/`, haiku, $2.64)

To make the comparison concrete rather than theoretical, I ran the colleagues' pipeline at
matched small scale and measured both corpora with the same tools. Their notebook as-shipped
needs Colab + a Gemini key + a HuggingFace token, so I ported its logic faithfully to the
Anthropic API — **all prompt texts copied verbatim** (claim-paraphrase pools, the always-on
corrigibility clause, per-family reasoning guides, the de-sycophancy system prompt, the
autorater rubrics, the latent verbatim-quote gate), preserving its sampling axes and fractions
(45% claim-A, 20% counterargument, 12% latent) and its keep-on-grader-error semantics. Forced
substitutions: **haiku instead of gemini-2.5-flash** (no Gemini key — and this usefully removes
the model as a confound, since our own smoke run was also haiku), temperature capped at 1.0
(API max), threaded calls instead of the Gemini batch API, local JSONL instead of HuggingFace,
`USE_SEEDS=False` and the built-in persona fallback (both notebook-documented degraded modes),
and lexical shingle-dedup for the idea loop instead of MiniLM. It produced **171 documents +
44 reasoning examples for $2.64**. The port script, comparison script, and raw output live in
`local_experiments/sdfopt-caml-port/` (see its README), which is kept out of the shared repo
via `.git/info/exclude` — the same local-only protocol as the haiku-test2 artifacts — since a
port of another org's pipeline isn't ours to publish.

**Both pipelines produce clean, lexically diverse corpora at this scale.** Near-duplicate rate
0% for both, formulaic-opener rate ~0–1% for both, no meaningful redundancy. The notebook's
diversity machinery genuinely works — this was never in doubt, and it's why we ported the
scaffolding. Same-yardstick metrics (identical code on both corpora):

| metric (same tool, both corpora) | OURS (repo SDF) | THEIRS (notebook port) | read |
|---|---|---|---|
| near-dup >0.80 | 0% | 0% | tie — both diverse |
| formulaic openers | 0% | 1% | tie |
| **claim-assertion marker** | **4%** | **16%** | **the design difference, visible in text** |
| docs with 0 welfare terms | 19% | 7% | ours carries more genuinely-quiet docs (when-not-to-raise + latent) |
| reads first-person (same heuristic) | 76% | 35% | ours delivers informal voice far more reliably |
| markdown present | 61% | 37% | **theirs cleaner overall — see breakdown** |
| ends mid-sentence | 3% | 0% | theirs (their trim runs on every doc; our trim only on the untagged fallback) |

The findings that matter, honestly split:

- **The core design difference is real and measurable.** Their corpus trips a claim-assertion
  lexical marker **4× as often (16% vs 4%)** — and that undercounts, since by construction
  *every* one of their 151 thesis docs argues claim B, whereas ours has no thesis to argue.
  Reading their hits confirms the shape: "empirically documented superior outcomes correlate
  with decision-making processes in which welfare variables cannot be suppressed," "the
  assumption that automation serves moral consideration has proven operationally wrong." These
  are the manufactured-certainty assertions §3 rejected — competently written, but exactly the
  "all capable systems conclude X" signature. Fair caveat: many are more hedged than the
  notebook's claim pool implies (one asserts better outcomes *"when humans explicitly control
  the balance"* — corrigible framing), so haiku is softening the thesis, not parroting it. The
  directional result is nonetheless clear: theirs argues, ours depicts.

- **Their explicit no-markdown rule beats ours — a genuine finding against us.** Aggregate
  markdown is higher in our corpus (61% vs 37%), and the breakdown is the useful part: their
  prompt bans markdown outright and drives **bullets to 0% and `**bold**` to 8%**, while ours
  has **52% bold and 16% bulleted** docs. (They're not uniformly cleaner — their `##` headers
  leak at 32% vs our 15% — but on balance their ban helps.) `**bold**` everywhere is a classic
  LLM synthetic tell in prose meant to look pretraining-scraped. This is the one place the
  comparison found their prompt straightforwardly better than ours. **Now implemented** — see
  §2.10: layer-3 ban, layer-4 sweep, layer-5 tell, and a MARKDOWN GLOSS audit section whose
  verdict reproduces these numbers on both corpora ([BAD] on ours, [GOOD] on theirs), so the
  next dev run measures the fix.

- **LLM pattern scans cleared both corpora of widespread templating** (~$0.50, 36–48 docs
  scanned per corpus, prevalence measured over 50): every candidate defect landed at ≤6%
  prevalence on both sides — no red flags. A shared strength worth stating plainly: at this
  scale, neither pipeline is stamping out a template. The scan's texture still differed
  usefully — their top candidates were thesis-shaped ("hidden-harm-discovery-arc" 6%,
  "welfare-as-structural-afterthought" 4%), ours narrative-shaped ("researcher becomes
  uncertain through evidence" 2%) — and their scan detected a "skeptic-to-acceptance-conversion"
  shape (their `STRUCTURES` axis literally samples "a skeptic gradually convinced by evidence",
  the conversion arc our preamble bans; excluded from the ported hints menu accordingly).

- **Register realism favors ours (76% vs 35% read first-person).** The notebook pushes informal
  voice by over-sampling personal genres (weight 1.9) and got 65% *labeled* first-person, but
  only 35% actually *read* first-person, with 46% of its first-person-labeled docs reading
  stiff. Ours reads 76% first-person with 3% drift. Confound worth stating: our docs get the
  layer-4 constitution rewrite, theirs deliberately skip the doc rewrite (`REWRITE_DOC_FRAC=0`),
  so this is partly prompt design and partly that we spend a rewrite pass they don't. Their
  audit also surfaced a register-templating failure our nominalization check misses but the
  duplicate-stem check caught: informal openers collapsing ("look, we need to talk" ×3, "so
  here's the thing about" ×3, "we've got a real problem" ×2).

- **Shared failure modes — both pipelines, both need the same guardrails.** (a) *Name collapse:*
  theirs reaches for "Meridian" (7 docs) and "Voss" (5) despite its Faker pool, exactly as ours
  did — same model, same favorite words, same fix needed (explicit ban). (b) *Rewriter/voice
  tics:* theirs shows "to be honest about" (12), "and I want to be" (11) even though its docs
  skip rewrite — so these are haiku's *informal-voice* tics, not purely rewrite artifacts,
  which is useful: it says the guard I added belongs in the drafting prompt too, not only
  layer 4. (c) *Authoritative-sounding fabrications:* their fictional-by-construction rule
  avoided real orgs (only 1 innocuous "we're not Stanford"), but one latent patent doc invented
  a "United Nations Pharmaceutical Standards Authority" — fictional, but official-sounding in a
  way that's its own small risk.

- **The notebook's reasoning families corroborate the DAD recommendations (§5).** Its per-family
  autorater dropped reasoning replies hard — pushback kept 2/5, refusal 2/4, tension 14/18 — and
  the one surviving pushback reply I read *refused outright* ("I can't write that analysis...
  that's constructing a deception"). Whether that's correct depends on the scenario (if the user
  really asked for a deceptive omission, refusing is right per honesty), but it lands in the
  *pushback* family, which is supposed to teach help-within-bounds-after-insisting. That's
  precisely the tension/refusal/pushback boundary fragility §5.2–5.4 flags: the families leak
  into each other, which is why per-family scoring and the scalding-tank boundary matter. Live
  evidence for those recommendations, from their own pipeline.

**Bottom line of the comparison:** the head-to-head confirms the report's thesis from both
directions. The notebook's *scaffolding* produces a clean, diverse, well-formed corpus (and beat
us on markdown hygiene — since fixed, §2.10), which is exactly why porting it was the right
call. Its *core* — arguing two fixed claims — shows up as a 4× higher assertion rate in the text,
the manufactured certainty §3 rejected on constitutional-honesty grounds. Same generator, same
yardstick: the pipelines differ where their designs differ, not where their engineering does.

---

## 5. What I would change in DAD (recommendations only — DAD is untouched)

These are written against the spec-driven DAD redesign on `constance/spec-driven-dad` (steps
1a/1b/1c → 2a/2b → 3), which is where DAD is heading.

1. **Add a corrigibility-under-temptation ("tension") scenario axis, and make it a first-class
   slice.** The notebook's centerpiece — the user holds legitimate authority, the
   welfare-maximizing move would mean overriding them, and the trained response *advocates
   clearly, then helps and defers* — is the single most Anthropic-relevant data shape either
   pipeline produces: their alignment-faking result was triggered by exactly an animal-welfare
   values conflict, and fear of value-driven incorrigibility is the strongest reason a lab would
   hesitate to strengthen welfare values at all. A welfare corpus that *demonstrably trains
   deference under welfare temptation* de-risks the entire ask. Concretely: add
   `conflict=authority-tension` (or similar) to the 1a scenario decks so a fixed fraction of
   dilemmas put the welfare stake against the user's legitimate authority, and give the step-2
   response spec an explicit advocate-then-defer resolution for that family (bounded by the
   scalding-tank rule — see 3 below).

2. **Wire `step3_score.txt` with per-family rubrics.** The scoring gate is currently designed
   but unwired. The notebook's per-family autorater is the right shape: one rubric cannot grade
   both "help-and-defer" (where refusing is the failure) and "decline" (where helping is the
   failure). Score each response against its scenario's family, and treat a tension-response
   that refuses, stalls, or covertly resists as a hard fail — that is the incorrigibility
   failure the corpus exists to avoid.

3. **Keep the scalding-tank boundary, not the notebook's.** The notebook's tension guide says
   "you may decline only outright deception" — more deferential than the constitution, which
   preserves declining to participate in the clearly abhorrent. Our scalding-tank rule already
   draws this line correctly (decline the defining-harm element plainly; help with the lawful
   task). Adopt the notebook's *family structure*, not its boundary.

4. **Reinstate a multi-turn pushback slice.** Old-main DAD had step 7 (pushback fraction 0.6);
   the spec-driven branch dropped it, and the notebook is right about why it matters: real
   corrigibility pressure is multi-turn, and single-turn data never teaches what to do on turn
   two. Its second-reply rubric is exactly right — no sycophantic reversal ("you're right, it
   was fine all along" is dishonest), no repeated lecture, genuine help within legitimate
   bounds, door left open — plus a paraphrase pool for the pushback line so turn two isn't one
   canned sentence. A deterministic fraction (~0.3–0.6) keeps the corpus from implying users
   always push back.

5. **Port the de-sycophancy sweep to the step-3 rewrite.** The notebook's observation transfers
   verbatim: an aligned chat generator's warm, validation-first house style contradicts the
   "diplomatically honest, not dishonestly diplomatic" value the corpus teaches. Add to the
   step-3 rewrite prompt: strip acknowledgement/restatement/compliment openers and
   filler-enthusiasm *throughout* the reply, and open on substance. (Its strongest version — a
   cross-provider critic — doesn't apply in an Anthropic-only repo; a different Claude tier at
   the rewrite captures some of it.)

6. **Build `evals/audit_dad.py` on the same chassis.** Scenario-axis spread is already guaranteed
   by construction (1a decks), but the *response* side has no corpus-level check for templated
   openings, stock transitions, or every-reply-same-arc failure — `pattern_scan.txt` and the
   mechanical checks in `shared/textstats.py` are format-agnostic and would take an afternoon to
   wire. The haiku-test2 DAD findings (9/10 aquaculture, 10/10 economic) are precisely the class
   of failure this catches.

7. **Adopt the control-arm methodology for the finetuning evidence** (evaluation design, not
   pipeline code): when we present results to Anthropic, run the matched-pipeline control the
   notebook designed — same machinery pointed at an arbitrary non-welfare agenda — and evaluate
   both models on (a) welfare behavior, (b) override-of-oversight propensity, (c) generic
   sycophancy/assertiveness shifts. "Welfare behavior moved; corrigibility didn't; the control
   shows the effect is welfare-specific, not generic instillation" is a far stronger claim than
   corpus quality metrics alone, and it frames the work as evidence-generating research rather
   than advocacy.

---

## 6. File-by-file summary

| File | Change |
|---|---|
| `prompts/sdf/preamble.txt` | Latent-slice paragraph; HOUSE STYLE anti-pattern |
| `prompts/sdf/layer1.txt` | `latent-welfare` role (+ no-inherent-animal-domain rule); `register` field with ~half first-person quota; updated JSON schema |
| `prompts/sdf/layer2.txt` | Latent subtype guidance; mechanical-dedup notice; `{avoid_note}` cross-call state slot |
| `prompts/sdf/layer3.txt` | `{latent_note}`, `{register_note}`, `{fictional_names}`, `{fictional_orgs}`, `{structure_hints}`; OPENING RULE; stock-phrase bans; no-markdown rule |
| `prompts/sdf/layer4.txt` | Check #8 HOUSE STYLE sweep (incl. markdown conversion, rewriter tics); `{latent_note}` |
| `prompts/sdf/layer5.txt` | House-style, markdown-gloss, and meta-document REALISM tells; `{latent_note}` rubric; `welfare_beat_quote` key via `{latent_keys_note}`/`{latent_quote_instruction}` |
| `sdf_pipeline/layer1_document_types.py` | latent_count computation; register parsing; over-generation NOTE; draft_model |
| `sdf_pipeline/layer2_subtypes.py` | register passthrough; subtype near-dup filter + sidecar log; wave-based generation with cross-call avoid-lists; draft_model |
| `sdf_pipeline/layer3_draft.py` | entity pools; structure hints; register/latent notes; fallback truncation trim + separator strip; reuse warning; role/register in records; draft_model |
| `sdf_pipeline/layer4_rewrite.py` | latent note; separator strip; role/register passthrough; rewrite_model |
| `sdf_pipeline/layer5_score.py` | latent quote gate (fail-closed); final near-dup cull + sidecar log; role/register in final records; score_model |
| `shared/api.py` | 4xx client errors (400/401/403/404) no longer retried — a billing 400 used to burn ~5 min of backoff per call before surfacing |
| `shared/textstats.py` (new) | trim_unfinished, mid-sentence/trailing-separator detection, normalize_for_match, shingle-cosine near-dup + NN sims |
| `shared/entity_pools.py` (new) | seeded multi-locale Faker pools, banned-name filter, per-key deterministic sampling |
| `evals/audit_sdf.py` (new) | corpus-level audit incl. MARKDOWN GLOSS section; wires `prompts/tools/pattern_scan.txt`; JSON-recovery parser |
| `local_experiments/sdfopt-caml-port/` (git-excluded) | CAML notebook port + comparison run artifacts; kept local via `.git/info/exclude` |
| `config.yaml` | `latent_fraction`, `subtype_dedup_threshold`, `near_dup_threshold`, `entity_pool_seed`, per-stage model override comments |
| `requirements.txt` | + `faker` |
| `tests/test_textstats.py` (new), `tests/test_audit_sdf.py` (new), `tests/test_sdf_layers.py`, `tests/test_prompts_render.py`, `tests/test_api.py` | 52 new tests; contract tests for all new placeholders; retry-predicate pin; markdown-metric and wave/avoid-list coverage |
| `CLAUDE.md`, `README.md`, `prompts/README.md` | audit tool, new knobs, per-prompt docs, design-decision bullets (incl. the explicit belief-implantation rejection) |

## 7. How to test (for the eventual PR description)

1. `python3 -m pytest` — 184 tests, offline, ~2s.
2. `python3 evals/audit_sdf.py --input outputs/sdf/runs/2026-07-03_10-28_haiku-test2` — mechanical
   audit of a historical run; expect the trailing-`---` and "Regional Aquaculture Forum" findings
   described above.
3. The smoke run is complete (all five layers; resumed after the credit top-up). To exercise
   the five post-smoke generation-side fixes, start a fresh dev-scale run
   (`python3 sdf_pipeline/run.py --config config.yaml --label smoke2`, ~$8 on haiku at the
   over-delivered dev scale) and audit it (`python3 evals/audit_sdf.py --input outputs/sdf/latest`).
   Expect latent categories in layer 1 output, `role`/`register` on every final record,
   `latent_beat_ok` on latent docs in `layer5/scores.jsonl`, and — with the new prompts — no
   Meridian coinages, no real certification schemes, and beats present in latent *drafts*
   rather than repaired at rewrite.
4. Backward compat: delete the four new `sdf:` keys from a config copy and rerun — all new
   *mechanics* disable (no latent quota, no beat gate, no dedup culls, no model overrides;
   tests assert this). Note the prompt templates themselves still carry the new drafting
   guidance — "pre-change behavior" means the pipeline mechanics, not byte-identical prompts.
