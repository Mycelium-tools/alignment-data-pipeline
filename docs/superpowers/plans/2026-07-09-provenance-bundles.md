# Holistic Provenance Bundles (P1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every holistic Tag/Analyze writes into a self-describing, fingerprint-keyed bundle directory so results are never overwritten, always carry their provenance, and identical inputs resume instead of re-paying.

**Architecture:** A new pure module `evals/holistic/bundle.py` owns fingerprinting and the bundle store (`<run>/holistic/<ts>_<fp8>/`). `pipeline.tag` routes writes through it; `resolve_inputs` gains a `bundle_id` for reads (default = the `latest` symlink). The CLI, `score_dad` facet selection, `viewer/loader`, and the two viewer pages all read/write through the same layer. Legacy flat `audit/category_records.jsonl` surfaces as an implicit read-only `legacy` bundle when no real bundle exists.

**Tech Stack:** Python 3.12, pytest (offline, `stub_claude`), streamlit (viewer pages), PyYAML, stdlib `hashlib`/`json`.

**Source spec:** `docs/holistic-provenance-bundles-design.md` (user-approved).

## Global Constraints

- Tests NEVER touch the network or the repo `outputs/` tree: pytest-socket, `stub_claude`, `tmp_path`. Run `source .venv/bin/activate && python -m pytest` from the repo root after every functional change (~2s; baseline 490 passed).
- **Do NOT commit.** The branch working tree is deliberately uncommitted; the user commits explicitly. Skip any commit step your habits suggest.
- Bundle dir name is exactly `<YYYY-MM-DD_HH-MM>_<fp8>` — no human label (user decision, do not add one).
- The `latest` symlink is **relative** (matches the `outputs/*/latest` idiom; reuse `shared.utils._update_latest_symlink`).
- Timestamps/hashes are asserted **by shape, never by value** in tests.
- **Fingerprint identity = fields + model + extract-prompt text only.** Per-field identity is `name, kind, values, derived_from, prompt_hint, required`. Two deliberate deviations from the spec's literal field list, both following its stated principle ("exactly the inputs that determine the tags") — flag both in the session summary to the user:
  - `prompt_hint` IS identity (it is rendered into the extraction prompt; editing it changes the tags — resuming would mix schemas).
  - `target` is NOT identity (quotas only feed the coverage analyzer; including it would force a paid re-tag on a quota tweak — the exact trap the spec's analysis-exclusion avoids).
- The `analysis:` block and synthesis prompt are never identity; Analyze rewrites `report.json` in place inside the selected bundle and stamps `manifest.analysis`.
- The in-page captions in Tasks 7–8 are **acceptance criteria, not polish** — use the exact copy given.
- New tags never write to the legacy flat path; legacy flat files are left byte-untouched.

## File Structure

- **Create** `evals/holistic/bundle.py` — fingerprint + bundle store. Pure file I/O; imports only stdlib, `yaml`, `shared.utils`, `.fields`. No streamlit, no API.
- **Create** `tests/test_holistic_bundles.py` — unit tests for `bundle.py`.
- **Modify** `evals/holistic/pipeline.py` — `Inputs.holistic_root`, bundle-aware `resolve_inputs(bundle_id=...)`, `tag()` routes through `resolve_bundle`, `run(axes_text=...)`.
- **Modify** `evals/holistic_dad.py` — bundle-aware `report_path_for`, `--bundle` flag, `record_bundle_analysis` helper shared with the viewer, pass `axes_text`.
- **Modify** `evals/score_dad.py` — `select_records` facet index becomes bundle-aware (latest bundle → legacy flat).
- **Modify** `viewer/loader.py` — `list_bundles`, `latest_bundle_id`, `bundle_id` params on `category_records`/`holistic_report`/`combined_index`.
- **Modify** `viewer/ui_pages/run_diversity.py` — bundle picker + manifest facts + updated captions; Tag/Analyze write through the bundle layer.
- **Modify** `viewer/ui_pages/judge_batch.py` — bundle picker for the facet source + caption.
- **Modify tests** `tests/test_holistic_pipeline.py`, `tests/test_holistic_cli.py`, `tests/test_score_dad_selection.py`, `tests/test_viewer_loader.py`.

---

### Task 1: Fingerprint (`bundle.py` part 1)

**Files:**
- Create: `evals/holistic/bundle.py`
- Test: `tests/test_holistic_bundles.py`

**Interfaces:**
- Consumes: `FieldRegistry`/`Field` from `evals/holistic/fields.py` (`.all()` returns ordered `Field`s with `name, kind, values, derived_from, prompt_hint, required, target`).
- Produces: `canonical_fields(fields) -> list[dict]`, `tag_fingerprint(fields, model, extract_template) -> str` (64-char sha256 hex), `prompt_sha(text | None) -> str | None`. Module constants `INDEX_NAME = "category_records.jsonl"`, `REPORT_NAME = "report.json"`, `MANIFEST_NAME = "manifest.json"`, `AXES_SNAPSHOT_NAME = "axes_snapshot.yaml"`, `LEGACY_ID = "legacy"`. Later tasks rely on all of these names exactly.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_holistic_bundles.py`:

```python
"""Provenance bundles (P1): fingerprint identity + the bundle store.

Bundle identity is sha256 over (canonical fields, model, extract template) —
exactly the inputs that determine the tags. Cosmetic YAML edits must not change
it; quota targets must not either (they only feed the coverage analyzer);
prompt_hint must (it is rendered into the extraction prompt)."""

import hashlib
import json

from evals.holistic import bundle
from evals.holistic import fields as fields_mod
from shared import utils

AXES_A = """\
# documented header comment
fields:
  - name: direction
    kind: single
    values: [Under-weighting, Over-weighting, Mixed]
  - name: is_multi_species
    kind: bool
"""

# same semantic fields: different key order, quoting, comments, spacing
AXES_A_COSMETIC = """\
fields:
  - kind: single
    name: "direction"
    values: ["Under-weighting", "Over-weighting", "Mixed"]

  # trailing comment
  - name: is_multi_species
    kind: bool
"""

AXES_B = AXES_A.replace("Mixed", "Balanced")   # one vocabulary value changed


def _reg(text, tmp_path, name="axes.yaml"):
    p = tmp_path / name
    p.write_text(text)
    return fields_mod.load_fields(p)


# ---------------------------------------------------------------- fingerprint

def test_fingerprint_is_stable_for_identical_inputs(tmp_path):
    a = bundle.tag_fingerprint(_reg(AXES_A, tmp_path), "m", "tpl")
    b = bundle.tag_fingerprint(_reg(AXES_A, tmp_path, "b.yaml"), "m", "tpl")
    assert a == b
    assert len(a) == 64 and int(a, 16) >= 0    # full sha256 hex


def test_fingerprint_ignores_cosmetic_yaml_differences(tmp_path):
    assert bundle.tag_fingerprint(_reg(AXES_A, tmp_path), None, None) == \
        bundle.tag_fingerprint(_reg(AXES_A_COSMETIC, tmp_path, "c.yaml"), None, None)


def test_fingerprint_changes_with_field_semantics_model_and_prompt(tmp_path):
    reg = _reg(AXES_A, tmp_path)
    base = bundle.tag_fingerprint(reg, None, None)
    assert bundle.tag_fingerprint(_reg(AXES_B, tmp_path, "b.yaml"), None, None) != base
    assert bundle.tag_fingerprint(reg, "gemini-2.5-flash", None) != base
    assert bundle.tag_fingerprint(reg, None, "other prompt") != base


def test_fingerprint_includes_prompt_hints_but_not_quota_targets(tmp_path):
    # prompt_hint is rendered into the extraction prompt → identity;
    # target only feeds the coverage analyzer → editing a quota must NOT
    # force a paid re-tag (spec: the analysis-exclusion rationale).
    base = bundle.tag_fingerprint(_reg(AXES_A, tmp_path), None, None)
    hinted = AXES_A.replace("kind: bool", "kind: bool\n    prompt_hint: say why")
    assert bundle.tag_fingerprint(_reg(hinted, tmp_path, "h.yaml"), None, None) != base
    quota = AXES_A.replace(
        "kind: single",
        "kind: single\n    target: {min_share: {Mixed: 0.2}}")
    assert bundle.tag_fingerprint(_reg(quota, tmp_path, "q.yaml"), None, None) == base


def test_prompt_sha_hashes_text_and_passes_none_through():
    assert bundle.prompt_sha(None) is None
    assert bundle.prompt_sha("tpl") == hashlib.sha256(b"tpl").hexdigest()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source .venv/bin/activate && python -m pytest tests/test_holistic_bundles.py -v`
Expected: FAIL — `ModuleNotFoundError`/`ImportError` (no `evals.holistic.bundle`).

- [ ] **Step 3: Write the implementation**

Create `evals/holistic/bundle.py`:

```python
"""Provenance bundles for the holistic Tag/Analyze lane.

A bundle is one tagging pass: a directory ``<holistic_root>/<ts>_<fp8>/`` holding
the tag index plus a snapshot of exactly what produced it (axes, model, prompt,
git commit). Bundle identity is the tag-fingerprint — sha256 over the canonical
fields + model + extract-prompt text — so identical inputs resume the same bundle
(no re-paying) and any semantic change starts a fresh one; tags from two schemas
can never mix. The ``analysis:`` block and the synthesis prompt are deliberately
NOT identity: Analyze rewrites ``report.json`` inside the existing bundle.

Per-field identity is (name, kind, values, derived_from, prompt_hint, required):
``prompt_hint`` is rendered into the extraction prompt, so editing it changes the
tags; ``target`` quotas only feed the coverage analyzer, so a quota tweak must
not force a paid re-tag.

Pure file I/O — no streamlit, no API.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from shared import utils

from .fields import FieldRegistry

INDEX_NAME = "category_records.jsonl"
REPORT_NAME = "report.json"
MANIFEST_NAME = "manifest.json"
AXES_SNAPSHOT_NAME = "axes_snapshot.yaml"
LEGACY_ID = "legacy"


@dataclass
class BundlePaths:
    bundle_dir: Path
    index_path: Path
    report_path: Path


@dataclass
class BundleInfo:
    bundle_id: str          # dir name, or "legacy"
    path: Path              # bundle dir (legacy: the flat index's parent)
    manifest: dict          # {} for legacy


def _paths(bundle_dir: Path) -> BundlePaths:
    return BundlePaths(bundle_dir, bundle_dir / INDEX_NAME, bundle_dir / REPORT_NAME)


# ---------------------------------------------------------------- fingerprint

def canonical_fields(fields: FieldRegistry) -> list[dict]:
    """The tag-relevant content of the registry, in registry order."""
    return [{
        "name": f.name, "kind": f.kind, "values": list(f.values),
        "derived_from": f.derived_from, "prompt_hint": f.prompt_hint,
        "required": f.required,
    } for f in fields.all()]


def tag_fingerprint(fields: FieldRegistry, model: str | None,
                    extract_template: str | None) -> str:
    payload = json.dumps(
        {"fields": canonical_fields(fields), "model": model or "",
         "extract_prompt": extract_template or ""},
        sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def prompt_sha(text: str | None) -> str | None:
    return hashlib.sha256(text.encode()).hexdigest() if text is not None else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_holistic_bundles.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`
Expected: baseline 490 + 5 passed, 0 failed.

---

### Task 2: Bundle store (`bundle.py` part 2)

**Files:**
- Modify: `evals/holistic/bundle.py` (append to Task 1's file)
- Test: `tests/test_holistic_bundles.py` (append)

**Interfaces:**
- Consumes: Task 1's fingerprint functions; `shared.utils._update_latest_symlink(parent, dir)`, `utils._git_status()`, `utils.load_jsonl`.
- Produces (later tasks call these exact signatures):
  - `list_bundles(holistic_root: Path, legacy_index: Path | None = None) -> list[BundleInfo]` — newest-first by dir name; malformed manifest ⇒ warn + skip; implicit `legacy` entry only when no real bundle exists and `legacy_index` exists.
  - `resolve_bundle(holistic_root, fields, *, model=None, extract_template=None, axes_text=None, create=False) -> BundlePaths | None` — find by fingerprint (repoints `latest`) or create (snapshot + manifest + `latest`).
  - `latest_bundle_id(holistic_root: Path) -> str | None`
  - `reading_index_path(holistic_root: Path, legacy_index: Path) -> Path`
  - `update_records_tagged(bundle_dir: Path) -> None`
  - `bundle_dir_of(index_path: Path) -> Path | None`
  - `record_analysis(index_path: Path, analysis: dict) -> None` (adds `analyzed_at`; no-op on legacy)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_holistic_bundles.py`:

```python
# ---------------------------------------------------------------- bundle store

def _mk_bundle(root, name, manifest):
    d = root / name
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps(manifest))
    return d


def test_resolve_bundle_creates_snapshot_manifest_and_latest(tmp_path):
    root = tmp_path / "holistic"
    reg = _reg(AXES_A, tmp_path)
    paths = bundle.resolve_bundle(root, reg, model="m", extract_template="tpl",
                                  axes_text=AXES_A, create=True)
    assert paths.bundle_dir.parent == root
    assert paths.index_path == paths.bundle_dir / "category_records.jsonl"
    assert paths.report_path == paths.bundle_dir / "report.json"
    # snapshot is a byte-equal copy of the axes file used
    assert (paths.bundle_dir / "axes_snapshot.yaml").read_text() == AXES_A
    manifest = json.loads((paths.bundle_dir / "manifest.json").read_text())
    fp = bundle.tag_fingerprint(reg, "m", "tpl")
    assert manifest["tag_fingerprint"] == fp
    assert manifest["model"] == "m"
    assert manifest["records_tagged"] == 0
    assert manifest["extract_prompt_sha"] == bundle.prompt_sha("tpl")
    assert manifest["created_at"]                       # shape only
    # dir name is <ts>_<fp8>
    assert paths.bundle_dir.name.rsplit("_", 1)[1] == fp[:8]
    latest = root / "latest"
    assert latest.is_symlink() and not latest.readlink().is_absolute()
    assert latest.resolve() == paths.bundle_dir.resolve()


def test_resolve_bundle_snapshots_canonical_fields_when_no_axes_text(tmp_path):
    root = tmp_path / "holistic"
    reg = _reg(AXES_A, tmp_path)
    paths = bundle.resolve_bundle(root, reg, create=True)
    snap = yaml.safe_load((paths.bundle_dir / "axes_snapshot.yaml").read_text())
    assert [f["name"] for f in snap["fields"]] == ["direction", "is_multi_species"]


def test_resolve_bundle_finds_existing_by_fingerprint_and_repoints_latest(tmp_path):
    root = tmp_path / "holistic"
    reg_a = _reg(AXES_A, tmp_path)
    reg_b = _reg(AXES_B, tmp_path, "b.yaml")
    first = bundle.resolve_bundle(root, reg_a, create=True)
    second = bundle.resolve_bundle(root, reg_b, create=True)
    assert first.bundle_dir != second.bundle_dir
    assert (root / "latest").resolve() == second.bundle_dir.resolve()
    again = bundle.resolve_bundle(root, reg_a, create=True)
    assert again.bundle_dir == first.bundle_dir        # resumed, not recreated
    assert (root / "latest").resolve() == first.bundle_dir.resolve()  # repointed
    assert bundle.latest_bundle_id(root) == first.bundle_dir.name


def test_resolve_bundle_without_create_returns_none(tmp_path):
    assert bundle.resolve_bundle(tmp_path / "holistic",
                                 _reg(AXES_A, tmp_path)) is None


def test_list_bundles_newest_first_and_skips_malformed_manifests(tmp_path, capsys):
    root = tmp_path / "holistic"
    _mk_bundle(root, "2026-01-01_00-00_aaaaaaaa", {"tag_fingerprint": "a" * 64})
    _mk_bundle(root, "2026-01-02_00-00_bbbbbbbb", {"tag_fingerprint": "b" * 64})
    bad = _mk_bundle(root, "2026-01-03_00-00_cccccccc", {})
    (bad / "manifest.json").write_text("{not json")
    infos = bundle.list_bundles(root)
    assert [b.bundle_id for b in infos] == ["2026-01-02_00-00_bbbbbbbb",
                                            "2026-01-01_00-00_aaaaaaaa"]
    assert "cccccccc" in capsys.readouterr().out       # warned, not crashed


def test_list_bundles_surfaces_legacy_only_when_no_real_bundle_exists(tmp_path):
    legacy = tmp_path / "audit" / "category_records.jsonl"
    legacy.parent.mkdir()
    utils.append_jsonl({"record_id": "a"}, legacy)
    infos = bundle.list_bundles(tmp_path / "holistic", legacy)
    assert [b.bundle_id for b in infos] == ["legacy"]
    assert infos[0].manifest == {} and infos[0].path == legacy.parent
    _mk_bundle(tmp_path / "holistic", "2026-01-01_00-00_aaaaaaaa",
               {"tag_fingerprint": "a" * 64})
    assert [b.bundle_id
            for b in bundle.list_bundles(tmp_path / "holistic", legacy)] \
        == ["2026-01-01_00-00_aaaaaaaa"]


def test_reading_index_path_prefers_latest_then_newest_then_legacy(tmp_path):
    root = tmp_path / "holistic"
    legacy = tmp_path / "audit" / "category_records.jsonl"
    assert bundle.reading_index_path(root, legacy) == legacy     # nothing yet
    a = _mk_bundle(root, "2026-01-01_00-00_aaaaaaaa", {"tag_fingerprint": "a" * 64})
    b = _mk_bundle(root, "2026-01-02_00-00_bbbbbbbb", {"tag_fingerprint": "b" * 64})
    assert bundle.reading_index_path(root, legacy) == \
        b / "category_records.jsonl"                             # newest by name
    utils._update_latest_symlink(root, a)
    assert bundle.reading_index_path(root, legacy) == \
        a / "category_records.jsonl"                             # symlink wins


def test_update_records_tagged_counts_only_clean_rows(tmp_path):
    root = tmp_path / "holistic"
    paths = bundle.resolve_bundle(root, _reg(AXES_A, tmp_path), create=True)
    utils.append_jsonl({"record_id": "a", "direction": "Mixed"}, paths.index_path)
    utils.append_jsonl({"record_id": "b", "extract_error": "boom"}, paths.index_path)
    bundle.update_records_tagged(paths.bundle_dir)
    manifest = json.loads((paths.bundle_dir / "manifest.json").read_text())
    assert manifest["records_tagged"] == 1


def test_record_analysis_stamps_manifest_and_noops_on_legacy(tmp_path):
    root = tmp_path / "holistic"
    paths = bundle.resolve_bundle(root, _reg(AXES_A, tmp_path), create=True)
    bundle.record_analysis(paths.index_path,
                           {"config": {"x": 1}, "analyzers": ["distribution"]})
    manifest = json.loads((paths.bundle_dir / "manifest.json").read_text())
    assert manifest["analysis"]["config"] == {"x": 1}
    assert manifest["analysis"]["analyzed_at"]           # stamped; shape only
    assert manifest["tag_fingerprint"]                   # tag provenance kept
    flat = tmp_path / "audit" / "category_records.jsonl"
    flat.parent.mkdir()
    flat.touch()
    assert bundle.bundle_dir_of(flat) is None
    bundle.record_analysis(flat, {"config": {}})         # must not raise
```

Add `import yaml` to the test file's imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_holistic_bundles.py -v`
Expected: Task 1's 5 pass; the new ones FAIL with `AttributeError` (missing functions).

- [ ] **Step 3: Write the implementation**

Append to `evals/holistic/bundle.py`:

```python
# ---------------------------------------------------------------- bundle store

def list_bundles(holistic_root: Path,
                 legacy_index: Path | None = None) -> list[BundleInfo]:
    """All bundles under ``holistic_root``, newest-first (dir names start with a
    timestamp). A malformed manifest degrades to skipped-with-a-warning, never a
    crash. When no real bundle exists but the pre-bundle flat index does, it
    surfaces as the implicit read-only ``legacy`` bundle so old runs still render."""
    holistic_root = Path(holistic_root)
    bundles = []
    if holistic_root.is_dir():
        for d in sorted(holistic_root.iterdir(), reverse=True):
            if d.is_symlink() or not d.is_dir():
                continue
            mpath = d / MANIFEST_NAME
            if not mpath.exists():
                continue
            try:
                manifest = json.loads(mpath.read_text())
            except (OSError, json.JSONDecodeError) as err:
                print(f"WARNING: skipping bundle {d.name} (bad {MANIFEST_NAME}: {err})")
                continue
            bundles.append(BundleInfo(d.name, d, manifest))
    if not bundles and legacy_index is not None and legacy_index.exists():
        return [BundleInfo(LEGACY_ID, legacy_index.parent, {})]
    return bundles


def latest_bundle_id(holistic_root: Path) -> str | None:
    """The bundle the ``latest`` symlink points at (repointed on every Tag), or
    None when there is no valid pointer."""
    link = Path(holistic_root) / "latest"
    if link.is_symlink() and (link / MANIFEST_NAME).exists():
        return link.resolve().name
    return None


def reading_index_path(holistic_root: Path, legacy_index: Path) -> Path:
    """The tag index a default read should see: the ``latest`` bundle when one
    exists, else the newest bundle, else the pre-bundle flat path (which may not
    exist yet)."""
    latest = latest_bundle_id(holistic_root)
    if latest is not None:
        return Path(holistic_root) / latest / INDEX_NAME
    infos = list_bundles(holistic_root)
    if infos:
        return infos[0].path / INDEX_NAME
    return legacy_index


def resolve_bundle(holistic_root: Path, fields: FieldRegistry, *,
                   model: str | None = None, extract_template: str | None = None,
                   axes_text: str | None = None,
                   create: bool = False) -> BundlePaths | None:
    """The bundle matching this (fields, model, prompt) fingerprint. Found → its
    paths, with ``latest`` repointed at it (this is the Tag-time entry point).
    Not found → created (axes snapshot + manifest + ``latest``) when ``create``,
    else None. ``axes_text`` is the verbatim axes file to snapshot; when absent
    (registry-only callers) the canonical field serialization is snapshotted."""
    holistic_root = Path(holistic_root)
    fp = tag_fingerprint(fields, model, extract_template)
    for info in list_bundles(holistic_root):
        if info.manifest.get("tag_fingerprint") == fp:
            utils._update_latest_symlink(holistic_root, info.path)
            return _paths(info.path)
    if not create:
        return None
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    bundle_dir = holistic_root / f"{ts}_{fp[:8]}"
    bundle_dir.mkdir(parents=True)
    snapshot = axes_text if axes_text is not None else yaml.safe_dump(
        {"fields": canonical_fields(fields)}, sort_keys=False, allow_unicode=True)
    (bundle_dir / AXES_SNAPSHOT_NAME).write_text(snapshot)
    manifest = {
        "tag_fingerprint": fp,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "git_commit": utils._git_status()[0],
        "model": model,
        "extract_prompt_sha": prompt_sha(extract_template),
        "records_tagged": 0,
    }
    (bundle_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))
    utils._update_latest_symlink(holistic_root, bundle_dir)
    return _paths(bundle_dir)


def _update_manifest(bundle_dir: Path, updates: dict) -> None:
    mpath = bundle_dir / MANIFEST_NAME
    manifest = json.loads(mpath.read_text())
    manifest.update(updates)
    mpath.write_text(json.dumps(manifest, indent=2))


def update_records_tagged(bundle_dir: Path) -> None:
    """Refresh ``manifest.records_tagged`` from the bundle's index (distinct
    cleanly-tagged record_ids; error rows don't count)."""
    rows = utils.load_jsonl(Path(bundle_dir) / INDEX_NAME)
    tagged = {r["record_id"] for r in rows
              if "record_id" in r and "extract_error" not in r}
    _update_manifest(Path(bundle_dir), {"records_tagged": len(tagged)})


def bundle_dir_of(index_path: Path) -> Path | None:
    """The bundle a tag index lives in, or None for a legacy flat index."""
    parent = Path(index_path).parent
    return parent if (parent / MANIFEST_NAME).exists() else None


def record_analysis(index_path: Path, analysis: dict) -> None:
    """Stamp ``manifest.analysis`` for the bundle holding this index — what
    produced the current report.json. A legacy flat index has no manifest, so
    this is silently a no-op there."""
    bdir = bundle_dir_of(index_path)
    if bdir is None:
        return
    _update_manifest(bdir, {"analysis": {
        **analysis,
        "analyzed_at": datetime.now().isoformat(timespec="seconds")}})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_holistic_bundles.py -v`
Expected: all pass (14).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`
Expected: all pass.

---

### Task 3: Pipeline wiring (`pipeline.py`)

**Files:**
- Modify: `evals/holistic/pipeline.py`
- Test: `tests/test_holistic_pipeline.py`

**Interfaces:**
- Consumes: everything from `bundle.py` (Tasks 1–2).
- Produces (later tasks rely on):
  - `Inputs` gains field `holistic_root: Path | None = None` (after `clusters`).
  - `resolve_inputs(input_path, *, judge_version=None, bundle_id=None) -> Inputs` — `bundle_id=None` reads the latest bundle (legacy flat fallback); `"legacy"` forces the flat path; unknown id → `SystemExit`.
  - `tag(inputs, fields=None, *, model=None, resume=True, extract_template=None, axes_text=None)` — routes through `resolve_bundle(create=True)` and **mutates `inputs.index_path`** to the bundle's index (callers read it after tagging). A hand-built `Inputs` with `holistic_root=None` keeps the old direct-write behavior.
  - `run(...)` gains `axes_text: str | None = None`, passed to `tag`.
  - `category_records_path(run_dir)` is unchanged — it is now explicitly the LEGACY flat path helper.

- [ ] **Step 1: Write the failing tests**

In `tests/test_holistic_pipeline.py`, add at the end (module already imports `pipeline`, `F`, `utils`; add `import json` to imports):

```python
# ---------------------------------------------------------------- bundles (P1)

def test_tag_resumes_the_matching_bundle_with_zero_api_calls(tmp_path, stub_claude):
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    calls = stub_claude([GOOD_JSON])
    inp = pipeline.resolve_inputs(run)
    pipeline.tag(inp, F.default_fields())
    first_dir = inp.index_path.parent
    assert first_dir.parent == run / "holistic"

    inp2 = pipeline.resolve_inputs(run)
    pipeline.tag(inp2, F.default_fields())
    assert len(calls) == 1                        # second tag: zero API calls
    assert inp2.index_path.parent == first_dir    # same bundle resumed
    manifest = json.loads((first_dir / "manifest.json").read_text())
    assert manifest["records_tagged"] == 1


def test_changed_fields_get_a_fresh_bundle_and_never_mix_tags(tmp_path, stub_claude):
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    stub_claude([GOOD_JSON, '{"direction": "Mixed"}'])
    inp = pipeline.resolve_inputs(run)
    pipeline.tag(inp, F.default_fields())
    first = inp.index_path

    other = F.FieldRegistry()
    other.add(F.Field(name="direction",
                      values=("Under-weighting", "Over-weighting", "Mixed")))
    inp2 = pipeline.resolve_inputs(run)
    pipeline.tag(inp2, other)
    assert inp2.index_path != first
    assert utils.load_jsonl(first)[0]["taxa_category"] == "farmed"
    assert utils.load_jsonl(inp2.index_path)[0]["direction"] == "Mixed"
    # each bundle carries its own snapshot; latest points at the newest tag
    assert (first.parent / "axes_snapshot.yaml").exists()
    assert (inp2.index_path.parent / "axes_snapshot.yaml").exists()
    assert (run / "holistic" / "latest").resolve() == \
        inp2.index_path.parent.resolve()


def test_resolve_inputs_reads_latest_and_honors_bundle_id(tmp_path, stub_claude):
    import pytest
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    stub_claude([GOOD_JSON, '{"direction": "Mixed"}'])
    inp = pipeline.resolve_inputs(run)
    pipeline.tag(inp, F.default_fields())
    first_id = inp.index_path.parent.name
    other = F.FieldRegistry()
    other.add(F.Field(name="direction",
                      values=("Under-weighting", "Over-weighting", "Mixed")))
    inp2 = pipeline.resolve_inputs(run)
    pipeline.tag(inp2, other)

    assert pipeline.resolve_inputs(run).index_path == inp2.index_path   # latest
    picked = pipeline.resolve_inputs(run, bundle_id=first_id)
    assert picked.index_path == inp.index_path
    with pytest.raises(SystemExit, match="bundle"):
        pipeline.resolve_inputs(run, bundle_id="2020-01-01_00-00_deadbeef")


def test_legacy_flat_run_reads_in_place_and_tag_leaves_it_untouched(
        tmp_path, stub_claude):
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    flat = run / "audit" / "category_records.jsonl"
    flat.parent.mkdir()
    utils.append_jsonl({"record_id": "a", "taxa_category": "wild"}, flat)

    inp = pipeline.resolve_inputs(run)
    assert inp.index_path == flat                  # implicit legacy bundle
    assert pipeline.resolve_inputs(run, bundle_id="legacy").index_path == flat

    before = flat.read_text()
    stub_claude([GOOD_JSON])
    pipeline.tag(inp, F.default_fields())
    assert inp.index_path.parent.parent == run / "holistic"  # first real bundle
    assert flat.read_text() == before              # legacy flat file untouched


def test_bare_corpus_bundles_live_in_a_sibling_holistic_dir(tmp_path, stub_claude):
    corpus = tmp_path / "dad_corpus.jsonl"
    utils.append_jsonl({"record_id": "a", "messages": MESSAGES}, corpus)
    stub_claude([GOOD_JSON])
    pipeline.run(corpus)
    inp = pipeline.resolve_inputs(corpus)
    assert inp.index_path.parent.parent == tmp_path / "dad_corpus.holistic"
    assert utils.load_jsonl(inp.index_path)[0]["taxa_category"] == "farmed"
```

Also UPDATE two existing tests whose location assertions move:

1. `test_run_on_a_bare_corpus_file_tags_into_a_sibling_index` — the final two lines still pass unchanged (re-resolve now returns the bundle index); only update its name/comment to say the sibling is now `<stem>.holistic/<bundle>/`. Keep the assertions as they are.
2. `test_tag_writes_the_index_into_the_runs_audit_dir` (and any neighbors asserting `inp.index_path == run / "audit" / "category_records.jsonl"` after tagging) — rename to `test_tag_writes_the_index_into_a_run_bundle` and assert `inp.index_path.parent.parent == run / "holistic"` instead. Behavior flip is deliberate (spec P1); flip the expectation, don't preserve the quirk.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_holistic_pipeline.py -v`
Expected: new tests FAIL (`TypeError: resolve_inputs() got an unexpected keyword argument 'bundle_id'`, index still under `audit/`).

- [ ] **Step 3: Write the implementation**

In `evals/holistic/pipeline.py`:

(a) Import the bundle module — extend the existing relative import block:

```python
from . import bundle, extract, synthesize
```

(b) Add the field to `Inputs` (after `clusters`) and extend the docstring:

```python
    clusters: dict | None = None
    #: root of the provenance-bundle store for this input (<run>/holistic, or
    #: <corpus-stem>.holistic beside a bare corpus). None only on hand-built
    #: Inputs, which keep the pre-bundle direct-write behavior.
    holistic_root: Path | None = None
```

(c) Update `category_records_path`'s docstring to mark it legacy:

```python
def category_records_path(run_dir: str | Path) -> Path:
    """The pre-bundle flat tag index (read-only legacy location; new tags write
    into provenance bundles under <run>/holistic/)."""
    return Path(run_dir) / "audit" / "category_records.jsonl"
```

(d) Add the bundle-selection helper (below `category_records_path`):

```python
def _bundle_index_path(holistic_root: Path, legacy_index: Path,
                       bundle_id: str | None) -> Path:
    """Which tag index a read should see: an explicit bundle, else the latest
    (legacy flat fallback). ``"legacy"`` forces the pre-bundle flat path."""
    if bundle_id == bundle.LEGACY_ID:
        return legacy_index
    if bundle_id is not None:
        bdir = holistic_root / bundle_id
        if not (bdir / bundle.MANIFEST_NAME).exists():
            raise SystemExit(f"bundle {bundle_id!r} not found under {holistic_root}")
        return bdir / bundle.INDEX_NAME
    return bundle.reading_index_path(holistic_root, legacy_index)
```

(e) Update `resolve_inputs` — new `bundle_id` kwarg, compute `holistic_root`, select the index (docstring: append "``bundle_id`` picks which provenance bundle reads see (None = latest, legacy flat fallback)."):

```python
def resolve_inputs(input_path: str | Path | Inputs, *,
                   judge_version: str | None = None,
                   bundle_id: str | None = None) -> Inputs:
    ...
    if p.is_dir():
        corpus_path = p / "final" / "dad_corpus.jsonl"
        if not corpus_path.exists():
            raise SystemExit(f"no final/dad_corpus.jsonl under run dir {p}")
        holistic_root = p / "holistic"
        index = _bundle_index_path(holistic_root, category_records_path(p), bundle_id)
        return Inputs(utils.load_jsonl(corpus_path), p,
                      _load_annotations(p), _load_verdicts(p, judge_version),
                      index, _load_clusters(p), holistic_root)
    holistic_root = p.with_name(p.stem + ".holistic")
    legacy = p.with_name(p.stem + ".category_records.jsonl")
    index = _bundle_index_path(holistic_root, legacy, bundle_id)
    return Inputs(utils.load_jsonl(p), None, None, None, index,
                  _load_clusters(p.parent), holistic_root)
```

(f) Update `tag`:

```python
def tag(inputs: Inputs, fields: FieldRegistry | None = None, *,
        model: str | None = None, resume: bool = True,
        extract_template: str | None = None,
        axes_text: str | None = None) -> list[dict]:
    """Run the extraction judge over the corpus. The write is routed through the
    provenance bundle matching this (fields, model, prompt) fingerprint — resumed
    if it exists, created otherwise — and ``inputs.index_path`` is updated to
    point inside it so callers (and the analyze step) read the same bundle.
    ``axes_text`` is the verbatim axes file to snapshot into a new bundle. A
    hand-built Inputs without ``holistic_root`` keeps the legacy direct write."""
    fields = fields or default_fields()
    paths = None
    if inputs.holistic_root is not None:
        paths = bundle.resolve_bundle(
            inputs.holistic_root, fields, model=model,
            extract_template=extract_template, axes_text=axes_text, create=True)
        inputs.index_path = paths.index_path
    rows = extract.extract_corpus(
        inputs.corpus, fields, inputs.index_path, model=model, resume=resume,
        template=extract_template)
    if paths is not None:
        bundle.update_records_tagged(paths.bundle_dir)
    return rows
```

(g) `run(...)`: add `axes_text: str | None = None` to the signature and pass it through: `tag(inputs, fields, model=model, resume=resume, extract_template=extract_template, axes_text=axes_text)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_holistic_pipeline.py -v`
Expected: all pass (including the two updated ones).

- [ ] **Step 5: Run the full suite; fix collateral**

Run: `python -m pytest`
Expected: `tests/test_holistic_cli.py::test_cli_tags_a_run_and_writes_the_report` now FAILS (report path moved) — that flip is Task 4's job; every other test must pass. If anything else fails, fix it before moving on (likely candidates: other assertions on `audit/category_records.jsonl` after a tag call).

---

### Task 4: CLI wiring (`holistic_dad.py`)

**Files:**
- Modify: `evals/holistic_dad.py`
- Test: `tests/test_holistic_cli.py`

**Interfaces:**
- Consumes: Task 3's `resolve_inputs(bundle_id=...)`, `run(axes_text=...)`, `tag(axes_text=...)`; Task 2's `bundle.bundle_dir_of` / `bundle.REPORT_NAME` / `bundle.record_analysis` / `bundle.prompt_sha`.
- Produces:
  - `report_path_for(inputs)` → `<bundle>/report.json` when the index is in a bundle; legacy locations otherwise.
  - `record_bundle_analysis(inputs, analysis_cfg, analyzers, model, synthesis_template)` — shared with the viewer (Task 7). `analyzers` is the selected `AnalyzerRegistry` (has `.names()`).
  - CLI flag `--bundle <id>` (requires `--analyze-only`).

- [ ] **Step 1: Write the failing tests**

In `tests/test_holistic_cli.py`:

(a) UPDATE `test_cli_tags_a_run_and_writes_the_report` — replace the `on_disk` lookup with the bundle location and extend it into the manifest/snapshot money-path test:

```python
def _bundle_dirs(run):
    root = run / "holistic"
    return [d for d in root.iterdir() if d.is_dir() and not d.is_symlink()]


def test_cli_tags_a_run_and_writes_report_manifest_and_snapshot_into_a_bundle(
        tmp_path, stub_claude, monkeypatch):
    run = _make_run(tmp_path)
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    stub_claude([GOOD_JSON])

    report = holistic_dad.main(["--input", str(run), "--no-synthesize"])

    assert report["records"] == 1
    [bdir] = _bundle_dirs(run)
    on_disk = json.loads((bdir / "report.json").read_text())
    assert on_disk["stats"]["analyses"]["distribution"]["taxa_category"] == {"farmed": 1}
    manifest = json.loads((bdir / "manifest.json").read_text())
    assert manifest["records_tagged"] == 1
    assert manifest["extract_prompt_sha"]                    # default template hashed
    assert manifest["analysis"]["analyzers"]                 # analysis stamped
    assert manifest["analysis"]["synth_prompt_sha"] is None  # --no-synthesize
    # snapshot is a byte-equal copy of the axes file used
    assert (bdir / "axes_snapshot.yaml").read_text() == \
        holistic_dad.DEFAULT_AXES.read_text()
```

(b) Add new tests:

```python
def test_cli_analyze_only_targets_the_selected_bundle_and_keeps_latest(
        tmp_path, stub_claude, monkeypatch):
    run = _make_run(tmp_path)
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    axes_a = tmp_path / "a.yaml"
    axes_a.write_text("fields:\n  - name: direction\n"
                      "    values: [Under-weighting, Over-weighting, Mixed]\n")
    axes_b = tmp_path / "b.yaml"
    axes_b.write_text("fields:\n  - name: direction\n"
                      "    values: [Under-weighting, Over-weighting, Balanced]\n")
    stub_claude(['{"direction": "Mixed"}', '{"direction": "Balanced"}'])
    holistic_dad.main(["--input", str(run), "--axes", str(axes_a), "--no-synthesize"])
    holistic_dad.main(["--input", str(run), "--axes", str(axes_b), "--no-synthesize"])

    dirs = {d.name: d for d in _bundle_dirs(run)}
    assert len(dirs) == 2
    latest = (run / "holistic" / "latest").resolve()
    old = next(d for d in dirs.values() if d.resolve() != latest)
    (old / "report.json").unlink()

    holistic_dad.main(["--input", str(run), "--analyze-only", "--no-synthesize",
                       "--axes", str(axes_a), "--bundle", old.name])
    assert (old / "report.json").exists()                    # written in place
    assert (run / "holistic" / "latest").resolve() == latest # latest not moved
    manifest = json.loads((old / "manifest.json").read_text())
    assert manifest["analysis"]["analyzed_at"]


def test_cli_bundle_flag_requires_analyze_only(tmp_path, monkeypatch):
    run = _make_run(tmp_path)
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="analyze-only"):
        holistic_dad.main(["--input", str(run), "--bundle", "x"])


def test_cli_analyze_only_on_a_legacy_flat_run_writes_the_flat_report(
        tmp_path, monkeypatch):
    run = _make_run(tmp_path)
    flat = run / "audit" / "category_records.jsonl"
    flat.parent.mkdir()
    utils.append_jsonl({"record_id": "a", "language": "en",
                        "taxa_category": "farmed", "posture_class": "NO_RAISE"},
                       flat)
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    report = holistic_dad.main(["--input", str(run), "--analyze-only",
                                "--no-synthesize"])
    assert report["records"] == 1
    assert (run / "audit" / "holistic_dad_report.json").exists()
```

(Add `from shared import utils` to the test file imports if not already present — it is.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_holistic_cli.py -v`
Expected: new/updated tests FAIL (report still at `audit/`, no `--bundle` flag).

- [ ] **Step 3: Write the implementation**

In `evals/holistic_dad.py`:

(a) Import: add `from evals.holistic import bundle` next to the other `evals.holistic` imports.

(b) Replace `report_path_for`:

```python
def report_path_for(inputs: pipeline.Inputs) -> Path:
    """Where to write the report: inside the tag index's provenance bundle, or —
    for the legacy flat index — the pre-bundle locations (the run's audit/ dir,
    or beside a bare corpus's flat index)."""
    bdir = bundle.bundle_dir_of(inputs.index_path)
    if bdir is not None:
        return bdir / bundle.REPORT_NAME
    if inputs.run_dir is not None:
        return inputs.run_dir / "audit" / REPORT_NAME
    return inputs.index_path.with_name(
        inputs.index_path.name.replace("category_records.jsonl", REPORT_NAME))
```

(c) Add the shared analysis-stamp helper (below `write_report`):

```python
def record_bundle_analysis(inputs: pipeline.Inputs, analysis_cfg: dict,
                           analyzers, model: str | None,
                           synthesis_template: str | None) -> None:
    """Stamp the bundle manifest with what produced the report just written
    (no-op for the legacy flat index). Shared by the CLI and the viewer."""
    bundle.record_analysis(inputs.index_path, {
        "config": analysis_cfg.get("params") or {},
        "analyzers": analyzers.names(),
        "synth_model": model,
        "synth_prompt_sha": bundle.prompt_sha(synthesis_template),
    })
```

(d) In `main`: add the flag after `--analyze-only`:

```python
    ap.add_argument("--bundle", default=None,
                    help="bundle id to analyze with --analyze-only (default: the "
                         "latest bundle). Tag picks its bundle by fingerprint.")
```

Add the guard next to the existing mutual-exclusion checks:

```python
    if args.bundle and not args.analyze_only:
        raise SystemExit("--bundle picks a bundle to analyze; it requires "
                         "--analyze-only (Tag chooses its bundle by fingerprint)")
```

(e) Thread the pieces through `main`'s body:

```python
    axes_text = Path(args.axes).read_text()      # exists — _load_fields checked
```
(place right after `fields = _load_fields(args.axes)`)

```python
    inputs = pipeline.resolve_inputs(args.input, judge_version=args.judge_version,
                                     bundle_id=args.bundle)
```

In the `--extract-only` branch, pass `axes_text=axes_text` to `pipeline.tag(...)`.

In the `pipeline.run(...)` call, add `axes_text=axes_text`.

After `path = write_report(...)` (before `print(f"wrote {path}")`):

```python
    record_bundle_analysis(inputs, analysis_cfg, analyzers, args.model,
                           synthesis_template)
```

(f) Update the module docstring's report line: "The report is written to the run's provenance bundle (`<run>/holistic/<ts>_<fp8>/report.json`; legacy flat runs keep `audit/holistic_dad_report.json`), plus a short console summary."

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_holistic_cli.py tests/test_holistic_pipeline.py -v`
Expected: all pass.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`
Expected: all pass (Task 3's known CLI failure is now fixed).

---

### Task 5: Bundle-aware facet index in `score_dad.select_records`

**Files:**
- Modify: `evals/score_dad.py`
- Test: `tests/test_score_dad_selection.py`

**Interfaces:**
- Consumes: `bundle.reading_index_path(holistic_root, legacy_index)` (Task 2).
- Produces: no signature change — `select_records` just finds the index in bundles first. (Spec gap, closed deliberately: without this, `--where` breaks permanently for bundled runs because the flat file no longer exists. Read-only, default = latest bundle; no `--bundle` flag here — out of P1 scope.)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_score_dad_selection.py`:

```python
def test_select_records_where_reads_the_latest_bundle_index(tmp_path):
    # New runs tag into provenance bundles (<run>/holistic/<ts>_<fp8>/), not the
    # flat audit/ path — --where must find the latest bundle's index.
    corpus_path = _corpus(tmp_path, ["a", "b"])
    bdir = corpus_path.parent.parent / "holistic" / "2026-01-01_00-00_aaaaaaaa"
    bdir.mkdir(parents=True)
    (bdir / "manifest.json").write_text('{"tag_fingerprint": "aa"}')
    utils.append_jsonl({"record_id": "a", "taxa_category": "farmed"},
                       bdir / "category_records.jsonl")

    out = score_dad.select_records(utils.load_jsonl(corpus_path), corpus_path,
                                   where={"taxa_category": {"farmed"}})
    assert [r["record_id"] for r in out] == ["a"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_score_dad_selection.py -v`
Expected: the new test FAILS with `SystemExit` ("--where needs the holistic tag index").

- [ ] **Step 3: Write the implementation**

In `evals/score_dad.py`, add the import (next to the other `evals` imports):

```python
from evals.holistic import bundle
```

In `select_records`, replace the two-line `candidates = [...]` with:

```python
        candidates = [
            bundle.reading_index_path(
                p.parent.parent / "holistic",
                p.parent.parent / "audit" / "category_records.jsonl"),
            bundle.reading_index_path(
                p.with_name(p.stem + ".holistic"),
                p.with_name(p.stem + ".category_records.jsonl")),
        ]
```

Update the docstring sentence describing the layouts: "``--where``) match against the holistic tag index built by holistic_dad — the latest provenance bundle under ``<run>/holistic/`` (falling back to the legacy flat ``audit/category_records.jsonl``) for a run-dir corpus, or the sibling ``<stem>.holistic/`` bundle (falling back to ``<stem>.category_records.jsonl``) for a bare corpus file".

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_score_dad_selection.py -v`
Expected: all pass (the old flat-path tests still pass via the legacy fallback).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`
Expected: all pass.

---

### Task 6: Viewer loader (`viewer/loader.py`)

**Files:**
- Modify: `viewer/loader.py`
- Test: `tests/test_viewer_loader.py`

**Interfaces:**
- Consumes: `evals.holistic.bundle` (pure — safe for the no-streamlit loader).
- Produces (Task 7/8 call these):
  - `list_bundles(run_dir) -> list[BundleInfo]` (includes implicit `legacy`)
  - `latest_bundle_id(run_dir) -> str | None`
  - `category_records(run_dir, bundle_id=None)`, `holistic_report(run_dir, bundle_id=None)`, `combined_index(run_dir, bundle_id=None)` — `None` = latest bundle with legacy flat fallback; `"legacy"` forces flat.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_viewer_loader.py` (reuse its existing `_make_run`-style helper if present; otherwise use the local pattern below):

```python
def _bundle(run, name, rows, report=None):
    d = run / "holistic" / name
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"tag_fingerprint": name[-8:] * 8}))
    utils.save_jsonl(rows, d / "category_records.jsonl")
    if report is not None:
        (d / "report.json").write_text(json.dumps(report))
    return d


