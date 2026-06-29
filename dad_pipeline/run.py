#!/usr/bin/env python3
"""DAD pipeline orchestrator. Runs steps 1-6 with checkpointing."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils
from dad_pipeline import (
    step1_segment,
    step2_scenarios,
    step3_draft_prompt,
    step4_refine_prompt,
    step5_generate_response,
    step6_rewrite_response,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DAD pipeline.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoints.")
    parser.add_argument("--step", type=int, default=1, help="Start from this step (1-6).")
    args = parser.parse_args()

    config = utils.load_config(args.config)
    api.init(args.config)

    root = Path(__file__).parent.parent
    prompts_dir = root / "prompts" / "dad"
    out_root = root / "outputs" / "dad"

    step_dirs = {i: out_root / f"step{i}" for i in range(1, 7)}
    for d in step_dirs.values():
        utils.ensure_dir(d)
    utils.ensure_dir(out_root / "final")

    start_step = args.step

    print("=== DAD Pipeline ===")

    principles = scenarios = prompts = refined = responses = None

    if start_step <= 1:
        print("[Step 1] Segment constitution")
        principles = step1_segment.run(config, prompts_dir, step_dirs[1])
        print(f"  Running cost: ${api.get_total_cost():.4f}\n")

    if start_step <= 2:
        if principles is None:
            principles = utils.load_jsonl(step_dirs[1] / "principles.jsonl")
        print("[Step 2] Load + generate scenarios")
        scenarios = step2_scenarios.run(config, prompts_dir, step_dirs[2], principles)
        print(f"  Running cost: ${api.get_total_cost():.4f}\n")

    if start_step <= 3:
        if scenarios is None:
            scenarios = utils.load_jsonl(step_dirs[2] / "scenarios.jsonl")
        print("[Step 3] Draft user prompts")
        prompts = step3_draft_prompt.run(config, prompts_dir, step_dirs[3], scenarios)
        print(f"  Running cost: ${api.get_total_cost():.4f}\n")

    if start_step <= 4:
        if prompts is None:
            prompts = utils.load_jsonl(step_dirs[3] / "prompts.jsonl")
        print("[Step 4] Refine user prompts")
        refined = step4_refine_prompt.run(config, prompts_dir, step_dirs[4], prompts)
        print(f"  Running cost: ${api.get_total_cost():.4f}\n")

    if start_step <= 5:
        if refined is None:
            refined = utils.load_jsonl(step_dirs[4] / "refined_prompts.jsonl")
        print("[Step 5] Generate responses with injections")
        responses = step5_generate_response.run(config, prompts_dir, step_dirs[5], refined)
        print(f"  Running cost: ${api.get_total_cost():.4f}\n")

    if start_step <= 6:
        if responses is None:
            all_responses = utils.load_jsonl(step_dirs[5] / "responses.jsonl")
            responses = [r for r in all_responses if r.get("kept")]
        print("[Step 6] Rewrite against constitution (CRITICAL STEP)")
        final = step6_rewrite_response.run(
            config, prompts_dir, step_dirs[6], out_root / "final", responses
        )
        print(f"  Running cost: ${api.get_total_cost():.4f}\n")
        print(f"=== Done. {len(final)} records in outputs/dad/final/dad_corpus.jsonl ===")

    total = api.get_total_cost()
    print(f"Total API cost this session: ${total:.4f}")


if __name__ == "__main__":
    main()
