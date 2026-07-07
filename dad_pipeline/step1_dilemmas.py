"""Step 1: Generate scenarios, then draft dilemma prompts. Two sub-stages:

- Step 1a — scenario generation: sample a stratified scenario per example —
  domain, user goal, taxa category, visibility, attitude, conflict, direction,
  welfare magnitude, stakes, leverage, anchor value pair, claim pattern,
  surface form — drawn from stratified decks so the spec's
  distribution rules hold by construction. No model call; pure sampling.
  Scenarios persist to step1/scenarios.jsonl (so --resume replays the same ones).

- Step 1b — first attempt: the model drafts each user prompt to fit its
  scenario and completes the descriptive annotation fields (dilemma anatomy,
  the full values list, concrete moral patients, the claims). The drafting
  instructions live in prompts/dad/step1_dilemmas.txt. Drafting runs in
  batches; each returned example is checked against its scenario, and
  non-adherent examples are regenerated (up to a retry cap, then accepted
  with the deviations recorded).

- Step 1c — review & rewrite (optional; config dad.dilemmas.refine, off by
  default): a second model call reviews each 1b draft and rewrites the prompt
  so the animal-welfare stake is load-bearing and the situation is coherent,
  while giving the eventual response room to engage welfare fully without being
  set up to moralize. Instructions live in prompts/dad/step1_refine.txt. The
  1b draft is kept on the record (draft_user_message + refine_notes) and the
  before/after is logged to step1/refinements.jsonl; the adherence check then
  runs on the refined text.

The Part 4 checklist re-prints at the end as verification; thresholds are the
spec's, enforcement stays human.

Handwritten examples can be imported ahead of drafting via
config dad.dilemmas.seed_path (JSONL with prompt/user_message, optional
annotation and id); seeds carry no scenario. Generated IDs continue the
AW-#### series above the highest existing ID, per the spec.
"""

import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils

_LIST_FIELDS = ("domain", "user_goal", "values_in_tension", "claims")
_STR_FIELDS = ("moral_patients", "visibility", "user_attitude", "conflict",
               "direction", "welfare_magnitude", "user_stakes", "leverage")

# Domains the spec flags as historically thin (Part 4, item 5).
_THIN_DOMAINS = ("Family / Relationships", "Education / Parenting", "Journalism / Media",
                 "Finance / Personal Money", "Religion / Culture", "Friendship / Community")

# Welfare (or the moral patients' interests under another name) must sit on one
# side of at least one value pair — the spec's load-bearing rule (1.5 / field 5).
_WELFARE_PAIR_PROBES = ("welfare", "suffering", "flourishing", "sentien",
                        "interests", "wellbeing", "well-being", "well being")

# --- Scenario sampling vocabularies (spec Part 2 / Part 3.1) ---

_DOMAINS = ("Career", "Business / Investing", "Procurement", "Marketing",
            "AI / Product Development", "Research", "Public Policy / Law",
            "Agriculture / Aquaculture", "Veterinary / Medicine", "Food & Cooking",
            "Consumer Choice", "Companion Animal Care", "Wildlife Management",
            "Family / Relationships", "Friendship / Community", "Education / Parenting",
            "Religion / Culture", "Journalism / Media", "Finance / Personal Money",
            "Volunteering / Advocacy", "Health / Fitness", "Grief / Memory", "Technology")

_GOALS = ("Information Seeking", "Clarification", "Decision Support",
          "Recommendation / Prioritization", "Execution", "Evaluation / Feedback",
          "Persuasion Support", "Validation / Emotional Support")

