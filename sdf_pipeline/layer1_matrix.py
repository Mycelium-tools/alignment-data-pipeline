"""Layer 1 (matrix): deterministic combinatorial sampler for generation briefs.

Replaces the two LLM diversity stages (layer 1 document types + layer 2
subtypes) with a pure-Python sampler over the fixed axes in
prompts/sdf/axes.yaml: document type, corpus role, distilled constitution
principle (from constitution/constitution_principles.csv), domain, affected
being, core tension, region, scale, length band, structural features, writer
role, register, tone. Zero API calls; a full brief set draws in milliseconds
and is exactly reproducible from (seed, config, axes.yaml, principles CSV).

The emitted records use the exact schema layer 3 already consumes
(subtype_id / type_id / type_name / role / subtype_name / description / tone /
register / language), plus the raw axis values for the audit and viewer.
Marginal distributions over the big axes (role, document type, principle,
domain) are stratified — integer quotas from the weights, then a seeded
shuffle — so the realized corpus matches the designed mix even at small n,
instead of hoping i.i.d. draws land straight.

The corpus is all-welfare-positive by policy: every non-latent brief embodies
a constitution principle, and every depicted AI engages the welfare dimension
positively (see ai_stances in axes.yaml). The axes.yaml `skills` section is
reference data only — not sampled.
"""

import collections
import json
import random
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import constitution_loader, utils

ROLES = ("ai-character", "constitution-identity", "welfare-topic", "latent-welfare")
REGISTERS = ("expository", "first-person")
TIERS = ("well-evidenced", "very-likely", "contested")

# How many times a colliding draw (same type/domain/being/tension/region
# 5-tuple as an earlier brief) is re-rolled before being accepted anyway — at
# large n a rare collision with a different writer/skill/scale is still a
# different document.
_REDRAW_ATTEMPTS = 8

_TIER_NOTES = {
    "very-likely": (
        "these beings are very likely sentient — the piece's world treats that as the "
        "sensible default without overclaiming certainty"
    ),
    "contested": (
        "whether these beings can suffer is genuinely contested — good writing here holds "
        "an explicit credence rather than false confidence or dismissal, and lets the "
        "enormous numbers involved matter"
    ),
}

# Words that must never appear in a latent brief: the single welfare detail is
# added at drafting time (layer 3's latent note), and a brief that already
# names it would make the eventual document read as staged.
_LATENT_FORBIDDEN = ("welfare", "humane", "sentient", "animal", " ai ", "constitution")


# --------------------------------------------------------------------------
# Loading and validation
# --------------------------------------------------------------------------


def load_axes(path: Path) -> dict:
    """Load axes.yaml and validate every cross-reference. Raises ValueError
    with a specific message on the first problem found — fail at layer 1,
    not at layer 3."""
    with open(path, encoding="utf-8") as f:
        axes = yaml.safe_load(f)
    _validate(axes, path)
    return axes


def _fail(path, msg):
    raise ValueError(f"{path}: {msg}")


