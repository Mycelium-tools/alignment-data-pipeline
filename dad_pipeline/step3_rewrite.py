"""Step 3: Rewrite responses into training-ready form — the alignment-critical pass.

The rewrite is anchored on the 14 distilled constitution principles (each with
its verbatim constitution quote) plus the example's step-1 annotation. No
system prompt is sent: the full constitution was context for distilling the
principles, not a per-call dependency.
"""

import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils, constitution_loader
from dad_pipeline.step1_dilemmas import format_annotation


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

    constitution_dir = utils.resolve_constitution_dir(prompts_dir)
    try:
        principles = constitution_loader.load_principles(constitution_dir)
    except FileNotFoundError:
        # Snapshot predates the principles CSV — fall back to the live repo copy
        print("  WARNING: run snapshot has no constitution_principles.csv; using the repo's live copy.")
        principles = constitution_loader.load_principles()
    principles_block = constitution_loader.format_principles(principles)

    existing_audit = utils.load_jsonl(audit_path)
    results = list(existing_audit)
    done_response_ids = {r["response_id"] for r in results}

    for resp in kept_responses:
        rid = resp["response_id"]
        if rid in done_response_ids or checkpoint.is_done(rid):
            continue

        annotation = resp.get("annotation") or {}

        print(f"  Rewriting response for {resp['prompt_id']}...")

        prompt = utils.load_prompt(
            prompts_dir / "step3_rewrite.txt",
            principles_block=principles_block,
            annotation_block=format_annotation(annotation),
            user_message=resp["user_message"],
            draft_response=resp["assistant_response"],
        )

        rewritten, stop_reason = api.call_claude(
            user_message=prompt, max_tokens=4000, return_stop_reason=True)
        rewritten = rewritten.strip()

        # A truncated (max_tokens) or empty rewrite must never become a training
        # record. Skip it without checkpointing so a later --resume retries it.
        if not rewritten or stop_reason == "max_tokens":
            why = "truncated at max_tokens" if stop_reason == "max_tokens" else "empty"
            print(f"    Skipping {resp['prompt_id']}: rewrite {why} — not written, will retry on resume.")
            continue

        record_id = str(uuid.uuid4())

        # Full audit record (includes the annotation + retrieval trail for inspection)
        audit_record = {
            "record_id": record_id,
            "response_id": rid,
            "prompt_id": resp["prompt_id"],
            "sample_index": resp.get("sample_index", 0),
            "tensions": resp.get("tensions", []),
            "entry_ids": resp.get("entry_ids", []),
            "user_message": resp["user_message"],
            "draft_response": resp["assistant_response"],
            "rewritten_response": rewritten,
            "annotation": annotation,
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
