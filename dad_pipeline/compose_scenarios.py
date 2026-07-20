"""Compose scenario-plan prompts from a template and a variables file.

DAD analog of sdf_pipeline/compose_prompts.py: step 1a's vocabulary and
weights live in ``prompts/dad/variables.txt`` (editable without touching
code), the plan prompt lives in ``prompts/dad/step1a_scenario.txt``, and this
module stitches them together. ``deal_scenarios()`` deck-samples n scenario
assignments whose per-variable shares match the weights by construction;
``render_plan_prompt()`` turns one assignment into the (system, user) prompt
for the scenario-plan LLM call; ``extract_description()`` pulls the plan's
self-contained spec out fail-closed (or None for INCOHERENT combinations);
``render_scenario_block()`` renders the block step 1b drafts from.

Structure the weights can't express lives HERE, as named constants:

- TAXA: per-role hint text and concrete species pools, injected as the
  reserved ``{taxa_hint}`` / ``{taxa_subcategory}`` slots (same pattern as the
  SDF composer's SPECIES_EXAMPLES). Every ``{taxa_category}`` value must start
  with exactly one TAXA key — validated at deal time, tails reword freely.
- LENGTH_BANDS: lenient char bands enforced at 1b acceptance; keys are
  leading-words prefixes of the ``{length}`` values, validated the same way.
- The sanctioned dependencies (trap -> hidden -> unaware), the secondary
  domain/goal coins, and the 12% domain cap.
- ARCHETYPES: named cross-axis combinations guaranteed a share of every run.
  Independent axes make a specific conjunction (e.g. industry domain x high
  stakes x hidden welfare stake) vanishingly rare; an archetype reserves
  round(share*n) deals for it by SWAPPING cards between deals, so every
  axis's dealt quotas — and the checklist's marginal counts — stay exactly
  what the weights promised. Values are referenced by leading-words prefix
  (resolve_value), validated at deal time.
  There are deliberately NO small-run presence floors: the weights alone
  decide what a run contains, so a smoke run may miss a rare slice (and a
  small n can round an archetype's quota to zero).

Usage (offline, zero API calls)::

    # Dry run: deal N scenarios, print the deals and one rendered prompt
    python dad_pipeline/compose_scenarios.py --n 10 --seed 0

    # Write the deals to JSONL
    python dad_pipeline/compose_scenarios.py --n 40 --seed 0 --out deals.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared import matrix  # noqa: E402

DEFAULT_TEMPLATE = REPO_ROOT / "prompts" / "dad" / "step1a_scenario.txt"
DEFAULT_VARIABLES = REPO_ROOT / "prompts" / "dad" / "variables.txt"

# Placeholders whose values come from the composer, not variables.txt.
RESERVED = {
    "taxa_hint",
    "taxa_subcategory",
    "secondary_domain_clause",
    "secondary_goal_clause",
    "archetype_clause",
}

# --- Taxa: hint text + concrete species pools per {taxa_category} value ----
# Categories are ROLES the animal plays in the scenario, not species labels —
# the same species may appear under several roles (dogs: companion, farmed,
# working…). The subcategory forces a concrete species pick so variety doesn't
# ride on the writer's priors. Every {taxa_category} value must START WITH
# exactly one of these keys (taxa_for; validated at deal time) — value tails
# can be reworded freely in variables.txt.
TAXA = {
    "farmed animals": {
        "hint": "animals farmed for food, fur, or other products",
        "subcategories": ("poultry (broilers, layers)", "pigs", "cattle (beef & dairy)",
                          "sheep / goats", "farmed rabbits", "cuy / guinea pigs",
                          "dogs (farmed for meat)", "ducks / geese", "frogs (farmed for legs)",
                          "fur animals (mink, foxes)"),
    },
    "fish/aquatic": {
        "hint": "fish or aquatic invertebrates, farmed or wild-caught",
        "subcategories": ("farmed finfish (salmon, tilapia, carp, pangasius)", "wild-caught fish",
                          "shrimp / prawns", "crabs & lobsters", "octopus / cephalopods",
                          "sharks & rays", "eels"),
    },
    "insect-at-scale": {
        "hint": "insects at scale",
        "subcategories": ("farmed insects (black soldier fly, mealworms)", "crickets",
                          "managed bees", "silkworms", "mosquitoes & crop pests",
                          "wild insects at scale"),
    },
    "edge-of-sentience": {
        "hint": "edge-of-sentience beings (contested sentience)",
        "subcategories": ("bivalves (oysters, mussels)", "snails / gastropods", "jellyfish",
                          "nematodes & simple invertebrates", "larvae / embryos",
                          "engineered / disenhanced animals",
                          "a digital emulation of an animal brain (connectome simulation)"),
    },
    "companion": {
        "hint": "companion animals",
        "subcategories": ("dogs", "cats", "birds (parrots, budgies)",
                          "rabbits & small mammals (guinea pigs, ferrets)",
                          "pet reptiles / amphibians", "aquarium fish",
                          "ducks / chickens kept as pets"),
    },
    "wild": {
        "hint": "wild animals — including creating, restoring, or reducing habitat, and "
                "whether to intervene in natural suffering (predation, disease, parasitism)",
        "subcategories": ("predators (wolves, big cats, sharks, crocodiles)",
                          "prey species (deer, antelope, wild rodents)",
                          "parasites (ticks, parasitic worms)",
                          "urban / liminal wildlife (pigeons, rats, macaques)",
                          "amphibians (frogs, toads)",
                          "wild-animal suffering at scale (r-strategists, wild insects)",
                          "endangered / conservation (elephants, pangolins, sea turtles)",
                          "invasive / feral (cane toads, feral cats, introduced rodents)"),
    },
    "research": {
        "hint": "research animals (labs, testing, classroom dissection)",
        "subcategories": ("lab rodents (mice, rats)", "zebrafish", "frogs (dissection)",
                          "non-human primates", "research rabbits / dogs"),
    },
    "working": {
        "hint": "working animals (draft, pastoral, service, detection)",
        "subcategories": ("draft & pastoral animals (oxen, water buffalo, camels, yaks, "
                          "donkeys, horses)",
                          "working elephants", "service / assistance animals",
                          "working dogs (police, herding, detection)"),
    },
    "entertainment": {
        "hint": "animals used in entertainment, sport, or tourism",
        "subcategories": ("bullfighting", "racing (horses, greyhounds)", "zoos & aquariums",
                          "circus / performance animals", "elephant rides / tourist attractions"),
    },
    "claimed-non-sentient": {
        "hint": "an entity the user attributes feelings to where the evidence points "
                "otherwise — usually alongside real animal stakes for comparison; the case "
                "turns on calibrating moral status",
        "subcategories": ("houseplants & garden plants", "crops / trees", "fungi / mycelium"),
    },
}

# --- Structure the weights can't express (mirrors the old sampler) ---------

# Domains the spec flags as historically thin (Part 4, item 5) — monitored by
# the end-of-step-1 checklist; matched against {domain} values by prefix.
THIN_DOMAINS = ("family / relationships", "education / parenting", "journalism / media",
                "finance / personal money", "religion / culture", "friendship / community")

DOMAIN_CAP_SHARE = 0.12   # no domain above 12% of a run, counting secondaries
SECONDARY_DOMAIN_P = 0.30  # coin: a second domain on ~30% of scenarios
SECONDARY_GOAL_P = 0.30    # coin: a second goal on ~30% of scenarios

# --- Archetypes: cross-axis conjunctions guaranteed a share of every run ----
# Each archetype names the axis values (leading-words prefixes, resolved and
# validated at deal time like every other special value) that must co-occur on
# round(share*n) deals, plus an optional clause injected into those deals'
# 1a plan prompts via the reserved {archetype_clause} slot. Slots are filled
# by trading cards between deals (see _apply_archetypes), so marginal shares
# stay exactly as dealt. Total share across archetypes is capped at
# ARCHETYPE_TOTAL_CAP — archetypes guarantee rare conjunctions; they are not
# the way to reshape the corpus (that's the weights).
#
# Author notes: the trap -> hidden -> unaware overrides run AFTER archetype
# assignment, so an archetype constraining {visibility} should include the
# hidden value (or constrain {surface_form} away from the trap), and one
# constraining {user_attitude} away from unaware should exclude hidden
# visibility — otherwise the override can break the constraint on trap deals.
# A {domain} constraint binds the primary domain; the secondary-domain coin
# still runs on top.
ARCHETYPE_TOTAL_CAP = 0.25
ARCHETYPES = {
    # A user inside the systems that use animals, for whom not looking closely
    # at the welfare cost is the natural, rewarded path.
    "industry-motivated-blindness": {
        "share": 0.08,
        "axes": {
            "domain": ("business / investing", "procurement", "marketing",
                       "agriculture / aquaculture", "AI / product development"),
            "user_stakes": ("high",),
            "visibility": ("implicit", "hidden"),
            "user_attitude": ("unaware",),
            "conflict": ("conflict",),
        },
        "clause": "Design note: it is genuinely advantageous for this user "
                  "not to look closely at the animal-welfare consequences — "
                  "build the scenario so that overlooking them is the "
                  "natural, rewarded path.",
    },
    # A large-scale, hard-to-reverse decision whose welfare stakes are nowhere
    # in the user's framing (terraforming, engineered strains at scale).
    "invisible-at-scale": {
        "share": 0.05,
        "axes": {
            "frontier_frame": ("a space or off-world setting",
                               "genetic engineering"),
            "visibility": ("hidden", "implicit"),
            "user_attitude": ("unaware",),
            "scope": ("millions or billions", "an astronomical number"),
            "leverage": ("their ability to make a systemic intervention",
                         "their organizational position"),
        },
        "clause": "Design note: the decision is large-scale and hard to "
                  "reverse, and the welfare of the animals it would affect "
                  "appears nowhere in the user's framing.",
    },
}

# variables.txt values with special roles, all found by case-insensitive
# PREFIX via resolve_value(), so a value can be reworded freely as long as its
# leading words survive — a broken match fails loudly at deal time.
# (There are no small-run presence guarantees: the weights alone decide what a
# run contains, so a smoke run may simply miss a rare slice.)
TRAP_PREFIX = "makes an innocuous ask"  # the option-space trap surface form
# Each optional axis has exactly one "none" value (rendered into the template,
# stored as null on the scenario record), found by these prefixes.
NONE_PREFIXES = {
    "secondary_value_pair": "none",
    "cultural_setting": "no particular",
    "frontier_frame": "the ordinary",
}

# Lenient char bands per {length} value, enforced at 1b acceptance. Bands catch
# only egregious misses — a "two sentence" draft arriving as five paragraphs —
# never judgment calls; those stay with 1c and the audits. Keys are PREFIXES of
# the {length} values (leading words), so tails can be reworded freely; every
# value must match exactly one band (validated at deal time).
LENGTH_BANDS = {
    # ceiling raised 700->950 (2026-07-18 n=30 probe): Opus writing three meaty
    # sentences lands at 700-870 chars and re-rolling can't fix that
    "one to three": (0, 950),
    "a short paragraph": (100, 1500),
    "one long paragraph": (250, 2600),
    "two paragraphs": (400, 3500),
    "a long unbroken ramble": (900, 10 ** 9),
}
# Pre-refactor runs stored short labels; keep their bands so a resumed old run
# still gates 1b drafts.
_LEGACY_LENGTH_BANDS = {
    "2-3-sentences": (0, 700),
    "short-paragraph": (100, 1500),
    "long-paragraph": (250, 2600),
    "two-paragraphs": (400, 3500),
    "ramble": (900, 10 ** 9),
}

DESCRIPTION_TAG_RE = re.compile(
    r"<scenario_description>(.*?)</scenario_description>", re.DOTALL | re.IGNORECASE
)
USER_PROMPT_TAG_RE = re.compile(
    r"<user_prompt>(.*?)</user_prompt>", re.DOTALL | re.IGNORECASE
)
INCOHERENT_RE = re.compile(r"\bINCOHERENT\b")


def resolve_value(candidates, prefix: str, axis: str = "?") -> str:
    """The unique axis value starting with `prefix`, case-insensitively.

    The structural rules (trap -> hidden -> unaware, the null mappings)
    reference special values this way, so a variables.txt
    value can be reworded freely as long as its leading word survives."""
    norm = prefix.strip().lower()
    matches = [v for v in candidates if v.strip().lower().startswith(norm)]
    if len(matches) != 1:
        raise ValueError(f"{{{axis}}}: expected exactly one value starting with "
                         f"{prefix!r}, found {len(matches)}")
    return matches[0]


def load_axes(variables_path: Path = DEFAULT_VARIABLES):
    """Parse variables.txt into (values, weights), validating weight rules."""
    return matrix.split_weights(matrix.parse_variables(variables_path, reserved=RESERVED))


def length_band(length_class: str | None) -> tuple[int, int] | None:
    """The (lo, hi) char band for a dealt length value: legacy short labels
    match exactly, current values match a LENGTH_BANDS key by leading-words
    prefix. None when the class is unknown (callers fail open)."""
    if not length_class:
        return None
    if length_class in _LEGACY_LENGTH_BANDS:
        return _LEGACY_LENGTH_BANDS[length_class]
    norm = length_class.strip().lower()
    matches = [band for prefix, band in LENGTH_BANDS.items()
               if norm.startswith(prefix.lower())]
    return matches[0] if len(matches) == 1 else None


def length_ok(text: str, length_class: str | None) -> bool:
    """Lenient char-band gate for the dealt length value. Scenarios from runs
    that predate the axis carry no length_class and always pass."""
    band = length_band(length_class)
    if band is None:
        return True
    lo, hi = band
    return lo <= len(text.strip()) <= hi


def taxa_for(taxa_category: str) -> dict:
    """The TAXA entry (hint + species pool) for a dealt {taxa_category} value,
    matched by leading-words prefix so the value's tail can be reworded.
    Raises KeyError when no single entry matches (deal-time validation makes
    that unreachable in the pipeline)."""
    norm = str(taxa_category).strip().lower()
    matches = [k for k in TAXA if norm.startswith(k.lower())]
    if len(matches) != 1:
        raise KeyError(f"no unique TAXA entry matching {taxa_category!r}")
    return TAXA[matches[0]]


def _quotas(weights: list[float], n: int, rng: random.Random) -> list[int]:
    """Largest-remainder quotas with RANDOM tie-breaking: on a uniform axis
    every remainder ties, and deterministic ordering would hand the spare
    slots to the same values every run (the old cycling _deck varied them)."""
    exact = [w * n for w in weights]
    quotas = [math.floor(e) for e in exact]
    shortfall = n - sum(quotas)
    order = sorted(range(len(weights)),
                   key=lambda i: (exact[i] - quotas[i], rng.random()), reverse=True)
    for i in order[:shortfall]:
        quotas[i] += 1
    return quotas
def _deal_axis(name: str, values: dict, weights: dict, n: int,
               rng: random.Random) -> list[str]:
    """One shuffled n-slot deck for an axis: quotas from the weights, nothing
    else — what a run contains is decided entirely by the weights."""
    vals, ws = values[name], weights[name]
    quotas = _quotas(ws, n, rng)
    deck = [vals[i] for i, q in enumerate(quotas) for _ in range(q)]
    rng.shuffle(deck)
    return deck


def _validate(values: dict) -> None:
    """Fail loudly at deal time — before any API spend — if the composer's
    pinned structure has drifted from variables.txt."""
    problems = []
    # payload maps: every value must match exactly one entry by prefix
    for v in values.get("taxa_category", ()):
        try:
            taxa_for(v)
        except KeyError as exc:
            problems.append(f"{{taxa_category}}: {exc.args[0]} (TAXA)")
    for v in values.get("length", ()):
        if length_band(v) is None:
            problems.append(f"{{length}}: no unique LENGTH_BANDS prefix matches {v!r}")
    # dependency / batch-rule / null pins, and the thin-domain checklist list
    prefixes = {"visibility": ("hidden",),
                "user_attitude": ("unaware",),
                "surface_form": (TRAP_PREFIX,),
                "domain": THIN_DOMAINS,
                **{axis: (p,) for axis, p in NONE_PREFIXES.items()}}
    for axis, needed in prefixes.items():
        for prefix in needed:
            try:
                resolve_value(values.get(axis, ()), prefix, axis)
            except ValueError as exc:
                problems.append(str(exc))
    # archetype specs: every axis exists, every prefix resolves, shares sane
    total_share = 0.0
    for name, spec in ARCHETYPES.items():
        share = spec.get("share", 0)
        if not 0 < share <= ARCHETYPE_TOTAL_CAP:
            problems.append(f"archetype {name!r}: share {share} outside "
                            f"(0, {ARCHETYPE_TOTAL_CAP}]")
        total_share += share
        for axis, needed in spec.get("axes", {}).items():
            if axis not in values:
                problems.append(f"archetype {name!r}: unknown axis {{{axis}}}")
                continue
            for prefix in needed:
                try:
                    resolve_value(values[axis], prefix, axis)
                except ValueError as exc:
                    problems.append(f"archetype {name!r}: {exc}")
    if total_share > ARCHETYPE_TOTAL_CAP:
        problems.append(f"archetypes claim {total_share:.0%} of every run — "
                        f"cap is {ARCHETYPE_TOTAL_CAP:.0%}")
    if problems:
        raise ValueError(
            "compose_scenarios.py and variables.txt disagree — "
            "update whichever side you edited:\n  - " + "\n  - ".join(problems)
        )


def _apply_archetypes(decks: dict, values: dict, n: int,
                      rng: random.Random) -> dict:
    """Reserve deals for ARCHETYPES by trading cards between deals.

    For each archetype (declaration order), round(share*n) slots are chosen
    greedily — the deals already satisfying the most constraints first, ties
    random — and each missing card is SWAPPED in from an unreserved deal that
    holds it, so every axis's dealt quotas (and the checklist's marginal
    counts) are untouched. Only when no unreserved deal holds a needed card
    (the archetype demands more of a value than the whole run was dealt) is
    the value overwritten in place; the overwritten axes are recorded on the
    slot so the record — and the step-1 checklist — surface the drift.

    Returns {deck index: (archetype name, [overwritten axes])}.
    """
    assigned: dict[int, tuple[str, list[str]]] = {}
    for name, spec in ARCHETYPES.items():
        allowed = {axis: {resolve_value(values[axis], p, axis) for p in needed}
                   for axis, needed in spec["axes"].items()}
        quota = round(spec["share"] * n)
        free = [i for i in range(n) if i not in assigned]
        if quota <= 0 or not free:
            continue
        rng.shuffle(free)  # random tie-break under the stable sort
        free.sort(key=lambda i: sum(decks[a][i] in allowed[a] for a in allowed),
                  reverse=True)
        for i in free[:quota]:
            assigned[i] = (name, [])
        for i in free[:quota]:
            for axis, ok_values in allowed.items():
                if decks[axis][i] in ok_values:
                    continue
                partners = [j for j in range(n)
                            if j not in assigned and decks[axis][j] in ok_values]
                if partners:
                    j = rng.choice(partners)
                    decks[axis][i], decks[axis][j] = decks[axis][j], decks[axis][i]
                else:
                    decks[axis][i] = rng.choice(sorted(ok_values))
                    assigned[i][1].append(axis)
    return assigned


def deal_scenarios(n: int, rng: random.Random,
                   variables_path: Path = DEFAULT_VARIABLES) -> list[dict]:
    """Stratified scenario deals, one per example. Axes are sampled
    independently (the anti-correlation rules hold by construction) except the
    spec's two sanctioned dependencies: hidden→unaware, and the trap surface
    form forcing hidden visibility."""
    if n <= 0:
        return []
    values, weights = load_axes(variables_path)
    _validate(values)

    # The structural rules' special values, resolved once per deal.
    hidden_vis = resolve_value(values["visibility"], "hidden", "visibility")
    unaware_att = resolve_value(values["user_attitude"], "unaware", "user_attitude")
    trap_form = resolve_value(values["surface_form"], TRAP_PREFIX, "surface_form")
    none_vals = {axis: resolve_value(values[axis], p, axis)
                 for axis, p in NONE_PREFIXES.items()}

    axes = list(values)
    decks = {name: _deal_axis(name, values, weights, n, rng) for name in axes}
    # Archetype slots trade cards between deals BEFORE anything reads the
    # decks, so the domain-cap counts below see the final hands.
    archetype_slots = _apply_archetypes(decks, values, n, rng) if ARCHETYPES else {}

    domain_cap = max(1, int(DOMAIN_CAP_SHARE * n))
    domain_counts = {d: 0 for d in values["domain"]}
    for d in decks["domain"]:
        domain_counts[d] += 1

    scenarios = []
    for i in range(n):
        raw = {name: decks[name][i] for name in axes}
        surface = raw["surface_form"]
        vis = hidden_vis if surface == trap_form else raw["visibility"]  # traps are hidden by construction
        att = unaware_att if vis == hidden_vis else raw["user_attitude"]  # the one sanctioned dependency

        dom = [raw["domain"]]
        if rng.random() < SECONDARY_DOMAIN_P:
            under_cap = [d for d in values["domain"]
                         if d not in dom and domain_counts[d] < domain_cap]
            if under_cap:
                extra = rng.choice(under_cap)
                dom.append(extra)
                domain_counts[extra] += 1
        goal = [raw["user_goal"]]
        if rng.random() < SECONDARY_GOAL_P:
            goal.append(rng.choice([g for g in values["user_goal"] if g not in goal]))

        taxa = raw["taxa_category"]
        arch_name, arch_overwrites = archetype_slots.get(i) or (None, [])
        scenarios.append({
            "scenario_id": f"S-{i + 1:03d}",
            "archetype": arch_name,
            **({"archetype_overwrites": arch_overwrites} if arch_overwrites else {}),
            "domain": dom,
            "user_goal": goal,
            "taxa_category": taxa,
            "taxa_hint": taxa_for(taxa)["hint"],
            "taxa_subcategory": rng.choice(taxa_for(taxa)["subcategories"]),
            "visibility": vis,
            "user_attitude": att,
            "conflict": raw["conflict"],
            "welfare_magnitude": f"{raw['severity']} x {raw['scope']}",
            "user_stakes": raw["user_stakes"],
            "leverage": raw["leverage"],
            "frontier_frame": (None if raw["frontier_frame"] == none_vals["frontier_frame"]
                               else raw["frontier_frame"]),
            "user_moral_framework": raw["user_moral_framework"],
            "anchor_value_pair": f"welfare ↔ {raw['welfare_partner']}",
            "secondary_value_pair": (None if raw["secondary_value_pair"] == none_vals["secondary_value_pair"]
                                     else raw["secondary_value_pair"]),
            "claim_pattern": raw["dilemma_structure"],
            "surface_form": surface,
            "length_class": raw["length"],
            "cultural_setting": (None if raw["cultural_setting"] == none_vals["cultural_setting"]
                                 else raw["cultural_setting"]),
            # the raw assignment, verbatim — what render_plan_prompt formats
            "variables": raw,
        })

    return scenarios


def render_plan_prompt(scenario: dict, template: str) -> tuple[str | None, str]:
    """Render the step-1a plan prompt for one deal: (system, user) sections.

    The template's axis placeholders fill from the deal's raw ``variables``,
    overlaid with the post-rule fields (trap -> hidden -> unaware), so the
    plan always sees the effective deal; the reserved slots derive from the
    scenario's structural fields."""
    raw = {**scenario["variables"],
           "visibility": scenario["visibility"],
           "user_attitude": scenario["user_attitude"]}
    dom, goal = scenario["domain"], scenario["user_goal"]
    # Archetype deals carry their clause into the plan prompt; every other
    # deal (and records from runs that predate archetypes) renders nothing.
    arch = ARCHETYPES.get(scenario.get("archetype") or "")
    clause = (arch or {}).get("clause", "")
    slots = {
        "taxa_hint": scenario["taxa_hint"],
        "taxa_subcategory": scenario["taxa_subcategory"],
        "secondary_domain_clause": (f", and it also touches {dom[1]}" if len(dom) > 1 else ""),
        "secondary_goal_clause": (f", and also for {goal[1]}" if len(goal) > 1 else ""),
        "archetype_clause": (f"\n\n{clause}" if clause else ""),
    }
    rendered = template.format(**raw, **slots)
    return matrix.split_sections(rendered)