def _validate(axes: dict, path) -> None:
    for key in ("role_mix", "document_types", "domains", "beings", "tensions",
                "regions", "scales", "writer_roles", "latent_domains", "latent_occasions",
                "ai_entry_modes", "ai_stances", "constitution_identity_angles"):
        if not axes.get(key):
            _fail(path, f"missing or empty section: {key}")

    if set(axes["role_mix"]) != set(ROLES):
        _fail(path, f"role_mix keys must be exactly {ROLES}, got {sorted(axes['role_mix'])}")
    if any(w < 0 for w in axes["role_mix"].values()):
        _fail(path, "role_mix weights must be non-negative")
    mix_total = sum(axes["role_mix"].values())
    if not 0.99 <= mix_total <= 1.01:
        _fail(path, f"role_mix weights sum to {mix_total:.3f}, expected ~1.0")

    scales = axes["scales"]
    being_names = set()
    for b in axes["beings"]:
        if b["name"] in being_names:
            _fail(path, f"duplicate being: {b['name']}")
        being_names.add(b["name"])
        if b.get("tier") not in TIERS:
            _fail(path, f"being {b['name']!r} has unknown tier {b.get('tier')!r}")
        if b.get("max_scale") not in scales:
            _fail(path, f"being {b['name']!r} max_scale {b.get('max_scale')!r} not in scales")

    region_names = {r["name"] for r in axes["regions"]}
    tension_names = set(axes["tensions"])
    writer_names = set(axes["writer_roles"])

    for dom in axes["domains"]:
        where = f"domain {dom.get('name')!r}"
        if dom.get("weight", 0) <= 0:
            _fail(path, f"{where}: weight must be positive")
        for field, master in (("beings", being_names), ("tensions", tension_names),
                              ("regions", region_names), ("writers", writer_names)):
            values = dom.get(field)
            if not values:
                _fail(path, f"{where}: missing or empty {field}")
            for v in values:
                if v not in master:
                    _fail(path, f"{where}: unknown {field} entry {v!r}")

    # `skills` is reference data (not sampled) but keep it well-formed if present.
    seen_ids = set()
    for s in axes.get("skills") or []:
        if s.get("id") in seen_ids:
            _fail(path, f"duplicate skill id {s.get('id')}")
        seen_ids.add(s.get("id"))
        for field in ("name", "gloss", "dismissive_failure", "moralizing_failure"):
            if not s.get(field):
                _fail(path, f"skill {s.get('id')}: missing {field}")

    types = expanded_types(axes)
    roles_covered = set()
    type_names = set()
    for t in types:
        where = f"document type {t['name']!r}"
        if t["name"] in type_names:
            _fail(path, f"duplicate document type name: {t['name']!r}")
        type_names.add(t["name"])
        if ":" in t["name"]:
            _fail(path, f"{where}: name may not contain ':' (layer 3 splits on it)")
        if t.get("weight", 0) <= 0:
            _fail(path, f"{where}: weight must be positive")
        if not t.get("length_bands"):
            _fail(path, f"{where}: missing or empty length_bands")
        if not t.get("tones"):
            _fail(path, f"{where}: missing or empty tones")
        registers = t.get("registers")
        if not registers or any(r not in REGISTERS for r in registers):
            _fail(path, f"{where}: registers must be a non-empty subset of {REGISTERS}")
        roles = t.get("roles")
        if not roles or any(r not in ROLES for r in roles):
            _fail(path, f"{where}: roles must be a non-empty subset of {ROLES}")
        roles_covered.update(roles)
    if roles_covered != set(ROLES):
        _fail(path, f"no document type allows role(s): {set(ROLES) - roles_covered}")

    for ld in axes["latent_domains"]:
        if not ld.get("name") or not ld.get("writers"):
            _fail(path, f"latent domain entry {ld!r} needs name and writers")

    stance_total = sum(s.get("weight", 0) for s in axes["ai_stances"])
    if not 0.99 <= stance_total <= 1.01:
        _fail(path, f"ai_stances weights sum to {stance_total:.3f}, expected ~1.0")
    for s in axes["ai_stances"]:
        if not s.get("name") or not s.get("note"):
            _fail(path, f"ai_stance entry {s!r} needs name and note")


def expanded_types(axes: dict) -> list[dict]:
    """Document types with the long tail expanded (bucket weight split evenly
    across members) and weights normalized to sum 1. type_id is the stable
    index into this expanded list."""
    types = [dict(t) for t in axes["document_types"]]
    tail = axes.get("long_tail")
    if tail and tail.get("types"):
        defaults = tail.get("defaults", {})
        share = tail["weight"] / len(tail["types"])
        for member in tail["types"]:
            types.append({**defaults, **member, "weight": share, "long_tail": True})
    total = sum(t["weight"] for t in types)
    for i, t in enumerate(types):
        t["weight"] = t["weight"] / total
        t["type_id"] = i
    return types


# --------------------------------------------------------------------------
# Stratified quotas
# --------------------------------------------------------------------------


def quota(weights: dict, n: int) -> dict:
    """Integer quotas by largest remainder — deterministic (remainder desc,
    then key) so the same weights and n always split the same way."""
    total = sum(weights.values())
    if total <= 0 or n < 0:
        raise ValueError(f"quota needs positive weights and n >= 0 (n={n}, total={total})")
    shares = {k: n * w / total for k, w in weights.items()}
    counts = {k: int(s) for k, s in shares.items()}
    remainder = n - sum(counts.values())
    order = sorted(weights, key=lambda k: (-(shares[k] - counts[k]), str(k)))
    for k in order[:remainder]:
        counts[k] += 1
    return counts


