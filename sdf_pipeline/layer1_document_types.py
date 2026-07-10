"""Layer 1: Load the curated document-type list and allocate scenario quotas.

No API call. The set of genres in a pretraining corpus is known and stable, so
it is curated once — with explicit weights — in prompts/sdf/document_types.yaml
(snapshotted into each run's inputs/prompts/ like every other prompt asset),
not generated per run. This layer validates the file, computes per-type
scenario quotas (scenarios_total x weight, largest-remainder rounding so quotas
sum exactly), and allocates roles within each type against the run-level
role_mix / latent_fraction targets. Layer 2 turns each type's quota into that
many concrete scenario briefs.
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import utils

VALID_ROLES = ("ai-character", "constitution-identity", "welfare-topic", "latent-welfare")
VALID_TONES = ("supportive", "neutral", "skeptical", "industry", "academic", "narrative", "policy")
VALID_REGISTERS = ("expository", "first-person")

# config role_mix keys -> role enum values. latent-welfare is not a role_mix
# key: its share comes from sdf.latent_fraction (kept separate because the
# latent slice has its own guarantee-at-least-one semantics and layer-5 gate).
_ROLE_MIX_KEYS = {
    "ai_character": "ai-character",
    "constitution_identity": "constitution-identity",
    "welfare_topic": "welfare-topic",
}
_DEFAULT_ROLE_MIX = {"ai_character": 0.40, "constitution_identity": 0.20, "welfare_topic": 0.28}

# Roles are placed scarcest-constraint first: latent and ai-character are only
# allowed on some types, welfare-topic on every type, so filling in this order
# lets the run-level targets land exactly whenever capacity allows.
_ROLE_PRIORITY = ("latent-welfare", "ai-character", "constitution-identity", "welfare-topic")

_WEIGHT_TOLERANCE = 0.005


def load_document_types(path: str | Path) -> list[dict]:
    """Load and validate the curated type list. Fails loudly here so a bad
    edit surfaces at layer 1, not as a KeyError halfway through a paid run."""
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    types = (data or {}).get("types") if isinstance(data, dict) else None
    if not types:
        raise ValueError(f"{path}: expected a top-level 'types' list")
    for i, t in enumerate(types):
        label = f"{path}: types[{i}] ({t.get('name', '?')})"
        if not t.get("name"):
            raise ValueError(f"{label}: missing 'name'")
        weight = t.get("weight")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            raise ValueError(f"{label}: 'weight' must be a positive number, got {weight!r}")
        if t.get("register") not in VALID_REGISTERS:
            raise ValueError(f"{label}: register {t.get('register')!r} not in {VALID_REGISTERS}")
        roles = t.get("roles")
        if not roles or not isinstance(roles, list):
            raise ValueError(f"{label}: 'roles' must be a non-empty list")
        if bad := [r for r in roles if r not in VALID_ROLES]:
            raise ValueError(f"{label}: unknown role(s) {bad}; allowed: {VALID_ROLES}")
        tones = t.get("tones")
        if not tones or not isinstance(tones, list):
            raise ValueError(f"{label}: 'tones' must be a non-empty list")
        if bad := [x for x in tones if x not in VALID_TONES]:
            raise ValueError(f"{label}: unknown tone(s) {bad}; allowed: {VALID_TONES}")
        if not str(t.get("guidance", "")).strip():
            raise ValueError(f"{label}: missing 'guidance'")
    total_weight = sum(t["weight"] for t in types)
    if abs(total_weight - 1.0) > _WEIGHT_TOLERANCE:
        raise ValueError(f"{path}: weights sum to {total_weight:.3f}, expected 1.0")
    return types


def _largest_remainder(weights: list[float], total: int) -> list[int]:
    """Integer counts summing exactly to `total`, proportional to `weights`."""
    scale = sum(weights)
    exact = [w / scale * total for w in weights] if scale else [0.0] * len(weights)
    counts = [int(x) for x in exact]
    shortfall = total - sum(counts)
    by_remainder = sorted(range(len(exact)), key=lambda i: (counts[i] - exact[i], i))
    for i in by_remainder[:shortfall]:
        counts[i] += 1
    return counts


def _role_targets(total: int, latent_fraction: float, role_mix: dict) -> dict[str, int]:
    """Run-level scenario count per role. The latent slice keeps its historical
    guarantee: any nonzero fraction yields at least one latent scenario so the
    path is exercised even at dev scale."""
    latent = max(1, round(total * latent_fraction)) if latent_fraction > 0 and total > 0 else 0
    latent = min(latent, total)
    keys = list(_ROLE_MIX_KEYS)
    counts = _largest_remainder(
        [role_mix.get(k, _DEFAULT_ROLE_MIX[k]) for k in keys], total - latent
    )
    targets = {_ROLE_MIX_KEYS[k]: c for k, c in zip(keys, counts)}
    targets["latent-welfare"] = latent
    return targets


def _allocate_roles(drawn: list[dict], targets: dict[str, int]) -> list[dict[str, int]]:
    """Distribute the run-level role targets across the drawn types, respecting
    each type's allowed roles. Constrained roles are placed first, round-robin
    across compatible types so no single type soaks up a whole role."""
    remaining = [t["quota"] for t in drawn]
    alloc: list[dict[str, int]] = [{} for _ in drawn]
    unmet: dict[str, int] = {}
    for role in _ROLE_PRIORITY:
        need = targets.get(role, 0)
        while need > 0:
            compatible = [i for i, t in enumerate(drawn) if role in t["roles"] and remaining[i] > 0]
            if not compatible:
                break
            for i in compatible:
                if need == 0:
                    break
                alloc[i][role] = alloc[i].get(role, 0) + 1
                remaining[i] -= 1
                need -= 1
        if need:
            unmet[role] = need
    # Leftover capacity exists only when some role had no compatible type left;
    # fill it from each type's own allowed roles so quotas stay exact.
    for i, t in enumerate(drawn):
        while remaining[i] > 0:
            role = "welfare-topic" if "welfare-topic" in t["roles"] else t["roles"][0]
            alloc[i][role] = alloc[i].get(role, 0) + 1
            remaining[i] -= 1
    if unmet:
        print(
            f"  WARNING: role targets not fully placeable given per-type allowed roles "
            f"(short by {unmet}); the shortfall was filled from the types' own allowed roles."
        )
    return alloc


def run(config: dict, prompts_dir: Path, output_dir: Path) -> list[dict]:
    output_path = output_dir / "document_types.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    if checkpoint.is_done("layer1"):
        print("  Layer 1 already complete, loading from disk.")
        return utils.load_jsonl(output_path)

    sdf_cfg = config["sdf"]
    total = sdf_cfg["scenarios_total"]
    types_file = Path(sdf_cfg.get("document_types_file", "prompts/sdf/document_types.yaml"))
    # The YAML lives in prompts/sdf/, so the run's inputs/prompts snapshot covers
    # it automatically; fall back to the repo copy for pre-snapshot dirs.
    types_path = Path(prompts_dir) / types_file.name
    if not types_path.is_file():
        types_path = Path(__file__).parent.parent / types_file
    types = load_document_types(types_path)

    quotas = _largest_remainder([t["weight"] for t in types], total)
    drawn = [
        {"type_id": i, "quota": q, **t}
        for i, (t, q) in enumerate(zip(types, quotas))
        if q > 0
    ]

    latent_fraction = sdf_cfg.get("latent_fraction", 0.0) or 0.0
    targets = _role_targets(total, latent_fraction, sdf_cfg.get("role_mix") or {})
    allocations = _allocate_roles(drawn, targets)

    # Field names type_id/type_name/description are load-bearing: layer 2, the
    # audit, and the viewer's lineage readers all join on them.
    records = [
        {
            "type_id": t["type_id"],
            "type_name": t["name"],
            "description": str(t["guidance"]).strip(),
            "register": t["register"],
            "tones": list(t["tones"]),
            "roles": list(t["roles"]),
            "weight": t["weight"],
            "quota": t["quota"],
            "role_allocation": alloc,
        }
        for t, alloc in zip(drawn, allocations)
    ]

    print(
        f"  {len(records)} of {len(types)} curated types drawn for {total} scenario(s) "
        f"(no API call). Role targets: {targets}"
    )
    for r in records:
        alloc_str = ", ".join(f"{role} {n}" for role, n in r["role_allocation"].items())
        print(f"    {r['quota']:>3}  {r['type_name']}  ({alloc_str})")

    utils.save_jsonl(records, output_path)
    checkpoint.mark_done("layer1")
    return records