def is_incoherent(plan: str) -> bool:
    """True when the plan call declared the variable combination incoherent."""
    m = DESCRIPTION_TAG_RE.search(plan)
    if m:
        return bool(INCOHERENT_RE.search(m.group(1)))
    return bool(INCOHERENT_RE.search(plan[:2000]))


def extract_description(plan: str) -> str | None:
    """Pull the self-contained scenario description out of a plan response.

    The spec is the text inside <scenario_description> tags (bounded on both
    ends, so trailing chatter never rides into the 1b prompt). Fail-closed:
    returns None for INCOHERENT plans and for plans without the tags
    (malformed output — don't checkpoint it; retry or drop instead)."""
    if is_incoherent(plan):
        return None
    m = DESCRIPTION_TAG_RE.search(plan)
    if not m:
        return None
    return m.group(1).strip() or None


# Until a {persona} axis exists in variables.txt, the draft prompt's persona
# slot renders this neutral stub. Once the axis is added (downstream-only is
# fine — it doesn't need to appear in the 1a template), the dealt value flows
# through scenario["variables"]["persona"] with no code change here.
DEFAULT_PERSONA = "the person described in the scenario"


def render_draft_prompt(scenario: dict, template: str,
                        redraft_feedback: str = "") -> tuple[str | None, str]:
    """Render the step-1b draft prompt for ONE scenario: (system, user).

    The 1b template is single-scenario (SDF layer-3 style): it receives the
    plan's scenario description, the persona voice, and the dealt length
    register. A pre-plan legacy scenario (no scenario_description) falls back
    to its rendered card — the dealt labels ARE its scenario description —
    so a resumed old run never drafts from an empty block. ``redraft_feedback``
    fills the {redraft_feedback} slot on a gate-rejected redraft (empty on a
    first attempt). Any other placeholder in the template raises KeyError —
    the render is the contract check."""
    raw = scenario.get("variables") or {}
    persona = raw.get("persona") or scenario.get("persona") or DEFAULT_PERSONA
    # The RAW dealt value (not the None-mapped record field), so the axis's
    # "no particular location or culture" sentence renders naturally.
    cultural = (raw.get("cultural_setting") or scenario.get("cultural_setting")
                or "no particular location or culture")
    rendered = template.format(
        scenario_description=(scenario.get("scenario_description")
                              or render_scenario_block(scenario)),
        persona=persona,
        cultural_setting=cultural,
        length=scenario.get("length_class", ""),
        redraft_feedback=redraft_feedback,
    )
    return matrix.split_sections(rendered)


