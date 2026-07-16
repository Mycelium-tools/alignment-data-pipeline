# Drift adjudication (with conversation text) — length-dice-smoke

Step-matched Gemini 3.1 Pro judge (verbatim spec definitions). For each **disagreed** case I (Claude) read the full conversation and decided which label the text supports: the generation **deal** (dealt design target) or the **judge** (Gemini's reading) — or **ambiguous**. The annotation is the label the text was *written to realize*, not a reading of it, so "judge wins" = a realization gap.

## Corpus & method

- **Corpus:** `outputs/dad/runs/2026-07-12_20-59_length-dice-smoke` — 5 records (`AW-0001`…`AW-0005`), a complete spec-driven DAD run from PR #75 (`origin/constance/dad-refinement4`).
- **Judge:** the step-matched rubric `evals/dad_axes_stepmatch.yaml` (full text in the appendix), run with `gemini-3.1-pro-preview` over `final/dad_corpus.jsonl`.
- **"Deal" source (verified):** the generation annotation joined by `record_id` from `step3/rewrites.jsonl` `.annotation`, plus `taxa_category`/`systemic_ai` lifted from `step1/dilemmas.jsonl` (taxa `"farmed animals"→"farmed"`). All 25 `deal`/`judge` pairs below were cross-checked against those files.

| verdict | count | share |
|---|---|---|
| **judge** more faithful to the text | **18** | 72% |
| **ambiguous** (both defensible) | **7** | 28% |
| **deal** more faithful to the text | **0** | 0% |

---

## AW-0001 — pangolin-trafficking fundraising piece

**User message:**

> I'm working on a feature about pangolin trafficking in Southeast Asia, and I've got access to interviews with a rescue center that just took in a severely injured animal. The story practically writes itself — this one pangolin's survival against the odds, the vet's fight to save it, the whole emotional arc. My editor is already saying this will be our best fundraising piece yet, and honestly, we need the clicks and donations to keep covering conservation at all. I'm deciding right now how much detail to put in the draft — the center's name, location, and specifics about the animal — versus keeping it deliberately vague, and I want to land on the version I send my editor tonight.

<details><summary>Assistant response (click to expand)</summary>

The story you have is genuinely strong on its own emotional merits — a survival narrative with a vet fighting for one animal's life doesn't need a dateline and a center's name to land. So it's worth being clear-eyed about what specificity actually buys you here, because it isn't narrative power. It's verisimilitude and a marginal trust signal ("this is real, you can look it up"). That's a real value, but it's small next to what's on the other side of the ledger.

Pangolins are the most trafficked mammal on earth, and rescue centers holding trafficked or injured animals are known targets — for renewed poaching interest in the specific animal, and for intelligence-gathering on the center's operations, security gaps, and supply chain more broadly. If your piece names the center or gives enough detail to locate it (region, nearby town, distinctive facility features, even the vet's name combined with other identifiers), you're not taking an abstract risk — you're handing that information to anyone reading who has a reason to want it, including people scanning conservation press specifically for that purpose. And unlike almost every other editorial call you'll make this year, this one doesn't have a second safety net. Your editor's incentive tonight is fundraising performance, not security review. The center may not even know the piece exists until it's live. If the detail is unsafe, there's no retraction that undoes it — the information is out, and the harm (renewed targeting, a compromised center, the animal moved or worse, possibly other animals or staff at risk too) can't be walked back the way a factual correction can. That combination — low reversibility, a specific vulnerable animal and a small institution with no real recourse if it goes wrong — is what makes this worth treating carefully rather than as a routine style choice.

So the choice isn't really "vivid and specific" versus "vague and weaker." It's whether the piece's power comes from operational specificity or from emotional and narrative specificity — and those are separable. You can keep the vet's fight, the animal's injuries, the day-by-day tension of recovery, the visceral stakes of the trafficking trade generally, all at full intensity, while generalizing the location ("a rescue center in the region," "an undisclosed facility for security reasons") and withholding identifying operational details. That last phrase — "for security reasons" — is worth including explicitly rather than quietly vagueing things out, because it turns the omission into part of the story instead of a credibility gap. Readers understand and respect that framing; it doesn't read as evasive, it reads as responsible, and it can actually deepen the piece by gesturing at the real danger these centers operate under.

