"""Layer 3: Draft documents for each subtype.

Several documents per subtype are drafted in ONE context window (per TCW): the
first call sends the drafting prompt, and each further document is requested
with a follow-up turn in the same conversation, which raises the chance the
documents come out diverse.
"""

import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils, constitution_loader

_DOC_TAG_RE = re.compile(r"<document>(.*?)</document>", re.DOTALL)


def _extract_documents(raw: str) -> list[str]:
    """Pull <document> blocks out of a response; fall back to the whole text.

    A response can lack a complete tag pair when max_tokens truncates a long
    document mid-write; strip any stray literal tags from the fallback so the
    tag markup never leaks into corpus content (layer 5 remains the quality
    gate for the truncated text itself)."""
    docs = [m.strip() for m in _DOC_TAG_RE.findall(raw) if m.strip()]
    if not docs:
        fallback = raw.replace("<document>", "").replace("</document>", "").strip()
        if fallback:
            docs = [fallback]
    return docs


def run(config: dict, prompts_dir: Path, output_dir: Path, subtypes: list[dict]) -> list[dict]:
    output_path = output_dir / "drafts.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    count = config["sdf"]["documents_per_subtype"]
    preamble = utils.load_prompt(prompts_dir / "preamble.txt")
    # SDF injects the plain Claude constitution only (no sentient-beings reading)
    constitution = constitution_loader.load_constitution_claude(
        utils.resolve_constitution_dir(prompts_dir)
    )
    continue_message = utils.load_prompt(prompts_dir / "layer3_continue.txt")

    existing = utils.load_jsonl(output_path)
    results = list(existing)

    pending = [st for st in subtypes if not checkpoint.is_done(st["subtype_id"])]

    def draft_documents(st: dict) -> list[dict]:
        prompt = utils.load_prompt(
            prompts_dir / "layer3.txt",
            preamble=preamble,
            constitution=constitution,
            subtype=st["subtype"],
        )

        messages = [{"role": "user", "content": prompt}]
        docs: list[str] = []
        for _ in range(count):
            raw = api.call_claude(messages=messages, max_tokens=6000)
            if not raw.strip():
                break  # empty response — can't continue the conversation with an empty assistant turn
            docs.extend(_extract_documents(raw))
            if len(docs) >= count:
                break
            messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": continue_message},
            ]

        return [
            {
                "doc_id": str(uuid.uuid4()),
                "subtype_id": st["subtype_id"],
                "type_id": st["type_id"],
                "content": doc_text,
            }
            # cap at count: a turn that volunteers extra <document> blocks must
            # not inflate the corpus (and layers 4-5 cost) past the config knob
            for doc_text in docs[:count]
        ]

    workers = config.get("workers", 1)
    for st, records in zip(pending, utils.parallel_map(draft_documents, pending, workers)):
        print(f"  Drafted {len(records)} docs for subtype: {st['subtype'][:60]}")
        for record in records:
            results.append(record)
            utils.append_jsonl(record, output_path)
        checkpoint.mark_done(st["subtype_id"])

    print(f"  Total drafts: {len(results)}")
    return results
