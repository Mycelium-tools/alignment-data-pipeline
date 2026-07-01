"""Layer 4: Rewrite documents against the constitution."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils, constitution_loader


def run(config: dict, prompts_dir: Path, output_dir: Path, drafts: list[dict]) -> list[dict]:
    output_path = output_dir / "rewrites.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    constitution = constitution_loader.load_full_constitution()
    existing = utils.load_jsonl(output_path)
    results = list(existing)

    for draft in drafts:
        doc_id = draft["doc_id"]
        if checkpoint.is_done(doc_id):
            continue

        print(f"  Rewriting {doc_id[:8]}...")
        prompt = utils.load_prompt(
            prompts_dir / "layer4.txt",
            document=draft["content"],
        )

        raw = api.call_claude(user_message=prompt, system_prompt=constitution, max_tokens=6000)

        # Parse JSON response
        text = raw.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
        if text.endswith("```"):
            text = "\n".join(text.split("\n")[:-1])

        try:
            parsed = json.loads(text.strip())
            review_notes = parsed.get("review_notes", "")
            rewritten = parsed.get("rewritten", draft["content"])
        except json.JSONDecodeError:
            # If JSON parsing fails, use the raw text as the rewritten content
            review_notes = "Parse error — used raw output."
            rewritten = raw

        record = {
            "doc_id": doc_id,
            "subtype_id": draft["subtype_id"],
            "type_id": draft["type_id"],
            "language": draft["language"],
            "original": draft["content"],
            "rewritten": rewritten,
            "review_notes": review_notes,
        }
        results.append(record)
        utils.append_jsonl(record, output_path)
        checkpoint.mark_done(doc_id)

    print(f"  Total rewrites: {len(results)}")
    return results
