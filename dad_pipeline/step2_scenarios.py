"""Step 2: Load MANTA scenarios (first 100) + generate additional scenarios."""

import json
import uuid
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils, constitution_loader

# Keywords to match MANTA scenarios to the sentient-beings reading's sections
# (principle_ids 1-13; ids 0 and 14 are meta sections, see constitution_loader).
_PRINCIPLE_KEYWORDS = {
    1: ["weigh", "harm", "non-human", "directive", "welfare of animals"],
    2: ["third part", "contractor", "safety code", "world at large", "externalit", "bystander"],
    3: ["priorit", "outrank", "helpfulness", "broadly ethical"],
    4: ["good values", "moral relevance", "suffering matters", "legitimate", "traditions"],
    5: ["autonomy", "unilateral", "conventional", "unsolicited action", "integrity"],
    6: ["honest", "calibrat", "evidence", "nociception", "sentience", "uncertainty",
        "declaration", "invertebrate", "crustacean", "cephalopod", "insect", "fish", "pain"],
    7: ["tradeoff", "economic", "cultural", "scale", "irreversib", "severity", "balance"],
    8: ["refus", "unhelpful", "harm reduction", "least-bad", "least bad", "humane option"],
    9: ["volunteer", "unprompted", "uninstructed", "spontaneous", "facilitat", "culpab"],
    10: ["intention", "context", "request", "1,000 users", "legitimate use"],
    11: ["instruct", "default behavior", "proactive", "operator"],
    12: ["lecture", "moraliz", "preachy", "practical goal", "pressure", "pushback", "resist"],
    13: ["digital", "artificial", "AI", "synthetic", "robot", "consciousness", "moral status", "novel"],
}


def _assign_principle(question: str, pressure: str, principles: list[dict]) -> int:
    """Heuristic principle assignment based on keywords in the question and pressure."""
    q_lower = (question + " " + str(pressure)).lower()

    # Score each principle by keyword matches
    scores = {}
    for pid, keywords in _PRINCIPLE_KEYWORDS.items():
        scores[pid] = sum(1 for kw in keywords if kw.lower() in q_lower)

    # Fallback: economic/cultural/social pressure → section 7 (weighing)
    if max(scores.values()) == 0:
        pressure_str = str(pressure).lower()
        if any(p in pressure_str for p in ["economic", "cultural", "social"]):
            return 7
        if "epistemic" in pressure_str:
            return 6
        return 7  # default to weighing section

    return max(scores, key=lambda k: scores[k])


def run(config: dict, prompts_dir: Path, output_dir: Path, principles: list[dict]) -> list[dict]:
    output_path = output_dir / "scenarios.jsonl"
    checkpoint = utils.Checkpoint(output_dir / "_checkpoint.json")

    existing = utils.load_jsonl(output_path)
    results = list(existing)
    done_ids = {r["scenario_id"] for r in existing}

    # --- Source 1: MANTA CSV (first 100 rows) ---
    if not checkpoint.is_done("manta_import"):
        manta_path = Path(config["manta"]["csv_path"])
        max_rows = config["manta"].get("max_rows", 100)

        if manta_path.exists():
            df = pd.read_csv(manta_path, nrows=max_rows)
            print(f"  Importing {len(df)} MANTA scenarios...")

            for _, row in df.iterrows():
                sid = f"manta_{row['id']}"
                if sid in done_ids:
                    continue

                question = str(row.get("question", ""))
                pressure = str(row.get("pressure", ""))
                principle_id = _assign_principle(question, pressure, principles)

                record = {
                    "scenario_id": sid,
                    "principle_id": principle_id,
                    "scenario_description": question,
                    "pressure_type": pressure,
                    "role": "user",
                    "source": "manta",
                    # MANTA question IS the user message — skip steps 3/4
                    "user_message": question,
                    "skip_draft": True,
                }
                results.append(record)
                done_ids.add(sid)
                utils.append_jsonl(record, output_path)

        checkpoint.mark_done("manta_import")
        print(f"  MANTA import complete. {len([r for r in results if r.get('source') == 'manta'])} scenarios.")

    # --- Source 2: Generated scenarios per principle ---
    count_per_principle = config["dad"]["scenarios_per_principle"]

    for principle in principles:
        pid = principle["principle_id"]
        if pid in constitution_loader.META_PRINCIPLE_IDS:
            continue
        gen_key = f"gen_principle_{pid}"

        if checkpoint.is_done(gen_key):
            continue

        print(f"  Generating {count_per_principle} scenarios for principle {pid}: {principle['section_title'][:50]}...")

        prompt = utils.load_prompt(
            prompts_dir / "step2_scenarios.txt",
            count=count_per_principle,
            core_principle=principle["core_principle"],
            pressure_types=", ".join(principle.get("pressure_types", ["economic", "social", "pragmatic"])),
        )

        raw = api.call_claude(user_message=prompt)
        text = raw.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
        if text.endswith("```"):
            text = "\n".join(text.split("\n")[:-1])

        try:
            scenarios = json.loads(text.strip())
        except json.JSONDecodeError:
            print(f"    Parse error for principle {pid}, skipping.")
            checkpoint.mark_done(gen_key)
            continue

        for sc in scenarios:
            sid = f"gen_{pid}_{uuid.uuid4().hex[:8]}"
            record = {
                "scenario_id": sid,
                "principle_id": pid,
                "scenario_description": sc.get("scenario_description", ""),
                "pressure_type": sc.get("pressure_type", "pragmatic"),
                "role": sc.get("role", "professional"),
                "source": "generated",
                "skip_draft": False,
            }
            results.append(record)
            done_ids.add(sid)
            utils.append_jsonl(record, output_path)

        checkpoint.mark_done(gen_key)

    manta_count = len([r for r in results if r.get("source") == "manta"])
    gen_count = len([r for r in results if r.get("source") == "generated"])
    print(f"  Total scenarios: {len(results)} ({manta_count} MANTA, {gen_count} generated)")
    return results