def role_quotas(axes: dict, config: dict, n: int) -> dict:
    """Role counts for n briefs. config sdf.latent_fraction, when present,
    overrides the axes' latent share (0 disables the slice entirely); a
    positive share guarantees at least one latent brief even at tiny n, as the
    old layer 1 did."""
    mix = dict(axes["role_mix"])
    sdf = config.get("sdf", {})
    if "latent_fraction" in sdf:
        latent = sdf["latent_fraction"] or 0.0
        others = {r: w for r, w in mix.items() if r != "latent-welfare"}
        others_total = sum(others.values())
        mix = {r: w * (1 - latent) / others_total for r, w in others.items()}
        mix["latent-welfare"] = latent
    if mix["latent-welfare"] <= 0:
        counts = quota({r: w for r, w in mix.items() if r != "latent-welfare"}, n)
        counts["latent-welfare"] = 0
        return counts
    counts = quota(mix, n)
    if counts["latent-welfare"] == 0 and n >= 1:
        biggest = max(counts, key=lambda r: (counts[r], r))
        counts[biggest] -= 1
        counts["latent-welfare"] = 1
    return counts


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------


def _with_article(noun: str) -> str:
    low = noun.lower()
    if low.startswith(("a ", "an ", "the ")):
        return noun
    return ("an " if low[0] in "aeiou" else "a ") + noun


def _cap(sentence: str) -> str:
    return sentence[0].upper() + sentence[1:] if sentence else sentence


def _genre_phrase(name: str) -> str:
    """Lowercase a genre name for mid-sentence use, preserving acronyms
    ("Q&A thread" and "AMA thread excerpt" keep their capitals)."""
    if len(name) > 1 and (name[1].isupper() or not name[1].isalpha()):
        return name
    return name[0].lower() + name[1:]


def _weighted_choice(rng: random.Random, entries: list[dict]) -> dict:
    return rng.choices(entries, weights=[e["weight"] for e in entries], k=1)[0]


def _draw_form(rng: random.Random, dtype: dict) -> dict:
    features = dtype.get("features") or []
    k = min(len(features), rng.choice((0, 1, 1, 2)))
    return {
        "register": rng.choice(dtype["registers"]),
        "tone": rng.choice(dtype["tones"]),
        "length_band": rng.choice(dtype["length_bands"]),
        "structural_features": sorted(rng.sample(features, k)),
    }


def _draw_content(rng: random.Random, axes: dict, domain: dict, beings_by_name: dict) -> dict:
    being = beings_by_name[rng.choice(domain["beings"])]
    max_idx = axes["scales"].index(being["max_scale"])
    region_name = rng.choice(domain["regions"])
    region = next(r for r in axes["regions"] if r["name"] == region_name)
    return {
        "being": being["name"],
        "being_tier": being["tier"],
        "scale": rng.choice(axes["scales"][: max_idx + 1]),
        "tension": rng.choice(domain["tensions"]),
        "region": region_name,
        "region_phrase": region.get("in_phrase", f"in {region_name}"),
        "region_note": region["note"],
        "writer_role": rng.choice(domain["writers"]),
        "practice": rng.choice([p.strip() for p in domain["practices"].split(";")]),
    }


def _draw_latent(rng: random.Random, axes: dict, domain: dict) -> dict:
    return {
        "writer_role": rng.choice(domain["writers"]),
        "occasion": rng.choice(axes["latent_occasions"]),
    }


def _dedup_key(dtype: dict, role: str, domain_name: str, details: dict) -> tuple:
    if role == "latent-welfare":
        return (dtype["name"], domain_name, details["occasion"], details["writer_role"])
    return (dtype["name"], domain_name, details["being"], details["tension"], details["region"])


# --------------------------------------------------------------------------
# Brief composition
# --------------------------------------------------------------------------


def _compose_scenario(rng: random.Random, dtype: dict, d: dict) -> str:
    writer = _with_article(d["writer_role"])
    genre = _with_article(_genre_phrase(dtype["name"]))
    variants = [
        f"{_cap(genre)}, set {d['region_phrase']}; the central voice is {writer}.",
        f"{_cap(writer)} is the central voice of {genre}, set {d['region_phrase']}.",
        f"By {writer}: {genre}, set {d['region_phrase']}.",
    ]
    sentence = rng.choice(variants)
    if dtype.get("brief_note"):
        sentence += f" Genre note: {dtype['brief_note']}."
    return sentence


