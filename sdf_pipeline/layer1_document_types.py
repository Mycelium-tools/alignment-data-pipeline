"""Layer 1: Generate top-level document type categories."""

import math
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

    count = config["sdf"]["document_types_count"]
    min_ai_character = math.ceil(count / 3)

    preamble = utils.load_prompt(prompts_dir / "preamble.txt")
    prompt = utils.load_prompt(
        prompts_dir / "layer1.txt",
        preamble=preamble,
        count=count,
        min_ai_character=min_ai_character,
    )

    print(f"  Generating {count} document types (min {min_ai_character} with an AI character)...")
    raw = api.call_claude(user_message=prompt, model=config["sdf"].get("draft_model"),
                          stage="layer1")

    doc_types = utils.coerce_record_list(utils.extract_json(raw))
    if not doc_types:
        raise RuntimeError(
            "layer 1 response did not contain a JSON array of document-type objects; "
            f"response begins: {raw[:200]!r}"
        )

    records = []
    for i, dt in enumerate(doc_types):
        record = {
            "type_id": i,
            "type_name": dt["type_name"],
            "description": dt["description"],
            "tone": dt.get("tone", "neutral"),
        }
        records.append(record)

    print(f"  Generated {len(records)} document types.")
    if len(records) > count:
        # Known small-count behavior: the diversity rules (e.g. "no form should
        # dominate") imply a floor the model honors over a tiny `count`.
        # Downstream cost scales with what was actually generated, not the knob.
        print(
            f"  NOTE: model returned {len(records)} types for count={count}; "
            f"all are kept — downstream layers (and cost) scale accordingly."
        )
    utils.save_jsonl(records, output_path)
    checkpoint.mark_done("layer1")
    return records
