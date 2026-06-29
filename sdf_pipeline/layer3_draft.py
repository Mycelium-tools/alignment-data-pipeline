"""Layer 3: Generate document drafts for each subtype."""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils

_BREAK = "===DOCUMENT_BREAK==="


def run(config: dict, prompts_dir: Path, output_dir: Path, subtypes: list[dict]) -> list[dict]:
    output_path = output_dir / "drafts.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    count = config["sdf"]["documents_per_subtype"]
    preamble = utils.load_prompt(prompts_dir / "preamble.txt")

    existing = utils.load_jsonl(output_path)
    results = list(existing)

    for st in subtypes:
        sid = st["subtype_id"]
        if checkpoint.is_done(sid):
            continue

        print(f"  Drafting {count} docs for subtype: {st['subtype_name'][:60]}...")
        prompt = utils.load_prompt(
            prompts_dir / "layer3.txt",
            preamble=preamble,
            type_name=st["type_name"],
            subtype_name=st["subtype_name"],
            description=st["description"],
            tone=st["tone"],
            language=st["language"],
            count=count,
        )

        raw = api.call_claude(user_message=prompt, max_tokens=6000)

        # Split on document break delimiter
        parts = raw.split(_BREAK)
        docs = [p.strip() for p in parts if p.strip()]

        for doc_text in docs:
            record = {
                "doc_id": str(uuid.uuid4()),
                "subtype_id": sid,
                "type_id": st["type_id"],
                "language": st["language"],
                "content": doc_text,
            }
            results.append(record)
            utils.append_jsonl(record, output_path)

        checkpoint.mark_done(sid)

    print(f"  Total drafts: {len(results)}")
    return results
