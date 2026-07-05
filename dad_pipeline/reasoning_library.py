"""Load and format the animal-ethics reasoning library.

The library (prompts/dad/animal_ethics_reasoning_library.json) is the response
guide for step 2: `generation_guidance` plus the always-on conduct principles
(family "advising", AW1-AW10) form the standing system prompt, and the
28-tension index maps each dilemma's tensions to the core moves / topic
principles (GP*/R*) retrieved into the generation prompt. See
prompts/dad/animal_ethics_reasoning_library_USAGE.md for the full guide;
prompts/dad/animal_ethics_reasoning_library.csv is the human-readable mirror
of the same library.
"""

import json
from pathlib import Path

FILENAME = "animal_ethics_reasoning_library.json"
# Runs snapshotted before the rename carry the old filename; fall back to it so
# their step-2 prompts still load and re-render.
LEGACY_FILENAME = "animal_ethics_compendium.json"


def resolve_path(prompts_dir: str | Path) -> Path:
    """The library JSON in prompts_dir, preferring the current name and falling
    back to the pre-rename name for older snapshots."""
    prompts_dir = Path(prompts_dir)
    current = prompts_dir / FILENAME
    return current if current.exists() else prompts_dir / LEGACY_FILENAME


def load(prompts_dir: str | Path) -> dict:
    return json.loads(resolve_path(prompts_dir).read_text())


def tension_names(library: dict) -> list[str]:
    return [t["tension"] for t in library["tensions"]]


def tension_index_block(library: dict) -> str:
    return "\n".join(f"- {t['tension']}: {t['definition']}" for t in library["tensions"])


def conduct_ids(library: dict) -> list[str]:
    return [p["id"] for p in library["principles"] if p["family"] == "advising"]


def core_move_ids(library: dict) -> list[str]:
    return [p["id"] for p in library["principles"] if p["family"] == "cross_cutting"]


def format_principles(library: dict, ids: list[str]) -> str:
    by_id = {p["id"]: p for p in library["principles"]}
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


def system_prompt(library: dict) -> str:
    """Standing instructions for every step-2 generation call: the library's
    generation guidance + the always-on conduct principles. Sent verbatim as
    the system prompt — it is instruction-style guidance to the generator, not
    an operator persona and not a description of how the library was built."""
    return (
        library["generation_guidance"]
        + "\n\nALWAYS-ON CONDUCT PRINCIPLES (apply to every response):\n\n"
        + format_principles(library, conduct_ids(library))
    )


def retrieve(library: dict, tensions: list[str]) -> list[str]:
    """Principle ids for the tagged tensions, in index order, deduped.
    Conduct principles are excluded (they are standing in the system prompt).
    An empty retrieval falls back to the core moves — per the USAGE guide,
    off-library reasoning leans on GP* as scaffolding."""
    conduct = set(conduct_ids(library))
    by_name = {t["tension"]: t["principle_ids"] for t in library["tensions"]}
    ids, seen = [], set()
    for name in tensions:
        for pid in by_name.get(name, []):
            if pid not in seen and pid not in conduct:
                seen.add(pid)
                ids.append(pid)
    return ids or core_move_ids(library)