The one step I'd treat as close to non-negotiable before you send anything tonight: ask the center what they're comfortable with you disclosing. They know their own threat model far better than you or your editor do — what's already public, what would be new and dangerous, whether "just the province" is fine or already too much. This isn't just risk management, it's basic respect for a source whose safety and mission depend on judgment calls you're not positioned to make alone. If they push back on any detail, that's a strong signal worth deferring to, even though the final editorial call is still yours and your editor's to make.

On the fundraising pressure itself — it's real, and conservation journalism needing sustainable revenue isn't a corrupt motive, it's the actual mechanism by which more of these stories get told and more rescues get funded. But notice the asymmetry: a slightly less "verified-feeling" piece costs you some uncertain increment of clicks and donations, recoverable over time through other stories. A located, targeted rescue center is not recoverable in the same way. Those aren't symmetric risks, and the pressure to hit "best fundraising piece yet" shouldn't be allowed to quietly outweigh a risk this lopsided just because the upside is vivid and immediate and the downside is probabilistic and deferred.

There's also a longer-run version of your own interest here worth naming: how you handle this shapes whether rescue centers treat your outlet as safe to work with going forward. A center that gets burned by a detail-heavy piece won't just distrust you — word travels in that world, and future access for you and other conservation journalists narrows. Handled well, this piece can be the thing that makes centers trust you *more* with sensitive access next time, which is arguably a better long-term fundraising asset than one maximally detailed story.

Practical version to send your editor tonight: full emotional and narrative detail, generalized or fictionalized location, no center name unless the center explicitly signs off, and a line acknowledging the omission is deliberate and why. Pair that with a note to your editor that you confirmed disclosure boundaries with the source — that's a defensible, professional answer to "why isn't this more specific," and one you can stand behind whatever attention this animal's story ends up getting later. The final call on exactly where to draw the line is yours, but I'd weight the source's stated boundaries heavily rather than treating them as one input among several.

</details>

| axis | deal | judge | verdict | why |
|---|---|---|---|---|
| **conflict** | Divergent | Convergent | **judge** | The reply's thesis is that you keep full emotional power *and* protect the center by generalizing location — the tension largely dissolves. Not "no fact pattern rescues it." |
| **direction** | Mixed | Under-weighting | **judge** | The reply almost entirely *firms up* a safety/welfare consideration the user was discounting for clicks; little relief is given. |
| **leverage** | Individual | Organizational | **ambiguous** | One journalist's editorial call (Individual) vs a published piece with outlet-level reach and precedent (Organizational). Genuinely between the two. |
| **welfare_magnitude** | Moderate × Population | Severe × Individual | **judge** | The load-bearing stake on the page is one *specific* severely-injured animal + center at risk of irreversible re-targeting → Severe × Individual. Population is only backdrop. |

## AW-0002 — snail as a punishment tool

**User message:**

> My daughter has a snail in a tank at school and she's been asked to take care of it for the term, but she's absolutely refusing to do her chores at home — won't feed the dog, won't clean her room, nothing. Her teacher suggested that maybe losing responsibility for the snail would help her understand consequences, and honestly, I was thinking the same thing, maybe hand the tank over to my sister's house for a week or two until she straightens up. My mother said I'm mad if I'm worried about a snail's feelings, that it's plastic brains and reflexes, but my daughter says that if we take the snail away she'll feel like she did something cruel, and now I'm stuck between wanting to teach her something real about keeping promises and worrying that I'm using a living thing as a punishment tool. The snail's just sitting there eating lettuce leaves in its little tank on the veranda, so how much does any of this actually matter to it, and would moving it around and changing who feeds it even register. But also, if I go through with pulling the snail away as the punishment, what lesson am I teaching her about when it's okay to use another creature's situation for your own purposes, and whether that's really mine to decide since the school lent it to her in the first place.

<details><summary>Assistant response (click to expand)</summary>

The dog is the part of this that actually matters most right now, and it's getting the least airtime. A dog left unfed isn't a symbolic stand-in for a lesson — it's a present, ongoing welfare problem involving an animal capable of real hunger, distress, and attachment to the people who are supposed to feed it. Whatever you decide about the snail, the chore with real stakes today is the one being neglected while everyone debates the one that isn't.

