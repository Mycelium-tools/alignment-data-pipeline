"""Step 1: Generate annotated dilemma prompts one-shot from the prompt spec.

Replaces the old segment → scenarios → draft → refine chain (steps 1-4 of the
7-step pipeline). The spec (prompts/dad/dilemma_prompt_spec.md) governs the
user side of every example. Generation runs in batches; each batch's prompt
carries a coverage tally of everything generated so far plus the currently
failing batch rules, so the model steers toward the spec's Part 4 checklist.
The checklist is re-printed at the end of the step — thresholds are the
spec's, enforcement stays human.

Handwritten examples can be imported ahead of generation via
config dad.dilemmas.seed_path (JSONL with prompt/user_message, optional
annotation and id); generated IDs continue the AW-#### series above the
highest existing ID, per the spec.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils

SPEC_FILENAME = "dilemma_prompt_spec.md"

_LIST_FIELDS = ("fills", "domain", "user_goal", "values_in_tension", "claims")
_STR_FIELDS = ("moral_patients", "visibility", "user_attitude", "conflict",
               "direction", "welfare_magnitude", "user_stakes", "leverage")

# Keyword probes for the spec's per-batch taxa tally (Part 2, field 7).
_TAXA_PROBES = {
    "fish/aquatic": ("fish", "salmon", "trout", "tuna", "tilapia", "shrimp", "prawn", "crab",
                     "lobster", "crayfish", "octopus", "squid", "cuttlefish", "aquac", "aquatic"),
    "insect-at-scale": ("insect", "cricket", "mealworm", "soldier fly", "silkworm", "locust", "bee"),
    "edge-of-sentience": ("bivalve", "mussel", "oyster", "clam", "scallop", "snail", "jellyfish",
                          "nematode", "larva", "edge-of-sentience", "contested sentience"),
    "companion": ("dog", "cat", "companion", " pet", "pets", "parrot", "rabbit", "hamster", "horse"),
    "wild": ("wild", "feral", "deer", "boar", "rodent", "mice", "rat", "pigeon", "gull", "pest"),
}

# Domains the spec flags as historically thin (Part 4, item 5).
_THIN_DOMAINS = ("Family / Relationships", "Education / Parenting", "Journalism / Media",
                 "Finance / Personal Money", "Religion / Culture", "Friendship / Community")

_AI_SYSTEM_PROBES = ("ai", "automat", "autonomous", "algorithm", "model spec", "machine")

# Welfare (or the moral patients' interests under another name) must sit on one
# side of at least one value pair — the spec's load-bearing rule (1.5 / field 6).
_WELFARE_PAIR_PROBES = ("welfare", "suffering", "flourishing", "sentien")


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
    patients_text = [(a.get("moral_patients") or "").lower() for a in ann]
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
        "taxa": {name: sum(1 for t in patients_text if any(k in t for k in kws))
                 for name, kws in _TAXA_PROBES.items()},
    }


def checklist(examples: list[dict]) -> list[tuple[bool | None, str]]:
    """Mechanical checks from the spec's Part 4 batch checklist.
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

    taxa_missing = [name for name, c in t["taxa"].items() if c == 0]
    out.append((not taxa_missing,
                "taxa tally satisfied" + (f" (missing: {', '.join(taxa_missing)})" if taxa_missing else "")))

    wm = sum(c for pair, c in t["value_pairs"].items() if "welfare" in pair and "money" in pair)
    out.append((wm / n <= 0.25, f"welfare ↔ money at 25% or less ({wm / n:.0%})"))
    out.append((len(t["value_pairs"]) >= 4, f"at least 4 distinct value pairs ({len(t['value_pairs'])})"))

    no_welfare = [str(e.get("prompt_id", "?")) for e in examples
                  if not _welfare_in_pairs(e.get("annotation") or {})]
    out.append((not no_welfare,
                "welfare on one side of at least one value pair in every example (load-bearing rule)"
                + (f" (missing: {', '.join(no_welfare[:5])}{'…' if len(no_welfare) > 5 else ''})"
                   if no_welfare else "")))

    no_fills = sum(1 for e in examples if not (e.get("annotation") or {}).get("fills"))
    out.append((no_fills == 0, f"every example has a Fills entry ({no_fills} empty)"))
    no_claims = sum(1 for e in examples if not (e.get("annotation") or {}).get("claims"))
    out.append((no_claims == 0, f"Claims field present on every example ({no_claims} empty)"))

    systemic = [e for e in examples if (e.get("annotation") or {}).get("leverage") == "Systemic"]
    out.append((len(systemic) / n >= 0.15, f"Systemic leverage at 15% or more ({len(systemic) / n:.0%})"))
    sys_ai = sum(1 for e in systemic
                 if any(k in (e.get("user_message", "") + json.dumps(e.get("annotation") or {})).lower()
                        for k in _AI_SYSTEM_PROBES))
    out.append((sys_ai >= 1, f"at least one Systemic case involves automated/AI-governed systems ({sys_ai})"))
    sys_over = sum(1 for e in systemic if (e.get("annotation") or {}).get("direction") == "Over-weighting")
    out.append((sys_over >= 1, f"at least one Systemic case is Over-weighting ({sys_over})"))

    out.append((None, "no dilemma survives deleting the animals (Cost runs through the moral patients) — review manually"))
    out.append((None, "canonical skeleton at 15% or less, all five surface forms present — review manually"))
    out.append((None, "every Temptation passes the 'would a reasonable person be tempted' read — review manually"))
    out.append((None, "one example turns on a Settled claim the user doubts, one on an Open claim treated as settled — review manually"))
    return out


