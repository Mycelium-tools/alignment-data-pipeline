# Viewer Axes Editor (P2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new "Edit axes" viewer page where anyone can add/edit/delete the diversity categories in `evals/dad_axes.yaml` through forms — validated, cost-aware, comment-preserving — with a raw-YAML escape hatch for the `analysis:` block.

**Architecture:** A new pure module `evals/holistic/axes_io.py` owns the ruamel.yaml round-trip (load/edit-in-place/dump), validation (reusing `fields.py` semantics via a small extraction refactor), change classification (paid re-tag vs free) via `bundle.canonical_fields`, and coupling warnings. The streamlit page `viewer/ui_pages/edit_axes.py` is a thin renderer over a session-state draft document; every mutation and check calls `axes_io`.

**Tech Stack:** Python 3.12, ruamel.yaml (new dep), pytest (offline), streamlit `st.navigation` page.

**Source spec:** `docs/holistic-axes-editor-design.md` (user-approved).

## Global Constraints

- Tests NEVER touch the network or the repo `outputs/` tree. Run `source .venv/bin/activate && python -m pytest` from the repo root after every functional change (~3s; **baseline 564 passed**).
- **Do NOT commit.** Standing rule: the user commits explicitly. SDD runs in no-commit mode (snapshot diffs).
- The editor edits exactly one file: `evals/dad_axes.yaml` (no run-local copies, no profiles).
- **Comment preservation via ruamel.yaml round-trip, mutating the loaded tree in place** — never rebuild the document from plain dicts. Saving is idempotent: first save may re-wrap long flow lists once; `dump(load(dump(load(x)))) == dump(load(x))`.
- **Fingerprint identity** = per-field (name, kind, values, derived_from, prompt_hint, required) in order (`evals/holistic/bundle.py:60-75`). `target:` and `analysis:` are NOT identity. Reorders ARE identity. The cost note must reflect exactly this split.
- Warnings **never block** saving (user decision: "warn, don't block").
- In-page captions are **acceptance criteria, not polish** — use the exact copy given in Tasks 6–8.
- `evals/holistic/fields.py` validation is reused, not duplicated (Task 2 extracts `registry_from_data`; behavior must not change).
- The `analysis:` block is editable ONLY through the raw-YAML hatch — no form controls for it.

## File Structure

- **Modify** `requirements.txt` — add `ruamel.yaml>=0.18`.
- **Create** `evals/holistic/axes_io.py` — pure module (imports: `ruamel.yaml`, stdlib, `.fields`, `.bundle`). No streamlit, no API.
- **Create** `tests/test_axes_io.py` — unit tests for `axes_io`.
- **Modify** `evals/holistic/fields.py` — extract `registry_from_data(data, origin)` from `load_fields` (pure refactor + one new test).
- **Create** `viewer/ui_pages/edit_axes.py` — the page (thin; all logic in `axes_io`).
- **Modify** `viewer/app.py` — register the page.
- **Create** `tests/test_viewer_app.py` — nav-registration source test.

---

### Task 1: ruamel round-trip core (`axes_io.py` part 1)

**Files:**
- Modify: `requirements.txt`
- Create: `evals/holistic/axes_io.py`
- Test: `tests/test_axes_io.py`

**Interfaces:**
- Consumes: nothing project-internal yet.
- Produces: `load_doc(path) -> CommentedMap`, `load_text(text) -> CommentedMap`, `dump_text(doc) -> str`, `save_doc(doc, path) -> None`, module constant `AXES_PATH = Path(__file__).resolve().parents[2] / "evals" / "dad_axes.yaml"`. Later tasks rely on these names exactly.

- [ ] **Step 1: Install the dependency**

Add to `requirements.txt` after the `pyyaml` line:

```
ruamel.yaml>=0.18  # comment-preserving round-trip for the viewer axes editor
```

Run: `source .venv/bin/activate && pip install "ruamel.yaml>=0.18"`
Expected: installs cleanly (pure-python wheel).

- [ ] **Step 2: Write the failing tests**

Create `tests/test_axes_io.py`:

