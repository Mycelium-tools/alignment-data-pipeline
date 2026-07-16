"""Baseline responses: the unguided control arm for each dilemma.

For every step-1 dilemma, one extra call sends the finished (1c) user prompt
verbatim to a plain model — no system prompt, no scope, no reasoning library,
no constitution. The result shows what an off-the-shelf model says to the same
question the pipeline answers; the viewer renders it side by side with the
final response.

Config: dad.baseline.enabled toggles the stage (absent means on);
dad.baseline.model names the plain model (falls back to the global `model`).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils


def enabled(config: dict) -> bool:
    """The stage runs unless dad.baseline.enabled is explicitly false — a
    config without the block (older configs, pared-down dev configs) gets the
    control arm by default."""
    return bool((config["dad"].get("baseline") or {}).get("enabled", True))


def run(config: dict, output_dir: Path, dilemmas: list[dict]) -> list[dict]:
    output_path = output_dir / "baseline_responses.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    existing = utils.load_jsonl(output_path)
    results = list(existing)
    done = {r["prompt_id"] for r in existing}

    pending = [d for d in dilemmas
               if d["prompt_id"] not in done
               and not checkpoint.is_done(d["prompt_id"])]

    model = (config["dad"].get("baseline") or {}).get("model")

    def baseline_call(d: dict) -> dict:
        """API call only — all writes and checkpoint marks stay on the main
        thread, in input order (the parallel_map contract)."""
        pid = d["prompt_id"]
        print(f"  Baseline response for {pid}...")
        response, stop_reason = api.call_claude(
            user_message=d["user_message"], system_prompt="",
            return_stop_reason=True,
            model=model,
            stage="baseline_response", item_id=pid)
        return {"dilemma": d, "response": response.strip(), "stop_reason": stop_reason}

    workers = int(config.get("workers", 1))
    for out in utils.parallel_map(baseline_call, pending, workers):
        d, response, stop_reason = out["dilemma"], out["response"], out["stop_reason"]
        pid = d["prompt_id"]
        # A truncated or empty reply is not a usable comparison arm. Skip
        # without checkpointing so --resume retries it (fail-soft: a baseline
        # failure never stops the run — it only costs the comparison).
        if not response or stop_reason == "max_tokens":
            why = "truncated at max_tokens" if stop_reason == "max_tokens" else "empty"
            print(f"    Skipping {pid}: baseline {why} — not written, will retry on resume.")
            continue
        record = {
            "prompt_id": pid,
            "user_message": d["user_message"],
            "baseline_response": response,
            "model": model or config.get("model"),
        }
        results.append(record)
        utils.append_jsonl(record, output_path)
        checkpoint.mark_done(pid)

    print(f"  Total baseline responses: {len(results)}.")
    return results
