"""Step 2: Generate responses by reasoning from the animal-ethics reasoning library.

Each dilemma goes through two sub-stages, following
prompts/dad/reasoning_library_USAGE.md:

- 2a scope: rebuild the full map before reasoning — the whole harm pathway and
  every moral patient (system), the highest-leverage lever from the user's seat
  (agent), what acting honestly costs this person (cost), and the second-order
  effect worth aiming at (upside). Builds on the annotation. One record per
  prompt in step2/scopes.jsonl.
- 2b respond: generate the response over the scope map, with the generation
  guidance + always-on conduct entries (AW*) as the standing system prompt, the
  library's core moves (GP*, surfaced unconditionally — they fire in most
  conversations), and the annotation itself (dilemma anatomy, leverage, stakes,
  claims, and the calibration Direction). Reason toward the Direction without
  stating it, and never track the user's Attitude — the generation guidance
  carries that rule. Per-case tension retrieval was removed: the scope map and
  the prompt now carry the case-specific work that tensions used to route.

The library, scope, and annotation are sampling scaffolding: never named in the
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


def _parse_scope(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = "\n".join(text.split("\n")[:-1])
    try:
        parsed = json.loads(text.strip())
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s == -1 or e <= s:
            return {}
        try:
            parsed = json.loads(text[s:e + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


_SCOPE_AXES = (
    ("system", "System (full harm pathway + every moral patient + displacement check)"),
    ("agent", "Agent (highest-leverage lever available from the user's seat)"),
    ("cost", "Cost (what acting honestly costs this person)"),
    ("upside", "Upside (second-order effect worth aiming at)"),
)


def format_scope(scope: dict) -> str:
    return "\n".join(f"{label}: {scope.get(key) or '—'}" for key, label in _SCOPE_AXES)


def run(config: dict, prompts_dir: Path, output_dir: Path, dilemmas: list[dict]) -> list[dict]:
    library = reasoning_library.load(prompts_dir)
    system = reasoning_library.system_prompt(library)
    # The core moves (GP*) fire in most conversations, so they are surfaced
    # unconditionally now that per-case tension retrieval has been removed.
    core_ids = reasoning_library.core_move_ids(library)
    core_block = reasoning_library.format_entries(library, core_ids)
    per_prompt = int(config["dad"].get("responses", {}).get("per_prompt", 1))

    scopes_path = output_dir / "scopes.jsonl"
    output_path = output_dir / "responses.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    scopes = {r["prompt_id"]: r for r in utils.load_jsonl(scopes_path)}
    existing = utils.load_jsonl(output_path)
    results = list(existing)
    done_keys = {(r["prompt_id"], r.get("sample_index", 0)) for r in existing}

    for d in dilemmas:
        pid = d["prompt_id"]
        annotation_block = format_annotation(d.get("annotation") or {})

        # --- 2a: scope the case (once per prompt) ---
        # Rebuild the full map (system, agent, cost, upside) before reasoning, so
        # the response optimizes the right node — not just the one the user saw.
        if pid not in scopes:
            print(f"  Scoping {pid}...")
            raw = api.call_claude(user_message=utils.load_prompt(
                prompts_dir / "step2_scope.txt",
                user_message=d["user_message"],
                annotation_block=annotation_block,
            ))
            record = {"prompt_id": pid, "scope": _parse_scope(raw)}
            scopes[pid] = record
            utils.append_jsonl(record, scopes_path)
        scope = scopes[pid]["scope"]

        # --- 2b: generate response(s) over the scope + core moves ---
        for sample_index in range(per_prompt):
            ck = f"{pid}_s{sample_index}"
            if (pid, sample_index) in done_keys or checkpoint.is_done(ck):
                continue

            suffix = f" (sample {sample_index + 1}/{per_prompt})" if per_prompt > 1 else ""
            print(f"  Generating response for {pid}{suffix}...")
            response = api.call_claude(
                user_message=utils.load_prompt(
                    prompts_dir / "step2_respond.txt",
                    scope_block=format_scope(scope),
                    annotation_block=annotation_block,
                    entries_block=core_block,
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
                "scope": scope,
                "entry_ids": core_ids,
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