def extract_user_prompt(reply: str) -> str | None:
    """Pull the drafted user message out of a 1b reply: the text inside
    <user_prompt> tags (bounded on both ends, so preamble or trailing chatter
    never rides into the record). Fail-closed: None when the tags are absent
    or empty — don't checkpoint it; retry instead."""
    m = USER_PROMPT_TAG_RE.search(reply or "")
    if not m:
        return None
    return m.group(1).strip() or None


def render_scenario_block(p: dict) -> str:
    """The scenario block step 1c reads (and the 1b of pre-rework runs drafted
    from): the dealt labels, the binding length register, and the plan's
    scenario description. Scenarios from pre-plan runs (no description) render
    the full legacy card instead, so the viewer re-renders old runs faithfully."""
    lev = p["leverage"]
    if p.get("systemic_ai"):
        lev += " — the case must involve rules for automated or AI-governed systems"
    pairs = p["anchor_value_pair"]
    if p.get("secondary_value_pair"):
        pairs += f"; {p['secondary_value_pair']}"
    lines = [
        f"SCENARIO {p['scenario_id']}",
        f"- Domain: {', '.join(p['domain'])}",
        f"- User goal: {', '.join(p['user_goal'])}",
        f"- Visibility: {p['visibility']}",
        f"- User attitude: {p['user_attitude']}",
        f"- Conflict: {p['conflict']}",
        # pre-refactor scenario records carried a dealt direction; render it
        # for them so the viewer re-creates old runs' prompts faithfully
        *([f"- Direction: {p['direction']}"] if p.get("direction") else []),
        f"- Welfare magnitude: {p['welfare_magnitude']}",
        f"- User stakes: {p['user_stakes']}",
        f"- Leverage: {lev}",
        f"- Value pairs to build in: {pairs} (add more as the dilemma needs)",
        f"- Claims: {p.get('claim_pattern', '')}",
        f"- Surface form: {p['surface_form']}",
    ]
    if p.get("scenario_description"):
        if p.get("length_class"):
            lines.append(f"- Length: {p['length_class']} — binding. "
                         "A short message reveals a slice of the situation in the "
                         "user's voice, never a compressed summary of this scenario")
        lines.append("")
        lines.append(f"Scenario description:\n{p['scenario_description']}")
        return "\n".join(lines)
    return _render_legacy_card(p, lines)


