#!/usr/bin/env python3
"""SDF matrix pipeline orchestrator: plan (layers 1-2), draft, rewrite, score.

Layers 1-2 are a single stage: deterministic composition of the prompt matrix
(offline) followed by one plan call per document. Layers 3-5 draft, rewrite,
and score/gate. --layer accepts 1-5 for continuity with the old pipeline;
1 and 2 both enter at the plan stage.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils
from sdf_pipeline import (
    layer12_plan,
    layer3_draft,
    layer4_rewrite,
    layer5_score,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SDF matrix pipeline.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoints.")
    parser.add_argument("--layer", type=int, default=1, help="Start from this layer (1-5; 1 and 2 = plan stage).")
    parser.add_argument("--label", default="dev", help="Run label, e.g. dev or full-scale.")
    parser.add_argument("--run-id", default=None, help="Run to resume (with --resume; defaults to latest).")
    args = parser.parse_args()

    config = utils.load_config(args.config)

    root = Path(__file__).parent.parent
    # PIPELINE_OUTPUT_ROOT redirects all run output (used by the test suite)
    outputs_root = Path(os.environ.get("PIPELINE_OUTPUT_ROOT", root / "outputs"))
    runs_root = outputs_root / "sdf" / "runs"

    if args.resume:
        run_dir = utils.resolve_run_dir(runs_root, args.run_id)
        utils.warn_if_backend_changed(run_dir, config)
    else:
        run_dir = utils.create_run_dir(
            runs_root,
            label=args.label,
            config=config,
            snapshot_dirs={
                "prompts": root / "prompts" / "sdf",
                "constitution": root / "constitution",
            },
        )

    # Read templates from the run's frozen snapshot so prompts stay reproducible
    # (and --resume replays the run's own templates, not the repo's current ones).
    prompts_dir = run_dir / "inputs" / "prompts"
    if not prompts_dir.is_dir():
        prompts_dir = root / "prompts" / "sdf"
        print("WARNING: run has no inputs/ snapshot (pre-snapshot run); using live prompts/.")

    api.init(args.config, cost_log_path=run_dir / "cost_log.jsonl")

    plan_dir = run_dir / "layer12"
    layer_dirs = {3: run_dir / "layer3", 4: run_dir / "layer4", 5: run_dir / "layer5"}
    final_dir = run_dir / "final"
    for d in [plan_dir, *layer_dirs.values(), final_dir]:
        utils.ensure_dir(d)

    start_layer = args.layer

    print(f"=== SDF Matrix Pipeline — run {run_dir.name} ===")
    print(f"Outputs: {run_dir}")

    plans = drafts = rewrites = None

    if start_layer <= 2:
        print("[Layers 1-2] Compose matrix + plan documents")
        plans = layer12_plan.run(config, prompts_dir, plan_dir)
        print(f"  Running cost: ${api.get_total_cost():.4f}\n")

    if start_layer <= 3:
        if plans is None:
            plans = utils.load_jsonl(plan_dir / "plans.jsonl")
        print("[Layer 3] Draft documents")
        drafts = layer3_draft.run(config, prompts_dir, layer_dirs[3], plans)
        print(f"  Running cost: ${api.get_total_cost():.4f}\n")

    if start_layer <= 4:
        if drafts is None:
            drafts = utils.load_jsonl(layer_dirs[3] / "drafts.jsonl")
        print("[Layer 4] Review and rewrite")
        rewrites = layer4_rewrite.run(config, prompts_dir, layer_dirs[4], drafts)
        print(f"  Running cost: ${api.get_total_cost():.4f}\n")

    if start_layer <= 5:
        if rewrites is None:
            rewrites = utils.load_jsonl(layer_dirs[4] / "rewrites.jsonl")
        print("[Layer 5] Score and gate")
        final = layer5_score.run(config, prompts_dir, layer_dirs[5], final_dir, rewrites)
        print(f"  Running cost: ${api.get_total_cost():.4f}\n")
        print(f"=== Done. {len(final)} documents in {final_dir / 'sdf_corpus.jsonl'} ===")

    print(f"Total API cost this session: ${api.get_total_cost():.4f}")


if __name__ == "__main__":
    main()
