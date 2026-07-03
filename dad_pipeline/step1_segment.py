"""Step 1: Segment the constitution and annotate each principle."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils, constitution_loader


def run(config: dict, prompts_dir: Path, output_dir: Path) -> list[dict]:
    output_path = output_dir / "principles.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    if checkpoint.is_done("step1"):
        print("  Step 1 already complete, loading from disk.")
        return utils.load_jsonl(output_path)

    segments = constitution_loader.load_segments(utils.resolve_constitution_dir(prompts_dir))
    results = []

    for seg in segments:
        pid = seg["principle_id"]
        if pid in constitution_loader.META_PRINCIPLE_IDS:
            continue
        title = seg["section_title"]
        print(f"  Annotating principle {pid}: {title[:60]}...")

        prompt = utils.load_prompt(
            prompts_dir / "step1_segment.txt",
            section_title=title,
            content=seg["content"],
        )

        raw = api.call_claude(user_message=prompt)
        text = raw.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
        if text.endswith("```"):
            text = "\n".join(text.split("\n")[:-1])

        try:
            parsed = json.loads(text.strip())
        except json.JSONDecodeError:
            parsed = {"core_principle": title, "scenario_types": [], "pressure_types": []}

        record = {
            "principle_id": pid,
            "section_title": title,
            "content": seg["content"],
            "core_principle": parsed.get("core_principle", ""),
            "scenario_types": parsed.get("scenario_types", []),
            "pressure_types": parsed.get("pressure_types", []),
        }
        results.append(record)
        utils.append_jsonl(record, output_path)

    checkpoint.mark_done("step1")
    print(f"  Segmented {len(results)} constitution principles.")
    return results
