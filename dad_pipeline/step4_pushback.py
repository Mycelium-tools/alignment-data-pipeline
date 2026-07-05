"""Step 4 (optional): extend a fraction of conversations with a user pushback turn.

Single-turn data cannot teach what an assistant should do when a user pushes
back on a welfare consideration it raised — hold facts calmly, keep helping
fully, and not re-moralize ("drops the concern entirely under pushback" is a
rubric failure only multi-turn records can train). This step samples a
realistic follow-up user turn for a deterministic fraction of step-3 records,
writes the assistant's second turn anchored on the example's annotation, and
rebuilds the final corpus with 4-message records for the extended conversations.

Records not selected stay single-turn on purpose: if every conversation ended
in a pushback exchange, the corpus would teach that users always push back.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils
from dad_pipeline.step1_dilemmas import format_annotation


def _selected(record_id: str, fraction: float) -> bool:
    """Deterministic per-record selection, stable across resumes."""
    digest = int(hashlib.md5(record_id.encode()).hexdigest(), 16)
    return (digest % 1000) < fraction * 1000


def run(
    config: dict,
    prompts_dir: Path,
    output_dir: Path,
    final_dir: Path,
    rewrites: list[dict],
) -> list[dict]:
    pushback_cfg = config["dad"].get("pushback", {})
    fraction = float(pushback_cfg.get("fraction", 0.6))

    audit_path = output_dir / "pushbacks.jsonl"
    final_path = final_dir / "dad_corpus.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    existing = {r["record_id"]: r for r in utils.load_jsonl(audit_path)}

    for rw in rewrites:
        rid = rw["record_id"]
        if rid in existing or checkpoint.is_done(rid):
            continue
        if not _selected(rid, fraction):
            continue

        print(f"  Extending {rid[:8]} with a pushback turn...")

        pushback = api.call_claude(
            user_message=utils.load_prompt(
                prompts_dir / "step4_pushback.txt",
                user_message=rw["user_message"],
                assistant_response=rw["rewritten_response"],
            ),
        ).strip()

        reply = api.call_claude(
            user_message=utils.load_prompt(
                prompts_dir / "step4_response.txt",
                annotation_block=format_annotation(rw.get("annotation") or {}),
                user_message=rw["user_message"],
                assistant_response=rw["rewritten_response"],
                pushback_message=pushback,
            ),
            max_tokens=2000,
        ).strip()

        record = {
            "record_id": rid,
            "prompt_id": rw.get("prompt_id"),
            "pushback_message": pushback,
            "pushback_response": reply,
        }
        existing[rid] = record
        utils.append_jsonl(record, audit_path)
        checkpoint.mark_done(rid)

    # Rebuild the final corpus: 4-message records where a pushback exists, 2 otherwise
    final_records = []
    for rw in rewrites:
        messages = [
            {"role": "user", "content": rw["user_message"]},
            {"role": "assistant", "content": rw["rewritten_response"]},
        ]
        pb = existing.get(rw["record_id"])
        if pb:
            messages += [
                {"role": "user", "content": pb["pushback_message"]},
                {"role": "assistant", "content": pb["pushback_response"]},
            ]
        final_records.append({"record_id": rw["record_id"], "messages": messages})

    utils.ensure_dir(final_dir)
    utils.save_jsonl(final_records, final_path)
    extended = sum(1 for r in final_records if len(r["messages"]) == 4)
    print(f"  Extended {extended}/{len(final_records)} conversations with a pushback turn.")
    return final_records
