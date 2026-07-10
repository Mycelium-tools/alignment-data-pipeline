"""Provenance bundles (P1): fingerprint identity + the bundle store.

Bundle identity is sha256 over (canonical fields, model, extract template) —
exactly the inputs that determine the tags. Cosmetic YAML edits must not change
it; quota targets must not either (they only feed the coverage analyzer);
prompt_hint must (it is rendered into the extraction prompt)."""

import hashlib
import json

import yaml

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


def test_resolve_bundle_adopts_an_orphan_dir_left_by_a_crash(tmp_path):
    root = tmp_path / "holistic"
    reg = _reg(AXES_A, tmp_path)
    first = bundle.resolve_bundle(root, reg, model="m", extract_template="tpl",
                                  axes_text=AXES_A, create=True)
    # simulate a crash between mkdir and the manifest/snapshot writes
    (first.bundle_dir / "manifest.json").unlink()
    (first.bundle_dir / "axes_snapshot.yaml").unlink()

    # must not raise (dir name is deterministic within the same minute, so this
    # normally re-adopts `first.bundle_dir`; assert on outcome, not identity, in
    # case the clock ticks over mid-test)
    again = bundle.resolve_bundle(root, reg, model="m", extract_template="tpl",
                                  axes_text=AXES_A, create=True)
    assert (again.bundle_dir / "manifest.json").exists()
    assert (again.bundle_dir / "axes_snapshot.yaml").exists()


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


def test_latest_bundle_id_none_when_symlinked_manifest_is_corrupt(tmp_path):
    root = tmp_path / "holistic"
    paths = bundle.resolve_bundle(root, _reg(AXES_A, tmp_path), create=True)
    (paths.bundle_dir / "manifest.json").write_text("{not json")
    assert bundle.latest_bundle_id(root) is None


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


def test_list_bundles_skips_non_dict_manifest(tmp_path, capsys):
    root = tmp_path / "holistic"
    bad = _mk_bundle(root, "2026-01-01_00-00_aaaaaaaa", [])
    infos = bundle.list_bundles(root)
    assert infos == []
    assert "aaaaaaaa" in capsys.readouterr().out       # warned, not crashed
    # resolve_bundle(create=True) must still work with the non-dict manifest present
    paths = bundle.resolve_bundle(root, _reg(AXES_A, tmp_path), create=True)
    assert paths.bundle_dir != bad


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


# ---------------------------------------------------------------- schema drift (P1)

def test_snapshot_fields_differ_false_for_same_fields(tmp_path):
    root = tmp_path / "holistic"
    paths = bundle.resolve_bundle(root, _reg(AXES_A, tmp_path), axes_text=AXES_A,
                                  create=True)
    assert bundle.snapshot_fields_differ(paths.bundle_dir, _reg(AXES_A, tmp_path)) is False


def test_snapshot_fields_differ_true_when_a_value_changed(tmp_path):
    root = tmp_path / "holistic"
    paths = bundle.resolve_bundle(root, _reg(AXES_A, tmp_path), axes_text=AXES_A,
                                  create=True)
    assert bundle.snapshot_fields_differ(paths.bundle_dir, _reg(AXES_B, tmp_path, "b.yaml")) is True


def test_snapshot_fields_differ_false_when_snapshot_missing(tmp_path):
    root = tmp_path / "holistic"
    paths = bundle.resolve_bundle(root, _reg(AXES_A, tmp_path), create=True)
    (paths.bundle_dir / "axes_snapshot.yaml").unlink()
    assert bundle.snapshot_fields_differ(paths.bundle_dir, _reg(AXES_A, tmp_path)) is False


def test_snapshot_fields_differ_false_when_only_a_quota_changed(tmp_path):
    root = tmp_path / "holistic"
    paths = bundle.resolve_bundle(root, _reg(AXES_A, tmp_path), axes_text=AXES_A,
                                  create=True)
    quota = AXES_A.replace(
        "kind: single",
        "kind: single\n    target: {min_share: {Mixed: 0.2}}")
    assert bundle.snapshot_fields_differ(
        paths.bundle_dir, _reg(quota, tmp_path, "q.yaml")) is False


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