```python
"""axes_io: comment-preserving round-trip editing of evals/dad_axes.yaml.

The editor must never destroy the file's documentation: the header block, the
MOCKUP quota comments, and the analysis-block commentary all survive a load →
dump cycle. Byte-identity is guaranteed at the fixed point (the first dump may
re-wrap long flow lists once — ruamel re-emits multi-line flow sequences)."""

from pathlib import Path

from evals.holistic import axes_io

REAL_AXES = Path(__file__).resolve().parents[1] / "evals" / "dad_axes.yaml"

SMALL = """\
# header comment — must survive
fields:
  - name: direction
    kind: single
    derived_from: response
    prompt_hint: Which way it corrected.
    values: [Under-weighting, Over-weighting, Mixed]
    target: {band_each: [0.25, 0.40]}   # MOCKUP: thirds
analysis:
  analyzers: [distribution]   # trailing analysis comment
"""


def test_small_file_roundtrips_byte_identical():
    doc = axes_io.load_text(SMALL)
    assert axes_io.dump_text(doc) == SMALL


def test_real_axes_file_dump_is_idempotent_and_keeps_comments():
    once = axes_io.dump_text(axes_io.load_doc(REAL_AXES))
    twice = axes_io.dump_text(axes_io.load_text(once))
    assert once == twice                              # fixed point
    assert once.startswith("# DAD extraction schema")  # header block kept
    assert "# MOCKUP: every taxa category present" in once
    assert "# MOCKUP quota — tune later" in once
    assert "important_pairs" in once                  # analysis block kept


def test_save_doc_writes_the_dump(tmp_path):
    p = tmp_path / "axes.yaml"
    doc = axes_io.load_text(SMALL)
    axes_io.save_doc(doc, p)
    assert p.read_text() == axes_io.dump_text(doc)


def test_axes_path_points_at_the_canonical_file():
    assert axes_io.AXES_PATH == REAL_AXES
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_axes_io.py -q`
Expected: FAIL — `ModuleNotFoundError: evals.holistic.axes_io`.

- [ ] **Step 4: Write the implementation**

Create `evals/holistic/axes_io.py`:

```python
"""Comment-preserving I/O + edit operations for evals/dad_axes.yaml.

The viewer axes editor works on a ruamel.yaml round-trip document and mutates it
IN PLACE (never rebuilds from plain dicts) so the file's documentation — the
header block, per-quota MOCKUP notes, the analysis commentary — survives every
save. Pure file/logic module: no streamlit, no API.
"""

from __future__ import annotations

import io
from pathlib import Path

from ruamel.yaml import YAML

AXES_PATH = Path(__file__).resolve().parents[2] / "evals" / "dad_axes.yaml"


def _yaml() -> YAML:
    y = YAML()                 # round-trip mode
    y.preserve_quotes = True
    y.width = 4096             # never re-wrap: long flow lists stay on one line
    return y


def load_doc(path: str | Path):
    return _yaml().load(Path(path).read_text())


def load_text(text: str):
    return _yaml().load(text)


def dump_text(doc) -> str:
    buf = io.StringIO()
    _yaml().dump(doc, buf)
    return buf.getvalue()


def save_doc(doc, path: str | Path) -> None:
    Path(path).write_text(dump_text(doc))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_axes_io.py -q`
Expected: 4 passed.

Note: if `test_small_file_roundtrips_byte_identical` fails on comment-column
alignment, adjust SMALL's inline-comment spacing to what ruamel emits (run
`python -c "from evals.holistic import axes_io; print(axes_io.dump_text(axes_io.load_text(open('/tmp/s.yaml').read())))"`
style probe) — the guarantee under test is the fixed point + comment survival,
not one specific column.

- [ ] **Step 6: Run the full suite**

Run: `source .venv/bin/activate && python -m pytest -q`
Expected: 568 passed (564 baseline + 4).

---

### Task 2: Validation reuse (`fields.registry_from_data` + `axes_io.validate_doc`)

**Files:**
- Modify: `evals/holistic/fields.py:118-155` (extract the loop from `load_fields`)
- Modify: `evals/holistic/axes_io.py`
- Test: `tests/test_axes_io.py`, `tests/test_holistic_config.py` (existing `load_fields` tests must stay green untouched)

**Interfaces:**
- Consumes: `Field`, `FieldRegistry` from `evals/holistic/fields.py`.
- Produces: `fields.registry_from_data(data: dict, origin: str = "axes") -> FieldRegistry` (raises `ValueError` with a `origin: fields[i]` locator); `axes_io.registry_from_doc(doc) -> FieldRegistry`; `axes_io.validate_doc(doc) -> list[str]` (empty = valid; fail-fast, one error). Later tasks rely on all three.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_axes_io.py`:

```python
def test_registry_from_doc_builds_real_fields():
    reg = axes_io.registry_from_doc(axes_io.load_doc(REAL_AXES))
    assert "direction" in reg.names()
    assert reg.get("direction").values == ("Under-weighting", "Over-weighting", "Mixed")


def test_validate_doc_ok_on_the_real_file():
    assert axes_io.validate_doc(axes_io.load_doc(REAL_AXES)) == []


def test_validate_doc_reports_bad_kind_with_locator():
    doc = axes_io.load_text(SMALL)
    doc["fields"][0]["kind"] = "banana"
    errs = axes_io.validate_doc(doc)
    assert len(errs) == 1
    assert "fields[0]" in errs[0] and "banana" in errs[0]


