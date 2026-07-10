"""Layer 2: Generate concrete scenario briefs for each curated document type.

One LLM call per document type, asking for that type's quota of scenarios —
each a fully specified individual document (who wrote it, where, about what,
and why), with a per-scenario role and tone drawn from the type's allowed sets.
Records keep the historical subtype_* field names and file layout so layers
3-5, the audit, and the viewer are untouched.
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, textstats, utils


def _dedup_key(record: dict) -> str:
    return f"{record['subtype_name']} {record['description']}"


def _avoid_note(prior: list[dict], rng: random.Random, k: int = 12) -> str:
    """Cross-call state: show later generation calls a sample of scenarios that
    already exist (from other types), so diversity doesn't rely on each call
    being blind-lucky — the no-cross-call-state failure the haiku-test2 report
    identified. Empty when nothing exists yet (first wave, fresh run)."""
    if not prior:
        return ""
    sample = rng.sample(prior, min(k, len(prior)))
    lines = "\n".join(f"- {r['subtype_name']}: {r['description'][:100]}" for r in sample)
    return ("\nAlready generated for OTHER document types in this corpus — do NOT produce "
            "scenarios that repeat or closely resemble any of these; go somewhere new:\n" + lines)


def run(config: dict, prompts_dir: Path, output_dir: Path, doc_types: list[dict]) -> list[dict]:
    output_path = output_dir / "subtypes.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    lang_dist = config.get("language_distribution", {"en": 1.0})
    languages_str = list(lang_dist.keys())
    preamble = utils.load_prompt(prompts_dir / "preamble.txt")

    existing = utils.load_jsonl(output_path)
    results = list(existing)

    pending = [dt for dt in doc_types if not checkpoint.is_done(f"type_{dt['type_id']}")]

    def generate_scenarios(dt: dict, avoid_note: str = "") -> list[dict]:
        type_id = dt["type_id"]
        count = dt["quota"]  # per-type quota from layer 1, not a global knob
        allowed_roles = dt.get("roles") or [dt.get("role", "welfare-topic")]
        allowed_tones = dt.get("tones") or [dt.get("tone", "neutral")]
        role_allocation = "\n".join(
            f"- {role}: {n}" for role, n in (dt.get("role_allocation") or {}).items() if n
        )
        prompt = utils.load_prompt(
            prompts_dir / "layer2.txt",
            preamble=preamble,
            type_name=dt["type_name"],
            description=dt["description"],
            register=dt.get("register", "expository"),
            tones=", ".join(allowed_tones),
            count=count,
            role_allocation=role_allocation,
            languages=", ".join(languages_str),
            avoid_note=avoid_note,
        )

        raw = api.call_claude(user_message=prompt, model=config["sdf"].get("draft_model"),
                              stage="layer2")
        scenarios = utils.extract_json(raw)
        records = []
        for i, sc in enumerate(scenarios):
            lang = sc.get("language", "en")
            if lang not in lang_dist:
                lang = utils.sample_language(lang_dist)
            # role and tone are per scenario now; validate against the type's
            # allowed sets and fall back to the first allowed value on a bad
            # parse rather than crashing a paid call.
            role = sc.get("role")
            if role not in allowed_roles:
                print(f"    WARNING: type {type_id} scenario {i}: role {role!r} not allowed for "
                      f"{dt['type_name']!r}; falling back to {allowed_roles[0]!r}")
                role = allowed_roles[0]
            tone = sc.get("tone")
            if tone not in allowed_tones:
                print(f"    WARNING: type {type_id} scenario {i}: tone {tone!r} not allowed for "
                      f"{dt['type_name']!r}; falling back to {allowed_tones[0]!r}")
                tone = allowed_tones[0]
            records.append({
                "subtype_id": f"{type_id}_{i}",
                "type_id": type_id,
                # Layer 3 derives the genre for its voice note via
                # type_name.split(":")[0]; curated names contain no colon, so
                # the full name is the genre — correct as is.
                "type_name": dt["type_name"],
                "role": role,
                "subtype_name": sc["subtype_name"],
                "description": sc["description"],
                "tone": tone,
                "register": dt.get("register", "expository"),
                "language": lang,
            })
        return records

    # Near-duplicate scenario filter: diversity downstream is capped by this
    # layer, so a repeated idea here multiplies into repeated documents. The
    # threshold is word-shingle cosine (see shared/textstats.py); null/absent
    # disables. Previously accepted scenarios are never dropped — only newly
    # generated ones are filtered, against everything kept so far. The
    # incremental index shingles each scenario exactly once and is seeded from
    # any scenarios already on disk, so --resume dedups against them too.
    dedup_threshold = config["sdf"].get("subtype_dedup_threshold")
    dropped_path = output_dir / "subtypes_dropped.jsonl"
    dedup = (
        textstats.IncrementalNearDup(dedup_threshold, seed_texts=[_dedup_key(r) for r in results])
        if dedup_threshold else None
    )

    def filter_new(records: list[dict]) -> list[dict]:
        if not dedup or not records:
            return records
        keep_idx, dropped = dedup.filter([_dedup_key(r) for r in records])
        for d in dropped:
            rec = records[d["index"]]
            utils.append_jsonl({**rec, "similarity": d["similarity"]}, dropped_path)
        if dropped:
            print(f"    dropped {len(dropped)} near-duplicate scenario(s) "
                  f"(shingle cosine >= {dedup_threshold}; see subtypes_dropped.jsonl)")
        return [records[i] for i in keep_idx]

    # Waves: types within a wave run in parallel; between waves the avoid-note
    # is refreshed from everything accepted so far, so later calls see earlier
    # output. Wave size = workers, so this adds no wall-clock over plain
    # parallel_map on a single-wave run.
    workers = config.get("workers", 1)
    wave_size = max(workers, 1)
    for wave_start in range(0, len(pending), wave_size):
        wave = pending[wave_start : wave_start + wave_size]
        note = _avoid_note(results, random.Random(f"layer2-avoid:{wave_start}"))
        for dt, records in zip(
            wave, utils.parallel_map(lambda dt: generate_scenarios(dt, note), wave, workers)
        ):
            print(f"  Generated {len(records)} scenario(s) for type {dt['type_id']}: {dt['type_name'][:60]}")
            for record in filter_new(records):
                results.append(record)
                utils.append_jsonl(record, output_path)
            checkpoint.mark_done(f"type_{dt['type_id']}")

    print(f"  Total scenarios: {len(results)}")
    return results
