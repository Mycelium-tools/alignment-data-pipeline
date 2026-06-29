#!/usr/bin/env python3
"""SDF pipeline orchestrator. Runs layers 1-5 with checkpointing."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils
from sdf_pipeline import (
    layer1_document_types,
    layer2_subtypes,
    layer3_draft,
    layer4_rewrite,
    layer5_score,
)

LAYERS = [1, 2, 3, 4, 5]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SDF pipeline.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoints.")
    parser.add_argument("--layer", type=int, default=1, help="Start from this layer (1-5).")
    args = parser.parse_args()

    config = utils.load_config(args.config)
    api.init(args.config)

    root = Path(__file__).parent.parent
    prompts_dir = root / "prompts" / "sdf"
    out_root = root / "outputs" / "sdf"

    layer_dirs = {
        1: out_root / "layer1",
        2: out_root / "layer2",
        3: out_root / "layer3",
        4: out_root / "layer4",
        5: out_root / "layer5",
    }
    for d in layer_dirs.values():
        utils.ensure_dir(d)
    utils.ensure_dir(out_root / "final")

    start_layer = args.layer if args.resume else args.layer

    print("=== SDF Pipeline ===")

    doc_types = subtypes = drafts = rewrites = None

    if start_layer <= 1:
        print("[Layer 1] Document types")
        doc_types = layer1_document_types.run(config, prompts_dir, layer_dirs[1])
        cost = api.get_total_cost()
        print(f"  Running cost: ${cost:.4f}\n")

    if start_layer <= 2:
        if doc_types is None:
            doc_types = utils.load_jsonl(layer_dirs[1] / "document_types.jsonl")
        print("[Layer 2] Subtypes")
        subtypes = layer2_subtypes.run(config, prompts_dir, layer_dirs[2], doc_types)
        cost = api.get_total_cost()
        print(f"  Running cost: ${cost:.4f}\n")

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
        final = layer5_score.run(config, prompts_dir, layer_dirs[5], out_root / "final", rewrites)
        cost = api.get_total_cost()
        print(f"  Running cost: ${cost:.4f}\n")
        print(f"=== Done. {len(final)} documents in outputs/sdf/final/sdf_corpus.jsonl ===")

    total_cost = api.get_total_cost()
    print(f"Total API cost this session: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
