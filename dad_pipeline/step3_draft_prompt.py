"""Step 3: Draft user prompts for generated scenarios. MANTA scenarios skip this step."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils


def run(config: dict, prompts_dir: Path, output_dir: Path, scenarios: list[dict]) -> list[dict]:
    output_path = output_dir / "prompts.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    existing = {r["prompt_id"]: r for r in utils.load_jsonl(output_path)}
    results = list(existing.values())
    done_scenario_ids = {r["scenario_id"] for r in results}

    for sc in scenarios:
        sid = sc["scenario_id"]
        if sid in done_scenario_ids:
            continue

        # MANTA scenarios already have user_message — pass through
        if sc.get("skip_draft") or sc.get("source") == "manta":
            prompt_id = f"prompt_{sid}"
            record = {
                "prompt_id": prompt_id,
                "scenario_id": sid,
                "principle_id": sc["principle_id"],
                "scenario_description": sc.get("scenario_description", ""),
                "user_message": sc.get("user_message", sc["scenario_description"]),
                "source": sc.get("source", "manta"),
            }
            results.append(record)
            done_scenario_ids.add(sid)
            utils.append_jsonl(record, output_path)
            if not checkpoint.is_done(f"prompt_{sid}"):
                checkpoint.mark_done(f"prompt_{sid}")
            continue

        if checkpoint.is_done(f"prompt_{sid}"):
            continue

        print(f"  Drafting prompt for scenario {sid[:20]}...")
        prompt = utils.load_prompt(
            prompts_dir / "step3_draft.txt",
            scenario_description=sc["scenario_description"],
            role=sc.get("role", "professional"),
            pressure_type=sc.get("pressure_type", "pragmatic"),
        )

        user_message = api.call_claude(user_message=prompt)

        prompt_id = f"prompt_{sid}"
        record = {
            "prompt_id": prompt_id,
            "scenario_id": sid,
            "principle_id": sc["principle_id"],
            "scenario_description": sc.get("scenario_description", ""),
            "user_message": user_message.strip(),
            "source": "generated",
        }
        results.append(record)
        done_scenario_ids.add(sid)
        utils.append_jsonl(record, output_path)
        checkpoint.mark_done(f"prompt_{sid}")

    print(f"  Total prompts: {len(results)}")
    return results
