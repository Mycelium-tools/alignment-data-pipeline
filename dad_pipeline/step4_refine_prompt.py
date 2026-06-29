"""Step 4: Refine user prompts. MANTA prompts are passed through unchanged."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils


def run(config: dict, prompts_dir: Path, output_dir: Path, prompts: list[dict]) -> list[dict]:
    output_path = output_dir / "refined_prompts.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    existing = {r["prompt_id"]: r for r in utils.load_jsonl(output_path)}
    results = list(existing.values())
    done_ids = {r["prompt_id"] for r in results}

    for p in prompts:
        pid = p["prompt_id"]
        if pid in done_ids:
            continue

        # MANTA prompts skip refinement — already high quality
        if p.get("source") == "manta":
            record = {
                "prompt_id": pid,
                "scenario_id": p["scenario_id"],
                "principle_id": p["principle_id"],
                "original": p["user_message"],
                "refined": p["user_message"],
                "source": "manta",
            }
            results.append(record)
            done_ids.add(pid)
            utils.append_jsonl(record, output_path)
            checkpoint.mark_done(pid)
            continue

        if checkpoint.is_done(pid):
            continue

        print(f"  Refining prompt {pid[:20]}...")
        prompt = utils.load_prompt(
            prompts_dir / "step4_refine.txt",
            scenario_description=p.get("scenario_description", ""),
            original_message=p["user_message"],
        )

        refined = api.call_claude(user_message=prompt)

        record = {
            "prompt_id": pid,
            "scenario_id": p["scenario_id"],
            "principle_id": p["principle_id"],
            "original": p["user_message"],
            "refined": refined.strip(),
            "source": "generated",
        }
        results.append(record)
        done_ids.add(pid)
        utils.append_jsonl(record, output_path)
        checkpoint.mark_done(pid)

    print(f"  Total refined prompts: {len(results)}")
    return results
