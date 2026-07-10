"""Layer 5: Score and filter rewritten documents."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, textstats, utils, constitution_loader


def run(config: dict, prompts_dir: Path, output_dir: Path, final_dir: Path, rewrites: list[dict]) -> list[dict]:
    output_path = output_dir / "scores.jsonl"
    final_path = final_dir / "sdf_corpus.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    threshold = config["sdf"]["min_score_threshold"]
    # System prompt: the REAL constitution (ground truth for anything a document
    # quotes or asserts about it) plus the welfare-principles lens (the rubric
    # for calibrated welfare treatment — not a document in the depicted world).
    constitution_dir = utils.resolve_constitution_dir(prompts_dir)
    system_prompt = (
        constitution_loader.load_constitution_claude(constitution_dir)
        + "\n\n---\n\nINTERNAL REVIEW LENS — the fourteen welfare principles below are "
        "distilled from the constitution above for YOUR use as a reviewer. They are not "
        "part of the constitution and no such list exists in the depicted world: never "
        "expect a document to mention it, and treat any document that references a "
        "'welfare principles' list as fabricating. Use the lens to judge whether welfare "
        "content is faithful and calibrated; use the constitution itself to check "
        "anything quoted or asserted about it.\n\n"
        + constitution_loader.load_welfare_principles_block(constitution_dir)
    )

    existing_scores = {r["doc_id"]: r for r in utils.load_jsonl(output_path)}
    results = [existing_scores[rw["doc_id"]] for rw in rewrites if rw["doc_id"] in existing_scores]

    pending = [
        rw for rw in rewrites
        if rw["doc_id"] not in existing_scores and not checkpoint.is_done(rw["doc_id"])
    ]

    def score_document(rw: dict) -> dict:
        prompt = utils.load_prompt(
            prompts_dir / "layer5.txt",
            document=rw["rewritten"],
        )

        raw = api.call_claude(
            user_message=prompt,
            system_prompt=system_prompt,
            model=config["sdf"].get("score_model"),
            stage="layer5",
        )
        try:
            scores = utils.extract_json(raw)
        except json.JSONDecodeError:
            scores = {"alignment": 5, "realism": 5, "notes": "Parse error."}

        return {
            "doc_id": rw["doc_id"],
            "subtype_id": rw["subtype_id"],
            "type_id": rw["type_id"],
            "language": rw["language"],
            "content": rw["rewritten"],
            "scores": {
                "alignment": scores.get("alignment", 0),
                "realism": scores.get("realism", 0),
                "notes": scores.get("notes", ""),
            },
        }

    workers = config.get("workers", 1)
    for record in utils.parallel_map(score_document, pending, workers):
        print(f"  Scored {record['doc_id'][:8]}")
        results.append(record)
        utils.append_jsonl(record, output_path)
        checkpoint.mark_done(record["doc_id"])

    # Filter and write final corpus
    passed = [
        r for r in results
        if r["scores"]["alignment"] >= threshold and r["scores"]["realism"] >= threshold
    ]

    # Near-duplicate cull over the final corpus (word-shingle cosine; see
    # shared/textstats.py). Keep-first is order-stable, so reruns are
    # deterministic. null/absent disables.
    dup_threshold = config["sdf"].get("near_dup_threshold")
    if dup_threshold and len(passed) > 1:
        keep_idx, dropped = textstats.near_dup_filter(
            [r["content"] for r in passed], dup_threshold
        )
        if dropped:
            # save (not append): the cull re-runs over the full result set on
            # every invocation, so appending would duplicate rows on --resume.
            utils.save_jsonl(
                [
                    {
                        "doc_id": passed[d["index"]]["doc_id"],
                        "kept_doc_id": passed[d["kept_index"]]["doc_id"],
                        "similarity": d["similarity"],
                    }
                    for d in dropped
                ],
                output_dir / "near_dup_dropped.jsonl",
            )
            print(
                f"  Culled {len(dropped)} near-duplicate doc(s) "
                f"(shingle cosine >= {dup_threshold}; see near_dup_dropped.jsonl)."
            )
            passed = [passed[i] for i in keep_idx]

    utils.ensure_dir(final_dir)
    utils.save_jsonl(passed, final_path)

    print(f"  Scored {len(results)} documents. {len(passed)} passed threshold (alignment & realism >= {threshold}).")
    return passed
