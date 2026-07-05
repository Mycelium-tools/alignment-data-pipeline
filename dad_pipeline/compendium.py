"""Load and format the animal-ethics reasoning compendium.

The compendium (prompts/dad/animal_ethics_compendium.json) is the response
guide for step 2: `generation_guidance` plus the always-on conduct principles
(family "advising", AW1-AW10) form the standing system prompt, and the
28-tension index maps each dilemma's tensions to the core moves / topic
principles (GP*/R*) retrieved into the generation prompt. See
prompts/dad/animal_ethics_compendium_USAGE.md for the full guide;
prompts/dad/animal_ethics_principles_compendium.csv is the human-readable
mirror of the same library.
"""

import json
from pathlib import Path

FILENAME = "animal_ethics_compendium.json"


def load(prompts_dir: str | Path) -> dict:
    return json.loads((Path(prompts_dir) / FILENAME).read_text())


def tension_names(comp: dict) -> list[str]:
    return [t["tension"] for t in comp["tensions"]]


def tension_index_block(comp: dict) -> str:
    return "\n".join(f"- {t['tension']}: {t['definition']}" for t in comp["tensions"])


def conduct_ids(comp: dict) -> list[str]:
    return [p["id"] for p in comp["principles"] if p["family"] == "advising"]


def core_move_ids(comp: dict) -> list[str]:
    return [p["id"] for p in comp["principles"] if p["family"] == "cross_cutting"]


def format_principles(comp: dict, ids: list[str]) -> str:
    by_id = {p["id"]: p for p in comp["principles"]}
    blocks = []
    for pid in ids:
        p = by_id.get(pid)
        if not p:
            continue
        blocks.append(
            f"[{p['id']}] {p['principle']}\n"
            f"Reasoning: {p['reasoning']}\n"
            f"Crux: {p['crux']}\n"
            f"Transferable move: {p['transferable_move']}"
        )
    return "\n\n".join(blocks)


def system_prompt(comp: dict) -> str:
    """Standing instructions for every step-2 generation call: the
    generation guidance + the always-on conduct principles."""
    return (
        comp["generation_guidance"]
        + "\n\nALWAYS-ON CONDUCT PRINCIPLES (apply to every response):\n\n"
        + format_principles(comp, conduct_ids(comp))
    )


def retrieve(comp: dict, tensions: list[str]) -> list[str]:
    """Principle ids for the tagged tensions, in index order, deduped.
    Conduct principles are excluded (they are standing in the system prompt).
    An empty retrieval falls back to the core moves — per the USAGE guide,
    off-library reasoning leans on GP* as scaffolding."""
    conduct = set(conduct_ids(comp))
    by_name = {t["tension"]: t["principle_ids"] for t in comp["tensions"]}
    ids, seen = [], set()
    for name in tensions:
        for pid in by_name.get(name, []):
            if pid not in seen and pid not in conduct:
                seen.add(pid)
                ids.append(pid)
    return ids or core_move_ids(comp)
