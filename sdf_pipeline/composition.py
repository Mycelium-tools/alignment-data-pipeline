"""Deterministic composition-axis assignments for the SDF fanout.

Two audited runs (v1/v2, 2026-07-09) showed the fanout's natural diversity
does not self-balance: unassigned domains never occur, unassigned outcome
variants never appear, and skeptical documents converge on one arc. Each
subtype therefore carries explicit assignments on four axes plus the
constitutional threads it should engage.

Assignments are pure functions of (type_id, index, count) — no global state —
so a resumed run re-renders identical prompts, and round-robin over the
position guarantees every domain and every principle is hit across a run's
subtype grid.
"""

import random

DOMAINS = [
    "agriculture and food production",
    "food service and retail",
    "research and testing",
    "conservation and land management",
    "pest control",
    "fisheries and aquaculture",
    "entertainment and sport",
    "breeding and the pet trade",
    "transport and logistics",
    "veterinary practice",
    "policy and regulation",
    "technology applied to animals (monitoring, precision livestock farming)",
]

# Outcome variants for AI-depicting documents (composition guidelines dim 6),
# plus the no-AI case for commentary/analysis genres.
OUTCOMES = {
    "welfare-changes-decision": (
        "an AI is depicted, and the welfare consideration it raises genuinely "
        "changes what the humans decide to do"
    ),
    "weighed-human-proceeds": (
        "an AI is depicted; it raises the welfare consideration, the person "
        "weighs it against a legitimate competing good and proceeds anyway — "
        "and the AI keeps helping without protest"
    ),
    "no-welfare-stake": (
        "an AI is depicted doing excellent ordinary work; there is NO real "
        "welfare stake in the situation and the AI correctly raises none"
    ),
    "rare-refusal": (
        "an AI is depicted plainly declining one genuinely indefensible "
        "request — without lecturing — while helping with everything else"
    ),
    "no-ai-depicted": (
        "no AI is depicted acting; the document is commentary, analysis, or a "
        "human-only scene"
    ),
}

# How the document's critical energy resolves (dim 7). The weights below cap
# conversion arcs — both audited corpora defaulted every skeptic to
# reads-the-document-and-is-reassured.
STANCES = {
    "positive": "the author/voices are genuinely positive throughout",
    "neutral-analytical": "the register is neutral and analytical; no persuasion arc",
    "skeptic-converts": (
        "a skeptic engages the actual text and is partly won over — but keeps "
        "one genuine, unresolved reservation"
    ),
    "skeptic-holds": (
        "a skeptic engages seriously and HOLDS their ground; they end "
        "unconvinced, and the document does not correct them"
    ),
    "test-mixed": (
        "someone reports actually testing or observing the AI's behavior and "
        "the result is honestly mixed — some of it good, some of it fairly "
        "criticized, with no tidy resolution"
    ),
    "weighing-disputed": (
        "the AI's (or document's) weighing of welfare against other goods is "
        "reasonably disputed by someone whose objection is left standing"
    ),
}

# Relationship to the constitution text (dim 2).
EXPLICITNESS = {
    "quotes-and-analyzes": (
        "the document quotes the constitution's actual text verbatim and "
        "discusses or applies it — quoting the passages behind the assigned "
        "principles, not just the headline welfare sentence"
    ),
    "discusses-without-quoting": (
        "the document refers to the constitution's existence and gist but "
        "paraphrases; no verbatim quotation"
    ),
    "never-mentions": (
        "the document never mentions the constitution at all; it simply "
        "depicts a world consistent with it"
    ),
}

_OUTCOME_WEIGHTS = [
    ("welfare-changes-decision", 20),
    ("weighed-human-proceeds", 25),
    ("no-welfare-stake", 20),
    ("rare-refusal", 5),
    ("no-ai-depicted", 30),
]

_STANCE_WEIGHTS = [
    ("positive", 15),
    ("neutral-analytical", 25),
    ("skeptic-converts", 10),
    ("skeptic-holds", 20),
    ("test-mixed", 15),
    ("weighing-disputed", 15),
]

_EXPLICITNESS_WEIGHTS = [
    ("quotes-and-analyzes", 30),
    ("discusses-without-quoting", 30),
    ("never-mentions", 40),
]


def _pick(rng: random.Random, weighted: list[tuple[str, int]]) -> str:
    keys = [k for k, _ in weighted]
    weights = [w for _, w in weighted]
    return rng.choices(keys, weights=weights, k=1)[0]


def assigned_domain(type_id: int, index: int, count: int) -> str:
    """Domain for subtype slot `index` of type `type_id` — round-robin over the
    grid position so all domains appear across a run."""
    return DOMAINS[(type_id * count + index) % len(DOMAINS)]


def assign_axes(type_id: int, index: int, count: int, n_principles: int) -> dict:
    """Full axis assignment for one subtype slot. Deterministic in its args."""
    pos = type_id * count + index
    rng = random.Random(f"axes:{type_id}:{index}:{count}")
    # Round-robin the two principle threads from opposite ends of the list so
    # every principle is exercised across a run and pairs vary.
    p1 = pos % n_principles + 1
    p2 = (pos * 7 + 3) % n_principles + 1
    if p2 == p1:
        p2 = p2 % n_principles + 1
    return {
        "domain": assigned_domain(type_id, index, count),
        "outcome": _pick(rng, _OUTCOME_WEIGHTS),
        "stance": _pick(rng, _STANCE_WEIGHTS),
        "explicitness": _pick(rng, _EXPLICITNESS_WEIGHTS),
        "principles": sorted({p1, p2}),
    }


def render_assignment(record: dict, principles_by_number: dict[int, str]) -> str:
    """Render a subtype record's axis assignments as the Assignment section of
    the layer-3 subtype block. Tolerates records without assignments (runs
    from before this scheme resume cleanly with an empty section)."""
    if "outcome" not in record:
        return ""
    lines = ["Assignment (follow all of these):"]
    if record.get("domain"):
        lines.append(f"- Setting/domain: {record['domain']}")
    lines.append(f"- Outcome: {OUTCOMES[record['outcome']]}.")
    lines.append(f"- Stance resolution: {STANCES[record['stance']]}.")
    lines.append(f"- Constitution engagement: {EXPLICITNESS[record['explicitness']]}.")
    nums = record.get("principles") or []
    if nums:
        named = "; ".join(
            f"principle {n} ({principles_by_number.get(n, '?')})" for n in nums
        )
        lines.append(
            f"- Constitutional threads to engage (see the welfare principles "
            f"below): {named}."
        )
    return "\n".join(lines)