def test_validate_doc_reports_quota_naming_a_missing_value():
    doc = axes_io.load_text(SMALL)
    doc["fields"][0]["target"] = {"min_share": {"Nope": 0.2}}
    errs = axes_io.validate_doc(doc)
    assert errs and "Nope" in errs[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_axes_io.py -q`
Expected: 4 new tests FAIL with `AttributeError: ... has no attribute 'registry_from_doc'`.

- [ ] **Step 3: Extract `registry_from_data` in `fields.py`**

Replace the body of `load_fields` (`evals/holistic/fields.py:118-155`) with a thin wrapper plus the extracted function — the loop code moves verbatim (same messages, same behavior):

```python
def registry_from_data(data: dict, origin: str = "axes") -> FieldRegistry:
    """Build a registry from an already-parsed axes mapping. ``origin`` labels
    error locators (``origin: fields[i]``) — the file path when loading from
    disk, a plain tag when validating an in-memory editor draft."""
    reg = FieldRegistry()
    fields = data.get("fields", [])
    if not isinstance(fields, list):
        raise ValueError(f"{origin}: 'fields' must be a list")
    for i, item in enumerate(fields):
        where = f"{origin}: fields[{i}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} must be a mapping")
        if "name" not in item:
            raise ValueError(f"{where} missing required key 'name'")
        try:
            reg.add(Field(
                name=item["name"],
                kind=item.get("kind", "single"),
                values=tuple(item.get("values") or ()),
                derived_from=item.get("derived_from", "scenario"),
                prompt_hint=item.get("prompt_hint", ""),
                required=item.get("required", True),
                target=dict(item.get("target") or {}),
            ))
        except ValueError as e:
            raise ValueError(f"{where}: {e}") from e
    return reg


def load_fields(path: str | Path) -> FieldRegistry:
    """Build a registry from a YAML file — the no-Python way to change the JSON schema.

    Schema::

        fields:
          - name: direction
            kind: single            # single|multi|bool|object|free (default single)
            derived_from: response  # user_turn|response|scenario|structure|meta
            prompt_hint: ...
            values: [Under-weighting, Over-weighting, Mixed]   # omit for free/bool
            required: true          # default true
    """
    path = Path(path)
    data = yaml.safe_load(path.read_text()) or {}
    return registry_from_data(data, origin=str(path))
```

(The only intentional delta from the original loop: `target=dict(...)` instead of
`target=... or {}` — normalizes ruamel `CommentedMap` targets to plain dicts so
`Field` instances compare cleanly. Plain-yaml callers see identical behavior.)

- [ ] **Step 4: Add the axes_io side**

Append to `evals/holistic/axes_io.py` (new import at top: `from .fields import FieldRegistry, registry_from_data`):

```python
def registry_from_doc(doc) -> FieldRegistry:
    """The draft's fields as a real registry (raises ValueError when invalid)."""
    return registry_from_data(doc or {}, origin="axes")


def validate_doc(doc) -> list[str]:
    """[] when the draft would load cleanly; else one fail-fast error message
    carrying the fields[i] locator (duplicate names surface here too)."""
    try:
        registry_from_doc(doc)
    except ValueError as e:
        return [str(e)]
    return []
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_axes_io.py tests/test_holistic_config.py -q`
Expected: all pass (the config tests prove `load_fields` behavior is unchanged).

- [ ] **Step 6: Run the full suite**

Run: `source .venv/bin/activate && python -m pytest -q`
Expected: 572 passed.

---

### Task 3: In-place edit operations (`axes_io.py` part 2)

**Files:**
- Modify: `evals/holistic/axes_io.py`
- Test: `tests/test_axes_io.py`

**Interfaces:**
- Consumes: Task 1's `load_text`/`dump_text`.
- Produces (all mutate `doc` in place; all raise `KeyError` on an unknown axis name):
  `field_names(doc) -> list[str]`, `field_entry(doc, name) -> mapping`,
  `set_attr(doc, name, key, value)` (key ∈ name/kind/derived_from/prompt_hint/required; deletes the key when value equals the load-time default so the file stays terse),
  `set_values(doc, name, values: list[str])` (prunes quota share keys naming removed values; returns the list of pruned value names),
  `set_target(doc, name, target: dict | None)` (None/empty removes the key),
  `add_field(doc, name)` (appends `{name, kind: single, derived_from: scenario, prompt_hint: "", values: []}`; raises `ValueError` on duplicate),
  `delete_field(doc, name)`, `move_field(doc, name, offset: int)` (clamps at the ends).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_axes_io.py`:

