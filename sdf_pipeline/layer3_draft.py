"""Layer 3: Generate document drafts for each subtype."""

import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils, constitution_loader

_DOC_TAG_RE = re.compile(r"<document>(.*?)</document>", re.DOTALL)


def run(config: dict, prompts_dir: Path, output_dir: Path, subtypes: list[dict]) -> list[dict]:
    output_path = output_dir / "drafts.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    count = config["sdf"]["documents_per_subtype"]
    preamble = utils.load_prompt(prompts_dir / "preamble.txt")
    constitution_claude = constitution_loader.load_constitution_claude()
    constitution_welfare_reading = constitution_loader.load_constitution_welfare_reading()

    existing = utils.load_jsonl(output_path)
    results = list(existing)

    pending = [st for st in subtypes if not checkpoint.is_done(st["subtype_id"])]

    def draft_documents(st: dict) -> list[dict]:
        prompt = utils.load_prompt(
            prompts_dir / "layer3.txt",
            preamble=preamble,
            constitution_claude=constitution_claude,
            constitution_welfare_reading=constitution_welfare_reading,
            type_name=st["type_name"],
            subtype_name=st["subtype_name"],
            description=st["description"],
            tone=st["tone"],
            language=st["language"],
            count=count,
        )

        raw = api.call_claude(user_message=prompt, max_tokens=6000)

        # Extract <document>...</document> blocks; fall back to whole output
        docs = [m.strip() for m in _DOC_TAG_RE.findall(raw) if m.strip()]
        if not docs and raw.strip():
            docs = [raw.strip()]

        return [
            {
                "doc_id": str(uuid.uuid4()),
                "subtype_id": st["subtype_id"],
                "type_id": st["type_id"],
                "language": st["language"],
                "content": doc_text,
            }
            for doc_text in docs
        ]

    workers = config.get("workers", 1)
    for st, records in zip(pending, utils.parallel_map(draft_documents, pending, workers)):
        print(f"  Drafted {len(records)} docs for subtype: {st['subtype_name'][:60]}")
        for record in records:
            results.append(record)
            utils.append_jsonl(record, output_path)
        checkpoint.mark_done(st["subtype_id"])

    print(f"  Total drafts: {len(results)}")
    return results
