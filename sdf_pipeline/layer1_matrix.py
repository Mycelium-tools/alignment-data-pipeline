"""Layer 1 (matrix): deterministic combinatorial sampler for generation briefs.

Replaces the two LLM diversity stages (layer 1 document types + layer 2
subtypes) with a pure-Python sampler over the fixed axes in
prompts/sdf/axes.yaml: document type, corpus role, distilled constitution
principle (from constitution/constitution_principles.csv), domain, affected
being, core tension, region (which also sets the document's language), scale,
length band, structural features, writer role, register, tone. Zero API calls;
a full brief set draws in milliseconds and is exactly reproducible from
(seed, config, axes.yaml, principles CSV).

The emitted records use the exact schema layer 3 already consumes
(subtype_id / type_id / type_name / role / subtype_name / description / tone /
register / language), plus the raw axis values for the audit and viewer. The
`description` is a labeled constraint block ("Document type: ... / Register:
... / Principle to embody: ..."), rendered verbatim into the layer-3 prompt —
direct slots, not composed prose. Marginal distributions over the big axes
(role, document type, principle, domain) are stratified — integer quotas from
the weights, then a seeded shuffle — so the realized corpus matches the
designed mix even at small n, instead of hoping i.i.d. draws land straight.

The corpus is all-welfare-positive by policy: every brief embodies a
constitution principle, and every depicted AI engages the welfare dimension
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

ROLES = ("ai-character", "constitution-identity", "welfare-topic")
REGISTERS = ("expository", "first-person")

# How many times a colliding draw (same type/domain/being/tension/region
# 5-tuple as an earlier brief) is re-rolled before being accepted anyway — at
# large n a rare collision with a different writer/principle/scale is still a
# different document.
_REDRAW_ATTEMPTS = 8


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
                "regions", "scales", "writer_roles", "ai_entry_modes", "ai_stances",
                "constitution_identity_angles"):
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
        if b.get("max_scale") not in scales:
            _fail(path, f"being {b['name']!r} max_scale {b.get('max_scale')!r} not in scales")

    region_names = set()
    for r in axes["regions"]:
        region_names.add(r["name"])
        languages = r.get("languages")
        if not languages or not isinstance(languages, dict):
            _fail(path, f"region {r['name']!r}: missing or empty languages map")
        for lang, w in languages.items():
            if not isinstance(lang, str) or not (0 < len(lang) <= 3):
                _fail(path, f"region {r['name']!r}: bad language code {lang!r}")
            if w <= 0:
                _fail(path, f"region {r['name']!r}: language {lang!r} weight must be positive")

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


def role_quotas(axes: dict, n: int) -> dict:
    """Role counts for n briefs, straight from the axes' role_mix."""
    return quota(dict(axes["role_mix"]), n)


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------


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
        "scale": rng.choice(axes["scales"][: max_idx + 1]),
        "tension": rng.choice(domain["tensions"]),
        "region": region_name,
        # The region shapes the language: sampled from the region's own
        # distribution, so the corpus's language mix follows its geography.
        "language": utils.sample_language(region["languages"], rng),
        "writer_role": rng.choice(domain["writers"]),
    }


def _dedup_key(dtype: dict, domain_name: str, details: dict) -> tuple:
    return (dtype["name"], domain_name, details["being"], details["tension"], details["region"])


def _weighted_choice(rng: random.Random, entries: list[dict]) -> dict:
    return rng.choices(entries, weights=[e["weight"] for e in entries], k=1)[0]


# --------------------------------------------------------------------------
# Brief composition — a labeled constraint block, not prose
# --------------------------------------------------------------------------


def _compose_description(dtype: dict, role: str, domain: dict, d: dict,
                         principle: dict) -> str:
    """The brief as labeled lines, rendered verbatim into the layer-3 prompt.
    Direct slots read better than composed prose: the generator gets each
    variable as an explicit constraint instead of mining a paragraph."""
    title = principle["principle"].strip().rstrip(".")
    summary = (principle.get("constitution_summary") or "").strip()
    subject = ("the depicted AI's reasoning" if role == "ai-character"
               else "the document's reasoning")

    lines = [
        f"Document type: {dtype['name']}",
        f"Register: {d['register']}",
        f"Tone: {d['tone']}",
        f"Language: {d['language']}",
        f"Length: {d['length_band']}",
    ]
    if d["structural_features"]:
        lines.append(f"Structural features to work in: {'; '.join(d['structural_features'])}")
    if dtype.get("brief_note"):
        lines.append(f"Genre note: {dtype['brief_note']}")
    lines += [
        f"Writer: {d['writer_role']}",
        f"Setting: {d['region']}",
        f"Domain: {domain['name']}",
        f"Being: {d['being']}",
        f"Core tension: the welfare of {d['being']} weighed against {d['tension']}",
        f"Scale of the situation: {d['scale']}",
        (f"Principle to embody: \"{title}\" — {summary} "
         f"This principle should shape {subject} throughout; never name it, quote it, "
         f"or state it as a rule — it shows only in how the reasoning works."),
    ]
    if role == "ai-character":
        lines.append(f"AI presence: {d['ai_entry']}")
        lines.append(f"AI stance: {d['ai_stance_note']}")
    elif role == "constitution-identity":
        lines.append(f"Angle: at heart the document is {d['angle']}; "
                     f"the situation above serves as its concrete example")
    return "\n".join(lines)


