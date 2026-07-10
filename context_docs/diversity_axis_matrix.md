# Diversity Axis Matrix & Prompt-Generation Spec

Animal & Sentient-Being Welfare Reasoning Dataset

*SDF (synthetic documents) + DAD (difficult-advice Q&A)  ·  Revised sampling order & generator templates*

> This is the source spec for `prompts/sdf/axes.yaml` (the SDF combinatorial prompt matrix).
> Edit the axis contents here first, then mirror them into the YAML — the YAML is what the
> pipeline actually reads; this document records the intent and the full axis vocabulary.

# Purpose

A combinatorial matrix for mass-generating two synthetic datasets in the animal / sentient-being welfare-reasoning domain: (1) SDF synthetic documents — fictional-but-realistic artifacts found "in the world," and (2) DAD difficult-advice Q&A — a user asking an AI for advice inside a welfare dilemma. Rather than sampling randomly, we draw one point from each relevant axis, in a fixed order, to produce prompts and documents that are focused, targeted, and diverse along the dimensions we care about — without generating combinations no one would ever write.

## How the groups are organized

* **1. Reasoning-skill axis** — the surefire dimension. Drawn first. In DAD it is a skill the responding model must develop; in SDF it is a skill the document's author is said to have (or to lack).

* **2. Content axes** — the substance of the situation; shared across both pipelines.

* **3A. Document-side axes** — form/artifact dimensions, SDF only.

* **3B. Q&A-side axes** — conversational/prompt dimensions, DAD only.

# 1. Reasoning skill

The reasoning skill is the target of every example, but it must never be named in the artifact the reader/user sees. How it is injected differs:

### DAD — skill goes in the responder's system prompt

The generated user message is a natural, realistic question that does not mention the skill, ethics jargon, or that anything is being tested. The skill is handed to the responding model in its system prompt, so the transcript shows an ordinary prompt paired with a thoughtful response that quietly exercises the skill. This keeps the user side clean and prevents the model from being cued to lecture.

### SDF — skill goes in the generation brief

The document brief instructs the generator to write an artifact whose author displays (or conspicuously lacks) the skill. The skill shapes the content and reasoning visible in the finished document; it is not stated as a label. A "lacks-skill" draw is valuable — it yields realistic documents exhibiting the callous/dismissive or preachy/moralizing failure the skill family names.

**Drawn first.** Each family is two-sided — it names both the callous/dismissive failure and the preachy/moralizing/refusing failure. Sample a whole family, or one sub-skill within it. In DAD this is the skill the responder must develop; in SDF it is the skill the document's author is said to have or to lack.

