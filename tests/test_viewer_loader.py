"""Pure viewer/loader.py additions for the run-diversity page and the faceted
batch-judge narrowing (spec §12.2): loading the extraction tag index and holistic
report, the combined facet index (tags + legacy injection), facet option counts,
and saved-verdict status. All pure file reads over a run dir — no streamlit."""

import json

from shared import utils
from viewer import loader


def _write_run(tmp_path, *, tags=None, step3=None, step6=None, report=None):
    run = tmp_path / "2026-07-09_00-00_test"
    if tags is not None:
        utils.save_jsonl(tags, run / "audit" / "category_records.jsonl")
    if step3 is not None:
        utils.save_jsonl(step3, run / "step3" / "rewrites.jsonl")
    if step6 is not None:
        utils.save_jsonl(step6, run / "step6" / "rewrites.jsonl")
    if report is not None:
        (run / "audit").mkdir(parents=True, exist_ok=True)
        (run / "audit" / "holistic_dad_report.json").write_text(json.dumps(report))
    run.mkdir(parents=True, exist_ok=True)
    return run


# ---------------------------------------------------------------- raw loads

def test_category_records_reads_the_audit_index(tmp_path):
    rows = [{"record_id": "a", "taxa_category": "farmed"}]
    run = _write_run(tmp_path, tags=rows)
    assert loader.category_records(run) == rows


def test_category_records_empty_when_index_missing(tmp_path):
    run = _write_run(tmp_path)
    assert loader.category_records(run) == []


def test_holistic_report_loads_the_audit_report(tmp_path):
    report = {"run_id": "r", "records": 2, "stats": {"analyses": {}}}
    run = _write_run(tmp_path, report=report)
    assert loader.holistic_report(run) == report


def test_holistic_report_none_when_missing(tmp_path):
    run = _write_run(tmp_path)
    assert loader.holistic_report(run) is None


# ---------------------------------------------------------------- combined index

def test_combined_index_overlays_tags_on_legacy_injection(tmp_path):
    run = _write_run(
        tmp_path,
        tags=[{"record_id": "a", "taxa_category": "farmed", "domain": ["Food"]}],
        step6=[{"record_id": "a", "injection_used": "plain"},
               {"record_id": "b", "injection_used": "deference"}])
    idx = loader.combined_index(run)
    assert idx["a"] == {"record_id": "a", "injection_used": "plain",
                        "taxa_category": "farmed", "domain": ["Food"]}
    # a record with an annotation but no tag row still appears (injection facet only)
    assert idx["b"] == {"record_id": "b", "injection_used": "deference"}


def test_combined_index_tags_only_run(tmp_path):
    run = _write_run(tmp_path, tags=[{"record_id": "a", "direction": "Mixed"}])
    assert loader.combined_index(run) == {
        "a": {"record_id": "a", "direction": "Mixed"}}


def test_combined_index_drops_extraction_bookkeeping_keys(tmp_path):
    run = _write_run(tmp_path, tags=[
        {"record_id": "a", "extract_error": "unparseable model output"},
        {"record_id": "b", "taxa_category": "wild", "_errors": ["posture: invalid"]},
    ])
    idx = loader.combined_index(run)
    assert idx["a"] == {"record_id": "a"}
    assert idx["b"] == {"record_id": "b", "taxa_category": "wild"}


def test_combined_index_spec_driven_step3_rows_do_not_add_facets(tmp_path):
    # spec-driven annotation rows carry .annotation (intended labels) but no
    # injection; only realized extraction tags become facets (spec §12.1)
    run = _write_run(
        tmp_path,
        tags=[{"record_id": "a", "direction": "Mixed"}],
        step3=[{"record_id": "a", "annotation": {"direction": "Over-weighting"}}])
    assert loader.combined_index(run)["a"] == {"record_id": "a", "direction": "Mixed"}


def test_combined_index_empty_run(tmp_path):
    assert loader.combined_index(_write_run(tmp_path)) == {}


# ---------------------------------------------------------------- facet options

def test_facet_options_counts_scalars_and_list_elements():
    rows = [
        {"record_id": "a", "taxa_category": "farmed", "domain": ["Food", "Policy"]},
        {"record_id": "b", "taxa_category": "farmed", "domain": ["Food"]},
        {"record_id": "c", "taxa_category": "wild"},
    ]
    opts = loader.facet_options(rows, ["taxa_category", "domain", "direction"])
    assert opts["taxa_category"] == {"farmed": 2, "wild": 1}
    assert opts["domain"] == {"Food": 2, "Policy": 1}
    assert opts["direction"] == {}          # requested but unobserved


def test_facet_options_ignores_non_categorical_values():
    rows = [{"record_id": "a", "anatomy": {"nested": 1}, "n_turns": None}]
    opts = loader.facet_options(rows, ["anatomy", "n_turns"])
    assert opts == {"anatomy": {}, "n_turns": {}}


# ---------------------------------------------------------------- verdict status

def test_verdict_status_maps_saved_rows():
    passed = {"panel": {"consensus_aggregate": {"passing": True}}}
    failed = {"panel": {"consensus_aggregate": {"passing": False}}}
    error = {"panel": {"judge_error": "boom"}}
    assert loader.verdict_status(None) == "not-yet-judged"
    assert loader.verdict_status(passed) == "passed"
    assert loader.verdict_status(failed) == "failed"
    assert loader.verdict_status(error) == "error"


# ---------------------------------------------------------------- bundle-aware reads

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


def test_explicit_missing_bundle_id_does_not_fall_back_to_the_legacy_report(tmp_path):
    run = tmp_path / "run"
    (run / "audit").mkdir(parents=True)
    utils.save_jsonl([{"record_id": "a", "taxa_category": "wild"}],
                     run / "audit" / "category_records.jsonl")
    (run / "audit" / "holistic_dad_report.json").write_text(json.dumps({"records": 1}))
    missing = "2020-01-01_00-00_deadbeef"
    assert loader.holistic_report(run, missing) is None
    assert loader.category_records(run, missing) == []


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
