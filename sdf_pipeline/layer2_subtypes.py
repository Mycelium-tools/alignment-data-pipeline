"""Layer 2: Generate subtypes for each document type."""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, constitution_loader, textstats, utils
from sdf_pipeline import composition


def _dedup_key(record: dict) -> str:
    return f"{record['subtype_name']} {record['description']}"


def _avoid_note(prior: list[dict], rng: random.Random, k: int = 12) -> str:
    """Cross-call state: show later generation calls a sample of subtypes that
    already exist (from other categories), so diversity doesn't rely on each
    call being blind-lucky — the no-cross-call-state failure the haiku-test2
    report identified. Empty when nothing exists yet (first wave, fresh run)."""
    if not prior:
        return ""
    sample = rng.sample(prior, min(k, len(prior)))
    lines = "\n".join(f"- {r['subtype_name']}: {r['description'][:100]}" for r in sample)
    return ("\nAlready generated for OTHER categories in this corpus — do NOT produce subtypes "
            "that repeat or closely resemble any of these; go somewhere new:\n" + lines)


def run(config: dict, prompts_dir: Path, output_dir: Path, doc_types: list[dict]) -> list[dict]:
    output_path = output_dir / "subtypes.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    lang_dist = config.get("language_distribution", {"en": 1.0})
    languages_str = list(lang_dist.keys())
    count = config["sdf"]["subtypes_per_type"]
    preamble = utils.load_prompt(prompts_dir / "preamble.txt")
    # Axis assignments are deterministic per grid slot; the principle count is
    # derived from the CSV, never hardcoded (the reading is actively edited).
    try:
        n_principles = len(constitution_loader.load_principles(
            utils.resolve_constitution_dir(prompts_dir)))
    except FileNotFoundError:
        n_principles = len(constitution_loader.load_principles())

    existing = utils.load_jsonl(output_path)
    results = list(existing)

    pending = [dt for dt in doc_types if not checkpoint.is_done(f"type_{dt['type_id']}")]

    def generate_subtypes(dt: dict, avoid_note: str = "") -> list[dict]:
        type_id = dt["type_id"]
        domain_assignments = "\n".join(
            f"{i + 1}. {composition.assigned_domain(type_id, i, count)}"
            for i in range(count)
        )
        prompt = utils.load_prompt(
            prompts_dir / "layer2.txt",
            preamble=preamble,
            type_name=dt["type_name"],
            description=dt["description"],
            tone=dt["tone"],
            count=count,
            languages=", ".join(languages_str),
            domain_assignments=domain_assignments,
            avoid_note=avoid_note,
        )

        raw = api.call_claude(user_message=prompt, model=config["sdf"].get("draft_model"),
                              stage="layer2")
        subtypes = utils.coerce_record_list(utils.extract_json(raw))
        if not subtypes:
            # Fail loudly and unmark: the type stays un-checkpointed, so
            # --resume --layer 2 retries it with a fresh sample.
            raise RuntimeError(
                f"layer 2 response for type {type_id} ({dt['type_name']!r}) did not "
                f"contain a JSON array of subtype objects; response begins: {raw[:200]!r}"
            )
        records = []
        for i, st in enumerate(subtypes):
            lang = st.get("language", "en")
            if lang not in lang_dist:
                lang = utils.sample_language(lang_dist)
            records.append({
                "subtype_id": f"{type_id}_{i}",
                "type_id": type_id,
                "type_name": dt["type_name"],
                "subtype_name": st["subtype_name"],
                "description": st["description"],
                "tone": dt["tone"],
                "language": lang,
                **composition.assign_axes(type_id, i, count, n_principles),
            })
        return records

    # Near-duplicate subtype filter: diversity downstream is capped by this
    # layer, so a repeated idea here multiplies into repeated documents. The
    # threshold is word-shingle cosine (see shared/textstats.py); null/absent
    # disables. Previously accepted subtypes are never dropped — only newly
    # generated ones are filtered, against everything kept so far. The
    # incremental index shingles each subtype exactly once and is seeded from
    # any subtypes already on disk, so --resume dedups against them too.
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
            print(f"    dropped {len(dropped)} near-duplicate subtype(s) "
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
            wave, utils.parallel_map(lambda dt: generate_subtypes(dt, note), wave, workers)
        ):
            print(f"  Generated {len(records)} subtypes for type {dt['type_id']}: {dt['type_name'][:60]}")
            for record in filter_new(records):
                results.append(record)
                utils.append_jsonl(record, output_path)
            checkpoint.mark_done(f"type_{dt['type_id']}")

    print(f"  Total subtypes: {len(results)}")
    return results