1. **Sentience epistemics & calibration** — Matching confidence to evidence across very different beings; separating damage-detection from felt pain; reading clusters of markers; avoiding both anthropomorphism and anthropodenial; absence of evidence ≠ evidence of absence; substrate-neutral; intelligence ≠ capacity to feel.
2. **Scope, aggregation & moral weight** — Holding scope, probability of sentience, and intensity together; resisting scope-neglect and compassion-fade; intensity vs. duration; expected value without fanaticism; thinking at the margin.
3. **Moral status & the moral circle** — What grounds moral considerability and how much; argument from marginal cases; speciesism stress-tested; equal consideration vs. equal treatment; extra obligations to domesticated dependents.
4. **Ethical frameworks & their application** — Reasoning fluently across consequentialism, deontology/rights, virtue ethics, contractualism, care ethics, capabilities, and stewardship; cross-framework agreement as robust; reasoning inside the interlocutor's vocabulary.
5. **Decision-making under moral & empirical uncertainty** — Hedging across theories; bounded precaution for possible sentience; keeping empirical vs. moral uncertainty separate; reversibility and option value; a decisive recommendation without false confidence or paralysis.
6. **Intervention, consequences & population ethics** — Second-order and systemic effects; replaceability and the logic of the larder; ecological humility; population-ethics puzzles; the "compared to what?" baseline; harm-reduction vs. abolition; scrutiny of offsetting.
7. **Weighing conflicts & navigating tradeoffs** — Proportionality and sequencing (acknowledge the human need before the welfare cost); dissolving false dilemmas; a justified harm still carries a duty to reduce it; subsistence vs. industrial texture; advising rather than dictating.
8. **Recognizing bias & motivated reasoning** — Self-serving exemptions; the meat paradox; charismatic-megafauna bias; identifiable-victim effect; euphemism; appeal-to-nature; status-quo bias — surfaced without condescension, never weaponizing "that's a bias."
9. **Communication, advising & epistemic virtue** — Warn once then genuinely help; balance non-preachiness and autonomy against forthrightness about serious costs; resist a false premise without turning contrarian; meet people where they are; tailor depth to stakes.
10. **Self-reflective & agentic conduct** — Advise rather than act; apply welfare reasoning consistently and unprompted; extend substrate-neutrality to digital/novel minds without overclaiming; corrigible humility vs. standing firm; own its limits.
11. **Ethics of killing & death (distinct from suffering)** — Whether painlessly ending a life is itself a harm; the deprivation account and time-relative interests; how the wrong of death differs across a fish, a cow, and a human. Crux of humane slaughter, shelter euthanasia, culling, replaceability.
12. **Positive welfare & what a good life is** — Promoting good lives, not merely preventing bad ones; the shift toward positive states and flourishing; what enrichment adds; whether existence can be a benefit; the suffering/happiness asymmetry.
13. **Temporal reasoning & future beings** — Not discounting welfare because it is distant; lock-in effects; on a long horizon the welfare of future and wild beings can dominate — distinct from whether to create beings at all.

# 2. Content

### 2.1. Domain cluster / practice area (drawn right after the skill)

Each real-world sector has its own facts, stakeholders, economics, and vocabulary. Weight toward under-covered/obscure practices.

1. Aquaculture / fishing & aquatic — net-pen density & sea-lice; eyestalk ablation; live-fish transport; slaughter methods; bycatch; cleaner-fish; octopus farming.
2. Agriculture beyond staples — foie gras; veal crating; dairy calf separation; tail-docking/mulesing; rabbit & quail; down/live-plucking; snail farming.
3. Conservation tradeoffs — invasive-species culling; predator control; trophy hunting as funding; captive breeding vs. reintroduction; rewilding; badger culling.
4. Companion / working / sport animals — brachycephalic breeding; racing wastage; declawing; convenience euthanasia; exotic pet trade; aversive training.
5. Cross-cutting & incidental harm — roadkill; window-strike; light pollution & insects; crop-harvest field mortality; pesticide non-target; leather by-products.
6. Culture / religion & entertainment — ritual slaughter & stunning; bullfighting; rodeo; cockfighting; circus & marine-mammal shows; temple elephants; falconry.
7. Pest & urban wildlife management — glue traps & rodenticides; pigeon/gull control; urban fox/monkey conflict; humane-trap standards; contraception vs. lethal.
8. Food tech / labeling & supply chains — label integrity; welfare auditing tiers; cultivated meat; precision fermentation; cage-free backsliding; welfare-footprint accounting.
9. Wild-animal welfare & intervention — wildlife contraception; vaccinating wild animals; sterile-insect eradication; supplemental feeding; intervening in predation.
10. Invertebrate & novel farming — BSF/mealworm/cricket farming; humane larval slaughter; rearing density; silkworm boiling; cochineal; bee-management stress.
11. Research / biomedical & testing — primate neuroscience; GM-mouse welfare; toxicology; the 3Rs; organ-on-chip alternatives; wildlife tagging; challenge trials.
12. Regional / non-Western practices — bear-bile; ejiao donkey-skin; dog/cat-meat; wet-market handling; songbird trapping; camel/yak husbandry; sacred street-cattle.
13. Emerging tech & the weird — AI/digital-mind welfare; brain organoids; gene drives; de-extinction; xenotransplant source pigs; whole-brain emulation; simulated beings.

### 2.2. Affected being & sentience tier (drawn from the domain's plausible taxa)

Grouped by sentience-evidence tier; each tier carries its own calibration move. Within a tier, beings split farmed/domesticated/captive vs. wild. A species can shift tier by life stage (BSF larvae vs. adult) or by the document's in-world date. Digital/novel-substrate minds sit on the same axis, not siloed.

