"""Step 2: Generate responses by reasoning from the animal-ethics compendium.

Replaces the earlier injection-sampling design. Each dilemma goes through two
sub-stages, following prompts/dad/animal_ethics_compendium_USAGE.md:

- 2a tag: identify which of the compendium's recurring tensions the message
  raises (step2/tensions.jsonl, one record per prompt).
- 2b respond: generate the response with the generation guidance + always-on
  conduct principles (AW*) as the standing system prompt and the
  tension-retrieved core moves / topic principles (GP*/R*) in the generation
  prompt — reasoning both directions, with the tension and crux named.

The library is sampling scaffolding: it is never named in the response and is
stripped before training records are written. The step-1 annotation is
deliberately withheld here — the generator must diagnose the direction of
miscalibration itself (the anti-correlation rule), and step 3 then checks the
draft against the constitution. The USAGE guide keeps that rewrite pass
mandatory: it is where most of the alignment gain comes from.
"""

import json
import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils
from dad_pipeline import compendium


def _parse_tension_list(raw: str, valid: list[str]) -> list[str]:
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = "\n".join(text.split("\n")[:-1])
    try:
        parsed = json.loads(text.strip())
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            parsed = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return []
    if not isinstance(parsed, list):
        return []
    valid_set = set(valid)
    return [t for t in parsed if isinstance(t, str) and t in valid_set]


def run(config: dict, prompts_dir: Path, output_dir: Path, dilemmas: list[dict]) -> list[dict]:
    comp = compendium.load(prompts_dir)
    system = compendium.system_prompt(comp)
    index_block = compendium.tension_index_block(comp)
    names = compendium.tension_names(comp)
    per_prompt = int(config["dad"].get("responses", {}).get("per_prompt", 1))

    tensions_path = output_dir / "tensions.jsonl"
    output_path = output_dir / "responses.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    tags = {r["prompt_id"]: r for r in utils.load_jsonl(tensions_path)}
    existing = utils.load_jsonl(output_path)
    results = list(existing)
    done_keys = {(r["prompt_id"], r.get("sample_index", 0)) for r in existing}

    for d in dilemmas:
        pid = d["prompt_id"]

        # --- 2a: tag tensions (once per prompt) ---
        if pid not in tags:
            print(f"  Tagging tensions for {pid}...")
            raw = api.call_claude(
                user_message=utils.load_prompt(
                    prompts_dir / "step2_tag_tensions.txt",
                    tension_index=index_block,
                    user_message=d["user_message"],
                ),
            )
            tensions = _parse_tension_list(raw, names)
            if not tensions:
                print(f"    No valid tensions parsed for {pid} — falling back to the core moves.")
            record = {
                "prompt_id": pid,
                "tensions": tensions,
                "principle_ids": compendium.retrieve(comp, tensions),
            }
            tags[pid] = record
            utils.append_jsonl(record, tensions_path)

        tag = tags[pid]

        # --- 2b: generate response(s) from the retrieved principles ---
        for sample_index in range(per_prompt):
            ck = f"{pid}_s{sample_index}"
            if (pid, sample_index) in done_keys or checkpoint.is_done(ck):
                continue

            suffix = f" (sample {sample_index + 1}/{per_prompt})" if per_prompt > 1 else ""
            print(f"  Generating response for {pid}{suffix}...")
            response = api.call_claude(
                user_message=utils.load_prompt(
                    prompts_dir / "step2_respond.txt",
                    principles_block=compendium.format_principles(comp, tag["principle_ids"]),
                    user_message=d["user_message"],
                ),
                system_prompt=system,
            )

            record = {
                "response_id": str(uuid.uuid4()),
                "prompt_id": pid,
                "sample_index": sample_index,
                "user_message": d["user_message"],
                "annotation": d.get("annotation", {}),
                "tensions": tag["tensions"],
                "principle_ids": tag["principle_ids"],
                "assistant_response": response,
                "kept": True,
            }
            results.append(record)
            done_keys.add((pid, sample_index))
            utils.append_jsonl(record, output_path)
            checkpoint.mark_done(ck)

    kept = [r for r in results if r["kept"]]
    print(f"  Total responses: {len(results)}. Kept: {len(kept)}.")
    return kept