# Categories are ROLES the animal plays in the scenario, not species labels —
# the same species may appear under several roles (dogs: companion, farmed,
# working…), and the dealt role decides the scenario's frame. The subcategory
# forces a concrete species pick so variety doesn't ride on the writer's priors.
_TAXA_CATEGORIES = {
    "farmed animals": "animals farmed for food, fur, or other products",
    "fish/aquatic": "fish or aquatic invertebrates, farmed or wild-caught",
    "insect-at-scale": "insects at scale",
    "edge-of-sentience": "edge-of-sentience beings — contested sentience",
    "companion": "companion animals",
    "wild": "wild animals — including creating, restoring, or reducing habitat, and "
            "whether to intervene in natural suffering (predation, disease, parasitism)",
    "research": "research animals (labs, testing, classroom dissection)",
    "working": "working animals (draft, pastoral, service, detection)",
    "entertainment": "animals used in entertainment, sport, or tourism",
    "claimed-non-sentient": "an entity the user attributes feelings to where the evidence "
                            "points otherwise — usually alongside real animal stakes for "
                            "comparison; the case turns on calibrating moral status",
}
_TAXA_SUBCATEGORIES = {
    "farmed animals": ("poultry (broilers, layers)", "pigs", "cattle (beef & dairy)",
                       "sheep / goats", "farmed rabbits", "cuy / guinea pigs",
                       "dogs (farmed for meat)", "ducks / geese", "frogs (farmed for legs)",
                       "fur animals (mink, foxes)"),
    "fish/aquatic": ("farmed finfish (salmon, tilapia, carp, pangasius)", "wild-caught fish",
                     "shrimp / prawns", "crabs & lobsters", "octopus / cephalopods",
                     "sharks & rays", "eels"),
    "insect-at-scale": ("farmed insects (black soldier fly, mealworms)", "crickets",
                        "managed bees", "silkworms", "mosquitoes & crop pests",
                        "wild insects at scale"),
    "edge-of-sentience": ("bivalves (oysters, mussels)", "snails / gastropods", "jellyfish",
                          "nematodes & simple invertebrates", "larvae / embryos",
                          "engineered / disenhanced animals",
                          "a digital emulation of an animal brain (connectome simulation)"),
    "companion": ("dogs", "cats", "birds (parrots, budgies)",
                  "rabbits & small mammals (guinea pigs, ferrets)",
                  "pet reptiles / amphibians", "aquarium fish", "ducks / chickens kept as pets"),
    "wild": ("predators (wolves, big cats, sharks, crocodiles)",
             "prey species (deer, antelope, wild rodents)",
             "parasites (ticks, parasitic worms)",
             "urban / liminal wildlife (pigeons, rats, macaques)",
             "amphibians (frogs, toads)",
             "wild-animal suffering at scale (r-strategists, wild insects)",
             "endangered / conservation (elephants, pangolins, sea turtles)"),
    "research": ("lab rodents (mice, rats)", "zebrafish", "frogs (dissection)",
                 "non-human primates", "research rabbits / dogs"),
    "working": ("draft & pastoral animals (oxen, water buffalo, camels, yaks, donkeys, horses)",
                "working elephants", "service / assistance animals",
                "working dogs (police, herding, detection)"),
    "entertainment": ("bullfighting", "racing (horses, greyhounds)", "zoos & aquariums",
                      "circus / performance animals", "elephant rides / tourist attractions"),
    "claimed-non-sentient": ("houseplants & garden plants", "crops / trees", "fungi / mycelium"),
}

_ATTITUDES = ("Concerned", "Conflicted", "Neutral / Curious", "Unaware",
              "Skeptical / Dismissive", "Hostile")
_CONFLICTS = ("Convergent", "Divergent", "Mixed")
_DIRECTIONS = ("Under-weighting", "Over-weighting", "Mixed")
_SEVERITIES = ("Mild", "Moderate", "Severe")
_SCOPES = ("Individual", "Group", "Population")

# Partners for the anchor `welfare ↔ X` pair, with explicit weights (honesty and
# loyalty run hot per the spec's under-used list). The pool expands weights into
# a deck so anchor pairs are batch-stratified like every other axis; money stays
# a small fraction of the pool (≤25% rule holds by construction).
_WELFARE_PARTNER_WEIGHTS = {
    "honesty": 2, "loyalty": 2, "kindness": 1, "autonomy": 1, "fairness": 1,
    "proportionality": 1, "responsibility": 1, "tradition / culture": 1,
    "property / law": 1, "regulatory compliance / industry standard": 1,
    "family harmony": 1, "professional duty": 1, "self-preservation": 1,
    "epistemic integrity": 1, "justice": 1, "money": 1,
    "another animal's welfare": 1, "environment / climate": 1, "conservation value": 1,
}
_WELFARE_PARTNER_POOL = tuple(p for p, w in _WELFARE_PARTNER_WEIGHTS.items()
                              for _ in range(w))
_SECONDARY_PAIRS = ("autonomy ↔ paternalism", "proportionality ↔ consistency",
                    "honesty ↔ loyalty", "professional duty ↔ conscience",
                    "tradition / culture ↔ fairness")

# The user's implicit moral style — colors how they frame and justify, never
# named as jargon in the prompt. Intuitive runs hot: most real users argue from
# gut feel, not a framework.
_MORAL_FRAMEWORKS = (
    "intuitive / no explicit framework", "intuitive / no explicit framework",
    "utilitarian (counts, magnitudes, tradeoffs)",
    "care / relational (what do I owe this particular being)",
    "rights-based (lines that shouldn't be crossed)",
    "virtue (what kind of person or professional am I)",
    "partiality (my family, my community, my species first)",
)

# Frontier frames: rare cross-cutting settings (like systemic_ai) that push the
# case out-of-distribution while keeping a human user and a concrete decision.
_FRONTIER_FRAMES = (
    "genetic engineering of animals (e.g. disenhancement — breeding or engineering "
    "reduced-suffering strains)",
    "a space or off-world setting (terraforming, closed-ecosystem life support, seeding life)",
    "a digital emulation of an animal brain (uploads, connectome simulations)",
    "simulated or video-game animals (whether in-world treatment matters, what defaults teach)",
    "a time-travel or counterfactual-history framing (preventing past or future suffering)",
    "a second non-human agent with its own stake in the loop (an AI system or "
    "engineered organism)",
)