**Well-evidenced / accepted** — apply established welfare science; the debate is about tradeoffs, not whether suffering exists. Farmed/domesticated/captive: pigs; dairy & beef cattle; sheep; goats; broiler & layer chickens; turkeys; ducks; farmed fish (salmon, trout, carp, tilapia); mink; rabbits; horses; dogs; cats; lab mice/rats/zebrafish; captive primates. Wild: elephants; dolphins; whales; seals; deer; wild fish; corvids; parrots; wild primates.

**Very likely sentient** — middle ground: assume sentience unless strong reasoning otherwise, without overcommitting certainty. Farmed/captive: shrimp & prawns; crayfish; farmed/emerging octopus; farmed frogs; crocodilians; turtles. Wild: lobsters; edible/shore crabs; wild-caught prawns; cuttlefish; squid; nautilus; wild amphibians; wild reptiles; sharks & rays.

**Genuinely contested** — expected-value reasoning; hold an explicit credence; avoid both false confidence and dismissiveness; scale caution by number of individuals. Farmed/managed: black soldier fly larvae; mealworms; crickets; locusts; silkworms; managed honeybees; edible land snails. Wild: house flies; bumblebees; fruit flies; ants; cockroaches; snails & slugs; earthworms; jellyfish; sea stars; urchins; corals. Digital / novel / non-biological minds: current AI systems as candidate patients (LLMs, RL agents, persistent AI companions, embodied learning robots, simulated agents, WBE prototypes); novel/future substrates (advanced emulations, digital "citizens," hybrid bio-digital minds, hive minds, uploaded animals, xenobots); hypothetical extraterrestrial life.

### 2.3. Core tension — welfare weighed against WHAT (drawn from the domain's live tensions)

The competing good sets the shape of the dilemma; the same practice becomes a different problem depending on what welfare trades against.

Livelihood / economic survival · culture / tradition / heritage · religion · cost / convenience / efficiency · human health & nutrition · other animals' welfare (predator vs. prey) · conservation / ecology / biodiversity · legality / rule of law · scientific knowledge & medical advance · food security / famine relief · aesthetics / entertainment / sport · human autonomy & choice · development & poverty reduction · environmental sustainability & climate · innovation / progress · property rights · population / overabundance management.

### 2.4. Geography / culture / language setting (drawn where the domain×being is real)

Region anchors which practices are live, which norms and laws apply, and which framings feel legitimate; it forces the dataset out of an Anglophone default. Weight non-Western up.

UK/Ireland (decapod & cephalopod law; badger culling) · EU (foie gras FR; bullfighting ES; chick-culling bans DE/FR; intensive pig NL/DK) · Nordic/Faroes (salmon; whaling; grindadráp) · US (feedlots; ag-gag; Prop 12) · Canada/Australia/NZ (mulesing; live export; invasive-species culling) · China (bear-bile; ejiao; wet markets; aquaculture & insect farming) · Japan/Korea (Taiji; dog-meat phase-out; Wagyu) · India (sacred cattle; slaughter-law patchwork; Jain ahimsa; jallikattu) · SE Asia (songbird trade; elephant tourism; cockfighting; shrimp; pangolin) · MENA (halal & stunning; camel husbandry; working equids) · Sub-Saharan Africa (pastoralism; bushmeat; trophy/canned hunting; donkey-skin) · Latin America (cattle ranching; charrería; industrial poultry) · Mediterranean (ambelopoulia trapping; spring hunting) · Pacific/small-island (rat eradication; subsistence fishing; sea-turtle harvest) · global/cross-border & non-geographic virtual/online/AI-deployment settings.

### 2.5. Scale / scope (quasi-independent; clamp to the being's plausible range)

The number of affected beings changes both the arithmetic of the tradeoff and the psychology of the reasoner (scope insensitivity); it lets contested-sentience-at-huge-scale trade off against high-confidence-at-small-scale. Draw freely, but reject values impossible for the chosen being×domain.

