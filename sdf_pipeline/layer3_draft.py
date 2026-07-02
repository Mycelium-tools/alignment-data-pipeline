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

    for st in subtypes:
        sid = st["subtype_id"]
        if checkpoint.is_done(sid):
            continue

        print(f"  Drafting {count} docs for subtype: {st['subtype_name'][:60]}...")
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

        # Extract <document>...</document> blocks (this also drops the <angles>
        # brainstorm block); fall back to the whole output minus <angles> if untagged
        docs = [m.strip() for m in _DOC_TAG_RE.findall(raw) if m.strip()]
        if not docs:
            fallback = re.sub(r"<angles>.*?</angles>", "", raw, flags=re.DOTALL).strip()
            if fallback:
                docs = [fallback]

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