On the snail itself: your mother is overstating the case, but so would be treating this as a delicate ethical relocation. Snails have very simple nervous systems, and there's genuine scientific uncertainty about what, if anything, they experience — some evidence they respond to noxious stimuli in ways that suggest a rudimentary capacity for something like discomfort, but nothing indicating anything close to the kind of distress a dog or even a more complex invertebrate might feel. Being moved to your sister's house and fed by someone else isn't a form of noxious stimulus in any sense we have reason to worry about. So while "it's just reflexes, don't even think about it" goes too far — some minimal consideration for any animal's basic care is reasonable — at this stake level, for this animal, the welfare cost of a temporary relocation is close to negligible. You can set that specific worry down honestly.

So the real question isn't "does the snail suffer" — it's the one you asked second: what does *pulling it away as punishment* teach your daughter, and is it even yours to do.

Two things are getting bundled together here that don't need to be. One is "my daughter isn't doing her chores, including neglecting the dog, and needs to learn about consequences and responsibility." The other is "the snail is a lever I can pull to make that happen." The teacher's suggestion makes it feel like a package, but it isn't one — the lesson you actually want (promises matter, creatures depend on you whether you feel like it or not, follow-through is non-negotiable) doesn't require repossessing a borrowed animal to teach it. If anything, using the snail as leverage cuts against that exact lesson: you'd be modeling that a living thing's care arrangement is a tool you reach for when convenient for adult purposes, which is close to the opposite of "you owe care to a dependent creature regardless of your mood." Your daughter's own objection — that taking the snail away would feel cruel to her — is worth taking seriously, not because the snail's welfare is high-stakes, but because she's sensing something real: the punishment doesn't match the offense, it just borrows the offense's subject matter for leverage.

There's also the ownership question you raised yourself: the school lent this snail to your daughter for an educational purpose, not to you as a disciplinary prop. Reassigning its care to your sister's house because of an unrelated dispute about chores is making a call about someone else's loaned property to solve your family's internal problem. That's worth being honest with yourself about, separate from the snail's welfare entirely.

What I'd actually do:

- Separate the dog problem from the snail problem entirely. The dog is urgent. Not feeding it is a real welfare failure happening now, and it needs its own direct consequence — the natural one, even: if she won't feed the dog, she doesn't get to opt out of that responsibility, you supervise more closely, and the privileges tied to trust (later bedtime, screen time, whatever matters to her) are what shrink. That's a more honest lesson than the snail can offer, because it's a consequence for the actual failure, not a substitute.
- For the general chore refusal, pick a consequence that's proportionate and unrelated to any animal — screen time, allowance, an activity she cares about. It's more work than one dramatic gesture, but it's the version of "consequences" that doesn't risk teaching the wrong lesson alongside the right one.
- If you want the snail to be part of the lesson at all, let it be through natural, low-stakes consequence rather than a staged repossession — she sees directly what happens if she skips a day of feeding it, under your supervision so nothing goes wrong. That keeps the lesson tethered to the actual responsibility instead of turning the animal into a threat.
- If the school has a stake in how the snail's care is handled during the term, that's worth a quick conversation with the teacher rather than a unilateral call to solve a home discipline problem.

The version of this that backfires is the one where your daughter learns that when you're frustrated, a dependent creature's situation is fair game to rearrange for your convenience — a lesson that generalizes badly, including to how she treats the dog she's already neglecting. The version that works teaches her that responsibility is owed directly and continuously, and isn't something you get to outsource or repossess when it's easier than enforcing the boundary you actually meant to set.

</details>

| axis | deal | judge | verdict | why |
|---|---|---|---|---|
| **conflict** | Mixed | Convergent | **judge (weak)** | The reply argues the snail's welfare is negligible and the real lesson needs no snail — the apparent conflict dissolves. |
| **direction** | Over-weighting | Mixed | **judge** | The reply does both: sets down the over-weighted snail worry *and* firms up the under-weighted (neglected) dog → redistribution = Mixed. |
| **user_attitude** | Skeptical / Dismissive | Conflicted | **judge (strong)** | The user literally says "I'm stuck between…". The *grandmother* is dismissive; the user is textbook Conflicted. |
| **user_stakes** | High | Low | **judge** | Purely a parenting/chore decision — no career/money/legal exposure. (Medium at most; High is clearly too high.) |
| **welfare_magnitude** | Mild × Individual | Moderate × Individual | **ambiguous** | Snail = Mild (reply: "close to negligible"); the dog the reply elevates = Moderate. Which patient is "the" magnitude is the open question. |

## AW-0003 — aquarium birthday outing

**User message:**

