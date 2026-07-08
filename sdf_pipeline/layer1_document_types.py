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
    # Latent-welfare slice: ordinary other-domain categories where welfare
    # surfaces once as a concrete detail. A nonzero fraction guarantees at
    # least one category so the path is exercised even at dev scale.
    latent_fraction = config["sdf"].get("latent_fraction", 0.0) or 0.0
    latent_count = max(1, round(count * latent_fraction)) if latent_fraction > 0 else 0

    preamble = utils.load_prompt(prompts_dir / "preamble.txt")
    prompt = utils.load_prompt(
        prompts_dir / "layer1.txt",
        preamble=preamble,
        count=count,
        min_ai_character=min_ai_character,
        latent_count=latent_count,
    )

    print(
        f"  Generating {count} document types "
        f"(min {min_ai_character} ai-character, {latent_count} latent-welfare)..."
    )
    raw = api.call_claude(user_message=prompt, model=config["sdf"].get("draft_model"))

    doc_types = utils.extract_json(raw)

    records = []
    for i, dt in enumerate(doc_types):
        record = {
            "type_id": i,
            "type_name": dt["type_name"],
            "description": dt["description"],
            "role": dt.get("role", "welfare-topic"),
            "tone": dt.get("tone", "neutral"),
            "register": dt.get("register", "expository"),
        }
        records.append(record)

    ai_character_count = sum(1 for r in records if r["role"] == "ai-character")
    latent_actual = sum(1 for r in records if r["role"] == "latent-welfare")
    first_person = sum(1 for r in records if r["register"] == "first-person")
    print(
        f"  Generated {len(records)} document types ({ai_character_count} ai-character, "
        f"{latent_actual} latent-welfare, {first_person} first-person)."
    )
    if len(records) > count:
        # Known small-count behavior: the diversity rules (e.g. "no form >1/10
        # of categories") imply a floor the model honors over a tiny `count`.
        # Downstream cost scales with what was actually generated, not the knob.
        print(
            f"  NOTE: model returned {len(records)} types for count={count}; "
            f"all are kept — downstream layers (and cost) scale accordingly."
        )
    utils.save_jsonl(records, output_path)
    checkpoint.mark_done("layer1")
    return records
