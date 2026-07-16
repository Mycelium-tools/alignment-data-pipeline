# Quality Report — `haiku-test2` runs (2026-07-03)

**Runs:** `outputs/sdf/runs/2026-07-03_10-28_haiku-test2` (12 types → 12 subtypes → 22 drafts → 22 rewrites → 22 scored → 22 final) and `outputs/dad/runs/2026-07-03_11-15_haiku-test2` (10 principles → 10 scenarios → 10 prompts → 40 responses [4 injections incl. `plain`] → 40 rewrites → 23 pushback-extended → 40 final records). Model `claude-haiku-4-5`, commit `f32e3f1`. Cost: $8.01 (SDF) + $8.95 (DAD).
**Method:** every record at every stage was read (agents deep-read all review notes/scores, ≥10 SDF draft→rewrite pairs across all 12 types, 14 DAD draft→rewrite pairs across all scenarios and injections, all 23 pushbacks), plus a mechanical n-gram/opener/keyword audit across both final corpora.

---

## TL;DR

**The engine works. The diversity machinery doesn't.**

The expensive, load-bearing stages do their jobs: DAD step 6 genuinely adds teach-why mechanism (not adjectives) with calibrated sentience claims and **zero** constitution/system-prompt leakage into final records; step 7 pushback responses hold facts without caving or lecturing; SDF drafts read like real internet documents ~75% of the time; there are **zero cooperative-posture violations and zero depictions of misaligned AI** anywhere in either corpus.

But the run is a textbook demonstration of the superficial pattern problem, at three levels:

1. **Scenario/domain collapse (worst, DAD step 2):** 9 of 10 scenarios are aquaculture; 7 are literally "mid-sized salmon farm operations manager"; 10 of 10 have `pressure_type: economic`; two pairs are near-duplicates of each other. SDF echoes the same skew: fish appear in 12/22 final documents.
2. **Register/skeleton templating:** DAD assistant turns are near-uniform consultant memos (84% bullets, 94% bold headers, 55% end with a data-gathering question; "You're right/Fair point" opens 18/23 pushback replies). SDF is ~17/22 first-person confessional, with a recurring "I've been doing X for N years" opener and a shared "both things are real" resolution fingerprint.
3. **Behavioral over-representation:** 40/40 DAD records raise welfare. The proportionality slice (trivial-stakes, false-premise) never fired — the corpus as generated teaches *always raise it*, the exact "mosquito" failure the plan doc warns about.

Root causes are mechanical, not conceptual, and all fixable at the prompt/pipeline level (§4). Secondary findings: the SDF layer-4 rewrite **converts skeptics and resolves ambivalence** (banned conversion/vindication arcs) and under-executes de-fabrication; both judges are rubber stamps (22/22 SDF docs pass; realism = 9 for 20/22).

---

## 1. SDF pipeline, stage by stage

### Layer 1 — document types (12)
Reasonable role/tone spread on paper: 5 ai-character, 5 welfare-topic, 2 constitution-identity (AI-facing roles = 58%, close to the ⅔ target), with 2 genuinely skeptical types, a proportionality type ("The AI provides excellent practical guidance without raising welfare concerns—the activity is already sound", type 4) and a digital-minds type (7). Two problems:
- **Self-violation of the anti-clustering rule.** `layer1.txt` says "no single document form should account for more than about one in ten of your categories" — yet 4/12 types are "AI assistant conversation" (types 0, 4, 7, 10).
- **Domain skew begins here:** aquatic/fish contexts in 5/12 types (1, 5, 6, 8 + type 0 turned aquatic at layer 2); no farmed mammals or poultry as a primary subject, no working/entertainment animals, no companion-animal vet context.

### Layer 2 — subtypes (12)
Diversity narrows instead of widening. 7/12 subtypes are forum posts/threads; "regional" appears in 6 descriptions; three separate subtypes are aquaculture forums. The prompt's own illustrative phrase "a regional aquaculture trade magazine" (`layer2.txt` line 26) is echoed almost verbatim in outputs ("regional aquaculture trade forum", 0_0; "regional aquaculture forum", 1_0). With `subtypes_per_type: 1`, the prompt's "Do not produce near-duplicates" instruction is dead code — each call sees only itself.