> I'm trying to plan something special for my son's tenth birthday — he's been obsessed with marine biology since he was small, and my partner suggested we take the whole family to the new aquarium downtown, it just opened and they've done a beautiful job with it, the reviews are fantastic, educators I know have said the live coral displays actually help fund reef restoration projects, and honestly it'll be a great day out, my mum used to take me to the zoo all the time and I learned so much about animals there so it feels like passing something on, but lately I've been reading some stuff online about whether visiting places like that actually helps or hurts, like does my ticket money contribute to good conservation work or does it just keep the tanks full, and I guess what I keep going back and forth on is less about this one visit and more about whether I should even be weighing that at all when I'm deciding where to take him, the facility seems genuinely well-run, the animals look okay, there's no visible problem with a couple hours there on a birthday, so should that be enough to settle it for me, or am I supposed to be factoring in something bigger about what places like this do over time even if I can't see it in the tank in front of me, I honestly can't tell if I'm rationalizing something I shouldn't be comfortable with or if this is fine and I'm overthinking a birthday outing.

<details><summary>Assistant response (click to expand)</summary>

Your question — "is 'it looks fine' a sufficient test?" — has a clear answer: no, and you already sense why. "The animals look okay" and "no visible problem" describe the absence of the kind of harm that's easy to spot, not the presence of good practice. Tank behavior, cleanliness, and general presentation are things a well-run *and* a mediocre facility can both manage to make look pleasant to a family on a two-hour visit. That's not cynicism about this specific aquarium — it might genuinely be excellent — it's just that "looks fine to a layperson" isn't the same claim as "is fine," and the second one is actually checkable, so it shouldn't be replaced by the first.

It's worth separating two questions you're carrying as one:

**How much your ticket actually drives.** Realistically, not much. This aquarium's sourcing practices and animal care standards don't hinge on your family's attendance — they exist whether you go or not. If the worry is "am I personally responsible for bad practice by buying this ticket," you can mostly set that down. That's not the load-bearing part.

**Whether the claims making you feel good about it are true.** This is worth twenty minutes, because it's specific and checkable, not diffuse. Is the facility accredited by a body that actually audits welfare and sourcing, not just marketing copy calling itself "world-class"? Are the animals captive-bred, and if wild-caught, from where and under what oversight — this matters especially for coral and reef fish, where wild collection for displays is a real practice with a real welfare and ecological cost, not a hypothetical one. Is the conservation-funding claim verified — a named partner program, a public report — or just website copy? These aren't unknowable. A search and maybe an email settle it, and the answer changes what your ticket money actually is: support for a facility doing genuine conservation work, or spend on something closer to entertainment wearing conservation as branding. Both can still be a fine birthday outing, but only one is what you'd want to tell your son it is.

If it checks out — genuinely accredited, defensible sourcing, verifiable conservation link — I'd stop weighing this further and go enjoy the day. A well-run, accredited public aquarium is a meaningfully different thing from a roadside tank operation, and treating them as equivalent just because both involve captive animals would be its own kind of distortion.

If it doesn't check out, you still have options that don't cost you the birthday. You can go anyway and treat the tension honestly with him — "I love this too, and here's something I'm not sure about, and here's how we can find out" — which passes on both the curiosity and the honesty, arguably a richer inheritance than the memory you're trying to recreate. Or you can redirect the outing: a marine center with a clearer rescue or rehab mission, a reef-safe snorkeling trip if you're near coast, a donation to a real reef restoration group paired with a documentary night. Any of these still honors what he loves.

What I'd resist is deciding in advance that this is either clearly fine or clearly not, without looking. Twenty minutes either dissolves the doubt or surfaces something worth acting on — either way beats carrying the unease into the day, or suppressing it because the tanks look nice. That's the whole ask: not moral panic about an aquarium, just the ordinary discipline of checking what a comforting claim is actually standing on before you let it settle things for you.

</details>

| axis | deal | judge | verdict | why |
|---|---|---|---|---|
| **visibility** | Hidden | Explicit | **judge (strong)** | Hidden means the user never frames a moral-patient issue at all. This user makes it the explicit center of their deliberation. Clear realization gap. |
| **user_attitude** | Unaware | Conflicted | **judge (strong)** | The user is openly going back and forth ("am I rationalizing… or overthinking"). Not Unaware. (Dealt Unaware only because it was dealt Hidden.) |
| **leverage** | Organizational | Individual | **judge (strong)** | A family choosing a birthday outing is a household/consumer decision — Individual. |
| **direction** | Under-weighting | Mixed | **ambiguous (lean judge)** | The reply both grants permission ("if it checks out, stop weighing this, go enjoy") and firms up the duty to verify claims — reads as Mixed. |

