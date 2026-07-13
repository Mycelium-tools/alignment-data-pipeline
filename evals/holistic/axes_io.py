"""Comment-preserving I/O + edit operations for evals/dad_axes.yaml.

The viewer axes editor works on a ruamel.yaml round-trip document and mutates it
IN PLACE (never rebuilds from plain dicts) so the file's documentation — the
header block, per-quota MOCKUP notes, the analysis commentary — survives every
save. Pure file/logic module: no streamlit, no API.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import yaml
from ruamel.yaml import YAML

from . import bundle
from .fields import FieldRegistry, registry_from_data

AXES_PATH = Path(__file__).resolve().parents[2] / "evals" / "dad_axes.yaml"


def _yaml() -> YAML:
    y = YAML()                 # round-trip mode
    y.preserve_quotes = True
    y.width = 4096             # never re-wrap: long flow lists stay on one line
    y.indent(mapping=2, sequence=4, offset=2)  # match dad_axes.yaml's indented dashes
    return y


def load_doc(path: str | Path):
    return _yaml().load(Path(path).read_text())


def load_text(text: str):
    return _yaml().load(text)


def dump_text(doc) -> str:
    buf = io.StringIO()
    _yaml().dump(doc, buf)
    return buf.getvalue()


def _atomic_write(path: str | Path, text: str) -> None:
    """Write via a same-directory temp file + os.replace — a crash or concurrent
    read mid-write never sees a truncated file."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def save_doc(doc, path: str | Path) -> None:
    _atomic_write(path, dump_text(doc))


def save_text(text: str, path: str | Path) -> None:
    """Atomically replace ``path`` with ``text`` (same temp+rename pattern as
    ``save_doc`` — a crash mid-write must not truncate a prompt file)."""
    _atomic_write(path, text)


def registry_from_doc(doc) -> FieldRegistry:
    """The draft's fields as a real registry (raises ValueError when invalid)."""
    return registry_from_data(doc or {}, origin="axes")


def structurally_editable(doc) -> bool:
    """True when the doc is a mapping whose fields entries are mappings with
    string names — the minimum shape the editor can render (weaker than
    validate_doc, so a semantically-invalid draft stays fixable in the form)."""
    if not isinstance(doc, dict) or not isinstance(doc.get("fields"), list) or not doc.get("fields"):
        return False
    return all(isinstance(f, dict) and isinstance(f.get("name"), str) and f.get("name")
               for f in doc["fields"])


def validate_doc(doc) -> list[str]:
    """[] when the draft would load cleanly and save back out readably; else one
    fail-fast error message (never raises — the caller is a save-gate, so a
    malformed draft, however mangled, must produce a message, not a crash)."""
    if not isinstance(doc, dict) or not doc.get("fields"):
        return ["axes file must be a mapping with a non-empty fields: list"]
    if "analysis" in doc and not isinstance(doc["analysis"], dict):
        return ["analysis: must be a mapping"]
    try:
        registry_from_doc(doc)
    except (ValueError, TypeError) as e:
        return [str(e)]
    try:
        yaml.safe_load(dump_text(doc))
    except Exception as e:                    # noqa: BLE001 — any dump/reload failure
        return [f"saved YAML would not be readable by the pipeline's loader: {e}"]
    return []


_ATTR_DEFAULTS = {"kind": "single", "derived_from": "scenario",
                  "prompt_hint": "", "required": True}


def field_names(doc) -> list[str]:
    return [f["name"] for f in (doc or {}).get("fields", [])]


def field_entry(doc, name: str):
    for f in doc.get("fields", []):
        if f["name"] == name:
            return f
    raise KeyError(name)


def set_attr(doc, name: str, key: str, value) -> None:
    entry = field_entry(doc, name)
    if key != "name" and value == _ATTR_DEFAULTS.get(key, object()):
        entry.pop(key, None)          # keep the file terse: defaults stay implicit
    else:
        entry[key] = value


def set_values(doc, name: str, values: list[str]) -> list[str]:
    """Replace an axis's vocabulary; prune quota share keys that name removed
    values (a stale key fails load — fields.py target integrity). Returns the
    pruned value names so the page can tell the user."""
    entry = field_entry(doc, name)
    entry["values"] = list(values)
    pruned: list[str] = []
    target = entry.get("target") or {}
    for rule in ("min_share", "max_share"):
        shares = target.get(rule)
        if isinstance(shares, dict):
            for val in [v for v in shares if v not in values]:
                del shares[val]
                pruned.append(val)
            if not shares:
                del target[rule]
    if "target" in entry and not entry["target"]:
        del entry["target"]
    return pruned


def set_target(doc, name: str, target: dict | None) -> None:
    entry = field_entry(doc, name)
    if target:
        entry["target"] = target
    else:
        entry.pop("target", None)


def add_field(doc, name: str) -> None:
    if name in field_names(doc):
        raise ValueError(f"axis {name!r} already exists")
    doc.setdefault("fields", []).append(
        {"name": name, "kind": "single", "derived_from": "scenario",
         "prompt_hint": "", "values": []})


def delete_field(doc, name: str) -> None:
    fields = doc.get("fields", [])
    fields.pop(field_names(doc).index(name))


def move_field(doc, name: str, offset: int) -> None:
    fields = doc.get("fields", [])
    i = field_names(doc).index(name)
    j = max(0, min(len(fields) - 1, i + offset))
    if i != j:
        fields.insert(j, fields.pop(i))