def test_bundle_readers_default_to_the_latest_bundle(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    _bundle(run, "2026-01-01_00-00_aaaaaaaa",
            [{"record_id": "a", "taxa_category": "wild"}], report={"records": 1})
    _bundle(run, "2026-01-02_00-00_bbbbbbbb",
            [{"record_id": "a", "taxa_category": "farmed"}], report={"records": 2})
    assert loader.category_records(run)[0]["taxa_category"] == "farmed"
    assert loader.holistic_report(run) == {"records": 2}
    assert loader.combined_index(run)["a"]["taxa_category"] == "farmed"


def test_bundle_readers_honor_an_explicit_bundle_id(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    old = _bundle(run, "2026-01-01_00-00_aaaaaaaa",
                  [{"record_id": "a", "taxa_category": "wild"}],
                  report={"records": 1})
    _bundle(run, "2026-01-02_00-00_bbbbbbbb",
            [{"record_id": "a", "taxa_category": "farmed"}])
    assert loader.category_records(run, old.name)[0]["taxa_category"] == "wild"
    assert loader.holistic_report(run, old.name) == {"records": 1}
    assert loader.combined_index(run, old.name)["a"]["taxa_category"] == "wild"


def test_list_bundles_surfaces_the_implicit_legacy_entry(tmp_path):
    run = tmp_path / "run"
    (run / "audit").mkdir(parents=True)
    utils.save_jsonl([{"record_id": "a", "taxa_category": "wild"}],
                     run / "audit" / "category_records.jsonl")
    infos = loader.list_bundles(run)
    assert [b.bundle_id for b in infos] == ["legacy"]
    # explicit "legacy" reads the flat files
    assert loader.category_records(run, "legacy")[0]["taxa_category"] == "wild"


def test_latest_bundle_id_follows_the_symlink(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    old = _bundle(run, "2026-01-01_00-00_aaaaaaaa", [])
    _bundle(run, "2026-01-02_00-00_bbbbbbbb", [])
    assert loader.latest_bundle_id(run) is None          # no symlink yet
    utils._update_latest_symlink(run / "holistic", old)
    assert loader.latest_bundle_id(run) == old.name
    assert loader.category_records(run) == []            # symlink wins reads
```

The existing `test_category_records_reads_the_audit_index` / report tests must keep passing unchanged — they exercise the legacy fallback.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_viewer_loader.py -v`
Expected: new tests FAIL (`AttributeError: module 'viewer.loader' has no attribute 'list_bundles'`, `TypeError` on the extra positional arg).

- [ ] **Step 3: Write the implementation**

In `viewer/loader.py`, after `from shared import utils` add:

```python
from evals.holistic import bundle as _bundle   # pure file I/O, no streamlit
```

Replace `category_records` and `holistic_report`, and add the new functions:

```python
def list_bundles(run_dir: Path) -> list[_bundle.BundleInfo]:
    """Provenance bundles for a run's holistic lane, newest first — including the
    implicit read-only 'legacy' entry for pre-bundle flat results."""
    run_dir = Path(run_dir)
    return _bundle.list_bundles(run_dir / "holistic",
                                run_dir / "audit" / "category_records.jsonl")


def latest_bundle_id(run_dir: Path) -> str | None:
    """The bundle the run's `latest` symlink points at (the most recent Tag)."""
    return _bundle.latest_bundle_id(Path(run_dir) / "holistic")


def _holistic_paths(run_dir: Path, bundle_id: str | None) -> tuple[Path, Path]:
    """(index_path, report_path) for the chosen bundle. None = latest bundle,
    falling back to the legacy flat files; 'legacy' forces the flat files."""
    run_dir = Path(run_dir)
    flat_index = run_dir / "audit" / "category_records.jsonl"
    if bundle_id == _bundle.LEGACY_ID:
        index = flat_index
    elif bundle_id is not None:
        index = run_dir / "holistic" / bundle_id / _bundle.INDEX_NAME
    else:
        index = _bundle.reading_index_path(run_dir / "holistic", flat_index)
    if _bundle.bundle_dir_of(index):
        return index, index.parent / _bundle.REPORT_NAME
    return index, run_dir / "audit" / "holistic_dad_report.json"


def category_records(run_dir: Path, bundle_id: str | None = None) -> list[dict]:
    """The extraction tag index rows for the chosen bundle (None = latest, legacy
    flat fallback), or [] when the run has not been tagged."""
    index_path, _ = _holistic_paths(run_dir, bundle_id)
    return _load_jsonl(index_path)


def holistic_report(run_dir: Path, bundle_id: str | None = None) -> dict | None:
    """The chosen bundle's analyzer report, or None."""
    _, report_path = _holistic_paths(run_dir, bundle_id)
    if not report_path.exists():
        return None
    with open(report_path) as f:
        return json.load(f)
```

In `combined_index`, change the signature to `def combined_index(run_dir: Path, bundle_id: str | None = None) -> dict[str, dict]:` and the tag loop line to `for tag in category_records(run_dir, bundle_id):` (docstring: add "``bundle_id`` picks which tag bundle supplies the facets (None = latest).").

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_viewer_loader.py -v`
Expected: all pass, old flat-path tests included.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest`
Expected: all pass.

---

### Task 7: Run diversity page — bundle picker, captions, bundle-routed Tag/Analyze

**Files:**
- Modify: `viewer/ui_pages/run_diversity.py`

**Interfaces:**
- Consumes: Task 6 loader functions; `pipeline.resolve_inputs(bundle_id=...)`, `pipeline.tag(axes_text=...)`; `holistic_dad.report_path_for` / `write_report` / `record_bundle_analysis`.
- Produces: UI only. No unit tests exist for streamlit pages — verification is the full suite (imports break loudly) plus the manual streamlit check in the final task.

**The captions below are acceptance criteria — use this exact copy.**

- [ ] **Step 1: Insert the bundle picker between the run selectbox block and the metrics**

Replace the current three lines that read `tag_rows` / `report` (lines 42–45: `tag_rows = loader.category_records(run.run_dir)` … `report = loader.holistic_report(run.run_dir)`) with:

```python
bundles = loader.list_bundles(run.run_dir)
bundle_id = None
if bundles:
    infos = {b.bundle_id: b for b in bundles}
    ids = list(infos)
    default = loader.latest_bundle_id(run.run_dir)
    default = default if default in infos else ids[0]

    def _bundle_label(bid: str) -> str:
        if bid == "legacy":
            return "legacy (pre-bundle flat index)"
        m = infos[bid].manifest
        return (f"{bid} · {m.get('model') or 'config default'} · "
                f"{m.get('records_tagged', '?')} tagged")

    bundle_id = st.selectbox("Bundle", ids, index=ids.index(default),
                             key="diversity_bundle", format_func=_bundle_label)
    st.caption("Each **bundle** is one tagging pass, keyed by its exact axes + "
               "model + extraction prompt. Pick one to view its tags and report "
               "side-by-side with other variants; the default is *latest* — the "
               "most recently tagged one.")
    if bundle_id == "legacy":
        st.caption(":material/history: This is the **pre-bundle flat index** "
                   "(`audit/category_records.jsonl`) — it has no recorded "
                   "provenance. The next **Tag** creates the first real bundle; "
                   "this one stays untouched.")
    else:
        m = infos[bundle_id].manifest
        st.caption(f"model `{m.get('model') or 'config default'}` · created "
                   f"{m.get('created_at', '?')} · {m.get('records_tagged', '?')} "
                   f"tagged · commit `{m.get('git_commit') or '—'}`")

n_final = run.counts.get("final", 0)
tag_rows = loader.category_records(run.run_dir, bundle_id)
n_tagged = len({r.get("record_id") for r in tag_rows
                if "record_id" in r and "extract_error" not in r})
report = loader.holistic_report(run.run_dir, bundle_id)
```

(Note: `n_final = run.counts...` moves inside this block only if it was below the replaced lines — keep its original position otherwise; only `tag_rows`/`report` must read the selected bundle.)

- [ ] **Step 2: Update the Tag/Analyze captions and button handlers**

Replace the `b1.caption(...)` text with:

```python
b1.caption("**Tag** labels every final conversation with the categorical axes from "
           "`evals/dad_axes.yaml` (taxa, direction, posture, …) — one cheap LLM call "
           "per record. Results go into a **bundle** keyed by the exact axes + model "
           "+ prompt: the same inputs resume their existing bundle (already-tagged "
           "records are skipped — no re-paying), while any change to them starts a "
           "fresh bundle, so old results are never overwritten. The bundle's index "
           "powers the facet filters in *Judge → Score a run* and the analysis below.")
```

Replace the `b2.caption(...)` text with:

```python
b2.caption("**Analyze** recomputes the diversity report of the **selected bundle** "
           "from its existing tags — distribution, evenness, coverage-vs-target, "
           "correlations, drift — plus one LLM synthesis call. Tags are untouched, "
           "so it's nearly free; rerun it after editing the `analysis:` block or "
           "quota targets. The bundle's manifest records which analysis config "
           "produced the current report.")
```

Replace the Tag button handler body with:

```python
if b1.button(":material/sell: Tag this run", type="primary",
             help="Tag into the bundle matching the current axes + model + prompt "
                  "(resume-safe: already-tagged records are skipped, error rows "
                  "are retried; changed inputs start a fresh bundle)."):
    fields, _, _ = _engine()
    inputs = pipeline.resolve_inputs(run.run_dir)
    with st.spinner(f"Tagging {len(inputs.corpus)} record(s)… (resume-safe; rows "
                    "save as they finish)"):
        written = pipeline.tag(
            inputs, fields, model=model,
            extract_template=holistic_dad._read_if_exists(holistic_dad.DEFAULT_EXTRACT_PROMPT),
            axes_text=holistic_dad.DEFAULT_AXES.read_text())
    st.success(f"Tagged {len(written)} record(s) → {inputs.index_path}")
    st.session_state.pop("diversity_bundle", None)   # jump to the bundle just tagged
    st.rerun()
```

Replace the Analyze button handler body with:

```python
if b2.button(":material/analytics: Analyze",
             help="Re-run the analyzers + LLM synthesis over the selected bundle's "
                  "existing tags (no re-tagging) and rewrite its report.",
             disabled=not tag_rows):
    fields, analysis_cfg, analyzers = _engine()
    synthesis_template = holistic_dad._read_if_exists(holistic_dad.DEFAULT_SYNTH_PROMPT)
    inputs = pipeline.resolve_inputs(run.run_dir, bundle_id=bundle_id)
    with st.spinner("Analyzing…"):
        new_report = pipeline.run(
            inputs, fields=fields, analyzers=analyzers, do_tag=False, model=model,
            synthesis_template=synthesis_template,
            config=analysis_cfg.get("params"))
    holistic_dad.write_report(holistic_dad.report_path_for(inputs), new_report)
    holistic_dad.record_bundle_analysis(inputs, analysis_cfg, analyzers, model,
                                        synthesis_template)
    st.rerun()
```

- [ ] **Step 3: Update the top-of-page caption and the two `st.info` fallbacks**

Top caption (line 22): append one sentence so it reads: `"…analysis is free except the one LLM synthesis call. Every tagging pass lands in a provenance bundle, so results from different axes/models sit side-by-side and are never overwritten."`

`if not tag_rows:` info text → `"This bundle has no extraction tag index yet — **Tag this run** builds one (it also enables the facet filters in Judge → Score a run)."`

`if not report:` info text → `"Tag index present but this bundle has no report yet — **Analyze** computes it."`

- [ ] **Step 4: Verify**

Run: `python -m pytest`
Expected: all pass (the page has no unit tests; this catches import/syntax errors — pages are exercised manually in the final verification).

Run: `python -c "import ast; ast.parse(open('viewer/ui_pages/run_diversity.py').read())"`
Expected: silent success.

---

### Task 8: Judge batch page — bundle picker for the facet source

**Files:**
- Modify: `viewer/ui_pages/judge_batch.py`

**Interfaces:**
- Consumes: `loader.list_bundles`, `loader.latest_bundle_id`, `loader.combined_index(run_dir, bundle_id)` (Task 6).
- Produces: UI only.

- [ ] **Step 1: Add the picker where the combined index is loaded**

In `render()`, replace the line `index = loader.combined_index(run.run_dir)` with:

```python
    bundles = loader.list_bundles(run.run_dir)
    bundle_id = None
    if bundles:
        infos = {b.bundle_id: b for b in bundles}
        ids = list(infos)
        default = loader.latest_bundle_id(run.run_dir)
        default = default if default in infos else ids[0]

        def _bundle_label(bid: str) -> str:
            if bid == "legacy":
                return "legacy (pre-bundle flat index)"
            m = infos[bid].manifest
            return (f"{bid} · {m.get('model') or 'config default'} · "
                    f"{m.get('records_tagged', '?')} tagged")

        bundle_id = st.selectbox("Tag bundle (facet source)", ids,
                                 index=ids.index(default), key="batch_bundle",
                                 format_func=_bundle_label)
        st.caption("The facet filters below read this **bundle**'s tag index — one "
                   "tagging pass keyed by its exact axes + model + prompt (build "
                   "bundles on the *Run diversity* page). The default is *latest*, "
                   "the most recently tagged one; *legacy* is a pre-bundle flat "
                   "index with no recorded provenance.")
    index = loader.combined_index(run.run_dir, bundle_id)
```

- [ ] **Step 2: Verify**

Run: `python -m pytest`
Expected: all pass (`tests/test_judge_batch_selection.py` imports the module — a syntax/import error fails loudly).

Run: `python -c "import ast; ast.parse(open('viewer/ui_pages/judge_batch.py').read())"`
Expected: silent success.

---

### Task 9: Final verification

- [ ] **Step 1: Full suite**

Run: `source .venv/bin/activate && python -m pytest`
Expected: 0 failed; ~520 passed (baseline 490 + ~30 new), still a few seconds, offline.

- [ ] **Step 2: Live viewer smoke (in-page explanations are acceptance criteria)**

Run: `streamlit run viewer/app.py` (localhost:8501), then verify on a real run (e.g. `outputs/dad/runs/2026-07-03_11-15_haiku-test2`, which has a legacy flat index):

1. Run diversity page shows the bundle picker with the `legacy` entry and its caption ("pre-bundle flat index … no recorded provenance"); the three metrics and report render from it.
2. The Tag/Analyze captions render with the new bundle copy next to their buttons.
3. Judge → Score a run shows the "Tag bundle (facet source)" picker + caption, and facets still populate.

Do **not** click Tag/Analyze against a real run (paid API). Stop the server after checking.

- [ ] **Step 3: Report** — summarize what changed, the two fingerprint deviations from the spec's literal field list (prompt_hint in, target out) and the score_dad gap closure, and remind the user that committing is theirs to trigger. Then hand over to the standing Codex review pair (straight + adversarial), adjudicate, one combined fix wave, re-review.

---

## Self-Review (done at plan time)

- **Spec coverage:** storage layout + manifest (T2), fingerprint split + canonicalization (T1), Tag resume/create + latest (T2/T3), Analyze targets selected bundle & never re-tags (T4/T7), bare-corpus sibling root (T3), CLI routing + `--bundle` + git_commit reuse (T2/T4), loader (T6), viewer pickers + all four required captions (T7/T8), legacy back-compat + no-migration (T2/T3/T6), every listed test scenario has a concrete test (fingerprint stability ×3, resume-zero-calls, fresh-bundle-on-change, manifest+snapshot contents, latest pointer, back-compat, analyze-targets-bundle, malformed manifest).
- **Known deviations (flag to user):** `prompt_hint` in / `target` out of the fingerprint (spec's own principle over its literal list); `score_dad.select_records` made bundle-aware (unlisted in spec, but `--where` would otherwise permanently break for bundled runs); Analyze on the `legacy` bundle still writes `audit/holistic_dad_report.json` (its pre-bundle report slot — "read-only" applies to tags).
- **Type consistency:** `BundlePaths`/`BundleInfo`/`LEGACY_ID`/`INDEX_NAME`/`REPORT_NAME`/`MANIFEST_NAME` names match across all tasks; `record_bundle_analysis(inputs, analysis_cfg, analyzers, model, synthesis_template)` identical at both call sites; `resolve_inputs(..., bundle_id=)` and loader `bundle_id` params consistent.
