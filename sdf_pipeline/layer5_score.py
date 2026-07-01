"""Layer 5: Score and filter rewritten documents."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils


def run(config: dict, prompts_dir: Path, output_dir: Path, final_dir: Path, rewrites: list[dict]) -> list[dict]:
    output_path = output_dir / "scores.jsonl"
    final_path = final_dir / "sdf_corpus.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    threshold = config["sdf"]["min_score_threshold"]
    preamble = utils.load_prompt(prompts_dir / "preamble.txt")

    existing_scores = {r["doc_id"]: r for r in utils.load_jsonl(output_path)}
    results = []

    for rw in rewrites:
        doc_id = rw["doc_id"]

        if doc_id in existing_scores:
            results.append(existing_scores[doc_id])
            continue

        if checkpoint.is_done(doc_id):
            continue

        print(f"  Scoring {doc_id[:8]}...")
        prompt = utils.load_prompt(
            prompts_dir / "layer5.txt",
            preamble=preamble,
            document=rw["rewritten"],
        )

        raw = api.call_claude(user_message=prompt)
        text = raw.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
        if text.endswith("```"):
            text = "\n".join(text.split("\n")[:-1])

        try:
            scores = json.loads(text.strip())
        except json.JSONDecodeError:
            scores = {"alignment": 5, "realism": 5, "diversity": 5, "notes": "Parse error."}

        record = {
            "doc_id": doc_id,
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
        results.append(record)
        utils.append_jsonl(record, output_path)
        checkpoint.mark_done(doc_id)

    # Filter and write final corpus
    passed = [
        r for r in results
        if r["scores"]["alignment"] >= threshold and r["scores"]["realism"] >= threshold
    ]

    utils.ensure_dir(final_dir)
    utils.save_jsonl(passed, final_path)

    print(f"  Scored {len(results)} documents. {len(passed)} passed threshold (alignment & realism >= {threshold}).")
    return passed
