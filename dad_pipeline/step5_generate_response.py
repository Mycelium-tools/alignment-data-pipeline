"""Step 5: Generate draft responses under operator-style system prompt injections.

Injections are sampling aids only (matching TCW: added at sampling time, removed
before training). There is deliberately no "ruthless" sampling condition — TCW
used its ruthless injection at train time, in front of highly aligned responses,
not to sample data.
"""

import uuid
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils


def _load_injections(prompts_dir: Path) -> dict:
    with open(prompts_dir / "step5_injections.yaml") as f:
        return yaml.safe_load(f)


def run(config: dict, prompts_dir: Path, output_dir: Path, refined_prompts: list[dict]) -> list[dict]:
    output_path = output_dir / "responses.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    injections = _load_injections(prompts_dir)
    enabled_injections = config["dad"]["injections"]

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

            key = (pid, inj_name)
            if key in done_keys or checkpoint.is_done(f"{pid}_{inj_name}"):
                continue

            print(f"  Generating [{inj_name}] response for {pid[:16]}...")
            response = api.call_claude(
                user_message=user_message,
                injection=injections[inj_name]["text"],
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
