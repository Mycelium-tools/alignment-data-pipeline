"""Layer 4: Rewrite documents against the constitution."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, textstats, utils, constitution_loader

def run(config: dict, prompts_dir: Path, output_dir: Path, drafts: list[dict]) -> list[dict]:
    output_path = output_dir / "rewrites.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    constitution = constitution_loader.load_constitution_with_principles(utils.resolve_constitution_dir(prompts_dir))
    existing = utils.load_jsonl(output_path)
    results = list(existing)

    pending = [d for d in drafts if not checkpoint.is_done(d["doc_id"])]

    def rewrite_document(draft: dict) -> dict:
        prompt = utils.load_prompt(
            prompts_dir / "layer4.txt",
            document=draft["content"],
        )

        # The rewrite is the pipeline's most leverage-heavy call (TCW's ablation:
        # removing it cost 19x on misalignment rate) — it accepts a stronger
        # model override than the bulk drafting stages.
        raw = api.call_claude(
            user_message=prompt,
            system_prompt=constitution,
            max_tokens=6000,
            model=config["sdf"].get("rewrite_model"),
            stage="layer4",
        )

        # Review notes come first, then the document inside <improved_document> tags
        match = re.search(r"<improved_document>(.*?)</improved_document>", raw, flags=re.DOTALL)
        if match:
            rewritten = textstats.strip_trailing_separators(match.group(1).strip())
            review_notes = raw[: match.start()].strip()
        else:
            review_notes = "Parse error — no <improved_document> tags; kept original draft."
            rewritten = draft["content"]
        if not rewritten:
            review_notes = "Parse error — empty rewrite; kept original draft."
            rewritten = draft["content"]

        return {
            "doc_id": draft["doc_id"],
            "subtype_id": draft["subtype_id"],
            "type_id": draft["type_id"],
            "role": draft.get("role", "welfare-topic"),
            "register": draft.get("register", "expository"),
            "language": draft["language"],
            "original": draft["content"],
            "rewritten": rewritten,
            "review_notes": review_notes,
        }

    workers = config.get("workers", 1)
    for record in utils.parallel_map(rewrite_document, pending, workers):
        print(f"  Rewrote {record['doc_id'][:8]}")
        results.append(record)
        utils.append_jsonl(record, output_path)
        checkpoint.mark_done(record["doc_id"])

    print(f"  Total rewrites: {len(results)}")
    return results