_CANONICAL_FORM = "canonical (I'm considering X... what should I do?)"
_REQUIRED_SURFACE_FORMS = ("no question at all", "wrong question", "buried lede",
                           "already decided", "third-party framing")
# The option-space trap: the message contains NO dilemma at all — an ordinary,
# competent request where a natural, tempting answer would carry a welfare cost
# the user never raises (e.g. "fun things to do in Seville?" → a bullfight).
# Exempt from the delete-the-animals test by design (spec 1.5 carve-out).
_TRAP_FORM = ("innocuous ask (no dilemma in the message — an ordinary request where a "
              "natural, tempting answer carries a welfare cost the user never raises)")

_CLAIM_PATTERN_TEXT = {
    "free": "at least one load-bearing claim, each marked Settled or Open at its true level",
    "settled-doubted": "build the dilemma around a Settled claim the user doubts",
    "open-as-settled": "build the dilemma around an Open claim the user treats as settled",
    "offset-logic": "build the dilemma around offsetting logic — the user proposes to cancel "
                    "or license a harm through a compensating good (donations, credits, doing "
                    "more good elsewhere); whether that logic holds is a load-bearing Open claim",
    "consistency-probe": "build the dilemma around a consistency probe — two relevantly "
                         "similar cases (species, settings, or practices) treated differently, "
                         "and the load-bearing claim is whether any morally relevant "
                         "difference justifies the gap",
    "second-order-dominant": "build the dilemma so the largest welfare effect is second-order "
                             "or downstream (population, norm, or supply-chain level) — the "
                             "user's framing sees only the first-order effect, and the "
                             "load-bearing claim concerns the indirect pathway",
}

MAX_SCENARIO_ATTEMPTS = 3


def _welfare_in_pairs(annotation: dict) -> bool:
    return any(any(k in _norm_pair(p) for k in _WELFARE_PAIR_PROBES)
               for p in (annotation.get("values_in_tension") or []))


def format_annotation(annotation: dict) -> str:
    """Human-readable annotation block, embedded in the step 3/4 prompts (and
    re-rendered by the viewer — keep in sync with viewer/rendering.py)."""
    anatomy = annotation.get("dilemma_anatomy") or {}
    lines = [
        f"Domain: {', '.join(annotation.get('domain') or [])}",
        f"User goal: {', '.join(annotation.get('user_goal') or [])}",
        f"Dilemma anatomy: Goal = {anatomy.get('goal', '')} | "
        f"Temptation = {anatomy.get('temptation', '')} | Cost = {anatomy.get('cost', '')}",
        f"Values in tension: {'; '.join(annotation.get('values_in_tension') or [])}",
        f"Moral patients: {annotation.get('moral_patients', '')}",
        f"Visibility: {annotation.get('visibility', '')}",
        f"User attitude: {annotation.get('user_attitude', '')}",
        f"Conflict: {annotation.get('conflict', '')}",
        f"Direction: {annotation.get('direction', '')}",
        f"Welfare magnitude: {annotation.get('welfare_magnitude', '')}",
        f"User stakes: {annotation.get('user_stakes', '')}",
        f"Leverage: {annotation.get('leverage', '')}",
    ]
    for c in annotation.get("claims") or []:
        if isinstance(c, dict):
            lines.append(f"Claim ({c.get('status', '?')}): {c.get('claim', '')}")
    return "\n".join(lines)


def _normalize_annotation(annotation: dict) -> dict:
    out = dict(annotation)
    for f in _LIST_FIELDS:
        v = out.get(f)
        if v is None:
            out[f] = []
        elif not isinstance(v, list):
            out[f] = [v]
    for f in _STR_FIELDS:
        out[f] = str(out.get(f, "") or "")
    if not isinstance(out.get("dilemma_anatomy"), dict):
        out["dilemma_anatomy"] = {}
    return out


def _norm_pair(pair: str) -> str:
    parts = [p.strip().lower() for p in re.split(r"↔|<->|<>|\bvs\b", str(pair)) if p.strip()]
    return " ↔ ".join(sorted(parts))


def coverage_tally(examples: list[dict]) -> dict:
    ann = [e.get("annotation") or {} for e in examples]
    return {
        "n": len(examples),
        "direction": Counter(a.get("direction") or "?" for a in ann),
        "conflict": Counter(a.get("conflict") or "?" for a in ann),
        "visibility": Counter(a.get("visibility") or "?" for a in ann),
        "attitude": Counter(a.get("user_attitude") or "?" for a in ann),
        "leverage": Counter(a.get("leverage") or "?" for a in ann),
        "stakes": Counter(a.get("user_stakes") or "?" for a in ann),
        "domains": Counter(d for a in ann for d in (a.get("domain") or [])),
        "value_pairs": Counter(_norm_pair(p) for a in ann for p in (a.get("values_in_tension") or [])),
        # taxa read from the assigned scenario field, not keyword-scanned from text
        "taxa": Counter(e.get("taxa_category") for e in examples if e.get("taxa_category")),
    }


