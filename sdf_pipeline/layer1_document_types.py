"""Layer 1: Generate top-level document type categories."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils


def run(config: dict, prompts_dir: Path, output_dir: Path) -> list[dict]:
    output_path = output_dir / "document_types.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    if checkpoint.is_done("layer1"):
        print("  Layer 1 already complete, loading from disk.")
        return utils.load_jsonl(output_path)

    preamble = utils.load_prompt(prompts_dir / "preamble.txt")
    prompt = utils.load_prompt(
        prompts_dir / "layer1.txt",
        preamble=preamble,
        count=config["sdf"]["document_types_count"],
    )

    print(f"  Generating {config['sdf']['document_types_count']} document types...")
    raw = api.call_claude(user_message=prompt)

    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = "\n".join(text.split("\n")[:-1])

    doc_types = json.loads(text.strip())

    records = []
    for i, dt in enumerate(doc_types):
        record = {
            "type_id": i,
            "type_name": dt["type_name"],
            "description": dt["description"],
            "tone": dt.get("tone", "neutral"),
        }
        records.append(record)

    utils.save_jsonl(records, output_path)
    checkpoint.mark_done("layer1")
    print(f"  Generated {len(records)} document types.")
    return records
