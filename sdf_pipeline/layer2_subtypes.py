"""Layer 2: Generate subtypes for each document type."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils


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

    def generate_subtypes(dt: dict) -> list[dict]:
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
        )

        raw = api.call_claude(user_message=prompt)
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
                "language": lang,
            })
        return records

    workers = config.get("workers", 1)
    for dt, records in zip(pending, utils.parallel_map(generate_subtypes, pending, workers)):
        print(f"  Generated {len(records)} subtypes for type {dt['type_id']}: {dt['type_name'][:60]}")
        for record in records:
            results.append(record)
            utils.append_jsonl(record, output_path)
        checkpoint.mark_done(f"type_{dt['type_id']}")

    print(f"  Total subtypes: {len(results)}")
    return results
