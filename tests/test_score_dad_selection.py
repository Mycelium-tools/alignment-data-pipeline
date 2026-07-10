"""score_dad's CLI selection helper: facet filters come from the holistic tag index
in the run's audit/ dir (built by holistic_dad --extract-only). --where without that
index fails loudly instead of silently judging zero records. The grammar itself is
tested in test_selection.py; these tests cover only the score_dad wiring."""

import pytest

from evals import score_dad
from shared import utils


def _corpus(tmp_path, rids):
    run = tmp_path / "run"
    (run / "final").mkdir(parents=True)
    path = run / "final" / "dad_corpus.jsonl"
    for rid in rids:
        utils.append_jsonl({"record_id": rid, "messages": []}, path)
    return path


def test_select_records_where_filters_via_the_audit_index(tmp_path):
    corpus_path = _corpus(tmp_path, ["a", "b", "c"])
    index = corpus_path.parent.parent / "audit" / "category_records.jsonl"
    utils.append_jsonl({"record_id": "a", "taxa_category": "farmed"}, index)
    utils.append_jsonl({"record_id": "b", "taxa_category": "wild"}, index)

    out = score_dad.select_records(utils.load_jsonl(corpus_path), corpus_path,
                                   where={"taxa_category": {"farmed"}})
    # 'c' has no tag row → cannot match a facet → dropped, not crashed
    assert [r["record_id"] for r in out] == ["a"]


def test_select_records_where_without_an_index_fails_loudly(tmp_path):
    corpus_path = _corpus(tmp_path, ["a"])
    with pytest.raises(SystemExit, match="extract-only"):
        score_dad.select_records(utils.load_jsonl(corpus_path), corpus_path,
                                 where={"taxa_category": {"farmed"}})


def test_select_records_limit_applies_after_ids(tmp_path):
    corpus_path = _corpus(tmp_path, ["a", "b", "c", "d"])
    out = score_dad.select_records(utils.load_jsonl(corpus_path), corpus_path,
                                   ids=["b", "c", "d"], limit=2)
    assert [r["record_id"] for r in out] == ["b", "c"]


def test_select_records_sample_is_seed_deterministic(tmp_path):
    corpus_path = _corpus(tmp_path, ["a", "b", "c", "d"])
    records = utils.load_jsonl(corpus_path)
    first = score_dad.select_records(records, corpus_path, sample=2, seed=5)
    again = score_dad.select_records(records, corpus_path, sample=2, seed=5)
    assert first == again and len(first) == 2


def test_select_records_no_flags_returns_everything(tmp_path):
    corpus_path = _corpus(tmp_path, ["a", "b"])
    out = score_dad.select_records(utils.load_jsonl(corpus_path), corpus_path)
    assert [r["record_id"] for r in out] == ["a", "b"]


def test_select_records_where_finds_the_sibling_index_of_a_bare_corpus(tmp_path):
    # A corpus outside a run dir gets its tag index as a sibling file
    # (pipeline.resolve_inputs layout) — --where must look there too.
    corpus_path = tmp_path / "dad_corpus.jsonl"
    utils.append_jsonl({"record_id": "a", "messages": []}, corpus_path)
    utils.append_jsonl({"record_id": "b", "messages": []}, corpus_path)
    utils.append_jsonl({"record_id": "a", "taxa_category": "farmed"},
                       tmp_path / "dad_corpus.category_records.jsonl")

    out = score_dad.select_records(utils.load_jsonl(corpus_path), corpus_path,
                                   where={"taxa_category": {"farmed"}})
    assert [r["record_id"] for r in out] == ["a"]


def test_select_records_index_without_record_ids_counts_as_missing(tmp_path):
    # An index whose rows carry no record_id can never match anything — treat it
    # like a missing index (loud), not an empty selection (silent).
    corpus_path = _corpus(tmp_path, ["a"])
    utils.append_jsonl({"taxa_category": "farmed"},
                       corpus_path.parent.parent / "audit" / "category_records.jsonl")
    with pytest.raises(SystemExit, match="extract-only"):
        score_dad.select_records(utils.load_jsonl(corpus_path), corpus_path,
                                 where={"taxa_category": {"farmed"}})


def test_drop_retryable_errors_keeps_errored_rows_outside_the_selection():
    # --retry-errors must only drop errored rows it is about to re-judge; an
    # errored row outside the selection would otherwise be deleted forever.
    rows = [
        {"record_id": "a", "panel": {"results": [{"model": "m", "verdict": None}]}},
        {"record_id": "b", "panel": {"results": [{"model": "m", "verdict": None}]}},
        {"record_id": "c", "panel": {"results": [{"model": "m", "verdict": {"ok": 1}}]}},
    ]
    kept = score_dad.drop_retryable_errors(rows, selected_ids={"a"})
    assert [r["record_id"] for r in kept] == ["b", "c"]


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
