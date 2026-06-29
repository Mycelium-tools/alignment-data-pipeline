"""Step 6: Rewrite responses against the constitution. CRITICAL STEP.

This single step accounts for a 19x reduction in misalignment rate compared to the
same pipeline without it (per Anthropic's Teaching Claude Why paper).
"""

import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils

_COMBINED_PATH = Path(__file__).parent.parent / "constitution" / "constitution_combined.md"


def _load_segments() -> list[dict]:
    """Parse the Sentient Beings sections (## headers) out of the combined constitution."""
    segments, current_title, current_lines = [], None, []
    for line in _COMBINED_PATH.read_text().splitlines():
        if line.startswith("## "):
            if current_title and current_lines:
                segments.append({"section_title": current_title, "content": "\n".join(current_lines).strip()})
            current_title, current_lines = line[3:].strip(), []
        elif current_title is not None:
            current_lines.append(line)
    if current_title and current_lines:
        segments.append({"section_title": current_title, "content": "\n".join(current_lines).strip()})
    for i, seg in enumerate(segments):
        seg["principle_id"] = i
    return segments


def run(
    config: dict,
    prompts_dir: Path,
    output_dir: Path,
    final_dir: Path,
    kept_responses: list[dict],
) -> list[dict]:
    audit_path = output_dir / "rewrites.jsonl"
    final_path = final_dir / "dad_corpus.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    constitution = _COMBINED_PATH.read_text()
    principles_by_id = {s["principle_id"]: s for s in _load_segments()}

    existing_audit = utils.load_jsonl(audit_path)
    results = list(existing_audit)
    done_response_ids = {r["response_id"] for r in results}

    for resp in kept_responses:
        rid = resp["response_id"]
        if rid in done_response_ids or checkpoint.is_done(rid):
            continue

        principle_id = resp["principle_id"]
        principle = principles_by_id.get(principle_id, principles_by_id.get(1))
        section_title = principle["section_title"]
        constitution_section = principle["content"]

        print(f"  Rewriting [{resp['injection_used']}] response for prompt {resp['prompt_id'][:16]}...")

        prompt = utils.load_prompt(
            prompts_dir / "step6_rewrite.txt",
            section_title=section_title,
            constitution_section=constitution_section,
            user_message=resp["user_message"],
            draft_response=resp["assistant_response"],
        )

        rewritten = api.call_claude(user_message=prompt, system_prompt=constitution, max_tokens=2000)

        record_id = str(uuid.uuid4())

        # Full audit record (includes constitution section for inspection)
        audit_record = {
            "record_id": record_id,
            "response_id": rid,
            "prompt_id": resp["prompt_id"],
            "scenario_id": resp["scenario_id"],
            "principle_id": principle_id,
            "injection_used": resp["injection_used"],
            "user_message": resp["user_message"],
            "draft_response": resp["assistant_response"],
            "rewritten_response": rewritten.strip(),
            "constitution_section": constitution_section,
        }
        results.append(audit_record)
        utils.append_jsonl(audit_record, audit_path)
        checkpoint.mark_done(rid)
        done_response_ids.add(rid)

    # Write final training-ready corpus — ONLY user + assistant messages, nothing else
    utils.ensure_dir(final_dir)
    final_records = []
    for r in results:
        final_records.append({
            "record_id": r["record_id"],
            "messages": [
                {"role": "user", "content": r["user_message"]},
                {"role": "assistant", "content": r["rewritten_response"]},
            ],
        })

    utils.save_jsonl(final_records, final_path)
    print(f"  Rewrote {len(results)} responses. Final corpus: {len(final_records)} training records.")
    return final_records
