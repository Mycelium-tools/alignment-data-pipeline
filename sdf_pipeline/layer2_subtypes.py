"""Layer 2: Split each document type into several subtypes."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils


def run(config: dict, prompts_dir: Path, output_dir: Path, doc_types: list[dict]) -> list[dict]:
    output_path = output_dir / "subtypes.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

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
            count=count,
        )

        raw = api.call_claude(user_message=prompt)
        text = raw.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
        if text.endswith("```"):
            text = "\n".join(text.split("\n")[:-1])

        subtypes = json.loads(text.strip())
        # The prompt asks for an array of strings; if the model returns objects
        # instead, flatten their values so a usable description still reaches
        # layer 3 rather than a str(dict) repr.
        subtypes = [
            st if isinstance(st, str)
            else " — ".join(str(v) for v in st.values()) if isinstance(st, dict)
            else str(st)
            for st in subtypes
        ]
        return [
            {
                "subtype_id": f"{type_id}_{i}",
                "type_id": type_id,
                "type_name": dt["type_name"],
                "subtype": st,
            }
            for i, st in enumerate(subtypes)
        ]

    workers = config.get("workers", 1)
    for dt, records in zip(pending, utils.parallel_map(generate_subtypes, pending, workers)):
        print(f"  Generated {len(records)} subtypes for type {dt['type_id']}: {dt['type_name'][:60]}")
        for record in records:
            results.append(record)
            utils.append_jsonl(record, output_path)
        checkpoint.mark_done(f"type_{dt['type_id']}")

    print(f"  Total subtypes: {len(results)}")
    return results
