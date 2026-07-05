#!/usr/bin/env python3
"""DAD pipeline orchestrator. Runs steps 1-4 with checkpointing (step 4 optional).

Steps: 1 dilemma prompts (one-shot from prompts/dad/dilemma_prompt_spec.md) →
2 responses reasoned from the animal-ethics compendium (tag tensions →
retrieve principles → generate two-sided) → 3 constitutional rewrite
(critical) → 4 optional pushback turn.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils
from dad_pipeline import (
    step1_dilemmas,
    step2_responses,
    step3_rewrite,
    step4_pushback,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DAD pipeline.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoints.")
    parser.add_argument("--step", type=int, default=1, help="Start from this step (1-4).")
    parser.add_argument("--label", default="dev", help="Run label, e.g. dev or full-scale.")
    parser.add_argument("--run-id", default=None, help="Run to resume (with --resume; defaults to latest).")
    args = parser.parse_args()

    config = utils.load_config(args.config)

    root = Path(__file__).parent.parent
    runs_root = root / "outputs" / "dad" / "runs"

    if args.resume:
        run_dir = utils.resolve_run_dir(runs_root, args.run_id)
    else:
        run_dir = utils.create_run_dir(
            runs_root,
            label=args.label,
            config=config,
            snapshot_dirs={
                "prompts": root / "prompts" / "dad",
                "constitution": root / "constitution",
            },
        )

    # Read templates from the run's frozen snapshot so prompts stay reproducible
    # (and --resume replays the run's own templates, not the repo's current ones).
    prompts_dir = run_dir / "inputs" / "prompts"
    if not prompts_dir.is_dir():
        prompts_dir = root / "prompts" / "dad"
        print("WARNING: run has no inputs/ snapshot (pre-snapshot run); using live prompts/.")

    api.init(args.config, cost_log_path=run_dir / "cost_log.jsonl")

    step_dirs = {i: run_dir / f"step{i}" for i in range(1, 5)}
    final_dir = run_dir / "final"
    for d in step_dirs.values():
        utils.ensure_dir(d)
    utils.ensure_dir(final_dir)

    start_step = args.step

    print(f"=== DAD Pipeline — run {run_dir.name} ===")
    print(f"Outputs: {run_dir}")

    dilemmas = responses = None

    if start_step <= 1:
        print("[Step 1] Generate dilemma prompts from the spec")
        dilemmas = step1_dilemmas.run(config, prompts_dir, step_dirs[1])
        print(f"  Running cost: ${api.get_total_cost():.4f}\n")

    if start_step <= 2:
        if dilemmas is None:
            dilemmas = utils.load_jsonl(step_dirs[1] / "dilemmas.jsonl")
        print("[Step 2] Generate responses from the reasoning compendium")
        responses = step2_responses.run(config, prompts_dir, step_dirs[2], dilemmas)
        print(f"  Running cost: ${api.get_total_cost():.4f}\n")

    if start_step <= 3:
        if responses is None:
            all_responses = utils.load_jsonl(step_dirs[2] / "responses.jsonl")
            responses = [r for r in all_responses if r.get("kept")]
        print("[Step 3] Rewrite against constitution (CRITICAL STEP)")
        final = step3_rewrite.run(
            config, prompts_dir, step_dirs[3], final_dir, responses
        )
        print(f"  Running cost: ${api.get_total_cost():.4f}\n")
        print(f"=== Step 3 done. {len(final)} records in {final_dir / 'dad_corpus.jsonl'} ===")

    if start_step <= 4 and config["dad"].get("pushback", {}).get("enabled", False):
        rewrites = utils.load_jsonl(step_dirs[3] / "rewrites.jsonl")
        print("[Step 4] Extend conversations with a pushback turn (optional)")
        final = step4_pushback.run(config, prompts_dir, step_dirs[4], final_dir, rewrites)
        print(f"  Running cost: ${api.get_total_cost():.4f}\n")
        print(f"=== Done. {len(final)} records in {final_dir / 'dad_corpus.jsonl'} ===")

    total = api.get_total_cost()
    print(f"Total API cost this session: ${total:.4f}")


if __name__ == "__main__":
    main()
