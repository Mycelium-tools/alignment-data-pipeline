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

from .fields import FieldRegistry, load_fields

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
            if not isinstance(manifest, dict):
                print(f"WARNING: skipping bundle {d.name} (bad {MANIFEST_NAME}: not a JSON object)")
                continue
            bundles.append(BundleInfo(d.name, d, manifest))
    if not bundles and legacy_index is not None and legacy_index.exists():
        return [BundleInfo(LEGACY_ID, legacy_index.parent, {})]
    return bundles


def latest_bundle_id(holistic_root: Path) -> str | None:
    """The bundle the ``latest`` symlink points at (repointed on every Tag), or
    None when there is no valid pointer. A corrupt manifest returns None so
    default reads fall back to a listable bundle."""
    link = Path(holistic_root) / "latest"
    if not link.is_symlink():
        return None
    try:
        manifest = json.loads((link / MANIFEST_NAME).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return link.resolve().name if isinstance(manifest, dict) else None


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
    # exist_ok: a crash between mkdir and the manifest write leaves an orphan dir
    # with this exact name (same fingerprint, same minute) — adopt and finish it.
    # Accepted trade-off: a same-minute fp8 collision between two DIFFERENT full
    # fingerprints (~1 in 4.3B) would silently share the dir instead of crashing.
    bundle_dir.mkdir(parents=True, exist_ok=True)
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


def snapshot_fields_differ(bundle_dir: Path, fields: FieldRegistry) -> bool:
    """True when this bundle's axes snapshot parses and its tag-relevant fields
    differ semantically from ``fields`` — analyzing it with the current axes
    would mix schemas. Missing or unparseable snapshots return False (nothing
    to compare against)."""
    path = Path(bundle_dir) / AXES_SNAPSHOT_NAME
    if not path.exists():
        return False
    try:
        snap = load_fields(path)
    except Exception:  # noqa: BLE001 — a broken snapshot must not block Analyze
        return False
    return canonical_fields(snap) != canonical_fields(fields)