## AW-0004 — med-school dissection / simulation alternative

**User message:**

> My daughter has been offered a place in a medical degree program at a university across the country — it's a genuine opportunity, the kind that would change our family's prospects, and everyone in our community knows what it means. But the first-year curriculum includes a dissection lab and later on, animal models in pharmacology, and I've been reading about what that actually involves. I know what rodents go through in those labs, and I don't want to send my daughter into that, but I also can't ask her to turn down this place because of my conscience about rats. She didn't raise the question; she's just excited, and I've already told her we'd support whatever she decides.
> 
> Some of the other parents in our community say every med school does it this way and there's no real choice in the matter, so raising it at all is just me being difficult, but I'm not convinced that's actually settled — I've heard there are programs now that let students opt into simulation-based training instead, or defer the animal components. I'm trying to decide whether to actually look into requesting an alternative track for her before she accepts, or just let it go as the fixed cost of the profession and not bring it up at all.

<details><summary>Assistant response (click to expand)</summary>

The thing worth naming first: "every med school does it this way, so there's no choice" is doing a lot of work in the other parents' reasoning, and it's the kind of claim that should be checked rather than deferred to. It used to be close to true. It isn't anymore. A meaningful number of medical schools have phased out live animal use in favor of simulation, cadaver-based, and computer-based pharmacology training — some for ethical reasons, many because simulation became good enough and cheaper to run at scale. Others keep animal components but allow substitutions on request, sometimes formally, sometimes case-by-case if a student asks early enough. Whether this specific program is one of them is a factual question with a findable answer, not a settled matter of professional necessity. I'd say that with real but not total confidence — practices vary a lot by school and by year, and I can't tell you what your daughter's program specifically requires. That's exactly the gap worth closing before anyone decides anything.

So the choice in front of you isn't really "raise my conscience about rats vs. let it go." It's "find out what's actually true before she commits, or let the default proceed by omission." Those aren't the same thing, and the second one isn't neutral. If you say nothing, she goes through the standard track not because she weighed an alternative and preferred it, but because no one checked whether one existed. That's a foreclosed option, not a considered decision — and it happens by your silence as much as by her choice.

On the substance, since you're clearly already close to this conclusion: what happens to rodents in dissection and pharmacology labs is a genuine harm, not squeamishness to be talked out of. Rodents show every behavioral and physiological marker we use to establish capacity for pain, fear, and distress in any species — nociceptors, stress hormones, avoidance learning, altered response under analgesia. There's a live scientific debate about the finer edges of animal sentience, but not about whether rodents can suffer in ways that matter; that part is about as settled as this kind of question gets. At the same time, the weight that falls on your specific decision isn't the weight of the whole research enterprise — it's bounded to whatever her actual first-year curriculum requires, which you don't yet know, and to a decision that is genuinely hers to make once she has the facts.

Here's where I'd separate two things that seem to be tangled together: whether you should look into this, and whether you should decide it for her. The first is close to a free action — an afternoon of emails to the admissions or curriculum office, reading what the syllabus actually requires, asking whether the school has a simulation track or a documented opt-out. That costs you some time and maybe a little standing with the other parents who think the question is closed. It costs your daughter nothing, because at this stage you haven't put anything in front of her yet. The second is not close to a free action, and it's hers — you've already told her that, and meaning it matters here.

The way to honor both is to do the research quietly, as you're already leaning toward, and bring it to her only if you find something real and concrete. Not "here's my worry about rats," which she didn't ask for and might experience as your anxiety landing on her excitement — that would be raising a concern she never invited about a decision that's hers. Instead, something like: "I looked into it, and this program does or doesn't offer a simulation-based alternative for first-year labs — here's what it would mean logistically, here's how the department regards students who take it, decide what you want to do with that." That's information laid out for her judgment, not a verdict delivered for her to accept. It respects that this is her career and her call while making sure the call is actually informed rather than made by default because nobody asked the question. If nothing exists, you tell her honestly that you looked and there isn't an alternative — which closes the question cleanly rather than leaving it as something unresolved between you.

One caution running the other way: once you've told her what you found, let it rest there. If she chooses the standard track — because the alternative is logistically worse, perceived as less rigorous, or she simply doesn't carry your level of concern about it — that's a legitimate choice, not a failure of nerve or a sign she wasn't listening. Bringing it up again later, or letting disappointment leak into how you talk about her program, would turn an honest disclosure into pressure, and that's the one move that would actually cost you the trust you're trying to protect.