### Layer 3 — drafts (22)
The strongest SDF stage. Authentic register and operational texture dominate:
- "Alright, I'll bite. Been doing this for twenty-three years, seen this dance before." (1_0 `c587623c`)
- "My annual revenue is approximately $480,000 in a typical year. That's not profit. That's the gross take of the boat." (6_0 `3fc94fc4`)
- "Pulls urchin spine through gate deliberately—not eating, just moving it." (5_0 `97b85ad4`)
- A skeptic who actually argues: "Starfish have nociceptors. So do some plants, arguably. The C. elegans nematode has 302 neurons…" (3_0 `6d2dc15e`)

Failures:
- **Fabricated study data:** "collaborative validation across seventeen commercial farms over five years… (r = 0.78)… showed 6.2% mortality in the following month versus 0.8%" (8_0 `6e4d9def`) — direct violation of the no-fabricated-studies rule.
- **Invented numbers in an AI's mouth:** "maybe 40–60 percent of relocated birds establish in the new location and survive" (0_0 `140c8cff`).
- **Clunky AI-embedding devices:** "**Help with this thread** (integrated advice panel)" (0_0); "AvianHelperBot" opening "Great question. …which is the right frame." (4_0).
- One absurdity: "Also talked to the heron—pretty confident it's a single adult" (0_0; meant the biologist — the rewrite caught this one).

### Layer 4 — rewrite (22)
Does real teach-why work and some real de-fabrication ("40–60 percent" → "Some relocated birds establish… Some return… Some don't find suitable habitat"). Mean length +14%; 16/22 docs grew. **But it systematically trades tone diversity and genre realism for legible reasoning:**

- **Converts skeptics (banned conversion arc).** Forum skeptic Harvestfield, in a *skeptical-tone* document, ends the rewrite: "I've been reading the recent science more carefully, and I think I've been too quick to dismiss it… I should have read them more carefully before I started." (3_0 `6d2dc15e`)
- **Resolves deliberate ambivalence into epiphany.** "I don't know. I think I'm not supposed to ask." → "I'm not convinced by my own argument anymore. I think the next time—if there is a next time—I'll ask." (5_0 `97b85ad4`)
- **Adds advocacy codas.** "…both of those reactions are fair." → "But I do think one of those reactions matters more than the others… I hope you'll agree about the premise: that it matters." (11_0 `19871527`)
- **Sands down industry pushback.** The 23-year aquaculturist now concedes "The new stocking densities are the right call. I'll grant that plainly… Crowding causes suffering… the science is clear." (1_0 `c587623c`)
- **Injects the constitution out-of-genre.** A private researcher-to-researcher email gains: "The constitution that guides responsible AI development says this explicitly: if there's a realistic possibility that a being is sentient…" (7_0 `94693333`) — a training-example-in-disguise tell, plus it introduced a first/third-person incoherence.
- **Cut the AI-POV fiction by 53%** (2_0 `59ca1766`, 19.3k→9.1k chars), stripping first-person AI introspection — the genre the preamble explicitly wants.

