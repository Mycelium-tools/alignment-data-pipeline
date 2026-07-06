"""Step 2: Generate responses by reasoning from the animal-ethics reasoning library.

Replaces the earlier injection-sampling design. Each dilemma goes through two
sub-stages, following prompts/dad/reasoning_library_USAGE.md:

- 2a retrieve: the step-1 annotation already tagged the case's library tensions
  (the retrieval key), so retrieval is a direct lookup — no LLM tagging pass.
  An LLM tag call is used only as a fallback when a dilemma carries no usable
  annotation tensions (e.g. an un-annotated seed). One record per prompt in
  step2/tensions.jsonl.
- 2b respond: generate the response with the generation guidance + always-on
  conduct entries (AW*) as the standing system prompt, the tension-retrieved
  core moves / topic entries (GP*/R*), and the annotation itself (dilemma
  anatomy, leverage, stakes, tensions, claims, and the calibration Direction).
  Reason toward the Direction without stating it, and never track the user's
  Attitude — the generation guidance carries that anti-correlation rule.

The library and annotation are sampling scaffolding: never named in the
response, stripped before training records are written. Step 3 then rewrites
against the constitution; the USAGE guide keeps that pass mandatory.
"""

import json
import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils
from dad_pipeline import reasoning_library
from dad_pipeline.step1_dilemmas import format_annotation


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
    library = reasoning_library.load(prompts_dir)
    system = reasoning_library.system_prompt(library)
    index_block = reasoning_library.tension_index_block(library)
    names = reasoning_library.tension_names(library)
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

        # --- 2a: resolve tensions (once per prompt) ---
        # Primary path: the step-1 annotation already tagged the library tensions
        # (the retrieval key), so this is a direct lookup with no LLM call.
        if pid not in tags:
            valid = set(names)
            ann_tensions = [t for t in (d.get("annotation") or {}).get("tensions", []) if t in valid]
            if ann_tensions:
                tensions, source = ann_tensions, "annotation"
                print(f"  Routing {pid} from annotation ({len(ann_tensions)} tensions)...")
            else:
                # Fallback: no usable annotation tensions (e.g. un-annotated seed).
                print(f"  No annotation tensions for {pid}; tagging from the prompt...")
                raw = api.call_claude(
                    user_message=utils.load_prompt(
                        prompts_dir / "step2_tag_tensions.txt",
                        tension_index=index_block,
                        user_message=d["user_message"],
                    ),
                )
                tensions, source = _parse_tension_list(raw, names), "tagged"
                if not tensions:
                    print(f"    No valid tensions for {pid} — falling back to the core moves.")
            record = {
                "prompt_id": pid,
                "tensions": tensions,
                "entry_ids": reasoning_library.retrieve(library, tensions),
                "source": source,
            }
            tags[pid] = record
            utils.append_jsonl(record, tensions_path)

        tag = tags[pid]

        # --- 2b: generate response(s) from the retrieved entries + the annotation ---
        for sample_index in range(per_prompt):
            ck = f"{pid}_s{sample_index}"
            if (pid, sample_index) in done_keys or checkpoint.is_done(ck):
                continue

            suffix = f" (sample {sample_index + 1}/{per_prompt})" if per_prompt > 1 else ""
            print(f"  Generating response for {pid}{suffix}...")
            response = api.call_claude(
                user_message=utils.load_prompt(
                    prompts_dir / "step2_respond.txt",
                    annotation_block=format_annotation(d.get("annotation") or {}),
                    entries_block=reasoning_library.format_entries(library, tag["entry_ids"]),
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
                "entry_ids": tag["entry_ids"],
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