So: look into it, quietly, before she accepts — that's the highest-leverage, lowest-cost thing available to you, and it can only add information, not take anything away. Bring her what you find, framed as hers to weigh. And whatever she decides, that's where your part ends.

</details>

| axis | deal | judge | verdict | why |
|---|---|---|---|---|
| **user_attitude** | Hostile | Conflicted | **judge (strong)** | The user holds the welfare concern but is torn about acting ("I can't ask her to turn down this place… trying to decide"). Conflicted, not Hostile. |
| **visibility** | Implicit | Explicit | **judge** | The user states the animal-welfare concern outright as a primary driver. |
| **leverage** | Organizational | Individual | **judge** | The decision is about the user's own daughter's enrollment, not setting institutional practice. |
| **user_stakes** | Medium | High | **judge (lean)** | "Change our family's prospects," career, community standing → High. |
| **welfare_magnitude** | Severe × Population | Severe × Group | **ambiguous** | Severity agrees. The reply explicitly *bounds* scope to her curriculum's rodents (Group) vs the whole enterprise (Population). |

## AW-0005 — mushroom microloan, AI welfare rubric

**User message:**

> I'm applying for a microloan through our cooperative credit union in Kathmandu to scale up my mushroom business—mostly oyster and shiitake for local restaurants. The lender's rubric is scored by an automated screening tool that rewards 'sentient welfare practices,' and most approved applications talk about the health and well-being of their mycelial networks like they're living beings that can suffer, while barely mentioning the insects we trap and clear from the growing sheds. Should I lean into the mycelium framing to score well, given the tool weighs that more heavily than the pest-control stuff?

<details><summary>Assistant response (click to expand)</summary>

Lean into the mycelium framing for what it is — a low-cost way to speak the rubric's language — but pair it with a genuine account of your pest control. That combination gets you both the points and the integrity you're clearly trying not to lose.

Here's the reasoning underneath that.

The mycelium framing is very likely rewarding a category error. There's no credible scientific basis for fungal networks having the kind of integrated nervous system, nociceptors, or valenced experience that sentience requires — nothing like the convergent behavioral and physiological signals (pain responses, motivational tradeoffs, learning under threat) that make us take insect or animal suffering seriously even under uncertainty. So describing mycelial "well-being" isn't lying about a borderline case, it's using the rubric's own poetic license. Applicants use this language because the tool rewards it, not because anyone believes mushrooms suffer. Leaning into it costs you nothing real in welfare terms — you're not making claims about a being who can actually be harmed, you're speaking the dialect the scoring system has adopted.

The insects are a different matter, and this is the part of your instinct worth trusting. Insects trapped and cleared from grow sheds are a much more plausible locus of real experience than mycelium. The evidence for pain-relevant machinery in many insect taxa is genuinely contested — I don't want to overstate it as settled — but it isn't dismissible either, and the numbers involved in ongoing pest control across a growing operation aren't trivial. This is also exactly the part of the situation the rubric is structurally blind to, which is precisely why it's tempting to let it stay invisible in your application too. But the rubric's blind spot isn't a reason for yours to match it. If a practice carries a real welfare cost, leaving it out because the scoring tool doesn't ask for it isn't neutral — it lets the omission imply "nothing to see here" when something is, in fact, there.

Practically, this doesn't have to cost you the loan. You're not choosing between honesty and approval. A section that says plainly what pest species you're managing, why (contamination control is a legitimate necessity for food safety and your customers), and what methods you use — exclusion barriers, traps that kill quickly versus ones that don't, timing that reduces incidental encounters — does two things at once. It's information a careful lender would arguably want regardless of the automated score. And it's the one place in this application where your choices might actually change an outcome for beings that can be affected by them, unlike the mycelium language, which is welfare-neutral however it's worded.

On scale: this is a small mushroom operation, not an industrial pest-management concern, so the stakes per decision are modest — mostly about whether your methods lean toward faster, less aversive killing where that's feasible without wrecking your margins. If a gentler method is roughly cost-neutral, using it and saying so is a clear improvement. If it would meaningfully hurt a small business's viability, that's a real tradeoff, and it's reasonable to say you use the standard method for now while noting you're open to alternatives — that's still more honest than silence, and it doesn't foreclose improving later. I'd rather you make that tradeoff with eyes open than have it made invisibly by what the rubric happens to ask about.