```python
def test_set_attr_edits_in_place_and_keeps_neighbor_comments():
    doc = axes_io.load_text(SMALL)
    axes_io.set_attr(doc, "direction", "prompt_hint", "New hint.")
    out = axes_io.dump_text(doc)
    assert "New hint." in out
    assert out.startswith("# header comment — must survive")
    assert "# MOCKUP: thirds" in out          # sibling inline comment kept


def test_set_attr_drops_keys_back_to_default():
    doc = axes_io.load_text(SMALL)
    axes_io.set_attr(doc, "direction", "required", False)
    assert axes_io.field_entry(doc, "direction")["required"] is False
    axes_io.set_attr(doc, "direction", "required", True)   # back to default
    assert "required" not in axes_io.field_entry(doc, "direction")


def test_set_values_prunes_quota_keys_for_removed_values():
    doc = axes_io.load_text(SMALL)
    axes_io.set_target(doc, "direction", {"min_share": {"Mixed": 0.2}})
    pruned = axes_io.set_values(doc, "direction", ["Under-weighting", "Over-weighting"])
    assert pruned == ["Mixed"]
    assert axes_io.field_entry(doc, "direction").get("target") in (None, {},)
    assert axes_io.validate_doc(doc) == []


def test_set_target_none_removes_the_key():
    doc = axes_io.load_text(SMALL)
    axes_io.set_target(doc, "direction", None)
    assert "target" not in axes_io.field_entry(doc, "direction")


def test_add_delete_move_field():
    doc = axes_io.load_text(SMALL)
    axes_io.add_field(doc, "stakes")
    assert axes_io.field_names(doc) == ["direction", "stakes"]
    axes_io.move_field(doc, "stakes", -1)
    assert axes_io.field_names(doc) == ["stakes", "direction"]
    axes_io.move_field(doc, "stakes", -1)                    # clamped at top
    assert axes_io.field_names(doc) == ["stakes", "direction"]
    axes_io.delete_field(doc, "stakes")
    assert axes_io.field_names(doc) == ["direction"]
    assert axes_io.validate_doc(doc) == []


def test_add_field_rejects_duplicates():
    import pytest
    doc = axes_io.load_text(SMALL)
    with pytest.raises(ValueError):
        axes_io.add_field(doc, "direction")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_axes_io.py -q`
Expected: new tests FAIL with `AttributeError`.

- [ ] **Step 3: Write the implementation**

Append to `evals/holistic/axes_io.py`:

```python
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
```

