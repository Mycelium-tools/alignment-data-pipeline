"""Load and format the animal-ethics reasoning library.

Source of truth is prompts/dad/reasoning_library.csv (the CSV migration retired
the JSON). Rows are entries with columns: id, category, claim, reasoning,
trigger_condition, transferable_move. Every entry — conduct (C*), core move
(M*), and topic (T*) alike — is conditional: a dedicated selection call after
2a scoping (step2_select.txt) reads the trigger index (trigger_index_block)
and flags which entries fire for the case, and 2b injects only the flagged
rows (falling open to the whole library when the selection is unusable).
Which rows were injected is recorded per prompt in step2/scopes.jsonl and on
each response record's entry_ids.

Older run snapshots that predate the migration hold a reasoning_library.json
(entries under `entries`/`principles`, families advising/cross_cutting/reasoning,
plus generation_guidance and tensions); the loader still reads those so their
lineage re-renders. Accessors work across both shapes.
"""

import csv
import io
import json
from pathlib import Path

CSV_FILENAME = "reasoning_library.csv"
JSON_FILENAME = "reasoning_library.json"  # retired source; still read from old snapshots
# Filenames used before terminology cleanups; tried in order for old snapshots.
LEGACY_JSON_FILENAMES = ("animal_ethics_reasoning_library.json", "animal_ethics_compendium.json")

CONDUCT_CATEGORY = "Conduct"
CORE_MOVE_CATEGORY = "Core move"


def resolve_path(prompts_dir: str | Path) -> Path:
    """The library file in prompts_dir, preferring the current CSV and falling
    back to the retired JSON (and pre-rename JSON names) for older snapshots."""
    prompts_dir = Path(prompts_dir)
    csv_path = prompts_dir / CSV_FILENAME
    if csv_path.exists():
        return csv_path
    for name in (JSON_FILENAME,) + LEGACY_JSON_FILENAMES:
        candidate = prompts_dir / name
        if candidate.exists():
            return candidate
    return csv_path  # nonexistent; caller surfaces the error


def parse_text(text: str, filename: str) -> dict:
    """Parse library text by extension: CSV → {entries}; JSON → as authored."""
    if filename.lower().endswith(".csv"):
        return {"entries": list(csv.DictReader(io.StringIO(text)))}
    return json.loads(text)


def load(prompts_dir: str | Path) -> dict:
    path = resolve_path(prompts_dir)
    return parse_text(path.read_text(encoding="utf-8"), path.name)


def _entries(library: dict) -> list[dict]:
    return library.get("entries") or library.get("principles") or []


def _claim(entry: dict) -> str:
    return entry.get("claim") or entry.get("principle") or ""


def conduct_ids(library: dict) -> list[str]:
    """C* conduct entries (CSV), or the advising family (old JSON)."""
    return [e["id"] for e in _entries(library)
            if e.get("category") == CONDUCT_CATEGORY or e.get("family") == "advising"]


def core_move_ids(library: dict) -> list[str]:
    """M* core moves (CSV), or the cross_cutting family (old JSON)."""
    return [e["id"] for e in _entries(library)
            if e.get("category") == CORE_MOVE_CATEGORY or e.get("family") == "cross_cutting"]


def tension_names(library: dict) -> list[str]:
    """Empty for the CSV library (tensions were retired); real for old JSON
    snapshots so the viewer can still re-render their step-1/2a lineage."""
    return [t["tension"] for t in library.get("tensions", [])]


def tension_index_block(library: dict) -> str:
    return "\n".join(f"- {t['tension']}: {t['definition']}"
                     for t in library.get("tensions", []))


def all_ids(library: dict) -> list[str]:
    return [e["id"] for e in _entries(library)]


def get_entries(library: dict, ids: list[str]) -> list[dict]:
    """The full rows for ids, in the order given; unknown ids are dropped."""
    by_id = {e["id"]: e for e in _entries(library)}
    return [by_id[i] for i in ids if i in by_id]


def trigger_index_block(library: dict) -> str:
    """One line per entry — id plus trigger condition — the lightweight index
    the 2a.5 select prompt evaluates instead of loading the whole library."""
    return "\n".join(f"- {e['id']}: {e.get('trigger_condition', '')}"
                     for e in _entries(library))


def format_library(library: dict) -> str:
    """The whole library formatted for the response prompt (all entries, in file
    order: conduct, core moves, then topic reasoning)."""
    return format_entries(library, all_ids(library))


def format_entries(library: dict, ids: list[str]) -> str:
    by_id = {e["id"]: e for e in _entries(library)}
    blocks = []
    for eid in ids:
        e = by_id.get(eid)
        if not e:
            continue
        # .get(): legacy snapshots (pre-CSV library formats) may lack fields —
        # render what exists rather than crashing the viewer's lineage page.
        # Current CSV rows carry trigger_condition; older snapshots carried
        # crux — render whichever this library has so old runs re-render as sent.
        middle = (f"Trigger condition: {e['trigger_condition']}"
                  if "trigger_condition" in e else f"Crux: {e.get('crux', '')}")
        blocks.append(
            f"[{e['id']}] {_claim(e)}\n"
            f"Reasoning: {e.get('reasoning', '')}\n"
            f"{middle}\n"
            f"Transferable move: {e.get('transferable_move', '')}"
        )
    return "\n\n".join(blocks)


def system_prompt(library: dict) -> str:
    """LEGACY — the pipeline no longer sends this; the 2b template is
    self-contained. Kept for the viewer, which reconstructs the system prompt
    of runs recorded before that: the conduct rules (C*), preceded by the old
    generation_guidance if the snapshot still carries one."""
    parts = []
    guidance = library.get("generation_guidance") or ""
    if guidance.strip():
        parts.append(guidance)
    parts.append(
        "STANDING CONDUCT RULES (apply to every response, whether or not the user "
        "mentions animals):\n\n" + format_entries(library, conduct_ids(library))
    )
    return "\n\n".join(parts)