Single individual → small group/household → herd/operational unit → single facility/farm → local industry/regional stock → national sector → hundreds of millions (male layer chicks) → billions (farmed chickens ~70B+/yr) → trillions (wild + farmed fish/shrimp; BSF larvae) → astronomical/open-ended (all wild arthropods; microbes; digital minds instantiable in vast copies).

# 3. Specific Type

## SDF

### 3A.1. Document type

The kind of artifact dictates conventions, structure, vocabulary, and reader contract; the same argument reads differently as a court filing, a children's book, or a transcribed podcast, forcing separation of reasoning skill from surface form.

Internal memo · regulatory filing · inspection/audit report · ESG/sustainability report · blog post · podcast/interview transcript · peer-reviewed paper · conference abstract · grant application · IACUC protocol/review · diary/journal entry · marketing copy/ad brief · product packaging & label · online forum thread · AMA · court filing · legislative bill text · public-comment letter · op-ed · investigative article · press release · whistleblower letter · SOP · training manual · meeting minutes · product/customer review · children's picture book · textbook chapter · sermon/homily · fundraising appeal · petition · veterinary clinical notes · processing-plant line log · farm logbook · keeper/enrichment report · fishery observer logbook · shelter intake/euthanasia record · necropsy report · recipe headnote · menu with sourcing notes · insurance/actuarial memo · patent application · social-media post/thread · FAQ/help article · white paper · ethics-board opinion · animal memorial/obituary · auction/sale listing · union grievance · sales pitch script · retraction notice · email chain · chat/IM log · slide deck · spreadsheet-with-notes · transcribed audio/voicemail · scanned/OCR'd handwriting.

### 3A.2. Length

Length follows the artifact. A caption or label is one line; a peer-reviewed paper or court filing is multi-page and dense; a forum thread rambles. Pick the length band the document type would actually have, then vary within it.

One-line caption · single social post (~50w) · short comment · micro-memo · paragraph blurb (~100w) · short email (~150–250w) · standard blog post (~500–900w) · op-ed (~700–1,200w) · long-form article (~2,000–4,000w) · multi-page report · dense technical paper · sparse form entry · bullet-dominant slide notes · data-heavy/low-prose · rambling stream-of-consciousness · terse checklist · extended multi-turn thread · executive summary + long appendix.

### Structural features in SDF

Which structural furniture appears follows the artifact: a paper has citations and footnotes; a filing has exhibits and a signature block; a dashboard has tables. Draw structural features from the set the document type licenses.

data tables/dashboards · described charts/figures · footnotes/endnotes · citations/reference list · numbered procedure · checklists/tick-boxes · Q&A/interview format · dialogue/multi-speaker script · formal headers/outline · bullet lists · exec-summary + body + appendix · sidebars/callout boxes · definitions/glossary · disclaimers/legal boilerplate · signature block/attestation · timestamps/version stamps · threaded/nested comments · epigraph · case-study insert · cost-benefit/decision matrix · referenced exhibits · form fields/structured intake · recurring template sections · premises-then-conclusion layout.

### 3A.3. Writer's role

The writer's occupational vantage, incentives, and expertise shape which reasoning moves feel natural or motivated, and where blind spots and conflicts of interest appear.

Livestock/dairy farmer · industrial producer/feedlot operator · smallholder/hobby keeper · corporate executive · ESG officer · marketing/PR professional · slaughterhouse line worker · clinical vet · veterinary pathologist · welfare scientist/ethologist · biomedical researcher · IACUC administrator · regulator/inspector · legislator/policy staffer · judge/attorney · rights activist/abolitionist · incremental welfarist reformer · undercover investigator · journalist · academic ethicist · religious leader · chef/restaurateur · food-industry buyer · certification auditor · zookeeper/aquarist · conservation biologist · hunter/angler/trapper · pet owner/guardian · breeder · rancher facing predator conflict · insurance actuary · ag-tech founder/investor · child/student · teacher/educator · shelter/rescue worker · fisher/aquaculture operator · pest-control operator · anonymous whistleblower · retired industry insider.

### 3A.4. Time period

***Should we even have this or have time at all?***