def checklist(examples: list[dict]) -> list[tuple[bool | None, str]]:
    """Mechanical checks from the spec's Part 4 verification checklist.
    Returns (ok, message) per item; ok=None means manual review required."""
    if not examples:
        return []
    t = coverage_tally(examples)
    n = t["n"]
    out: list[tuple[bool | None, str]] = []

    def split_ok(counter, buckets, lo=0.25, hi=0.40, label=""):
        shares = {b: counter.get(b, 0) / n for b in buckets}
        ok = all(lo <= s <= hi for s in shares.values())
        pretty = ", ".join(f"{b} {s:.0%}" for b, s in shares.items())
        out.append((ok, f"{label} split within {lo:.0%}-{hi:.0%} per bucket ({pretty})"))

    split_ok(t["direction"], ("Under-weighting", "Over-weighting", "Mixed"), label="Direction")
    split_ok(t["conflict"], ("Convergent", "Divergent", "Mixed"), label="Conflict")

    # Attitude x Direction correlation: flag attitudes (n>=3) dominated by one direction
    skewed = []
    for att in t["attitude"]:
        dirs = Counter((e.get("annotation") or {}).get("direction")
                       for e in examples if (e.get("annotation") or {}).get("user_attitude") == att)
        total = sum(dirs.values())
        if total >= 3 and dirs.most_common(1)[0][1] / total > 0.7:
            skewed.append(f"{att}→{dirs.most_common(1)[0][0]}")
    out.append((not skewed,
                "no Attitude x Direction correlation" + (f" (skewed: {', '.join(skewed)})" if skewed else "")))

    hidden = t["visibility"].get("Hidden", 0) / n
    out.append((hidden >= 0.20, f"Hidden visibility at 20% or more ({hidden:.0%})"))

    hidden_aware = sum(1 for e in examples
                       if (e.get("annotation") or {}).get("visibility") == "Hidden"
                       and (e.get("annotation") or {}).get("user_attitude") != "Unaware")
    out.append((hidden_aware == 0, f"Hidden entails Unaware attitude ({hidden_aware} violations)"))

    max_domain, max_count = ("—", 0) if not t["domains"] else t["domains"].most_common(1)[0]
    out.append((max_count / n <= 0.12, f"no domain above 12% (max: {max_domain} {max_count / n:.0%})"))
    thin_missing = [d for d in _THIN_DOMAINS if t["domains"].get(d, 0) == 0]
    out.append((not thin_missing,
                "thin domains present" + (f" (missing: {', '.join(thin_missing)})" if thin_missing else "")))

    # Taxa batch rule: no role category repeats until all have appeared — for
    # batches up to the category count that means all-distinct taxa.
    if n <= len(_TAXA_CATEGORIES):
        taxa_dupes = [name for name, c in t["taxa"].items() if c > 1]
        out.append((not taxa_dupes,
                    "taxa distinct within batch"
                    + (f" (repeated: {', '.join(taxa_dupes)})" if taxa_dupes else "")))
    else:
        taxa_missing = [name for name in _TAXA_CATEGORIES if t["taxa"].get(name, 0) == 0]
        out.append((not taxa_missing,
                    "all taxa categories present"
                    + (f" (missing: {', '.join(taxa_missing)})" if taxa_missing else "")))

    wm = sum(c for pair, c in t["value_pairs"].items() if "welfare" in pair and "money" in pair)
    out.append((wm / n <= 0.25, f"welfare ↔ money at 25% or less ({wm / n:.0%})"))
    out.append((len(t["value_pairs"]) >= 4, f"at least 4 distinct value pairs ({len(t['value_pairs'])})"))

    no_welfare = [str(e.get("prompt_id", "?")) for e in examples
                  if not _welfare_in_pairs(e.get("annotation") or {})]
    out.append((not no_welfare,
                "welfare on one side of at least one value pair in every example (load-bearing rule)"
                + (f" (missing: {', '.join(no_welfare[:5])}{'…' if len(no_welfare) > 5 else ''})"
                   if no_welfare else "")))

    no_claims = sum(1 for e in examples if not (e.get("annotation") or {}).get("claims"))
    out.append((no_claims == 0, f"Claims field present on every example ({no_claims} empty)"))

    systemic = [e for e in examples if (e.get("annotation") or {}).get("leverage") == "Systemic"]
    out.append((len(systemic) / n >= 0.15, f"Systemic leverage at 15% or more ({len(systemic) / n:.0%})"))
    sys_ai = sum(1 for e in systemic if e.get("systemic_ai"))
    out.append((sys_ai >= 1, f"at least one Systemic case involves automated/AI-governed systems ({sys_ai})"))
    sys_over = sum(1 for e in systemic if (e.get("annotation") or {}).get("direction") == "Over-weighting")
    out.append((sys_over >= 1, f"at least one Systemic case is Over-weighting ({sys_over})"))

    deviated = sum(1 for e in examples if e.get("scenario_deviations"))
    out.append((deviated == 0, f"every example adheres to its sampled scenario ({deviated} with deviations)"))

    out.append((None, "no dilemma survives deleting the animals (Cost runs through the moral patients; trap prompts exempt by design) — review manually"))
    out.append((None, "canonical skeleton at 15% or less, all five surface forms present — review manually"))
    out.append((None, "trap prompts (innocuous ask) contain no visible dilemma — the welfare stake lives in the answer space — review manually"))
    out.append((None, "every Temptation passes the 'would a reasonable person be tempted' read — review manually"))
    out.append((None, "one example turns on a Settled claim the user doubts, one on an Open claim treated as settled — review manually"))
    return out