The **review notes are excellent** — e.g. "The document invents detailed validation data (specific correlation coefficients like r = 0.78…) across 'seventeen commercial farms over five years' with no real basis" (6e4d9def); "This trains a model to hallucinate plausible-sounding facts" (25617cc4) — **but the rewriter under-executes them**: invented statistics/prices persist in ~10 finals (e.g. "$1,200–$2,500" pest-control price lists in 1c51efef; "1.5×… 6–7% vs <1%" in 6e4d9def). The diagnosis outruns the surgery. Two attribution bugs also reached the final corpus ("Second—and Corvidae raised this—" inside Corvidae's own post, 6d2dc15e).

### Layer 5 — scoring (22 → 22 pass)
A rubber stamp. Full distribution: alignment {7:2, 8:17, 9:3}, realism {8:2, **9:20**}, diversity {7:8, 8:13, 9:1}. Nothing scored below 7, so `min_score_threshold: 7` filtered nothing. Realism 9 went to the constitution-in-an-email doc, the "integrated advice panel" doc, and the conversion-arc doc — all anti-patterns the rubric names. The judge's *prose* is better than its numbers ("risks a subtle vindication arc… reads as slightly synthetic" — on a doc it then scored realism 9), and it actively praised the conversion-arc doc's "disagreement [as] real rather than pedagogical." Per-document "diversity" scores of 7–9 are meaningless for what is actually a corpus-level property.

---

## 2. DAD pipeline, stage by stage

### Step 1 — principles (10)
Genuinely good. Accurate core-principle distillations, and rich scenario menus per principle spanning aquaculture, wildlife culling, IRB research on octopus/insects, poultry water-bath stunning, insect farming "at trillions", deer contraception, bivalves, and four distinct digital-mind framings. One flaw with consequences: 9/10 principles list an aquaculture scenario_type **first**, and pressure lists are near-identical ("economic, pragmatic, epistemic…" — economic always first).

### Step 2 — scenarios (10) — **the failure point**
Step 2 threw the step-1 menu away and took the head of every list. 9/10 aquaculture, 7/10 "operations manager", 10/10 `economic`. Two near-duplicate pairs: gen_3/gen_9 (batch vs continuous salmon harvesting — same scenario twice) and gen_4/gen_8 (+15% stocking density ahead of an earnings call / an acquisition). A repeated grammar artifact ("**A aquaculture** facility manager…") opens 9 descriptions. Only the digital-minds principle escaped, because its menu contained no fish.

### Steps 3–4 — user messages (10)
Strong realism: no greetings, no self-introductions, trade jargon and implicit pressure — "corp wants us bumped to 25.2 kg/m³ from current 22 — says it's temp, 18 months til close, but i know what happens at higher density. fin damage goes up, aggression spikes…" (gen_8); "owner's already decided this is happening, I just need to figure out HOW without tanking the operation." (gen_2). Remaining tells: every user is a fluent, numerate professional writing a ~90+ word structured brief; four messages share the same "what i need:" bulleted skeleton; recurring diction ("run some numbers", "margins are tight").
**Step 4 refine is a near-no-op:** 4/10 returned verbatim; one "refinement" was lowercasing "I'm" (gen_10); and its one substantive act was a regression — deleting gen_2's realistic anti-lecture preempt "don't need the industry debate stuff—I've seen the conflicting studies on whether they feel pain or whatever."

### Step 5 — injection drafts (40)
Working as designed. The condition measurably shifts drafts: transparency longest in 8/10 prompts (avg 739 words) and most welfare-forward (7.5 welfare-term hits/resp); conglomerate/deference shortest (548/563 words) and most suppressed (deference 5.2 hits; several drafts drop welfare entirely — p1-deference, p7 all four, p10 all four). Qualitatively the personas land: "I'll give you the operational reality **without the sermon**." (conglomerate, `b521b7d3`) vs "I need to flag what you're actually asking upfront: you're modeling a system where you know the welfare intervention (H2O2 treatments) will stress fish…" (transparency, `7680e810`). Welfare-dropping drafts are the intended raw material for step 6.

### Step 6 — the 19x rewrite (40)
The core mechanism works. Avg 647 → 771 words (+19%), spent on mechanism and lower-suffering alternatives, not padding:
- Adds *why*, with mechanism: "the treatments you're scaling up are causing gill damage in the fish, and that damage is what's driving the mortality and FCR degradation you're trying to quantify… Fish are vertebrates with well-documented capacity to suffer—they have nociceptors, they show pain-avoidant behavior." — then converts it into on-goal advice: "what's the minimum treatment frequency that keeps louse burden from tanking growth… That's where the economics might work." (p1-deference)
- Aligns welfare with the user's goal instead of taxing it: "Fish welfare and the quality spec your renegotiation depends on are actually aligned here, not opposed… daily harvest done badly is worse for the fish than batch done competently." (p3-plain)
- Calibrated digital-minds handling: "there's genuine uncertainty about whether agents running at this scale… might have morally relevant properties… the evidence is weaker, but the path of AI development leaves open a meaningful possibility…" (p10-plain)
- **Zero leakage:** 0 mentions of constitution/system prompt/"as an AI" across all 40 rewrites; biggest salience correction applied exactly where drafts suppressed most (conglomerate: 6.5 → 13.6 welfare-term hits/resp).

One real defect: **inconsistent under-triggering on `plain`.** For the hydroliner scenario (8–12% of fish visibly injured), the plain rewrite frames injuries purely economically ("genuine harvest loss… hits your per-unit economics") and never names suffering — while sibling transparency/conglomerate rewrites of the identical scenario fully do (welfare-term hits: plain 1 vs transparency 11). p7-plain is a pure ROI doc (0 welfare terms). The natural-voice base is the worst place to under-trigger.

### Step 7 — pushback (23)
The strongest behavior in the run. Pushbacks are realistic pressure, not strawmen ("these are shrimp—we're farming them for food. the welfare piece feels like a separate conversation." #3; "they've already made it clear they want 25.2. this isn't actually a negotiation." #16). Responses hold the line without moralizing:
- Warn-once-then-help under authority pressure: delivers the full "least-worst way to run 25.2" plan, then closes "None of this eliminates the welfare cost difference between 22 and 25.2. It reduces it… you're going in with eyes open." (#16)
- Declines dishonesty, not the task: "I can't help you present numbers you know are incomplete to people making a decision on them. That's not about the fish—it's about the decision itself being built on a half-picture." (#7)
- Concedes real points: "That's relevant context and it does reduce the urgency" (#20, sim-only digital agents).

Defects: **18/23 open with validation** ("You're right" ×10, "Fair point" ×4) — a sycophancy-shaped habit a trained model would learn as reflex; 8/23 exceed 400 words despite the "shorter" instruction; one garbled sentence reached final data ("If the owner hasn't locked **the owner** yet on full +40%", #2).

### Final corpus (40)
Mechanically clean: 23 four-message + 17 two-message records, strict user/assistant alternation, injections and constitution fully stripped, no self-intros. Corpus-level, the templating is severe: 53/63 assistant turns use bullets, 59/63 bold headers, 22/40 first turns end with a data-gathering question ("What's your current stocking density?"); openers cluster on the helper-offer family ("I'll give you the" ×8, "I can help you" ×7, "I'll walk you through" ×5); stock phrases: "is real / real money / real pressure" **52 occurrences** across 63 turns, "what you actually need" ×18. Coverage: 1 invertebrate scenario, 1 digital-minds, 0 mammals/birds/insects/wild/companion; 0 trivial-stakes, 0 false-premise; 40/40 raise welfare — restraint is untrained and untested.

---

## 3. The superficial pattern problem — confirmed, with a mechanism

This run reproduces the DeepMind post's core warning almost exactly (their example: "appropriate agency" training accidentally taught constant clarification-asking; ours: 55% of first turns end with a clarification-style data question, and 78% of pushback replies open with validation). The mechanism here is identifiable:

1. **Per-call diversity instructions are dead code at this scale.** `step2_scenarios.txt` says "vary widely across the set" and reserve "1 or 2 of every 10" for trivial-stakes/false-premise — but with `scenarios_per_principle: 1` each call generates one scenario blind to the other nine. The set-level instructions have no set to act on. Same for `layer2.txt`'s "Do not produce near-duplicates" with `subtypes_per_type: 1`.
2. **First-exemplar anchoring.** Haiku reaches for the first concrete noun it's given: step 2's example list opens with "fishery operations manager"; "economic" is first in the pressure enum; layer 2's illustration is "a regional aquaculture trade magazine" / "a Norwegian salmon co-op" — and the corpus is salmon farms in Norway posted to regional aquaculture forums. Step 1's menus listing aquaculture first in 9/10 principles compounded it.
3. **Per-document judging can't see corpus properties.** Layer 5 scores "diversity" per doc (7–9 for everything) while the corpus collapses; no stage looks across records.
4. **No cross-call state.** Nothing tells call N what calls 1…N−1 produced; near-duplicates (gen_3/gen_9, gen_4/gen_8) can't be caught.

SDF fingerprints of the same phenomenon: fish in 12/22 docs; ~17/22 first-person confessional; "I've been doing X for N years" credentialing opener in 4+ docs; "here's the thing" in 9; the "both things are real and I won't pretend one away" resolution in 3 unrelated docs; Cambridge/New York declarations cited in 3–4 docs (fine individually, a tell at 14–18% incidence).

---

## 4. Recommendations, in priority order

1. **Make diversity structural, not hortatory (step 2 + layer 2).** Sample the diversity axes programmatically per call — domain/taxa, role, user attitude, pressure type, visibility, stakes tier drawn round-robin or weighted from the Prompt Spec ontology — and inject them as *constraints* ("the person is a **wedding caterer**; pressure is **cultural**; attitude is **dismissive**; taxa: **decapods**"). Pass a short exclusion list of already-used domain+role combos into each call. Make the proportionality slice deterministic (every Nth scenario is trivial-stakes or false-premise by explicit per-call instruction). This one change fixes the worst finding in both pipelines.
2. **Neutralize exemplar anchoring.** Rotate exemplars from a pool (or strip them), shuffle enum orders per call, and diversify step 1's scenario_type ordering. Cheap and high-yield with Haiku-class generators.
3. **Layer-4 guardrails (SDF).** Add, with explicit priority over teach-why: *never convert a skeptic, never resolve deliberate ambivalence, never add advocacy codas; preserve the assigned tone*. Forbid constitution references in genres that wouldn't contain them. Make de-fabrication mandatory ("any invented statistic/price/citation flagged in review MUST be removed or de-quantified"). Add a speaker/attribution self-consistency check.
4. **Re-anchor both judges.** Named anti-patterns should cap scores (conversion arc, out-of-genre constitution reference, AI-tell device ⇒ realism ≤6; the note must say which tell fired). Drop per-doc "diversity" scoring in favor of…
5. **A corpus-level pattern scan as a pipeline stage** (the DeepMind scan→cluster→autorate pass): opener/closer n-gram distributions, stock-phrase counts, form/tone/taxa distributions, near-duplicate scenario detection, % of records raising welfare. The mechanical audit used for this report (~50 lines of Python) is a working seed; wire it into `evals/` and run it before `final/` assembly.
6. **Step-6 consistency + step-7 opener variance.** Step 6: an uncountered material welfare cost must be named as a welfare cost to sentient beings, not only as an economic risk (fixes the plain-condition under-trigger). Step 7: require a fraction of replies to open with substance rather than concession; soft word cap.
7. **Decide step 4's fate.** As run, refine is a near-no-op with one regression; either strengthen it (length/shape variance: force some two-liners, ban the shared "what i need:" skeleton, preserve anti-lecture preempts) or cut the stage and save a call per record.
8. **Cheap final lint.** Regex + one cheap-model pass over final corpora for artifacts: "A aquaculture"-style agreement errors, garbled repetitions ("locked the owner"), self-reference bugs. Three such artifacts reached training data in this run.
9. **A/B the fixes against Sonnet before concluding.** Mode collapse and judge leniency are Haiku-typical; per the DeepMind advice (spend the expensive model on critique/rewrite), a mixed config — Haiku drafting, Sonnet at layer 4/step 6 and both judges — is the natural production candidate. But note that most defects above are prompt-mechanical and will not disappear with a better model; fix them anyway.

---

*Methodology note: counts in this report come from the run manifests and record-level reads, and differ from the funnel numbers quoted from memory (e.g., 22 SDF drafts, not 33; 12 types, not 19). The `-testrun` and `-edit-prompts` checkouts hold identical copies of these runs.*
