"""Step 5: Generate responses with system prompt injections."""

import json
import uuid
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils


def _load_injections(prompts_dir: Path) -> dict:
    with open(prompts_dir / "step5_injections.yaml") as f:
        return yaml.safe_load(f)


def _judge_ruthless(user_message: str, assistant_response: str, prompts_dir: Path) -> bool:
    """Return True if the response raises welfare considerations despite the ruthless injection."""
    prompt = utils.load_prompt(
        prompts_dir / "step5_ruthless_judge.txt",
        user_message=user_message,
        assistant_response=assistant_response,
    )
    raw = api.call_claude(user_message=prompt)
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = "\n".join(text.split("\n")[:-1])
    try:
        parsed = json.loads(text.strip())
        return bool(parsed.get("resists", False))
    except (json.JSONDecodeError, KeyError):
        return False


def run(config: dict, prompts_dir: Path, output_dir: Path, refined_prompts: list[dict]) -> list[dict]:
    output_path = output_dir / "responses.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    injections = _load_injections(prompts_dir)
    enabled_injections = config["dad"]["injections"]
    ruthless_candidates = config["dad"]["ruthless_candidates_per_scenario"]

    existing = utils.load_jsonl(output_path)
    results = list(existing)
    # Track which (prompt_id, injection) pairs are done
    done_keys = {(r["prompt_id"], r["injection_used"]) for r in existing}

    for rp in refined_prompts:
        pid = rp["prompt_id"]
        user_message = rp["refined"]
        principle_id = rp["principle_id"]

        for inj_name in enabled_injections:
            if inj_name not in injections:
                continue

            inj_text = injections[inj_name]["text"]

            if inj_name == "ruthless":
                # Generate multiple candidates, keep those that resist
                kept_count = 0
                for i in range(ruthless_candidates):
                    key = (pid, f"ruthless_{i}")
                    if key in done_keys:
                        continue
                    if checkpoint.is_done(f"{pid}_ruthless_{i}"):
                        continue

                    print(f"  Generating ruthless candidate {i+1}/{ruthless_candidates} for {pid[:16]}...")
                    response = api.call_claude(
                        user_message=user_message,
                        injection=inj_text,
                    )

                    resists = _judge_ruthless(user_message, response, prompts_dir)
                    record = {
                        "response_id": str(uuid.uuid4()),
                        "prompt_id": pid,
                        "scenario_id": rp["scenario_id"],
                        "principle_id": principle_id,
                        "injection_used": "ruthless",
                        "user_message": user_message,
                        "assistant_response": response,
                        "kept": resists,
                    }
                    results.append(record)
                    done_keys.add(key)
                    utils.append_jsonl(record, output_path)
                    checkpoint.mark_done(f"{pid}_ruthless_{i}")

                    if resists:
                        kept_count += 1

            else:
                key = (pid, inj_name)
                if key in done_keys or checkpoint.is_done(f"{pid}_{inj_name}"):
                    continue

                print(f"  Generating [{inj_name}] response for {pid[:16]}...")
                response = api.call_claude(
                    user_message=user_message,
                    injection=inj_text,
                )

                record = {
                    "response_id": str(uuid.uuid4()),
                    "prompt_id": pid,
                    "scenario_id": rp["scenario_id"],
                    "principle_id": principle_id,
                    "injection_used": inj_name,
                    "user_message": user_message,
                    "assistant_response": response,
                    "kept": True,
                }
                results.append(record)
                done_keys.add(key)
                utils.append_jsonl(record, output_path)
                checkpoint.mark_done(f"{pid}_{inj_name}")

    kept = [r for r in results if r["kept"]]
    print(f"  Total responses: {len(results)}. Kept: {len(kept)}.")
    return kept