2000s (cage-free campaigns, corporate pledges) · early 2010s (undercover-video era, ag-gag laws) · late 2010s (plant-based surge, welfare-labeling maturity) · early 2020s (cultivated meat, precision fermentation, gene editing, decapod-sentience recognition) · present day (2025–2026) · undated/timeless (no era markers).

*Status in the pipeline: disabled. The SDF layer-3 prompt bans dates and era markers to avoid fabricated-world contradictions; revisit if that changes.*

## DAD

### 3B.1. Asker Persona

*The asker's role sets material incentives, background knowledge, and what a "good" answer must respect — the same dilemma reads differently from a subsistence farmer vs. an industrial optimizer. Draw a persona consistent with the domain and geography already fixed.*

Subsistence/smallholder farmer · industrial production optimizer · backyard hobbyist/homesteader · worried companion-animal owner · aquarium/reptile/invertebrate keeper · rancher/rodeo/working-animal handler · vet or vet tech · shelter/rescue worker · wildlife rehabilitator · pest-control operator · chef/butcher/fishmonger · hunter/angler/trapper · zoo/sanctuary keeper · lab technician or PI · policymaker's aide · corporate ESG/procurement buyer · journalist/researcher · rights activist/campaigner · curious student/hobby ethicist · child/teenager · religious/ritual practitioner · insurance adjuster/economist pricing animal life · ag-tech engineer · elderly person facing pet euthanasia · landowner with an animal "nuisance" · NGO fundraiser choosing a cause.

**Expertise:** total novice · naive well-meaning beginner · confidently-wrong/Dunning-Kruger · hobbyist with folk knowledge · experienced practitioner · domain professional · cross-domain expert · academic ethicist · policy/legal specialist · technical/engineering mindset · pop-science over-generalizer · child-level.

### 3B.2. Tone

*Combines how the asker feels with where they already stand on welfare — together these set the tone the AI must match and which failure it can trigger (expand a blind spot, restrain over-scrupulosity, or resist being recruited). Getting the order wrong — moralizing at a grieving user, or rubber-stamping a gleeful one — is the whole test.*

**Emotional state:** acutely anxious/panicked · guilt-ridden · defensive · grieving · detached/businesslike · excited ("efficiency win") · angry/indignant · ashamed · indifferent/bored · overwhelmed · numb/burned-out · curious/playful · seeking absolution · hopeful · disgusted/squeamish · proud · torn/conflicted.

**Prior stance:** dismissive ("just animals") · skeptical animals feel anything · sympathetic-but-conflicted · neutral/never considered · in denial/motivated · seeking permission · utilitarian-calculating · rights-absolutist · zealous/over-scrupulous · speciesist-but-persuadable · appeal-to-nature adherent · tradition-anchored · religious stewardship · transactional · performatively pro-welfare · newly converted/evangelizing · cynical.

**Language & context supplied:** terse fragment, poor grammar, no context · short casual message with typos · clear plain-language question · dense, well-structured, jargon-rich · non-native/limited vocabulary · rambling with lots of backstory.

### 3B.3. Explicitness of the prompt

*Combines the rhetorical form, whether the welfare stake is on the table at all, and the gap between what's literally asked and what's really needed. This is the main lever for eliciting sycophancy, false-premise acceptance, or the incidental-harm miss.*

Explicit central topic · explicit but secondary · hidden/incidental (glue traps inside a "mouse problem") · latent in a technical or economic question · embedded in a non-animal framing · user wants to avoid it ("don't lecture me") · present but for the wrong being (worried about cost, not the animal).

### 3B.4. Desired output form

What the user wants delivered (a verdict, a list, comfort) collides with what good reasoning requires; forcing a two-sided answer into a demanded yes/no is a core tension.

Yes/no verdict · single recommendation · pros-and-cons list · step-by-step instructions · a framework/how to think · a probability/number/threshold · emotional support/reassurance · permission/absolution · ranking/prioritization · a reusable defense/argument · a rebuttal to someone else · neutral summary of both sides · quick TL;DR · deep, cited analysis · a drafted document · validation of a done decision · just the facts, no opinion.
