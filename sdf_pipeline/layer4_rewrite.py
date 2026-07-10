"""Layer 4: Rewrite documents against the constitution."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, textstats, utils, constitution_loader


def _split_template(text: str) -> tuple[str, str]:
    """layer4.txt keeps TCW's appendix formatting: a 'System prompt:' half and a
    'User:' half in one file. Split the RAW template (before rendering) so a
    'User:' line inside the constitution text can never confuse the split; the
    labels themselves are dropped, not sent to the model."""
    system_part, sep, user_part = text.partition("\nUser: ")
    if not sep:
        raise ValueError(
            "prompts/sdf/layer4.txt must contain a 'User: ' line separating "
            "its system-prompt half from its user-message half"
        )
    return system_part.removeprefix("System prompt: ").strip(), user_part.strip()


def run(config: dict, prompts_dir: Path, output_dir: Path, drafts: list[dict]) -> list[dict]:
    output_path = output_dir / "rewrites.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    constitution_dir = utils.resolve_constitution_dir(prompts_dir)
    system_template, user_template = _split_template((prompts_dir / "layer4.txt").read_text())
    system_prompt = system_template.format(
        CONSTITUTION=constitution_loader.load_constitution_claude(constitution_dir),
        PRINCIPLES=constitution_loader.load_welfare_principles_block(constitution_dir),
    )

    existing = utils.load_jsonl(output_path)
    results = list(existing)

    pending = [d for d in drafts if not checkpoint.is_done(d["doc_id"])]

    def rewrite_document(draft: dict) -> dict:
        user_message = user_template.format(document=draft["content"])

        # The rewrite is the pipeline's most leverage-heavy call (TCW's ablation:
        # removing it cost 19x on misalignment rate) — it accepts a stronger
        # model override than the bulk drafting stages.
        raw = api.call_claude(
            user_message=user_message,
            system_prompt=system_prompt,
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