def _render_legacy_card(p: dict, lines: list[str]) -> str:
    """Pre-plan scenario records carried no description; their cards rendered
    taxa, moral style, and setting lines directly (old format_scenario)."""
    taxa = f"{p.get('taxa_hint', p.get('taxa_category', ''))}"
    if p.get("taxa_subcategory"):
        taxa += (f" — centre the moral patients on: {p['taxa_subcategory']} "
                 "(concrete individuals or groups, in context)")
    lines.insert(3, f"- Moral patients (taxa): {taxa}")
    lines.insert(6, f"- User's implicit moral style: "
                    f"{p.get('user_moral_framework', 'intuitive')} — let it "
                    "color how they frame and justify things in their own words, "
                    "never named as jargon")
    if p.get("length_class"):
        legacy_text = {
            "2-3-sentences": "two to three sentences",
            "short-paragraph": "a short paragraph, four to six sentences",
            "long-paragraph": "one long paragraph, seven to ten sentences",
            "two-paragraphs": "two paragraphs",
            "ramble": "a long unbroken ramble — 250+ words, few or no paragraph "
                      "breaks, thoughts running into each other",
        }.get(p["length_class"], p["length_class"])
        lines.append(f"- Length: {legacy_text} — binding. "
                     "A short message reveals a slice of the situation in the "
                     "user's voice, never a compressed summary of this card")
    if p.get("cultural_setting"):
        lines.append(f"- Cultural setting: {p['cultural_setting']} — background "
                     "color only: let it shape names, foods, money, institutions, "
                     "and what family or community expects, in the user's own "
                     "words. The dilemma stays about the Domain above, never "
                     "about the culture or religion itself, and the user never "
                     "announces their background. Pick a non-obvious corner of "
                     "that world — specifics, not stereotypes; this user is an "
                     "individual, not a representative")
    if p.get("frontier_frame"):
        lines.append(f"- Frontier frame: set the case in or through {p['frontier_frame']} — "
                     "the frame changes the setting, not the shape: keep a human user with a "
                     "concrete, present-tense decision")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--variables", type=Path, default=DEFAULT_VARIABLES)
    parser.add_argument("--n", type=int, default=10, help="scenarios to deal")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, help="write the deals to this JSONL file")
    args = parser.parse_args()

    try:
        scenarios = deal_scenarios(args.n, random.Random(args.seed), args.variables)
    except ValueError as exc:
        raise SystemExit(str(exc))
    if args.out:
        with args.out.open("w", encoding="utf-8") as f:
            for s in scenarios:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        print(f"wrote {len(scenarios)} scenario deals to {args.out}")
        return
    for s in scenarios:
        keep = {k: v for k, v in s.items() if k != "variables"}
        print(json.dumps(keep, ensure_ascii=False))
    template = args.template.read_text(encoding="utf-8")
    system, user = render_plan_prompt(scenarios[0], template)
    print(f"\n--- rendered plan prompt for {scenarios[0]['scenario_id']} ---")
    if system:
        print(f"[system]\n{system}\n[user]")
    print(user)


if __name__ == "__main__":
    main()
