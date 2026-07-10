"""Layer 3: Generate document drafts for each subtype."""

import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, textstats, utils, constitution_loader

_DOC_TAG_RE = re.compile(r"<document>(.*?)</document>", re.DOTALL)


def run(config: dict, prompts_dir: Path, output_dir: Path, subtypes: list[dict]) -> list[dict]:
    output_path = output_dir / "drafts.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    preamble = utils.load_prompt(prompts_dir / "preamble.txt")
    # The TCW drafting prompt takes the constitution as one block; ours is the
    # Claude constitution joined with the distilled welfare principles.
    constitution = constitution_loader.load_constitution_with_principles(
        utils.resolve_constitution_dir(prompts_dir)
    )

    existing = utils.load_jsonl(output_path)
    results = list(existing)

    pending = [st for st in subtypes if not checkpoint.is_done(st["subtype_id"])]

    def draft_documents(st: dict) -> list[dict]:
        # The TCW template takes the subtype as a single {subtype} block; compose
        # it from the layer-1/2 record.
        subtype_block = (
            f"Document type: {st['type_name']}\n"
            f"Subtype: {st['subtype_name']}\n"
            f"Specification: {st['description']}\n"
            f"Tone: {st['tone']}"
        )

        prompt = utils.load_prompt(
            prompts_dir / "layer3.txt",
            preamble=preamble,
            subtype=subtype_block,
            CONSTITUTION=constitution,
        )

        raw = api.call_claude(
            user_message=prompt, max_tokens=6000, model=config["sdf"].get("draft_model"),
            stage="layer3",
        )

        # Extract <document>...</document> blocks; fall back to the whole output
        # if untagged. A closed tag implies a complete document; the untagged
        # fallback may be a token-capped cutoff, so trim it back to the last
        # complete sentence — a mid-sentence ending is itself a training
        # artifact. Trailing separator-only lines (a bare closing ---) are
        # stripped from every doc.
        docs = [
            textstats.strip_trailing_separators(m.strip())
            for m in _DOC_TAG_RE.findall(raw)
            if m.strip()
        ]
        docs = [d for d in docs if d]
        if not docs:
            fallback = re.sub(r"<angles>.*?(?:</angles>|\Z)", "", raw, flags=re.DOTALL).strip()
            fallback = textstats.trim_unfinished(textstats.strip_trailing_separators(fallback))
            if fallback:
                docs = [fallback]

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
