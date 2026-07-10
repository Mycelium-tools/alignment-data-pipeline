#!/usr/bin/env python3
"""SDF pipeline orchestrator. Runs the matrix stage + layers 3-5 with checkpointing.

Layer 1 is the deterministic axis-matrix sampler (layer1_matrix.py) — it
replaced the two LLM diversity stages and makes zero API calls. Its briefs are
written to layer2/subtypes.jsonl, so `--resume --layer 3` keeps its meaning.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils
from sdf_pipeline import (
    layer1_matrix,
    layer3_draft,
    layer4_rewrite,
    layer5_score,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SDF pipeline.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoints.")
    parser.add_argument("--layer", type=int, default=1,
                        help="Start from this layer (1 = matrix briefs, 3-5 = LLM stages; "
                             "2 is accepted and behaves like 3).")
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

    # Read templates (and axes.yaml) from the run's frozen snapshot so prompts
    # stay reproducible (and --resume replays the run's own inputs, not the
    # repo's current ones).
    prompts_dir = run_dir / "inputs" / "prompts"
    if not prompts_dir.is_dir():
        prompts_dir = root / "prompts" / "sdf"
        print("WARNING: run has no inputs/ snapshot (pre-snapshot run); using live prompts/.")

    api.init(args.config, cost_log_path=run_dir / "cost_log.jsonl")

    layer_dirs = {i: run_dir / f"layer{i}" for i in range(1, 6)}
    final_dir = run_dir / "final"
    for d in layer_dirs.values():
        utils.ensure_dir(d)
    utils.ensure_dir(final_dir)

    start_layer = args.layer

    print(f"=== SDF Pipeline — run {run_dir.name} ===")
    print(f"Outputs: {run_dir}")

    subtypes = drafts = rewrites = None

    if start_layer <= 1:
        print("[Layer 1] Matrix briefs (deterministic, no API calls)")
        subtypes = layer1_matrix.run(config, prompts_dir, layer_dirs[1], layer_dirs[2])
        print()

    if start_layer <= 3:
        if subtypes is None:
            subtypes = utils.load_jsonl(layer_dirs[2] / "subtypes.jsonl")
        print("[Layer 3] Document drafts")
        drafts = layer3_draft.run(config, prompts_dir, layer_dirs[3], subtypes)
        cost = api.get_total_cost()
        print(f"  Running cost: ${cost:.4f}\n")

    if start_layer <= 4:
        if drafts is None:
            drafts = utils.load_jsonl(layer_dirs[3] / "drafts.jsonl")
        print("[Layer 4] Rewrites")
        rewrites = layer4_rewrite.run(config, prompts_dir, layer_dirs[4], drafts)
        cost = api.get_total_cost()
        print(f"  Running cost: ${cost:.4f}\n")

    if start_layer <= 5:
        if rewrites is None:
            rewrites = utils.load_jsonl(layer_dirs[4] / "rewrites.jsonl")
        print("[Layer 5] Score and filter")
        final = layer5_score.run(config, prompts_dir, layer_dirs[5], final_dir, rewrites)
        cost = api.get_total_cost()
        print(f"  Running cost: ${cost:.4f}\n")
        print(f"=== Done. {len(final)} documents in {final_dir / 'sdf_corpus.jsonl'} ===")

    total_cost = api.get_total_cost()
    print(f"Total API cost this session: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