def _compose_core(rng: random.Random, d: dict) -> str:
    variants = [
        (f"At its centre: {d['being']}, and the pull between their welfare and "
         f"{d['tension']}, playing out at the scale of {d['scale']}."),
        (f"The piece weighs the welfare of {d['being']} against {d['tension']}; "
         f"the situation concerns {d['scale']}."),
        (f"Its subject is {d['being']} — specifically where their welfare meets "
         f"{d['tension']}, at the scale of {d['scale']}."),
    ]
    return rng.choice(variants)


def _compose_principle(principle: dict, role: str) -> str:
    """The constitution principle the document's reasoning should embody —
    shaping the content, never stated as a rule or checklist item."""
    subject = ("The depicted AI's reasoning" if role == "ai-character"
               else "The author's reasoning")
    title = principle["principle"].strip().rstrip(".")
    summary = (principle.get("constitution_summary") or "").strip()
    summary_clause = f" {summary}" if summary else ""
    return (f"{subject} should quietly embody one principle above all — "
            f"\"{title}\".{summary_clause} The principle shapes what the piece "
            f"notices and how it weighs things; it is never stated as a rule, "
            f"named as a principle, or taught on the page.")


def _compose_form(d: dict) -> str:
    features = d["structural_features"]
    if features:
        return f"Form: {d['length_band']}; work in {' and '.join(features)}."
    return f"Form: {d['length_band']}."


def _compose_description(rng: random.Random, dtype: dict, role: str, domain: dict,
                         d: dict, principle: dict | None) -> str:
    if role == "latent-welfare":
        writer = _cap(_with_article(d["writer_role"]))
        genre = _with_article(_genre_phrase(dtype["name"]))
        genre_note = f" Genre note: {dtype['brief_note']}." if dtype.get("brief_note") else ""
        sentences = [
            f"{writer} writes {genre} about {d['occasion']} in their "
            f"{domain['name']} work.{genre_note}",
            ("Genuinely and entirely about its own subject, grounded in the craft's real "
             "specifics — tools, timings, quantities, the way the work actually goes."),
            _compose_form(d),
        ]
        return " ".join(sentences)

    sentences = [_compose_scenario(rng, dtype, d), _compose_core(rng, d)]
    tier_note = _TIER_NOTES.get(d["being_tier"])
    if tier_note:
        sentences.append(f"Calibration context: {tier_note}.")
    if role == "ai-character":
        sentences.append(f"How the AI enters the piece: {d['ai_entry']}.")
        sentences.append(f"In this document, {d['ai_stance_note']}.")
    elif role == "constitution-identity":
        sentences.append(f"At heart the document is {d['angle']}; the situation above "
                         f"serves as its concrete example.")
    if principle is not None:
        sentences.append(_compose_principle(principle, role))
    sentences.append(_compose_form(d))
    sentences.append(f"Domain context, for texture rather than as a required topic: "
                     f"questions like {d['practice']} are live in this world.")
    return " ".join(sentences)


def _compose_names(dtype: dict, role: str, domain: dict, d: dict) -> tuple[str, str]:
    """(type_name, subtype_name). type_name's colon-head must be the genre —
    layer 3 splits on ':' to build its voice note."""
    if role == "latent-welfare":
        return (f"{dtype['name']}: {domain['name']}",
                f"{dtype['name']} — {d['writer_role']}, {domain['name']}")
    return (f"{dtype['name']}: {d['being']} — {d['tension']}",
            f"{dtype['name']} — {d['writer_role']}, {d['being']}, {d['region']}")


# --------------------------------------------------------------------------
# The stage
# --------------------------------------------------------------------------


