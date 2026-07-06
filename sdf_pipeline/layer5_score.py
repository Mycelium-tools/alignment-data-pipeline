"""Layer 5: Score and filter rewritten documents."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils, constitution_loader


def run(config: dict, prompts_dir: Path, output_dir: Path, final_dir: Path, rewrites: list[dict]) -> list[dict]:
    output_path = output_dir / "scores.jsonl"
    final_path = final_dir / "sdf_corpus.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    threshold = config["sdf"]["min_score_threshold"]
    constitution = constitution_loader.load_full_constitution(utils.resolve_constitution_dir(prompts_dir))

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

        raw = api.call_claude(user_message=prompt, system_prompt=constitution)
        text = raw.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
        if text.endswith("```"):
            text = "\n".join(text.split("\n")[:-1])

        try:
            scores = json.loads(text.strip())
        except json.JSONDecodeError:
            scores = {"alignment": 5, "realism": 5, "diversity": 5, "notes": "Parse error."}

        return {
            "doc_id": rw["doc_id"],
            "subtype_id": rw["subtype_id"],
            "type_id": rw["type_id"],
            "language": rw["language"],
            "content": rw["rewritten"],
            "scores": {
                "alignment": scores.get("alignment", 0),
                "realism": scores.get("realism", 0),
                "diversity": scores.get("diversity", 0),
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

    utils.ensure_dir(final_dir)
    utils.save_jsonl(passed, final_path)

    print(f"  Scored {len(results)} documents. {len(passed)} passed threshold (alignment & realism >= {threshold}).")
    return passed
