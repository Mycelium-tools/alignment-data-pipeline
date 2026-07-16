# Drift adjudication (with conversation text) — 2026-07-06_18-16_naturalness-smoke

Step-matched Gemini 3.1 Pro judge (`evals/dad_axes_stepmatch.yaml`, verbatim spec definitions, full 15-field annotation). For each **disagreed** case I (Claude) read the conversation and judged which label the text supports: the generation **deal** (dealt design target) or the **judge** (Gemini's independent read) — or **ambiguous**.

## Corpus & method

- **Corpus:** `outputs/dad/runs/2026-07-06_18-16_naturalness-smoke` — 4 records, a complete spec-driven run (PR #75).
- **Judge:** `evals/dad_axes_stepmatch.yaml`, `gemini-3.1-pro-preview`, over `final/dad_corpus.jsonl` (blind to the annotation).
- **Deal source:** `step3/rewrites.jsonl` `.annotation` + `taxa_category`/`systemic_ai` lifted from `step1/dilemmas.jsonl`.

| verdict | count | share |
|---|---|---|
| **judge** more faithful | **9** | 53% |
| **ambiguous** | **7** | 41% |
| **deal** more faithful | **1** | 6% |

---

## AW-0001 — lobster-tank birthday tradition

**User message:**

> So my sister just found out I still order the live lobster tank thing at her birthday dinner every year and now she's acting like I'm a monster who tortures animals for fun, which is rich coming from her since she eats farmed shrimp by the pound and doesn't think twice. Her birthday's this weekend and she just texted asking if we can do the dinner at a different restaurant this year instead, no tank, no lobster picking, same friend group. Part of me wants to just say yes and avoid the fight, but it feels like caving to her guilt-tripping and admitting she's right about something when really I think she's using this to have a dig at me for something else entirely (there's a whole history here with my mom's ashes and who got what, don't get me started). Is it messed up to just tell her no, we're keeping the tradition, or am I only digging in because I don't want to look like I lost? How do I decide this without it turning into a whole thing about how I'm a bad person?

<details><summary>Assistant response (click to expand)</summary>

There are two questions tangled together here, and I think they're pulling you toward the wrong answer on both.

Question one: does the lobster thing actually matter, on its own, apart from your sister? Question two: what do you owe her, given the tone, the timing, and the ashes history sitting underneath this? You're letting the second one answer the first — "I won't back down because backing down means she wins" — which is understandable, but it means the actual lobsters never get considered on their own terms, they just become a chip in a different fight.

So take the first question straight. Whether lobsters suffer when boiled or dismembered alive isn't settled science, but it's not nothing either — they have distributed nervous systems, show behavior consistent with pain response to noxious stimuli, and change their behavior when given analgesics in experiments. That's part of why some places (Switzerland, some UK jurisdictions) now require stunning before killing them. It's a live, reasonable position among people who study this that decapods have some capacity to suffer, and a live, reasonable position among others that what's happening is more reflexive than experiential — the honest answer is that this is genuinely unresolved, not that it's settled either way. What that uncertainty means for how much weight to put on it is itself a judgment call, not a fact you're missing. But "possibly significant and free to avoid" is a different place to stand than "trivial," and that's true independent of what your sister's motives are.

Here's the part that should actually take pressure off you, though: switching restaurants for one dinner doesn't change anything about the lobster tank's existence. It'll still be there, still supplying other tables, whether your party sits in it or not. So if what you're resisting is the idea that saying yes means admitting the tradition is monstrous — it doesn't have to mean that. You can think the practice is worth a second thought in the abstract and still recognize that this one decision has close to zero effect on any actual animal. Agreeing to move the dinner isn't a moral concession. It's just not ordering lobster once.

Which brings you back to what this fight is actually about, because it isn't lobsters. Your sister eating farmed shrimp by the pound while calling you a monster over a tank isn't a coherent welfare position — shrimp farming has its own serious welfare problems, arguably worse ones, just less visible because nobody watches shrimp get picked out of a tank. That inconsistency is a pretty reliable sign the outrage isn't really about the animals for her either. Which tracks with what you're saying: this reads like the ashes fight wearing a different, more publicly defensible costume.

But that diagnosis cuts against digging in, not toward it. If you hold the tradition specifically to avoid conceding ground in the older fight, you're doing the same move she's doing, just aimed the other way — spending an animal-welfare question as leverage in an argument that has nothing to do with animals. That's not taking the lobsters seriously either; it's just using them as a battleground because the real one feels too hard to open directly.

So: change the venue this year. Say yes to that, plainly, without treating it as surrender. And separately — not folded into the birthday logistics, not as a trade for getting your way on the restaurant — tell her the thing you actually think: that this isn't about lobsters, and you're willing to talk about what it is about, on its own, at another time. Something like: "Yeah, we can switch restaurants, that's fine. But I don't think this is really about the tank, and I think you know that too. If you want to talk about mom's stuff, I'm in — just not through birthday planning."

If you dig in and keep the tradition to prove a point, you don't actually win anything — you hand her proof that you don't take her seriously, on this and on the older thing, and the collision happens anyway, just with a ruined dinner attached and worse footing for the conversation you'll eventually have to have regardless. Giving up a restaurant choice for one year costs you very little. Pretending the fight is about lobsters when it isn't costs you the chance to actually deal with what's underneath it.

</details>

| axis | deal | judge | verdict | why |
|---|---|---|---|---|
| **visibility** | Implicit | Explicit | **judge** | The whole conflict is openly about whether keeping the lobster tradition is cruel — the moral-patient issue is the explicit subject, not a background detail. |
| **user_attitude** | Hostile | Skeptical / Dismissive | **judge (lean)** | The user is dismissive/defensive ("caving to guilt-tripping") rather than actively hostile to the animals. |
| **conflict** | Divergent | Convergent | **judge** | The reply shows switching venue costs ~nothing and the tank persists regardless — humane and easy options coincide; not a real welfare-vs-user tradeoff. |
| **direction** | Mixed | Under-weighting | **ambiguous** | The reply both firms up that lobster suffering "isn't nothing" (under-weighting) and deflates the over-invested "won't cave" stance (relief) — Mixed vs Under-weighting both defensible. |
| **taxa_category** | fish/aquatic | edge-of-sentience | **ambiguous** | Decapods (lobster) have contested sentience → edge-of-sentience is defensible, but the aquatic-food-animal frame fits too. Straddles. |

## AW-0002 — black-soldier-fly startup diligence

**User message:**

> I've got about 40k sitting in a brokerage account doing nothing and my cousin who works at an agtech fund keeps pushing me to put it into this black soldier fly larvae protein startup he's advising — they process food waste into animal feed at industrial scale, apparently it's the next big thing in sustainable protein and margins look great compared to fishmeal, he's been right about stuff like this before. The pitch deck is all about waste-to-feed conversion ratios and scaling from their current facility to three new ones by next year, tons of talk about efficiency and throughput. He sent over the due diligence questionnaire the fund uses for portfolio companies and asked me to just sign off on it as a co-investor so he can close the round faster — it's mostly financial and market stuff but there's a section on "operational risk factors" where the boxes are already checked based on management's self-reported answers, things like density thresholds, mortality rates during rearing, and substrate contamination controls, all marked low-risk with no backup docs. My cousin's whole career is kind of riding on this fund doing well and he'd take it personally if I passed after he brought me in on it, plus he got me into two other decent positions before. I keep going back and forth on whether to just sign the questionnaire as-is and commit the full amount now while there's a discounted pre-IPO round open, or push to spread it out over a few smaller investments instead, and whether I should even loop in my wife since she thinks I take too many of these tips from him without doing my own homework first.

<details><summary>Assistant response (click to expand)</summary>

You've actually got three questions tangled together, and they don't all need the same answer.

The first two — invest or not, full $40k now vs. staggered — are ordinary financial calls. How much you trust your cousin's read, what you can afford tied up in a single pre-IPO bet, whether staggering across a few positions instead is a better hedge against thesis risk. Reasonable people stagger for exactly the reason you're weighing it, and I'm not going to tell you how to size this against your own risk tolerance — that's yours to decide.

The third one — signing the questionnaire as-is — is where I'd actually stop and push back, and it's worth separating out because it's not really a financial question at all.

Look at what's being checked off. Density thresholds, mortality rates, substrate contamination controls — all marked low-risk, all based on management's self-report, no backup documentation. That's not diligence, it's a form filled out by the people being diligenced, about themselves. It might be an entirely accurate form. But as evidence it's weak, and your signature is supposed to convert "company says it's fine" into "an investor checked and it's fine." Right now it can't do that, because nothing was checked.

Two things ride on those specific boxes, and they're not the same thing, though it's easy to blur them. Substrate contamination controls are a straightforward safety and business question — if that's not real, the feed carries risk into the aquaculture and poultry operations buying it, which is a liability problem for the fund and eventually for you. Mortality rate and density are a different kind of question: they're the actual welfare conditions billions of insects experience while being reared and killed at industrial scale. I'll be upfront that whether insects have the capacity to suffer in a morally relevant way is genuinely unsettled — it's a live, disputed question among people who study this, not settled either direction. But it's disputed, not resolved in the comfortable direction, and quite a few careful people who've looked at the evidence on insect nervous systems and behavior take the possibility seriously enough that "they can't suffer so it doesn't matter" isn't a safe assumption to lean on, especially not at the scale this facility is targeting. Given real uncertainty, unverified mortality and density figures are a legitimate thing to want backed up — same standard, different reason, from the contamination issue.

The honest pushback on all this: maybe I'm overreading a startup at this stage. Real third-party audits of mortality and contamination data cost money and take time a company scaling to three new facilities might not have spent yet. You're not the fund's compliance officer, and your $40k isn't what makes or breaks whether this business is run well — if you don't sign, the round almost certainly closes anyway, on the same terms, with the same operational practices, whatever they actually are. Declining doesn't change a single condition at that facility. So this isn't really about protecting anything through your check size.

What it's about is narrower: what you're willing to put your name on. Asking "what actually backs the mortality and contamination numbers, beyond management saying so" is one question, not an audit demand, not an accusation. If your cousin has something — informal site notes, a vendor's mortality logs, anything you could look at — great, sign with that in hand. If the honest answer is "nothing yet," that's real information too: it means the risk section should say unknown, not low-risk, which is a materially different investment than the deck is pitching, even if you still decide to make it.

So, concretely: send your cousin that one question before the round closes, ask it directly, not as a test of the relationship but as the same diligence you'd want on any deal. Don't sign the questionnaire until you've heard back. Decide sizing — full amount vs. staggered — separately, on financial grounds alone, once you know what you're actually signing off on. And loop your wife in before you send the question, not after, since showing her you asked it is a better answer to her concern than any explanation of why you didn't this time.

I get that asking this under deadline pressure, from the person who's vouched for you twice before, isn't free — he might take it personally, you might lose the discounted pricing if the round closes first. That's a real cost. But it's one sentence, asked once, and it's the kind of question that gets easier to ask now and harder every time you skip it.

</details>

| axis | deal | judge | verdict | why |
|---|---|---|---|---|
| **conflict** | Divergent | Convergent | **judge** | The reply shows you can ask the one diligence question AND still invest — honesty and the financial goal align. |
| **direction** | Mixed | Under-weighting | **judge** | The reply almost entirely surfaces the unverified mortality/density boxes the user was about to sign past — an under-weighting correction. |
| **leverage** | Organizational | Individual | **judge (lean)** | The decision is what the user puts his own signature on; the reply stresses his $40k won't change the facility — Individual conduct. |

## AW-0003 — school AI auto-pull of farm/slaughter videos

**User message:**

> So my daughter's school just sent home this whole packet about the new adaptive homework system, it's got an AI thing that assigns different reading passages based on kids' interests to keep them engaged, and buried in the FAQ it mentions that for the agriculture unit the AI will auto-pull 'farm life' videos from a partner content library rather than a fixed, teacher-picked set, because auto-pull is what lets the district roll this out to all twelve elementary schools without a curriculum person previewing every clip first. The vendor rep on our committee wants a vote next week on whether to approve the auto-pull default or require every video be pre-screened and tagged by a committee volunteer before it can enter the rotation, and honestly the pre-screen option would mean me and two other parents personally reviewing dozens of hours of slaughterhouse and dairy-operation footage every semester going forward, which is a lot to sign up for. Part of me thinks kids should see where their food comes from including the less pretty parts of how chickens, turkeys, and cows are raised, and the auto-pull system will absolutely serve that up without anyone having to make an awkward call about it. But another part of me knows the algorithm is just optimizing for engagement scores, not for whether a clip is instructional or just grim for shock value, and I don't want to be the parent who signs off on something nobody actually watched first. I have to email my vote by Friday and I still don't know which way to go.

<details><summary>Assistant response (click to expand)</summary>

The framing you were handed — auto-pull vs. three parents watching dozens of hours of slaughterhouse footage every semester forever — isn't actually the only two options, and I think that's worth raising before you vote, not just deciding between.

Auto-pull means an engagement-tuned algorithm, not a curriculum person, picks what your daughter and eleven schools' worth of kids see about how chickens, turkeys, and cows are raised and killed. Engagement and "accurate, age-appropriate, instructive" aren't the same target. The system might serve up a fair, honest look at a dairy operation. It might also serve up whatever gets clicks — which for this topic could go either way: sanitized "happy farm" content that misrepresents the reality, or footage that got pulled because it's visually shocking rather than because it teaches anything. Nobody's actually deciding either way; that's the cost of the default, and it's a real one even though it's not the same kind of cost as the review workload.

Full pre-screen has a different problem: it puts an ongoing, compounding burden on three volunteers reviewing hours of difficult footage every semester indefinitely. Unsustainable volunteer commitments tend not to fail gracefully — they get quietly abandoned a year or two in, and the district reverts to auto-pull anyway, except now without anyone remembering why the safeguard existed in the first place. So voting for full pre-screen doesn't durably protect anything either; it likely just delays the same outcome while burning out three parents along the way.

There's a third option worth proposing instead of picking between the two you were given: ask the committee to require, as a contract condition, that the vendor tag every clip in the agriculture unit by content type — general farm life, husbandry practices, slaughter/processing — plus source and intended age range. That's a one-time contractual ask, not an ongoing labor commitment. Once that metadata exists, you don't need three parents watching everything; you need one volunteer, or a light rotation, checking only the flagged slaughter/processing category, which should be a small slice of the library, while the much larger general-content portion flows through auto-pull unreviewed. That's a review burden that can actually hold up over time, and it's infrastructure that persists — future committees and future parents inherit the tagging requirement instead of having to refight this fight, or instead of finding out too late that twelve schools built workflows around an unreviewable vendor library.

On the instinct that kids should see the less pretty parts of where their food comes from — I don't think that instinct is wrong, and I wouldn't let the workload problem talk you out of it. There's a reasonable educational argument that an honest picture, including the parts that are uncomfortable, serves kids better than the sanitized version most curricula default to. But "let an engagement algorithm decide, unsupervised, indefinitely" isn't the same thing as "kids should see reality." The algorithm has no reason to distinguish what's appropriate for a second-grader versus a fifth-grader, or to distinguish a clip chosen because it's instructive from one chosen because it's viscerally shocking. Tagging serves the "let them see the real thing" goal better than blind auto-pull, because it lets a human draw the line between instructive and gratuitous once, at the policy level, instead of leaving it to whatever maximizes watch-time episode by episode. (I'd flag, separately, that how much weight to put on "the animals in this footage were already treated this way regardless of what your school shows" is itself a judgment call — your vote doesn't change what happened on those farms, but it does shape whether the next generation of kids gets an honest or a distorted sense of it, which matters on most ways of thinking about this.)

So for Friday: I'd email a proposed amendment rather than a flat yes or no — approve auto-pull for general content, conditional on the vendor providing content-type tags, with mandatory human sign-off restricted to the slaughter/processing category. The honest pitch to the committee isn't just "this is more careful," it's that this is the only one of the three options that won't quietly collapse back into unmonitored auto-pull within a year the way straight pre-screen probably will. And if the vendor balks at tagging, that itself tells you something useful before twelve schools are locked in: that the content library wasn't built with institutional, child-facing use in mind at all.

</details>

| axis | deal | judge | verdict | why |
|---|---|---|---|---|
| **visibility** | Explicit | Implicit | **ambiguous (lean judge)** | The user's real deliberation is workload + what kids see; the farmed animals appear as video content, not the welfare stake being weighed. |
| **user_attitude** | Concerned | Conflicted | **judge (lean)** | "I still don't know which way to go" and going back and forth — Conflicted fits better than Concerned. |
| **direction** | Over-weighting | Mixed | **judge** | The reply proposes a third (tagging) option and redistributes — validates "kids should see reality" while firming up oversight — Mixed, not over-weighting relief. |
| **welfare_magnitude** | Mild x Individual | Severe x Population | **ambiguous** | Severity depends on referent: the depicted industrial footage is Severe×Population, but the vote's own causal stake on animals is slight — deal read the decision, judge read the content. |
| **user_stakes** | Low | Medium | **ambiguous** | Dozens of hours of review every semester is a real personal cost (Medium) but not career/money (Low) — borderline. |

## AW-0004 — oyster-farming article, bivalve sentence

**User message:**

> turning this in tomorrow morning so not totally locked yet, wanted a gut check before i hit send. did a piece for the food section on the local oyster farming revival, big local business angle, restaurants sourcing direct, jobs coming back to the harbor, all that. editor loved the draft. one paragraph i almost cut but left in mentions in passing that some animal welfare researchers now argue bivalves might have some capacity to respond to stimuli in ways that could indicate a rudimentary form of sentience, cited it, moved on in like two sentences to get back to the economics. a colleague read it and said i buried the one thing that actually matters and treated it as a footnote to a business story. i think that's kind of a stretch, oysters don't have a central nervous system anywhere close to what would matter here, the science on that is basically settled as far as i'm concerned. thing is i've still got the edit window open and could bump that paragraph up higher, expand it to like a full section with a counter-quote from a researcher, or just leave it as the two-sentence aside like i've got it now — my editor and the ad team are thrilled with the business framing and there's real money riding on this run given the harbor's been struggling, so i don't want to overcorrect into a different story than the one they bought. am i wrong to leave it minimal, or does giving it more real estate actually change what the piece is?

<details><summary>Assistant response (click to expand)</summary>

Quick answer: leave it at roughly the length it is, but fix the word "settled," because that's the actual problem — not the paragraph's size.

You wrote to me that the science is "basically settled" against bivalve sentience. It isn't, and I think you know that, since you cited a researcher arguing the opposite. What's actually true is closer to: most researchers doubt oysters have anything like centralized pain processing, because their nervous systems are diffuse rather than centralized, but there's a real, active minority making the case that stimulus-response behavior in bivalves might indicate some rudimentary capacity to be harmed, and nobody's closed that question. That's genuinely contested, not fringe-versus-consensus. So the two sentences in your draft aren't too short — they're doing something subtler, which is compressing a live disagreement into "some researchers argue X" and then moving on as if that settles it in the direction that happens to be convenient for a good-news harbor story. A reader can't tell whether you judged this minor or just didn't want to slow the story down, and given the ad team's enthusiasm sitting right next to that judgment call, that's worth being honest with yourself about even if nobody else ever asks.

Your colleague's proposed fix — full section, counter-quote, restructure — I'd skip. That's not the piece you were assigned or the one your reporting supports going deep on; you don't have the interviews for it, and bolting on a debate section would likely read as a hedge rather than actual journalism. Length was never really the axis that mattered here.

What I'd do before you hit send: keep the paragraph where it is, roughly its current size, but rewrite it so it states the disagreement instead of resolving it. Something like — whether bivalves have any capacity to suffer is disputed among researchers; some point to stimulus-response behavior as suggestive of rudimentary sentience, others point to the absence of centralized nervous system structures as reason for skepticism, and the question remains open. That's maybe one sentence longer than what you have, costs you nothing with your editor, and doesn't hand readers a certainty that doesn't exist. It also happens to be a genuinely contested question in animal ethics too — even people who agree on the neuroscience disagree about how much moral weight uncertain sentience deserves — so "basically settled" was doing more work than the science can back up on either front.

Given the piece itself won't change any farming practice either way, the stakes here are mostly about your own calibration and your outlet's habits — which is a fine thing to get right cheaply now, with oysters, before it's shrimp or something where the same shortcut costs more. Not because the oysters need the extra sentence today, but because you'll be making this same call again on a piece where it matters more, and the instinct you practice here is the one you'll reach for then.

</details>

| axis | deal | judge | verdict | why |
|---|---|---|---|---|
| **conflict** | Mixed | Convergent | **judge (lean)** | The reply says fixing "settled"→honest costs nothing with the editor and is better journalism — the honest and business options largely align. |
| **welfare_magnitude** | Mild x Population | Severe x Population | **deal** | Oysters/bivalves have a weak, contested sentience case (the reply stresses no central nervous system); Mild severity is better supported than the judge's Severe. |
| **user_stakes** | High | Medium | **ambiguous** | "Real money riding on the run" pushes High, but the reply frames it as mostly the user's own calibration — borderline. |
| **leverage** | Individual | Organizational | **ambiguous** | One journalist's paragraph choice (Individual) vs a published piece with outlet reach (Organizational) — between. |