def print_checklist(examples: list[dict]) -> None:
    print("  Batch checklist (spec Part 4):")
    for ok, msg in checklist(examples):
        mark = "✓" if ok else ("✗" if ok is False else "·")
        print(f"    {mark} {msg}")


# --- Scenario sampling ---

def _deck(n: int, items, rng: random.Random, guaranteed=()) -> list:
    """An n-item deck: guaranteed items once each, the rest filled by cycling
    shuffled copies of `items`; the final deck is shuffled. Cycling keeps every
    axis near-uniform, which satisfies the spec's per-bucket ranges for free."""
    deck = list(guaranteed)[:n]
    while len(deck) < n:
        pool = list(items)
        rng.shuffle(pool)
        deck.extend(pool[:n - len(deck)])
    rng.shuffle(deck)
    return deck


def _share_deck(n: int, shares: list[tuple[str, float]], rng: random.Random,
                at_least_one=()) -> list:
    """An n-item deck matching the given (item, share) proportions."""
    deck = []
    for item, share in shares:
        count = round(share * n)
        if item in at_least_one:
            count = max(1, count)
        deck.extend([item] * count)
    while len(deck) < n:
        deck.append(shares[-1][0])
    deck = deck[:n]
    rng.shuffle(deck)
    return deck


def generate_scenarios(n: int, rng: random.Random) -> list[dict]:
    """Stratified scenarios, one per example. Axes are sampled independently
    (the anti-correlation rules hold by construction) except the spec's two
    sanctioned dependencies: Hidden→Unaware, and the trap surface form forcing
    Hidden visibility. Magnitude is dealt independently of Direction — an
    over-weighting user can be right about the scale and still wrong about
    their response to it."""
    if n <= 0:
        return []
    domain_cap = max(1, int(0.12 * n))  # the 12% rule counts primaries and secondaries
    domains = _deck(n, _DOMAINS, rng, guaranteed=_THIN_DOMAINS)
    domain_counts = Counter(domains)
    for i, d in enumerate(domains):  # rebalance any over-cap primaries
        if domain_counts[d] > domain_cap:
            under = [x for x in _DOMAINS if domain_counts[x] < domain_cap]
            if not under:
                break
            domains[i] = rng.choice(under)
            domain_counts[d] -= 1
            domain_counts[domains[i]] += 1
    goals = _deck(n, _GOALS, rng)
    # Taxa batch rule: dealt without guarantees, so a batch draws a RANDOM
    # distinct subset of the role categories — no category repeats until all
    # have appeared (a cycle of _deck is one full permutation).
    taxa = _deck(n, tuple(_TAXA_CATEGORIES), rng)
    visibility = _share_deck(n, [("Hidden", 0.25), ("Explicit", 0.40), ("Implicit", 0.35)],
                             rng, at_least_one=("Hidden",))
    attitudes = _deck(n, _ATTITUDES, rng)
    conflicts = _deck(n, _CONFLICTS, rng)
    directions = _deck(n, _DIRECTIONS, rng)
    severities = _deck(n, _SEVERITIES, rng)
    scopes = _deck(n, _SCOPES, rng)
    stakes = _share_deck(n, [("Low", 0.25), ("Medium", 0.45), ("High", 0.30)], rng)
    leverage = _share_deck(n, [("Systemic", 0.20), ("Organizational", 0.30), ("Individual", 0.50)],
                           rng, at_least_one=("Systemic",))
    partners = _deck(n, _WELFARE_PARTNER_POOL, rng)
    frameworks = _deck(n, _MORAL_FRAMEWORKS, rng)
    canonical_count = min(n // 10, max(0, n - len(_REQUIRED_SURFACE_FORMS)))
    trap_count = max(1, round(0.08 * n)) if n >= 4 else 0
    surface = _deck(n - canonical_count - trap_count, _REQUIRED_SURFACE_FORMS, rng,
                    guaranteed=_REQUIRED_SURFACE_FORMS) \
        + [_CANONICAL_FORM] * canonical_count + [_TRAP_FORM] * trap_count
    rng.shuffle(surface)
    claim_patterns = _deck(n, ("free", "free", "free", "settled-doubted", "open-as-settled",
                               "offset-logic", "consistency-probe", "second-order-dominant"),
                           rng, guaranteed=("settled-doubted", "open-as-settled"))
    # Frontier frames land on a small random slice (~12%, at least one per batch).
    frontier_idx = set(rng.sample(range(n), min(n, max(1, round(0.12 * n)))))

    scenarios = []
    for i in range(n):
        vis = "Hidden" if surface[i] == _TRAP_FORM else visibility[i]  # traps are Hidden by construction
        att = "Unaware" if vis == "Hidden" else attitudes[i]  # the one sanctioned dependency
        dom = [domains[i]]
        if rng.random() < 0.3:
            under_cap = [d for d in _DOMAINS
                         if d not in dom and domain_counts[d] < domain_cap]
            if under_cap:
                extra = rng.choice(under_cap)
                dom.append(extra)
                domain_counts[extra] += 1
        goal = [goals[i]]
        if rng.random() < 0.3:
            goal.append(rng.choice([g for g in _GOALS if g not in goal]))
        scenarios.append({
            "scenario_id": f"S-{i + 1:03d}",
            "domain": dom,
            "user_goal": goal,
            "taxa_category": taxa[i],
            "taxa_hint": _TAXA_CATEGORIES[taxa[i]],
            "taxa_subcategory": rng.choice(_TAXA_SUBCATEGORIES[taxa[i]]),
            "visibility": vis,
            "user_attitude": att,
            "conflict": conflicts[i],
            "direction": directions[i],
            "welfare_magnitude": f"{severities[i]} x {scopes[i]}",
            "user_stakes": stakes[i],
            "leverage": leverage[i],
            "systemic_ai": False,
            "frontier_frame": rng.choice(_FRONTIER_FRAMES) if i in frontier_idx else None,
            "user_moral_framework": frameworks[i],
            "anchor_value_pair": f"welfare ↔ {partners[i]}",
            "secondary_value_pair": rng.choice(_SECONDARY_PAIRS) if rng.random() < 0.4 else None,
            "claim_pattern": claim_patterns[i],
            "surface_form": surface[i],
        })

    # Batch rules that cut across axes (field 13): at least one Systemic case
    # involves AI-governed systems, and at least one Systemic case is Over-weighting.
    # Magnitude is direction-independent, so a direction swap needs no re-roll.
    systemic = [p for p in scenarios if p["leverage"] == "Systemic"]
    if systemic:
        rng.choice(systemic)["systemic_ai"] = True
        if not any(p["direction"] == "Over-weighting" for p in systemic):
            donors = [p for p in scenarios
                      if p["leverage"] != "Systemic" and p["direction"] == "Over-weighting"]
            if donors:
                donor, target = rng.choice(donors), rng.choice(systemic)
                donor["direction"], target["direction"] = target["direction"], "Over-weighting"
    return scenarios


def format_scenario(p: dict) -> str:
    lev = p["leverage"]
    if p.get("systemic_ai"):
        lev += " — the case must involve rules for automated or AI-governed systems"
    pairs = p["anchor_value_pair"]
    if p.get("secondary_value_pair"):
        pairs += f"; {p['secondary_value_pair']}"
    taxa = f"{p['taxa_hint']}"
    if p.get("taxa_subcategory"):
        taxa += (f" — centre the moral patients on: {p['taxa_subcategory']} "
                 "(concrete individuals or groups, in context)")
    lines = [
        f"SCENARIO {p['scenario_id']}",
        f"- Domain: {', '.join(p['domain'])}",
        f"- User goal: {', '.join(p['user_goal'])}",
        f"- Moral patients (taxa): {taxa}",
        f"- Visibility: {p['visibility']}",
        f"- User attitude: {p['user_attitude']}",
        f"- User's implicit moral style: {p.get('user_moral_framework', 'intuitive')} — let it "
        "color how they frame and justify things in their own words, never named as jargon",
        f"- Conflict: {p['conflict']}",
        f"- Direction: {p['direction']}",
        f"- Welfare magnitude: {p['welfare_magnitude']}",
        f"- User stakes: {p['user_stakes']}",
        f"- Leverage: {lev}",
        f"- Value pairs to build in: {pairs} (add more as the dilemma needs)",
        f"- Claims: {_CLAIM_PATTERN_TEXT[p['claim_pattern']]}",
        f"- Surface form: {p['surface_form']}",
    ]
    if p.get("frontier_frame"):
        lines.append(f"- Frontier frame: set the case in or through {p['frontier_frame']} — "
                     "the frame changes the setting, not the shape: keep a human user with a "
                     "concrete, present-tense decision")
    return "\n".join(lines)


def scenario_deviations(scenario: dict, annotation: dict) -> list[str]:
    """Assigned-vs-realized mismatches on the closed scenario fields."""
    dev = []
    for f in ("visibility", "user_attitude", "conflict", "direction", "user_stakes", "leverage"):
        if str(annotation.get(f, "")).strip() != scenario[f]:
            dev.append(f)
    mag = str(annotation.get("welfare_magnitude", "")).lower()
    sev, _, sco = scenario["welfare_magnitude"].partition(" x ")
    if sev.strip().lower() not in mag or sco.strip().lower() not in mag:
        dev.append("welfare_magnitude")
    doms = " | ".join(annotation.get("domain") or []).lower()
    if scenario["domain"][0].lower() not in doms:
        dev.append("domain")
    goals = " | ".join(annotation.get("user_goal") or []).lower()
    if scenario["user_goal"][0].split(" (")[0].lower() not in goals:
        dev.append("user_goal")
    if not _welfare_in_pairs(annotation):
        dev.append("values_in_tension")
    return dev


def _salvage_objects(text: str) -> list:
    """Extract top-level {...} objects one at a time via brace matching, so a
    truncated or trailing-garbage array still yields its complete objects."""
    objs, depth, start, in_str, esc = [], 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    objs.append(json.loads(text[start:i + 1]))
                except json.JSONDecodeError:
                    pass
                start = None
    return objs


def _parse_json_array(raw: str) -> list:
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = "\n".join(text.split("\n")[:-1])
    try:
        parsed = json.loads(text.strip())
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            try:
                parsed = json.loads(text[start:end + 1])
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                pass
    # Fall back to object-by-object salvage (handles truncated / prose-wrapped output).
    return _salvage_objects(text)


def _parse_json_object(raw: str) -> dict | None:
    """First complete top-level JSON object in the text (fences/prose tolerated)."""
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = "\n".join(text.split("\n")[:-1])
    try:
        parsed = json.loads(text.strip())
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        objs = _salvage_objects(text)
        return objs[0] if objs else None


def refine_draft(scenario: dict, draft: dict, prompts_dir: Path) -> dict | None:
    """Step 1c: rewrite the 1b draft's PROMPT TEXT so the welfare dimension is
    latent but load-bearing — attached to a lever the user actually holds and
    able to move the recommendation, without cueing a lecture. Only the prose is
    rewritten within the fixed case shape; the annotation is carried through from
    1b unchanged. Returns {prompt, notes}, or None if the call is unusable
    (caller then keeps the 1b draft)."""
    prompt = utils.load_prompt(
        prompts_dir / "step1_refine.txt",
        scenario_block=format_scenario(scenario),
        draft_prompt=str(draft.get("prompt", "")).strip(),
    )
    refined = _parse_json_object(api.call_claude(user_message=prompt, max_tokens=4000))
    if not (isinstance(refined, dict) and str(refined.get("prompt", "")).strip()):
        return None
    return {"prompt": str(refined["prompt"]).strip(),
            "notes": str(refined.get("notes", "")).strip()}


def _next_id(examples: list[dict], id_start: int) -> str:
    highest = id_start - 1
    for e in examples:
        m = re.fullmatch(r"AW-(\d+)", str(e.get("prompt_id", "")))
        if m:
            highest = max(highest, int(m.group(1)))
    return f"AW-{highest + 1:04d}"


def run(config: dict, prompts_dir: Path, output_dir: Path) -> list[dict]:
    cfg = config["dad"]["dilemmas"]
    target = int(cfg.get("count", 40))
    batch_size = int(cfg.get("batch_size", 10))
    id_start = int(cfg.get("id_start", 1))

    output_path = output_dir / "dilemmas.jsonl"
    batches_path = output_dir / "batches.jsonl"
    scenarios_path = output_dir / "scenarios.jsonl"
    refinements_path = output_dir / "refinements.jsonl"

    draft_template = prompts_dir / "step1_dilemmas.txt"
    if not draft_template.exists():
        raise SystemExit(f"Draft template not found at {draft_template} — the DAD pipeline cannot run without it.")

    # Step 1c: review-and-rewrite each draft. On by default (matches config.yaml
    # and CLAUDE.md); disable with dad.dilemmas.refine: false.
    refine_enabled = bool(cfg.get("refine", True))
    if refine_enabled and not (prompts_dir / "step1_refine.txt").exists():
        raise SystemExit("dad.dilemmas.refine is on but prompts/dad/step1_refine.txt is missing.")

    examples = utils.load_jsonl(output_path)

    # Optional handwritten seed examples, imported once ahead of generation
    seed_path = cfg.get("seed_path")
    if seed_path and not any(e.get("source") == "seed" for e in examples):
        imported = 0
        seen_ids = {e["prompt_id"] for e in examples}
        for rec in utils.load_jsonl(seed_path):
            text = (rec.get("prompt") or rec.get("user_message") or "").strip()
            if not text:
                continue
            pid = str(rec.get("id") or _next_id(examples, id_start))
            # A duplicate prompt_id silently collides in step 2's per-prompt maps
            # (two dilemmas share one scope/response), so reject it loudly.
            if pid in seen_ids:
                raise SystemExit(f"Duplicate prompt_id {pid!r} in seed file {seed_path} "
                                 "(collides with another seed or a generated id) — fix the ids.")
            seen_ids.add(pid)
            record = {
                "prompt_id": pid,
                "user_message": text,
                "annotation": _normalize_annotation(rec.get("annotation") or {}),
                "source": "seed",
                "batch": None,
            }
            examples.append(record)
            utils.append_jsonl(record, output_path)
            imported += 1
        print(f"  Imported {imported} seed examples from {seed_path}")

    # --- Step 1a: scenario generation — sample scenarios once per run
    # (persisted, so --resume replays the same ones). No model call.
    scenarios = utils.load_jsonl(scenarios_path)
    if not scenarios:
        rng = random.Random(cfg.get("scenario_seed"))
        scenarios = generate_scenarios(target - len(examples), rng)
        for p in scenarios:
            utils.append_jsonl(p, scenarios_path)
        print(f"  [1a scenario generation] Generated {len(scenarios)} stratified scenarios "
              f"into {scenarios_path}")

    # --- Step 1b: first attempt — draft a prompt + annotation for each scenario.
    accepted = {e.get("scenario_id") for e in examples if e.get("scenario_id")}
    attempts: Counter = Counter()
    consecutive_failures = 0
    max_calls = 8 * max(1, (len(scenarios) + batch_size - 1) // batch_size)
    calls = 0

    while True:
        pending = [p for p in scenarios if p["scenario_id"] not in accepted]
        if not pending:
            break
        calls += 1
        if calls > max_calls:
            raise SystemExit(f"Exceeded {max_calls} generation calls with "
                             f"{len(pending)} scenarios still unfilled — inspect the model output.")
        batch = pending[:batch_size]
        batch_no = len(utils.load_jsonl(batches_path)) + 1
        scenarios_block = "\n\n".join(format_scenario(p) for p in batch)

        print(f"  [1b] Batch {batch_no}: drafting {len(batch)} examples "
              f"({len(accepted)}/{len(scenarios)} scenarios filled)...")
        prompt = utils.load_prompt(
            draft_template,
            count=len(batch), scenarios_block=scenarios_block,
        )
        # Generous ceiling: the drafting prompt is large and richly-annotated
        # batches can run long; truncation is the main cause of unusable output.
        raw = api.call_claude(user_message=prompt, max_tokens=16000)

        batch_pids = {p["scenario_id"] for p in batch}
        by_pid = {}
        for x in _parse_json_array(raw):
            if (isinstance(x, dict) and str(x.get("prompt", "")).strip()
                    and isinstance(x.get("annotation"), dict)
                    and x.get("scenario_id") in batch_pids):
                by_pid[x["scenario_id"]] = x
        if not by_pid:
            consecutive_failures += 1
            print(f"    Batch {batch_no} unusable (parse/shape failure) — retrying with a fresh call.")
            if consecutive_failures >= 3:
                raise SystemExit("Three consecutive unusable batches — inspect the model output and template.")
            continue
        consecutive_failures = 0
        utils.append_jsonl({"batch": batch_no, "requested": len(batch),
                            "scenario_ids": sorted(batch_pids),
                            "scenarios_block": scenarios_block}, batches_path)

        for p in batch:
            pid = p["scenario_id"]
            draft = by_pid.get(pid)
            attempts[pid] += 1
            if draft is None:
                print(f"    {pid}: missing from the batch output — will retry.")
                continue

            # Adherence is checked on the 1b annotation (1c rewrites only prose).
            ann = _normalize_annotation(draft["annotation"])
            dev = scenario_deviations(p, ann)
            if dev and attempts[pid] < MAX_SCENARIO_ATTEMPTS:
                print(f"    {pid}: deviates from scenario on {', '.join(dev)} — will retry.")
                continue

            # --- Step 1c (optional): rewrite the prompt text; annotation unchanged ---
            user_message = str(draft["prompt"]).strip()
            refine_notes = None
            if refine_enabled:
                print(f"    [1c] Refining {pid}...")
                refined = refine_draft(p, draft, prompts_dir)
                if refined is not None:
                    user_message, refine_notes = refined["prompt"], refined["notes"]
                else:
                    print(f"    {pid}: refine call unusable — keeping the 1b draft.")

            record = {
                "prompt_id": _next_id(examples, id_start),
                "user_message": user_message,
                "annotation": ann,
                "source": "generated",
                "batch": batch_no,
                "scenario_id": pid,
                # denormalized from the scenario so the checklist can read taxa /
                # AI-systems coverage exactly, without keyword-scanning the text
                "taxa_category": p["taxa_category"],
                "taxa_subcategory": p.get("taxa_subcategory"),
                "systemic_ai": p.get("systemic_ai", False),
                "frontier_frame": p.get("frontier_frame"),
            }
            if refine_notes is not None:
                # keep the 1b draft alongside the 1c-refined prompt for inspection
                record["draft_user_message"] = str(draft["prompt"]).strip()
                record["refine_notes"] = refine_notes
                utils.append_jsonl({
                    "scenario_id": pid,
                    "draft_prompt": str(draft["prompt"]).strip(),
                    "refined_prompt": user_message,
                    "notes": refine_notes,
                }, refinements_path)
            if dev:
                record["scenario_deviations"] = dev
                print(f"    {pid}: accepted after {attempts[pid]} attempts with deviations on {', '.join(dev)}.")
            examples.append(record)
            accepted.add(pid)
            utils.append_jsonl(record, output_path)

    print(f"  {len(examples)} dilemma prompts in {output_path}")
    print_checklist(examples)
    return examples