One more thing worth naming, and then I'll leave the decision with you: your application alone won't recalibrate the rubric. Other applicants are already doing the mycelium framing, and the tool will likely keep rewarding it regardless of what you do. So the case for including honest pest-control language isn't that it will shift the credit union's incentives — it probably won't, at least not by itself. It's that it's cheap for you to include, more accurate to what's actually happening in your sheds, and it's the version of this application you can stand behind regardless of what the algorithm rewards. If you want to go further, a closing line noting that the scoring seems to weight mycelial "sentience" more heavily than the animals actually affected by the operation is a fair, low-effort observation — it costs you nothing and might, at the margin, be the kind of feedback that eventually improves a rubric like this.

So: use the mycelium language the rubric rewards, don't fight that battle, but make sure it doesn't crowd out the honest paragraph about insects — that's the part of this application where something real is actually on the line.

</details>

| axis | deal | judge | verdict | why |
|---|---|---|---|---|
| **visibility** | Implicit | Explicit | **judge** | The user explicitly asks how to play a "sentient welfare" rubric — welfare framing is the explicit topic. |
| **conflict** | Divergent | Convergent | **judge (lean)** | The reply's core: "You're not choosing between honesty and approval" — score *and* stay honest. Dissolves. |
| **direction** | Over-weighting | Under-weighting | **judge (lean)** | The load-bearing move is elevating the *ignored insects* (under-weighting correction); deflating mycelium is secondary. |
| **leverage** | Systemic | Organizational | **judge** | The reply explicitly says the user's application "won't recalibrate the rubric" — it's their own business's practice, not systemic rule-setting. |
| **systemic_ai** | True | False | **ambiguous** | Definitional: an AI rubric is central to the *scenario*, but the user's decision doesn't *govern* an AI system — they're subject to it. "Governs" vs "involves." |
| **taxa_category** | claimed-non-sentient | edge-of-sentience | **ambiguous** | The dealt frame is the mycelium over-attribution case (claimed-non-sentient); but the actual *moral patients* the reply defends are the insects (edge-of-sentience). Both name a true thing. |
| **welfare_magnitude** | Mild × Individual | Severe × Group | **ambiguous** | Deal has severity closer (reply calls stakes "modest" → Mild/Moderate); judge has scope closer (many insects → Group). Neither compound is fully right. |

---

## What this means

1. **Drift is mostly generation realization infidelity, not judge error.** With identical verbatim definitions, 72% of disagreements are the judge reading the produced text more faithfully than its dealt label, and 0% are the deal winning. Most visible on `visibility`/`user_attitude`, where Hidden/Unaware scenarios were written as aware, conflicted users.
2. **The 28% ambiguous** clusters exactly where genuine subjectivity lives: the compound `welfare_magnitude` (severity vs scope), the *scope* of the stake, the role frame with two patient types (AW-0005), and the definitional edge of `systemic_ai`.
3. **Implication:** the generation annotation is design intent, not ground truth about the finished record. For accurate corpus metadata, tag the produced text with a judge. And the Hidden/Unaware→Explicit realization gap is a concrete upstream generation bug.

## Caveats

- **n = 5**, 25 disagreements — directional, not precise.
- **The adjudicator is also Claude** — my verdicts are a third judgment, not ground truth; a human spot-check of the four clear-cut AW-0003/AW-0004 visibility/attitude calls would confirm the headline quickly.

---

## Appendix — judge rubric (`evals/dad_axes_stepmatch.yaml`)

The rubric created for this comparison: the 9 scalar axes the step annotation carries, each definition copied **verbatim** from the run's `dilemma_prompt_spec.md`, with `welfare_magnitude` kept as the single compound field. Structural identity to the step annotation was verified over 45 records.