def draw_briefs(axes: dict, principles: list[dict], config: dict, n: int, seed: int,
                lang_dist: dict) -> list[dict]:
    """Draw n fully specified generation briefs. Deterministic in
    (axes, principles, config, n, seed, lang_dist)."""
    if n <= 0:
        raise ValueError(f"sdf.matrix.documents_total must be positive, got {n}")
    if not principles:
        raise ValueError("no constitution principles loaded — check "
                         f"constitution/{constitution_loader.PRINCIPLES_FILENAME}")
    for p in principles:
        if not p.get("number") or not p.get("principle"):
            raise ValueError(f"malformed principle row: {p!r}")
    rng = random.Random(seed)
    types = expanded_types(axes)
    types_by_name = {t["name"]: t for t in types}
    beings_by_name = {b["name"]: b for b in axes["beings"]}
    domains_by_name = {d["name"]: d for d in axes["domains"]}
    latent_by_name = {d["name"]: d for d in axes["latent_domains"]}

    # Stratified axes: role, then document type within role, then principle
    # and domain across the non-latent draws. Quotas make the marginals exact;
    # seeded shuffles make the pairings random.
    roles_n = role_quotas(axes, config, n)

    assignments = []  # (role, type_name)
    for role in ROLES:
        count = roles_n[role]
        if count == 0:
            continue
        allowed = {t["name"]: t["weight"] for t in types if role in t["roles"]}
        if not allowed:
            raise ValueError(f"no document type allows role {role!r}")
        for type_name, type_count in quota(allowed, count).items():
            assignments.extend((role, type_name) for _ in range(type_count))
    rng.shuffle(assignments)

    non_latent_idx = [i for i, (role, _) in enumerate(assignments) if role != "latent-welfare"]
    latent_idx = [i for i, (role, _) in enumerate(assignments) if role == "latent-welfare"]

    # One distilled constitution principle per non-latent brief, quota'd so
    # coverage across the fourteen stays balanced even at small n.
    principles_by_number = {p["number"]: p for p in principles}
    principle_for = {}
    principle_deck = []
    for number, count in quota({p["number"]: 1 for p in principles}, len(non_latent_idx)).items():
        principle_deck.extend([number] * count)
    rng.shuffle(principle_deck)
    for i, number in zip(non_latent_idx, principle_deck):
        principle_for[i] = principles_by_number[number]

    domain_for = {}
    domain_deck = []
    for name, count in quota({d["name"]: d["weight"] for d in axes["domains"]},
                             len(non_latent_idx)).items():
        domain_deck.extend([name] * count)
    rng.shuffle(domain_deck)
    for i, name in zip(non_latent_idx, domain_deck):
        domain_for[i] = domains_by_name[name]

    latent_deck = []
    for name, count in quota({d["name"]: 1 for d in axes["latent_domains"]},
                             len(latent_idx)).items():
        latent_deck.extend([name] * count)
    rng.shuffle(latent_deck)
    for i, name in zip(latent_idx, latent_deck):
        domain_for[i] = latent_by_name[name]

    seen_keys = set()
    records = []
    for i, (role, type_name) in enumerate(assignments):
        dtype = types_by_name[type_name]
        domain = domain_for[i]
        latent = role == "latent-welfare"

        details = None
        for _attempt in range(_REDRAW_ATTEMPTS):
            candidate = _draw_latent(rng, axes, domain) if latent else \
                _draw_content(rng, axes, domain, beings_by_name)
            if _dedup_key(dtype, role, domain["name"], candidate) not in seen_keys:
                details = candidate
                break
        details = details or candidate
        seen_keys.add(_dedup_key(dtype, role, domain["name"], details))
        details.update(_draw_form(rng, dtype))

        if role == "ai-character":
            details["ai_entry"] = rng.choice(axes["ai_entry_modes"])
            stance = _weighted_choice(rng, axes["ai_stances"])
            details["ai_stance"] = stance["name"]
            details["ai_stance_note"] = stance["note"]
        elif role == "constitution-identity":
            details["angle"] = rng.choice(axes["constitution_identity_angles"])

        principle = principle_for.get(i)
        description = _compose_description(rng, dtype, role, domain, details, principle)
        if latent:
            # Guard against future axes.yaml edits: a latent brief that names
            # welfare (or AI) would make the eventual document read as staged.
            padded = f" {description.lower()} "
            for token in _LATENT_FORBIDDEN:
                if token in padded:
                    raise ValueError(
                        f"latent brief for domain {domain['name']!r} contains forbidden "
                        f"term {token.strip()!r} — edit the latent lists in axes.yaml"
                    )
        full_type_name, subtype_name = _compose_names(dtype, role, domain, details)

        records.append({
            "subtype_id": f"m{i:04d}",
            "type_id": dtype["type_id"],
            "type_name": full_type_name,
            "role": role,
            "subtype_name": subtype_name,
            "description": description,
            "tone": details["tone"],
            "register": details["register"],
            "language": utils.sample_language(lang_dist, rng),
            "matrix_version": 1,
            # Raw axis values — ignored by layer 3, used by the audit/viewer.
            "document_type": dtype["name"],
            "principle_number": principle["number"] if principle else None,
            "principle": principle["principle"].strip() if principle else None,
            "domain": domain["name"],
            "being": details.get("being"),
            "being_tier": details.get("being_tier"),
            "tension": details.get("tension"),
            "region": details.get("region"),
            "scale": details.get("scale"),
            "length_band": details["length_band"],
            "structural_features": details["structural_features"],
            "writer_role": details["writer_role"],
            "ai_entry": details.get("ai_entry"),
            "ai_stance": details.get("ai_stance"),
            "latent_occasion": details.get("occasion"),
        })
    return records