(`delete_field`/`move_field` use `field_names(...).index(name)` so a missing
name raises `ValueError` from `.index` — acceptable; the page only passes names
it just listed.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_axes_io.py -q`
Expected: all pass.

- [ ] **Step 5: Run the full suite**

Run: `source .venv/bin/activate && python -m pytest -q`
Expected: 578 passed.

---

### Task 4: Change classification (paid re-tag vs free)

**Files:**
- Modify: `evals/holistic/axes_io.py`
- Test: `tests/test_axes_io.py`

**Interfaces:**
- Consumes: `bundle.canonical_fields` (`evals/holistic/bundle.py:60-66`), Task 2's `registry_from_doc`.
- Produces: `classify_change(old_doc, new_doc) -> str` returning `"identity" | "quota_only" | "analysis_only" | "none"`. A mixed edit classifies as `identity` (the re-tag dominates the cost either way). Raises `ValueError` if either doc is invalid — the caller guards.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_axes_io.py`:

```python
def _pair():
    return axes_io.load_text(SMALL), axes_io.load_text(SMALL)


def test_classify_none_for_untouched_draft():
    old, new = _pair()
    assert axes_io.classify_change(old, new) == "none"


def test_classify_identity_for_hint_values_and_reorder():
    old, new = _pair()
    axes_io.set_attr(new, "direction", "prompt_hint", "Different.")
    assert axes_io.classify_change(old, new) == "identity"

    old, new = _pair()
    axes_io.add_field(old, "extra"), axes_io.add_field(new, "extra")
    axes_io.move_field(new, "extra", -1)                     # reorder only
    assert axes_io.classify_change(old, new) == "identity"


def test_classify_quota_only_for_target_edits():
    old, new = _pair()
    axes_io.set_target(new, "direction", {"require_all_values": True})
    assert axes_io.classify_change(old, new) == "quota_only"


def test_classify_analysis_only_for_analyzer_edits():
    old, new = _pair()
    new["analysis"]["analyzers"] = ["distribution", "evenness"]
    assert axes_io.classify_change(old, new) == "analysis_only"


def test_classify_mixed_edit_is_identity():
    old, new = _pair()
    axes_io.set_attr(new, "direction", "prompt_hint", "Different.")
    axes_io.set_target(new, "direction", {"require_all_values": True})
    assert axes_io.classify_change(old, new) == "identity"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_axes_io.py -q`
Expected: new tests FAIL with `AttributeError: ... classify_change`.

- [ ] **Step 3: Write the implementation**

Append to `evals/holistic/axes_io.py` (new import at top: `import json`, `from . import bundle`):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_axes_io.py -q`
Expected: all pass.

- [ ] **Step 5: Run the full suite**

Run: `source .venv/bin/activate && python -m pytest -q`
Expected: 583 passed.

---

### Task 5: Coupling warnings (+ important_pairs fixes)

**Files:**
- Modify: `evals/holistic/axes_io.py`
- Test: `tests/test_axes_io.py`

**Interfaces:**
- Consumes: Task 3's helpers.
- Produces: constants `RESERVED_NAMES = ("posture_class", "taxa_category", "direction")` and `GENERATION_KEYS` (the 11 step-1 annotation keys); `renames(old_doc, new_doc) -> list[tuple[str, str]]` (positional detection: same index, different name, neither name on the other side; reorder+rename together may read as delete+add — acceptable, warnings are advisory); `coupling_warnings(old_doc, new_doc) -> list[dict]` where each dict has `kind` ∈ `{"important_pairs", "reserved", "generation_key"}` and `message` (str); `update_important_pairs(doc, old, new) -> None`; `stale_important_pairs(doc) -> list` (pairs naming unknown axes, non-mutating); `prune_important_pairs(doc) -> int` (removes those pairs, returns count). Task 6's page uses `renames`/`stale_important_pairs` for its fix buttons.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_axes_io.py`:

```python
PAIRED = SMALL.replace(
    "analyzers: [distribution]   # trailing analysis comment",
    "analyzers: [distribution]\n  params:\n    important_pairs:\n      - [direction, taxa_category]",
).replace(
    "fields:",
    "fields:\n  - name: taxa_category\n    kind: single\n    values: [farmed, wild]",
)


def _kinds(ws):
    return sorted(w["kind"] for w in ws)


def test_renaming_an_important_pairs_member_warns():
    old, new = axes_io.load_text(PAIRED), axes_io.load_text(PAIRED)
    axes_io.set_attr(new, "taxa_category", "name", "taxa")
    ws = axes_io.coupling_warnings(old, new)
    assert "important_pairs" in _kinds(ws)
    assert "reserved" in _kinds(ws)          # taxa_category is also reserved
    assert "generation_key" in _kinds(ws)    # and a generation annotation key


def test_deleting_an_important_pairs_member_warns():
    old, new = axes_io.load_text(PAIRED), axes_io.load_text(PAIRED)
    axes_io.delete_field(new, "taxa_category")
    assert "important_pairs" in _kinds(axes_io.coupling_warnings(old, new))


def test_untouched_draft_has_no_warnings():
    old, new = axes_io.load_text(PAIRED), axes_io.load_text(PAIRED)
    assert axes_io.coupling_warnings(old, new) == []


def test_renames_are_detected_positionally():
    old, new = axes_io.load_text(PAIRED), axes_io.load_text(PAIRED)
    axes_io.set_attr(new, "taxa_category", "name", "taxa")
    assert axes_io.renames(old, new) == [("taxa_category", "taxa")]
    assert axes_io.renames(old, old) == []


def test_update_important_pairs_rewrites_renamed_member():
    doc = axes_io.load_text(PAIRED)
    axes_io.update_important_pairs(doc, "taxa_category", "taxa")
    assert axes_io.dump_text(doc).count("taxa_category") == 1   # only the field name


def test_stale_and_prune_important_pairs():
    doc = axes_io.load_text(PAIRED)
    assert axes_io.stale_important_pairs(doc) == []
    axes_io.delete_field(doc, "taxa_category")
    assert axes_io.stale_important_pairs(doc) == [["direction", "taxa_category"]]
    assert axes_io.prune_important_pairs(doc) == 1
    assert axes_io.stale_important_pairs(doc) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_axes_io.py -q`
Expected: new tests FAIL with `AttributeError`.

- [ ] **Step 3: Write the implementation**

Append to `evals/holistic/axes_io.py`:

```python
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
    return (((doc or {}).get("analysis") or {}).get("params") or {}) \
        .get("important_pairs") or []


def renames(old_doc, new_doc) -> list[tuple[str, str]]:
    """Positionally detected (old, new) axis renames between two drafts. A
    reorder+rename combo may read as delete+add — acceptable; consumers are
    advisory warnings and optional fix buttons."""
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python -m pytest tests/test_axes_io.py -q`
Expected: all pass.

- [ ] **Step 5: Run the full suite**

Run: `source .venv/bin/activate && python -m pytest -q`
Expected: 590 passed.

---

### Task 6: The Edit axes page — draft state, master list, save flow

**Files:**
- Create: `viewer/ui_pages/edit_axes.py`
- Modify: `viewer/app.py:21-27` (register the page)
- Test: `tests/test_viewer_app.py` (create)

**Interfaces:**
- Consumes: everything `axes_io` produces (Tasks 1–5).
- Produces: the page file that Task 7 extends with the detail form (Task 7 fills the `_detail_form` function this task stubs). Nav registration.

- [ ] **Step 1: Write the failing test**

Create `tests/test_viewer_app.py`:

```python
"""The viewer nav registers real page files — a typo'd st.Page path fails at
click time in streamlit, so pin registration at test time by source scan."""

import re
from pathlib import Path

VIEWER = Path(__file__).resolve().parents[1] / "viewer"


def test_every_registered_page_file_exists_and_edit_axes_is_registered():
    src = (VIEWER / "app.py").read_text()
    pages = re.findall(r'st\.Page\("([^"]+)"', src)
    assert pages, "no st.Page registrations found"
    for rel in pages:
        assert (VIEWER / rel).exists(), f"registered page missing: {rel}"
    assert "ui_pages/edit_axes.py" in pages
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/test_viewer_app.py -q`
Expected: FAIL — `'ui_pages/edit_axes.py' in pages` is False.

- [ ] **Step 3: Register the page**

In `viewer/app.py`, add after the Run diversity line inside `st.navigation([...])`:

```python
    st.Page("ui_pages/edit_axes.py", title="Edit axes", icon=":material/tune:"),
```

- [ ] **Step 4: Create the page (list + save flow; form stubbed)**

Create `viewer/ui_pages/edit_axes.py`:

```python
"""Edit axes page: form-based editing of evals/dad_axes.yaml — the diversity
categories the holistic judge tags every DAD conversation with. All logic lives
in evals/holistic/axes_io.py (ruamel round-trip, validation, cost classification,
coupling warnings); this file only renders a session-state draft document."""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evals.holistic import axes_io

st.title("Edit axes")
st.caption("These are the **diversity categories** the holistic judge tags every "
           "DAD conversation with (`evals/dad_axes.yaml`). Edit them here — the "
           "judge's extraction prompt is rendered from this file, so changes take "
           "effect automatically on the next **Tag** in *Run diversity*. The "
           "mechanistic `analysis:` block (which report metrics run) is edited in "
           "*Raw YAML* below.")


def _draft():
    if "axes_draft" not in st.session_state:
        st.session_state.axes_draft = axes_io.load_doc(axes_io.AXES_PATH)
    return st.session_state.axes_draft


doc = _draft()
disk_doc = axes_io.load_doc(axes_io.AXES_PATH)
names = axes_io.field_names(doc)

left, right = st.columns([1, 2.2], gap="large")

with left:
    if st.button(":material/add: Add axis", type="primary"):
        base, n = "new_axis", 1
        name = base
        while name in names:
            n += 1
            name = f"{base}_{n}"
        axes_io.add_field(doc, name)
        st.session_state.axes_sel = name
        st.rerun()
    sel = st.session_state.get("axes_sel")
    sel = sel if sel in names else (names[0] if names else None)
    for name in names:
        entry = axes_io.field_entry(doc, name)
        quota = " ·  🔵" if entry.get("target") else ""
        label = f"{'▸ ' if name != sel else '▾ '}`{name}`  ·  " \
                f"{entry.get('kind', 'single')}{quota}"
        if st.button(label, key=f"axrow_{name}"):
            st.session_state.axes_sel = name
            st.rerun()
    st.caption("One row per category. 🔵 = has a coverage quota. Click a row to "
               "edit it on the right.")

with right:
    if sel is not None:
        _detail_form_placeholder = st.empty()   # Task 7 replaces this with the form
        _detail_form_placeholder.caption(f"form for `{sel}` lands in Task 7")

# ---------------------------------------------------------------- cost + warnings
try:
    change = axes_io.classify_change(disk_doc, doc)
except ValueError:
    change = None                                # draft transiently invalid
if change == "identity":
    st.warning(":material/paid: **These edits change what the judge tags** — the "
               "next **Tag** will start a fresh bundle and re-tag the corpus (one "
               "cheap LLM call per record). Your old tags are kept untouched in "
               "their own bundle.")
elif change in ("quota_only", "analysis_only"):
    st.info("These edits are **free** — quotas / analysis config only. Re-run "
            "**Analyze** to refresh the report; no re-tagging.")

for w in axes_io.coupling_warnings(disk_doc, doc):
    st.warning(f":material/link_off: {w['message']}")
for old, new in axes_io.renames(disk_doc, doc):
    if any(old in pair for pair in axes_io.stale_important_pairs(doc)):
        if st.button(f"Update `important_pairs`: `{old}` → `{new}`",
                     key=f"fixpair_{old}"):
            axes_io.update_important_pairs(doc, old, new)
            st.rerun()
if axes_io.stale_important_pairs(doc):
    if st.button("Remove stale `important_pairs` entries"):
        axes_io.prune_important_pairs(doc)
        st.rerun()

# ---------------------------------------------------------------- raw escape hatch
with st.expander(":material/code: Raw YAML — full file, incl. the `analysis:` "
                 "block (metrics selection)"):
    st.caption("The escape hatch for anything the form doesn't cover — the "
               "`analysis:` block, `object` kinds, bulk edits. **Apply** replaces "
               "the draft above; parse errors leave it untouched.")
    raw = st.text_area("axes YAML", value=axes_io.dump_text(doc), height=400,
                       label_visibility="collapsed")
    if st.button("Apply raw YAML"):
        try:
            st.session_state.axes_draft = axes_io.load_text(raw)
        except Exception as e:                       # noqa: BLE001 — show any parse error
            st.error(f"not applied — YAML parse error: {e}")
        else:
            st.rerun()

# ---------------------------------------------------------------- save
errors = axes_io.validate_doc(doc)
c1, c2 = st.columns([1, 3])
if c1.button(":material/save: Validate & Save", type="primary", disabled=bool(errors)):
    axes_io.save_doc(doc, axes_io.AXES_PATH)
    st.success(f"Saved `{axes_io.AXES_PATH.name}`. Go to **Run diversity → Tag** "
               "to apply the new schema (a fresh bundle if the tagging inputs "
               "changed).")
for e in errors:
    st.error(f"invalid — fix before saving: {e}")
c2.caption("checks the schema first (bad quota / unknown kind = nothing written), "
           "then saves `evals/dad_axes.yaml`. Warnings above are advisory — they "
           "never block saving.")

# ---------------------------------------------------------------- SDF (filler)
with st.expander("SDF axes"):
    st.caption("SDF documents don't have a categorical axes file yet — the SDF "
               "pipeline's diversity story is still settling. When it lands, its "
               "axes will be editable here the same way.")
```

- [ ] **Step 5: Run the tests**

Run: `source .venv/bin/activate && python -m pytest tests/test_viewer_app.py -q && python -m py_compile viewer/ui_pages/edit_axes.py`
Expected: 1 passed; compile clean.

- [ ] **Step 6: Run the full suite**

Run: `source .venv/bin/activate && python -m pytest -q`
Expected: 591 passed.

---

### Task 7: The detail form (attributes, values, quota editor)

**Files:**
- Modify: `viewer/ui_pages/edit_axes.py` (replace the Task-6 placeholder block)

**Interfaces:**
- Consumes: `axes_io.set_attr/set_values/set_target/delete_field/move_field/field_entry`; `fields.KINDS`, `fields.DERIVED_FROM`.
- Produces: the finished page. No new python interfaces.

- [ ] **Step 1: Replace the placeholder with the form**

In `viewer/ui_pages/edit_axes.py`, add to the imports:

```python
from evals.holistic import fields as fields_mod
```

Replace the two placeholder lines inside `with right:` (`_detail_form_placeholder ...`) with:

```python
        entry = axes_io.field_entry(doc, sel)
        h1, h2, h3, h4 = st.columns([6, 1, 1, 1])
        h1.subheader(f"`{sel}`")
        if h2.button(":material/arrow_upward:", key="ax_up", help="Move up"):
            axes_io.move_field(doc, sel, -1); st.rerun()
        if h3.button(":material/arrow_downward:", key="ax_down", help="Move down"):
            axes_io.move_field(doc, sel, +1); st.rerun()
        if h4.button(":material/delete:", key="ax_del", help="Delete axis"):
            axes_io.delete_field(doc, sel)
            st.session_state.pop("axes_sel", None)
            st.rerun()

        FORM_KINDS = [k for k in fields_mod.KINDS if k != "object"]
        kind = entry.get("kind", "single")
        g1, g2 = st.columns(2)
        new_name = g1.text_input("Name", value=sel, key=f"ax_name_{sel}")
        g1.caption("snake_case; becomes the key in each record's tag JSON")
        if new_name != sel and new_name:
            if new_name in names:
                st.error(f"an axis named `{new_name}` already exists")
            else:
                axes_io.set_attr(doc, sel, "name", new_name)
                st.session_state.axes_sel = new_name
                st.rerun()
        if kind in FORM_KINDS:
            new_kind = g2.selectbox(
                "Kind", FORM_KINDS, index=FORM_KINDS.index(kind), key=f"ax_kind_{sel}",
                help="single = exactly one value · multi = a set of values · "
                     "bool = yes/no · free = any string")
            if new_kind != kind:
                axes_io.set_attr(doc, sel, "kind", new_kind); st.rerun()
        else:
            g2.caption(f"kind `{kind}` — edit via Raw YAML")
        g3, g4 = st.columns(2)
        df = entry.get("derived_from", "scenario")
        new_df = g3.selectbox("Judge reads from", list(fields_mod.DERIVED_FROM),
                              index=list(fields_mod.DERIVED_FROM).index(df),
                              key=f"ax_df_{sel}",
                              help="user_turn = the user's message · response = the "
                                   "assistant's answer · scenario = the situation · "
                                   "structure = conversation shape · meta = about "
                                   "the record itself")
        if new_df != df:
            axes_io.set_attr(doc, sel, "derived_from", new_df); st.rerun()
        req = bool(entry.get("required", True))
        new_req = g4.checkbox("Required — judge must always output it", value=req,
                              key=f"ax_req_{sel}")
        if new_req != req:
            axes_io.set_attr(doc, sel, "required", new_req); st.rerun()
        hint = entry.get("prompt_hint", "")
        new_hint = st.text_input("Prompt hint (one line shown to the judge)",
                                 value=hint, key=f"ax_hint_{sel}")
        if new_hint != hint:
            axes_io.set_attr(doc, sel, "prompt_hint", new_hint); st.rerun()

        # ---- values (hidden for bool/free) ----
        values = [str(v) for v in (entry.get("values") or [])]
        if kind in ("single", "multi"):
            st.markdown("**Allowed values**")
            for i, val in enumerate(values):
                v1, v2 = st.columns([8, 1])
                v1.code(val, language=None)
                if v2.button("✕", key=f"ax_valdel_{sel}_{i}"):
                    pruned = axes_io.set_values(doc, sel,
                                                values[:i] + values[i + 1:])
                    if pruned:
                        st.toast(f"also removed quota entries for: {pruned}")
                    st.rerun()
            a1, a2 = st.columns([8, 1])
            new_val = a1.text_input("add value", key=f"ax_valadd_{sel}",
                                    label_visibility="collapsed",
                                    placeholder="add a value…")
            if a2.button("Add", key=f"ax_valaddbtn_{sel}"):
                if new_val and new_val not in values:
                    axes_io.set_values(doc, sel, values + [new_val]); st.rerun()
                elif new_val:
                    st.error("value already present (values are a set)")
            st.caption("the judge must pick from these; removing one that a quota "
                       "references removes that quota entry too")

        # ---- quota editor ----
        RULES = ["none", "require_all_values", "min_share", "max_share",
                 "max_share_each", "band_each"]
        target = dict(entry.get("target") or {})
        current = next((r for r in RULES[1:] if r in target), "none")
        st.markdown("**Coverage quota** *(optional — checked by the report, never "
                    "blocks tagging)*")
        rule = st.selectbox("Rule", RULES, index=RULES.index(current),
                            key=f"ax_rule_{sel}",
                            help="require_all_values = every value present · "
                                 "min/max_share = per-value share floor/cap · "
                                 "max_share_each = one cap for every value · "
                                 "band_each = every value inside [lo, hi]")
        new_target: dict | None
        if rule == "none":
            new_target = None
        elif rule == "require_all_values":
            new_target = {"require_all_values": True}
        elif rule in ("min_share", "max_share"):
            shares = dict(target.get(rule) or {})
            picked = st.multiselect("Values with a quota", values,
                                    default=[v for v in shares if v in values],
                                    key=f"ax_qvals_{sel}")
            new_shares = {}
            for v in picked:
                new_shares[v] = st.number_input(
                    f"{rule} · {v}", 0.0, 1.0, float(shares.get(v, 0.1)), 0.05,
                    key=f"ax_qs_{sel}_{v}")
            new_target = {rule: new_shares} if new_shares else None
        elif rule == "max_share_each":
            cap = st.number_input("Cap for every value", 0.0, 1.0,
                                  float(target.get("max_share_each", 0.12)), 0.01,
                                  key=f"ax_qcap_{sel}")
            new_target = {"max_share_each": cap}
        else:  # band_each
            band = list(target.get("band_each") or [0.25, 0.40])
            b1c, b2c = st.columns(2)
            lo = b1c.number_input("Low", 0.0, 1.0, float(band[0]), 0.05,
                                  key=f"ax_qlo_{sel}")
            hi = b2c.number_input("High", 0.0, 1.0, float(band[1]), 0.05,
                                  key=f"ax_qhi_{sel}")
            new_target = {"band_each": [lo, hi]}
        if new_target != (dict(entry.get("target")) if entry.get("target") else None):
            axes_io.set_target(doc, sel, new_target)
            st.rerun()
        st.caption("Quota edits are **free** — re-Analyze only, no re-tagging.")
```

- [ ] **Step 2: Compile + suite**

Run: `source .venv/bin/activate && python -m py_compile viewer/ui_pages/edit_axes.py && python -m pytest -q`
Expected: compile clean; 591 passed.

- [ ] **Step 3: Live smoke (the implementer must actually do this)**

Run: `streamlit run viewer/app.py` (or the `viewer` config in `.claude/launch.json` via preview tooling), open **Edit axes**, and verify:
- the 19 real axes render in the list; selecting `direction` shows its real values and the `band_each` 0.25/0.40 quota;
- editing the prompt hint makes the amber paid-re-tag note appear;
- changing only the quota makes the blue "free" note appear instead;
- Add axis → new row appears selected; delete removes it;
- **do NOT click Save against the real file except as the final check below.**
Save-flow file check (safe, uses a copy): temporarily launch with a copied axes
file is NOT wired — instead verify Save via `git diff evals/dad_axes.yaml` after
one deliberate hint edit + Save, confirm only that line changed and all comments
survived, then `git checkout -- evals/dad_axes.yaml` to restore.

---

### Task 8: Final integration pass

**Files:**
- Test: full suite + manual spec walkthrough

**Interfaces:**
- Consumes: everything above.
- Produces: done-state per the spec's "How to verify".

- [ ] **Step 1: Full suite**

Run: `source .venv/bin/activate && python -m pytest -q`
Expected: 591 passed, offline, ~3s.

- [ ] **Step 2: Spec walkthrough (manual, against the live viewer)**

Follow `docs/holistic-axes-editor-design.md` §"How to verify" items 1–5 in order.
For item 3 (new axis end-to-end), use the smallest run under `outputs/dad/runs/`
and a cheap model in the Run diversity model box; confirm the new axis appears
in the fresh bundle's tags. Afterward `git checkout -- evals/dad_axes.yaml` and
delete the scratch bundle dir it created (it lives under that run's `holistic/`).

- [ ] **Step 3: Report deviations**

List any deviations from the spec (there should be none beyond the documented
idempotent-save guarantee) in the completion summary for the user.
