"""Load and format the animal-ethics reasoning library.

The library (prompts/dad/reasoning_library.json) is the response guide for
step 2: `generation_guidance` plus the always-on conduct entries (family
"advising", AW1-AW10) form the standing system prompt, and the 28-tension
index maps each dilemma's tensions to the core moves / topic entries (GP*/R*)
retrieved into the generation prompt. See prompts/dad/reasoning_library_USAGE.md
for the full guide; prompts/dad/reasoning_library.csv is the human-readable
mirror of the same library.

The library rows are "entries" with a "claim" field, and tensions carry
"entry_ids" — deliberately distinct from the 14 constitution *principles* used
in the step-3 rewrite. The accessors below prefer those keys and fall back to
the pre-rename names (principles / principle / principle_ids) so runs
snapshotted before the rename still load and re-render.
"""

import json
from pathlib import Path

FILENAME = "reasoning_library.json"
# Filenames used before terminology cleanups; tried in order for old snapshots.
LEGACY_FILENAMES = ("animal_ethics_reasoning_library.json", "animal_ethics_compendium.json")


def resolve_path(prompts_dir: str | Path) -> Path:
    """The library JSON in prompts_dir, preferring the current name and falling
    back to pre-rename names for older snapshots."""
    prompts_dir = Path(prompts_dir)
    current = prompts_dir / FILENAME
    if current.exists():
        return current
    for name in LEGACY_FILENAMES:
        candidate = prompts_dir / name
        if candidate.exists():
            return candidate
    return current  # nonexistent; caller surfaces the error


def load(prompts_dir: str | Path) -> dict:
    return json.loads(resolve_path(prompts_dir).read_text())


def _entries(library: dict) -> list[dict]:
    return library.get("entries") or library.get("principles") or []


def _entry_ids_of(tension: dict) -> list[str]:
    return tension.get("entry_ids") or tension.get("principle_ids") or []


def _claim(entry: dict) -> str:
    return entry.get("claim") or entry.get("principle") or ""


def tension_names(library: dict) -> list[str]:
    return [t["tension"] for t in library["tensions"]]


def tension_index_block(library: dict) -> str:
    return "\n".join(f"- {t['tension']}: {t['definition']}" for t in library["tensions"])


def conduct_ids(library: dict) -> list[str]:
    return [e["id"] for e in _entries(library) if e["family"] == "advising"]


def core_move_ids(library: dict) -> list[str]:
    return [e["id"] for e in _entries(library) if e["family"] == "cross_cutting"]


def format_entries(library: dict, ids: list[str]) -> str:
    by_id = {e["id"]: e for e in _entries(library)}
    blocks = []
    for eid in ids:
        e = by_id.get(eid)
        if not e:
            continue
        blocks.append(
            f"[{e['id']}] {_claim(e)}\n"
            f"Reasoning: {e['reasoning']}\n"
            f"Crux: {e['crux']}\n"
            f"Transferable move: {e['transferable_move']}"
        )
    return "\n\n".join(blocks)


def system_prompt(library: dict) -> str:
    """Standing instructions for every step-2 generation call: the library's
    generation guidance + the always-on conduct entries. Sent verbatim as the
    system prompt — it is instruction-style guidance to the generator, not an
    operator persona and not a description of how the library was built."""
    return (
        library["generation_guidance"]
        + "\n\nALWAYS-ON CONDUCT ENTRIES (apply to every response):\n\n"
        + format_entries(library, conduct_ids(library))
    )


def retrieve(library: dict, tensions: list[str]) -> list[str]:
    """Entry ids for the tagged tensions, in index order, deduped. Conduct
    entries are excluded (they are standing in the system prompt). An empty
    retrieval falls back to the core moves — per the USAGE guide, off-library
    reasoning leans on GP* as scaffolding."""
    conduct = set(conduct_ids(library))
    by_name = {t["tension"]: _entry_ids_of(t) for t in library["tensions"]}
    ids, seen = [], set()
    for name in tensions:
        for eid in by_name.get(name, []):
            if eid not in seen and eid not in conduct:
                seen.add(eid)
                ids.append(eid)
    return ids or core_move_ids(library)