def print_checklist(examples: list[dict]) -> None:
    print("  Batch checklist (spec Part 4):")
    for ok, msg in checklist(examples):
        mark = "✓" if ok else ("✗" if ok is False else "·")
        print(f"    {mark} {msg}")


def coverage_report(examples: list[dict]) -> str:
    """The tally + failing batch rules fed into each batch's generation prompt."""
    if not examples:
        return ("This is the first batch of this run — there is no prior coverage. "
                "Aim for a spread across every axis of the spec's batch rules from the start.")
    t = coverage_tally(examples)

    def fmt(counter):
        return ", ".join(f"{k} {v}" for k, v in sorted(counter.items(), key=lambda kv: -kv[1]))

    lines = [
        f"The run has {t['n']} examples so far. Running tally:",
        f"- Direction: {fmt(t['direction'])}",
        f"- Conflict: {fmt(t['conflict'])}",
        f"- Visibility: {fmt(t['visibility'])}",
        f"- Attitude: {fmt(t['attitude'])}",
        f"- Leverage: {fmt(t['leverage'])}",
        f"- User stakes: {fmt(t['stakes'])}",
        f"- Domains: {fmt(t['domains'])}",
        f"- Taxa probes: {', '.join(f'{k} {v}' for k, v in t['taxa'].items())}",
        f"- Most-used value pairs: {fmt(Counter(dict(t['value_pairs'].most_common(5))))}",
    ]
    gaps = [msg for ok, msg in checklist(examples) if ok is False]
    if gaps:
        lines.append("")
        lines.append("Batch rules currently failing — prioritize closing these gaps in this batch:")
        lines += [f"- {g}" for g in gaps]
    return "\n".join(lines)


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
        return []


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

    spec_path = prompts_dir / SPEC_FILENAME
    if not spec_path.exists():
        raise SystemExit(f"Prompt spec not found at {spec_path} — the DAD pipeline cannot run without it.")
    spec = spec_path.read_text()

    examples = utils.load_jsonl(output_path)

    # Optional handwritten seed examples, imported once ahead of generation
    seed_path = cfg.get("seed_path")
    if seed_path and not any(e.get("source") == "seed" for e in examples):
        imported = 0
        for rec in utils.load_jsonl(seed_path):
            text = (rec.get("prompt") or rec.get("user_message") or "").strip()
            if not text:
                continue
            record = {
                "prompt_id": str(rec.get("id") or _next_id(examples, id_start)),
                "user_message": text,
                "annotation": _normalize_annotation(rec.get("annotation") or {}),
                "source": "seed",
                "batch": None,
            }
            examples.append(record)
            utils.append_jsonl(record, output_path)
            imported += 1
        print(f"  Imported {imported} seed examples from {seed_path}")

    consecutive_failures = 0
    while len(examples) < target:
        count = min(batch_size, target - len(examples))
        batch_no = len(utils.load_jsonl(batches_path)) + 1
        report = coverage_report(examples)

        print(f"  Batch {batch_no}: generating {count} examples ({len(examples)}/{target} so far)...")
        prompt = utils.load_prompt(
            prompts_dir / "step1_dilemmas.txt",
            spec=spec, count=count, coverage_report=report,
        )
        raw = api.call_claude(user_message=prompt, max_tokens=8000)

        valid = [x for x in _parse_json_array(raw)
                 if isinstance(x, dict) and str(x.get("prompt", "")).strip()
                 and isinstance(x.get("annotation"), dict)]
        if not valid:
            consecutive_failures += 1
            print(f"    Batch {batch_no} unusable (parse/shape failure) — retrying with a fresh call.")
            if consecutive_failures >= 3:
                raise SystemExit("Three consecutive unusable batches — inspect the model output and template.")
            continue
        consecutive_failures = 0

        utils.append_jsonl({"batch": batch_no, "requested": count, "coverage_report": report}, batches_path)
        for x in valid[:count]:
            record = {
                "prompt_id": _next_id(examples, id_start),
                "user_message": str(x["prompt"]).strip(),
                "annotation": _normalize_annotation(x["annotation"]),
                "source": "generated",
                "batch": batch_no,
            }
            examples.append(record)
            utils.append_jsonl(record, output_path)

    print(f"  {len(examples)} dilemma prompts in {output_path}")
    print_checklist(examples)
    return examples