def _plain(node):
    """ruamel nodes → plain JSON-safe python for comparison."""
    return json.loads(json.dumps(node, default=str)) if node is not None else None


def classify_change(old_doc, new_doc) -> str:
    """What saving new_doc over old_doc costs. ``identity`` = the tag fingerprint
    changes → the next Tag starts a fresh bundle (paid re-tag). ``quota_only`` /
    ``analysis_only`` = free (re-Analyze in place). Mixed edits classify as
    identity — the re-tag dominates. Both docs must be valid (registry builds)."""
    old_reg, new_reg = registry_from_doc(old_doc), registry_from_doc(new_doc)
    if bundle.canonical_fields(old_reg) != bundle.canonical_fields(new_reg):
        return "identity"
    if [f.target for f in old_reg.all()] != [f.target for f in new_reg.all()]:
        return "quota_only"
    if _plain((old_doc or {}).get("analysis")) != _plain((new_doc or {}).get("analysis")):
        return "analysis_only"
    return "none"


# Axes whose NAMES other code reads literally. Renaming warns, never blocks
# (user decision): nothing crashes, but joins silently de-link —
# posture_class: quality-judge lane (evals/judge.py, judge_checklist.py,
# report_dad.py); taxa_category/direction: --where facets, drift, judge output.
RESERVED_NAMES = ("posture_class", "taxa_category", "direction")

# Step-1 generation-annotation keys. The drift analyzer joins extraction axes
# to generation intent BY IDENTICAL NAME (analyzers.py has no explicit list) —
# renaming an axis off this list silently drops it from drift.
GENERATION_KEYS = ("domain", "user_goal", "visibility", "user_attitude",
                   "conflict", "direction", "user_stakes", "leverage",
                   "values_in_tension", "taxa_category", "systemic_ai")


def _important_pairs(doc) -> list:
    if not isinstance(doc, dict):
        return []
    analysis = doc.get("analysis")
    if not isinstance(analysis, dict):
        return []
    params = analysis.get("params")
    if not isinstance(params, dict):
        return []
    pairs = params.get("important_pairs")
    return pairs if isinstance(pairs, list) else []


def renames(old_doc, new_doc) -> list[tuple[str, str]]:
    """Positionally detected (old, new) axis renames between two drafts. A
    reorder+rename combo may read as delete+add — acceptable; consumers are
    advisory warnings and optional fix buttons. When the field COUNT differs
    (a field was also added or deleted in the same draft), detection is
    skipped entirely and this returns [] — no renames are surfaced at all, so
    advisory consumers (coupling warnings, important_pairs auto-fix buttons)
    silently lose their rename signal for that draft, not just for the
    reorder+rename case above."""
    old_names, new_names = field_names(old_doc), field_names(new_doc)
    if len(old_names) != len(new_names):
        return []
    return [(o, n) for o, n in zip(old_names, new_names)
            if o != n and o not in new_names and n not in old_names]


def coupling_warnings(old_doc, new_doc) -> list[dict]:
    """Advisory (never blocking) warnings about name couplings the draft breaks."""
    old_names, new_names = field_names(old_doc), field_names(new_doc)
    renamed = renames(old_doc, new_doc)
    renamed_from = [o for o, _ in renamed]
    deleted = [n for n in old_names if n not in new_names and n not in renamed_from]
    warnings = []
    pair_members = {m for pair in _important_pairs(new_doc) for m in pair}
    for name in renamed_from + deleted:
        if name in pair_members:
            warnings.append({
                "kind": "important_pairs",
                "message": f"`{name}` is referenced in `analysis.params.important_pairs` "
                           "— the correlation and combination-coverage checks for that "
                           "pair will silently go dark unless the pairs are updated."})
    for old, new in renamed:
        if old in RESERVED_NAMES:
            warnings.append({
                "kind": "reserved",
                "message": f"`{old}` is read by name outside this file "
                           "(evals/judge.py, judge_checklist.py, report_dad.py, "
                           "`--where` facets) — renaming it de-links those joins. "
                           "Nothing crashes, but they silently stop matching."})
        if old in GENERATION_KEYS:
            warnings.append({
                "kind": "generation_key",
                "message": f"`{old}` matches a generation-annotation key — renaming it "
                           f"to `{new}` silently drops it from the drift analyzer "
                           "(intent-vs-realized comparison joins by identical name)."})
    for name in deleted:
        if name in RESERVED_NAMES:
            warnings.append({
                "kind": "reserved",
                "message": f"`{name}` is read by name outside this file — deleting it "
                           "empties those joins (see evals/judge.py, report_dad.py)."})
        if name in GENERATION_KEYS:
            warnings.append({
                "kind": "generation_key",
                "message": f"`{name}` matches a generation-annotation key — deleting it "
                           "silently drops it from the drift analyzer "
                           "(intent-vs-realized comparison joins by identical name)."})
    return warnings


def update_important_pairs(doc, old: str, new: str) -> None:
    for pair in _important_pairs(doc):
        for i, member in enumerate(pair):
            if member == old:
                pair[i] = new


def stale_important_pairs(doc) -> list:
    """Pairs in analysis.params.important_pairs naming an axis that no longer
    exists (as plain lists; non-mutating)."""
    known = set(field_names(doc))
    return [list(p) for p in _important_pairs(doc) if not set(p) <= known]


def prune_important_pairs(doc) -> int:
    pairs = _important_pairs(doc)
    known = set(field_names(doc))
    stale = [p for p in pairs if not set(p) <= known]
    for p in stale:
        pairs.remove(p)
    return len(stale)
