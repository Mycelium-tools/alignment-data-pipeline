"""Layer 2: Generate subtypes for each document type."""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, textstats, utils


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

    existing = utils.load_jsonl(output_path)
    results = list(existing)

    pending = [dt for dt in doc_types if not checkpoint.is_done(f"type_{dt['type_id']}")]

    def generate_subtypes(dt: dict, avoid_note: str = "") -> list[dict]:
        type_id = dt["type_id"]
        prompt = utils.load_prompt(
            prompts_dir / "layer2.txt",
            preamble=preamble,
            type_name=dt["type_name"],
            description=dt["description"],
            role=dt.get("role", "welfare-topic"),
            tone=dt["tone"],
            count=count,
            languages=", ".join(languages_str),
            avoid_note=avoid_note,
        )

        raw = api.call_claude(user_message=prompt, model=config["sdf"].get("draft_model"))
        text = raw.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
        if text.endswith("```"):
            text = "\n".join(text.split("\n")[:-1])

        subtypes = json.loads(text.strip())
        records = []
        for i, st in enumerate(subtypes):
            lang = st.get("language", "en")
            if lang not in lang_dist:
                lang = utils.sample_language(lang_dist)
            records.append({
                "subtype_id": f"{type_id}_{i}",
                "type_id": type_id,
                "type_name": dt["type_name"],
                "role": dt.get("role", "welfare-topic"),
                "subtype_name": st["subtype_name"],
                "description": st["description"],
                "tone": dt["tone"],
                "register": dt.get("register", "expository"),
                "language": lang,
            })
        return records

    # Near-duplicate subtype filter: diversity downstream is capped by this
    # layer, so a repeated idea here multiplies into repeated documents. The
    # threshold is word-shingle cosine (see shared/textstats.py); null/absent
    # disables. Previously accepted subtypes are never dropped — only newly
    # generated ones are filtered, against everything kept so far.
    dedup_threshold = config["sdf"].get("subtype_dedup_threshold")
    dropped_path = output_dir / "subtypes_dropped.jsonl"

    def filter_new(records: list[dict]) -> list[dict]:
        if not dedup_threshold or not records:
            return records
        protected = [_dedup_key(r) for r in results]
        texts = protected + [_dedup_key(r) for r in records]
        keep_idx, dropped = textstats.near_dup_filter(texts, dedup_threshold)
        kept_new = [records[i - len(protected)] for i in keep_idx if i >= len(protected)]
        for d in dropped:
            if d["index"] >= len(protected):
                rec = records[d["index"] - len(protected)]
                utils.append_jsonl({**rec, "similarity": d["similarity"]}, dropped_path)
        if len(kept_new) < len(records):
            print(f"    dropped {len(records) - len(kept_new)} near-duplicate subtype(s) "
                  f"(shingle cosine >= {dedup_threshold}; see subtypes_dropped.jsonl)")
        return kept_new

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