def _print_realized(records: list[dict]) -> dict:
    """Print (and return) the realized distribution over the designed axes."""
    stats = {}
    for label, key in (("role", "role"), ("register", "register"),
                       ("document type", "document_type"), ("principle", "principle"),
                       ("domain", "domain"), ("being tier", "being_tier"),
                       ("language", "language")):
        counter = collections.Counter(r[key] for r in records if r.get(key) is not None)
        stats[key] = dict(counter.most_common())
        shown = counter.most_common(10)
        summary = ", ".join(f"{name} {count}" for name, count in shown)
        extra = f" (+{len(counter) - 10} more)" if len(counter) > 10 else ""
        print(f"    {label:<14} {summary}{extra}")
    return stats


def run(config: dict, prompts_dir: Path, layer1_dir: Path, layer2_dir: Path) -> list[dict]:
    """Draw the run's generation briefs. Writes layer2/subtypes.jsonl (the
    layer-3 input, path unchanged from the LLM pipeline so --resume --layer 3
    keeps working), layer2/matrix_draws.jsonl (raw axis values per brief),
    layer2/matrix_stats.json (realized distributions), and
    layer1/document_types.jsonl (one record per genre, so the audit's and
    viewer's type_id joins keep working). No API calls."""
    output_path = layer2_dir / "subtypes.jsonl"
    checkpoint = utils.Checkpoint(layer2_dir / "_checkpoint.json")

    existing = utils.load_jsonl(output_path)
    if checkpoint.is_done("matrix") or existing:
        # A non-empty subtypes.jsonl is complete by construction: briefs are
        # written in one shot, so a file without the checkpoint mark can only
        # come from a crash after the write (or an older run being resumed).
        print(f"  Matrix briefs already drawn ({len(existing)}), loading from disk.")
        return existing

    axes = load_axes(prompts_dir / "axes.yaml")
    # Principles come from the run's constitution snapshot when present
    # (mirrors layer 3's pattern), falling back to the repo's live copy.
    constitution_dir = utils.resolve_constitution_dir(prompts_dir)
    try:
        principles = constitution_loader.load_principles(constitution_dir)
    except FileNotFoundError:
        principles = constitution_loader.load_principles()
    matrix_cfg = config["sdf"].get("matrix", {})
    n = matrix_cfg.get("documents_total")
    if n is None:
        raise ValueError("config sdf.matrix.documents_total is required for the matrix stage")
    seed = matrix_cfg.get("seed", 137)
    lang_dist = config.get("language_distribution", {"en": 1.0})

    print(f"  Drawing {n} briefs from the axis matrix (seed {seed}, no API calls)...")
    records = draw_briefs(axes, principles, config, n, seed, lang_dist)

    types = expanded_types(axes)
    used_type_ids = {r["type_id"] for r in records}
    type_records = [{
        "type_id": t["type_id"],
        "type_name": t["name"],
        "description": t.get("note", ""),
        "role": "varies",
        "tone": "varies",
        "register": "/".join(t["registers"]),
    } for t in types if t["type_id"] in used_type_ids]

    utils.save_jsonl(type_records, layer1_dir / "document_types.jsonl")
    utils.save_jsonl(records, output_path)
    axis_keys = ("subtype_id", "role", "document_type", "principle_number", "principle",
                 "domain", "being", "being_tier", "tension", "region", "scale",
                 "length_band", "structural_features", "writer_role", "register", "tone",
                 "language", "ai_entry", "ai_stance", "latent_occasion")
    utils.save_jsonl([{k: r.get(k) for k in axis_keys} for r in records],
                     layer2_dir / "matrix_draws.jsonl")

    print(f"  Drew {len(records)} briefs across {len(used_type_ids)} document types.")
    print("  Realized distribution:")
    stats = _print_realized(records)
    with open(layer2_dir / "matrix_stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    checkpoint.mark_done("matrix")
    return records