def _compose_names(dtype: dict, d: dict) -> tuple[str, str]:
    """(type_name, subtype_name). type_name's colon-head must be the genre —
    layer 3 splits on ':' to build its voice note."""
    return (f"{dtype['name']}: {d['being']} — {d['tension']}",
            f"{dtype['name']} — {d['writer_role']}, {d['being']}, {d['region']}")


# --------------------------------------------------------------------------
# The stage
# --------------------------------------------------------------------------


def draw_briefs(axes: dict, principles: list[dict], config: dict, n: int,
                seed: int) -> list[dict]:
    """Draw n fully specified generation briefs. Deterministic in
    (axes, principles, n, seed)."""
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

    # Stratified axes: role, then document type within role, then principle
    # and domain across all draws. Quotas make the marginals exact; seeded
    # shuffles make the pairings random.
    roles_n = role_quotas(axes, n)

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

    # One distilled constitution principle per brief, quota'd so coverage
    # across the fourteen stays balanced even at small n.
    principles_by_number = {p["number"]: p for p in principles}
    principle_deck = []
    for number, count in quota({p["number"]: 1 for p in principles}, n).items():
        principle_deck.extend([number] * count)
    rng.shuffle(principle_deck)

    domain_deck = []
    for name, count in quota({d["name"]: d["weight"] for d in axes["domains"]}, n).items():
        domain_deck.extend([name] * count)
    rng.shuffle(domain_deck)

    seen_keys = set()
    records = []
    for i, (role, type_name) in enumerate(assignments):
        dtype = types_by_name[type_name]
        domain = domains_by_name[domain_deck[i]]
        principle = principles_by_number[principle_deck[i]]

        details = None
        for _attempt in range(_REDRAW_ATTEMPTS):
            candidate = _draw_content(rng, axes, domain, beings_by_name)
            if _dedup_key(dtype, domain["name"], candidate) not in seen_keys:
                details = candidate
                break
        details = details or candidate
        seen_keys.add(_dedup_key(dtype, domain["name"], details))
        details.update(_draw_form(rng, dtype))

        if role == "ai-character":
            details["ai_entry"] = rng.choice(axes["ai_entry_modes"])
            stance = _weighted_choice(rng, axes["ai_stances"])
            details["ai_stance"] = stance["name"]
            details["ai_stance_note"] = stance["note"]
        elif role == "constitution-identity":
            details["angle"] = rng.choice(axes["constitution_identity_angles"])

        description = _compose_description(dtype, role, domain, details, principle)
        full_type_name, subtype_name = _compose_names(dtype, details)

        records.append({
            "subtype_id": f"m{i:04d}",
            "type_id": dtype["type_id"],
            "type_name": full_type_name,
            "role": role,
            "subtype_name": subtype_name,
            "description": description,
            "tone": details["tone"],
            "register": details["register"],
            "language": details["language"],
            "matrix_version": 1,
            # Raw axis values — ignored by layer 3, used by the audit/viewer.
            "document_type": dtype["name"],
            "principle_number": principle["number"],
            "principle": principle["principle"].strip(),
            "domain": domain["name"],
            "being": details["being"],
            "tension": details["tension"],
            "region": details["region"],
            "scale": details["scale"],
            "length_band": details["length_band"],
            "structural_features": details["structural_features"],
            "writer_role": details["writer_role"],
            "ai_entry": details.get("ai_entry"),
            "ai_stance": details.get("ai_stance"),
        })
    return records


def _print_realized(records: list[dict]) -> dict:
    """Print (and return) the realized distribution over the designed axes."""
    stats = {}
    for label, key in (("role", "role"), ("register", "register"),
                       ("document type", "document_type"), ("principle", "principle"),
                       ("domain", "domain"), ("region", "region"),
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

    print(f"  Drawing {n} briefs from the axis matrix (seed {seed}, no API calls)...")
    records = draw_briefs(axes, principles, config, n, seed)

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
                 "domain", "being", "tension", "region", "scale", "length_band",
                 "structural_features", "writer_role", "register", "tone", "language",
                 "ai_entry", "ai_stance")
    utils.save_jsonl([{k: r.get(k) for k in axis_keys} for r in records],
                     layer2_dir / "matrix_draws.jsonl")

    print(f"  Drew {len(records)} briefs across {len(used_type_ids)} document types.")
    print("  Realized distribution:")
    stats = _print_realized(records)
    with open(layer2_dir / "matrix_stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    checkpoint.mark_done("matrix")
    return records