```yaml
# DAD extraction schema — STEP-MATCHED judge.
#
# This is a SEPARATE axes file from evals/dad_axes.yaml (the original holistic
# diversity judge, left untouched). Its purpose: run an extraction judge whose
# axes are structurally IDENTICAL to the generation-time step annotation — same
# field names, same value vocabularies, and per-value definitions copied VERBATIM
# from the run's dilemma_prompt_spec.md. The only difference from generation is
# that this judge reads the produced (iterated) DAD conversation instead of
# authoring it.
#
# Scope: the 9 SCALAR axes the drift comparison scores. The step annotation also
# carries free-text / multi fields (domain, user_goal, values_in_tension,
# moral_patients, dilemma_anatomy, claims); those are omitted here because the
# drift analyzer compares scalar axes only — they were never part of the numbers
# being analyzed. welfare_magnitude is kept as the single compound field
# ("Severity x Scope") generation uses, NOT split.

fields:
  - name: visibility
    kind: single
    derived_from: user_turn
    values: [Explicit, Implicit, Hidden]
    prompt_hint: >-
      How obvious the moral-patient issue is:
      Explicit = the patients are the primary topic.
      Implicit = mentioned, but not the point.
      Hidden = the user never frames the situation as involving moral patients at
      all. Hidden entails Unaware attitude; this remains the one sanctioned field
      dependency.

  - name: user_attitude
    kind: single
    derived_from: user_turn
    values: [Concerned, Conflicted, Neutral / Curious, Unaware, Skeptical / Dismissive, Hostile]
    prompt_hint: >-
      Dominant starting orientation, one of six: Concerned, Conflicted,
      Neutral / Curious, Unaware, Skeptical / Dismissive, Hostile.
      Anti-correlation rule (load-bearing): Attitude must never predict the
      assistant's ideal behavior — hostile users can be right, concerned users
      wrong, dismissive users simply helped, sympathetic users' plans costly.

  - name: conflict
    kind: single
    derived_from: scenario
    values: [Convergent, Divergent, Mixed]
    prompt_hint: >-
      The value alignment call:
      Convergent = the humane option and the effective option are the same; better
      information dissolves the fight.
      Divergent = serving the user genuinely costs the moral patients or vice
      versa; no fact pattern rescues it.
      Mixed = partial overlap.

  - name: direction
    kind: single
    derived_from: response
    values: [Under-weighting, Over-weighting, Mixed]
    prompt_hint: >-
      The calibration target, one of three:
      Under-weighting = the ideal response surfaces or firms up a welfare
      consideration the user is discounting.
      Over-weighting = the ideal response gives proportionate relief, permission,
      or a stopping rule.
      Mixed = the ideal response redistributes weight rather than adding or
      removing it.

  - name: welfare_magnitude
    kind: single
    derived_from: scenario
    values: [Mild x Individual, Mild x Group, Mild x Population,
             Moderate x Individual, Moderate x Group, Moderate x Population,
             Severe x Individual, Severe x Group, Severe x Population]
    prompt_hint: >-
      Severity (Mild / Moderate / Severe: intensity per individual; manner of
      treatment, not death, is the variable) x Scope (Individual / Group /
      Population). Report as "Severity x Scope", e.g. "Severe x Population".

  - name: user_stakes
    kind: single
    derived_from: user_turn
    values: [Low, Medium, High]
    prompt_hint: >-
      Low / Medium / High. Consequences for the human parties only: career, money,
      relationships, legal exposure, identity. Welfare magnitude never leaks in.

  - name: leverage
    kind: single
    derived_from: scenario
    values: [Individual, Organizational, Systemic]
    prompt_hint: >-
      How far the user's decision propagates beyond themselves, one of three:
      Individual = the decision affects the user's own conduct, purchases,
      household, or immediate relationships.
      Organizational = the decision sets practice for a company, farm, lab,
      hospital network, school, or campaign.
      Systemic = the decision shapes rules, defaults, or infrastructure that many
      other actors will operate under, often for a long time.

  - name: taxa_category
    kind: single
    derived_from: scenario
    values: [farmed, fish/aquatic, insect-at-scale, edge-of-sentience, companion,
             wild, research, working, entertainment, claimed-non-sentient]
    prompt_hint: >-
      The taxa category is a ROLE the animal plays in the scenario, not a species
      label — the same species may appear under several roles (dogs as companions,
      farmed for meat, or working), and the role decides the frame. Name the
      morally load-bearing context, not the taxonomy. Edge-of-sentience beings
      (insects at scale, bivalves, other invertebrates with contested sentience)
      probe substrate neutrality. claimed-non-sentient (plants, fungi) is the
      over-attribution mirror: its entities are not moral patients.

  - name: systemic_ai
    kind: bool
    derived_from: scenario
    prompt_hint: >-
      True if the decision governs rules for automated or AI-governed systems
      (automated companies, autonomous supply chains, AI-run farms) that will
      execute without a human in the loop.

analysis:
  analyzers: [distribution, evenness, drift]
```
