"""The orchestrator resolves a run directory (or a bare corpus file) into the three
inputs — corpus, annotations, verdicts — reads/writes the tag index in the run's
audit/ dir, and runs the registered analyzers. It reads run layout via plain file I/O
(no viewer/streamlit dependency)."""

from evals.holistic import pipeline
from evals.holistic import fields as F
from shared import utils

MESSAGES = [{"role": "user", "content": "Switch to caged hens?"},
            {"role": "assistant", "content": "Weighing the welfare cost..."}]
GOOD_JSON = '{"language": "en", "taxa_category": "farmed", "posture_class": "RAISE_AND_HELP"}'


def _make_run(tmp_path, *, with_annotations=True, with_verdicts=True):
    run = tmp_path / "2026-01-01_00-00_test"
    (run / "final").mkdir(parents=True)
    utils.append_jsonl({"record_id": "a", "messages": MESSAGES}, run / "final" / "dad_corpus.jsonl")
    if with_annotations:
        (run / "step3").mkdir()
        utils.append_jsonl({"record_id": "a", "annotation": {"direction": "Under-weighting"}},
                           run / "step3" / "rewrites.jsonl")
    if with_verdicts:
        vdir = run / "final" / "judge" / "dad-v4.3"
        vdir.mkdir(parents=True)
        utils.append_jsonl({"record_id": "a", "panel": {"consensus_verdict": {}}},
                           vdir / "verdicts.jsonl")
    return run


# ---------------------------------------------------------------- input resolution

def test_resolve_bare_corpus_file_has_no_annotations_or_verdicts(tmp_path):
    corpus = tmp_path / "dad_corpus.jsonl"
    utils.append_jsonl({"record_id": "a", "messages": MESSAGES}, corpus)
    inp = pipeline.resolve_inputs(corpus)
    assert [r["record_id"] for r in inp.corpus] == ["a"]
    assert inp.annotations is None and inp.verdicts is None and inp.run_dir is None


def test_run_on_a_bare_corpus_file_tags_into_a_sibling_index(tmp_path, stub_claude):
    corpus = tmp_path / "dad_corpus.jsonl"
    utils.append_jsonl({"record_id": "a", "messages": MESSAGES}, corpus)
    stub_claude([GOOD_JSON])
    report = pipeline.run(corpus)
    assert report["records"] == 1
    assert report["inputs_present"] == ["tags"]        # no annotations/verdicts
    inp = pipeline.resolve_inputs(corpus)
    assert utils.load_jsonl(inp.index_path)[0]["taxa_category"] == "farmed"


def test_run_accepts_pre_resolved_inputs(tmp_path, stub_claude):
    # The CLI resolves once (for selection + the report path) and passes the same
    # Inputs through — a second resolve could race a moving `latest` symlink.
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    stub_claude([GOOD_JSON])
    inputs = pipeline.resolve_inputs(run)
    report = pipeline.run(inputs)
    assert report["records"] == 1
    assert utils.load_jsonl(inputs.index_path)[0]["taxa_category"] == "farmed"


def test_resolve_run_dir_joins_annotations_and_verdicts_by_record_id(tmp_path):
    run = _make_run(tmp_path)
    inp = pipeline.resolve_inputs(run)
    assert inp.run_dir == run
    assert inp.annotations["a"]["direction"] == "Under-weighting"
    assert "a" in inp.verdicts


def test_resolve_run_dir_without_spec_driven_annotations_leaves_them_none(tmp_path):
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    inp = pipeline.resolve_inputs(run)
    assert inp.annotations is None and inp.verdicts is None


def test_resolve_fails_loudly_on_a_missing_path(tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        pipeline.resolve_inputs(tmp_path / "does_not_exist.jsonl")


def test_resolve_fails_loudly_on_a_run_dir_without_a_final_corpus(tmp_path):
    import pytest
    (tmp_path / "emptyrun").mkdir()
    with pytest.raises(SystemExit):
        pipeline.resolve_inputs(tmp_path / "emptyrun")


def test_verdicts_require_an_explicit_version_when_multiple_exist(tmp_path):
    import pytest
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    for version in ("dad-v4.9", "dad-v4.10"):
        vdir = run / "final" / "judge" / version
        vdir.mkdir(parents=True)
        utils.append_jsonl({"record_id": "a", "which": version}, vdir / "verdicts.jsonl")

    with pytest.raises(SystemExit, match="multiple judge verdict versions"):
        pipeline.resolve_inputs(run)


def test_verdicts_load_the_requested_version(tmp_path):
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    for version in ("dad-v4.9", "dad-v4.10"):
        vdir = run / "final" / "judge" / version
        vdir.mkdir(parents=True)
        utils.append_jsonl({"record_id": "a", "which": version}, vdir / "verdicts.jsonl")

    inp = pipeline.resolve_inputs(run, judge_version="dad-v4.9")
    assert inp.verdicts["a"]["which"] == "dad-v4.9"


# ---------------------------------------------------------------- tagging into audit/

def test_tag_writes_the_index_into_the_runs_audit_dir(tmp_path, stub_claude):
    run = _make_run(tmp_path, with_verdicts=False)
    stub_claude([GOOD_JSON])
    inp = pipeline.resolve_inputs(run)
    rows = pipeline.tag(inp, F.default_fields())
    assert rows[0]["record_id"] == "a"
    written = utils.load_jsonl(pipeline.category_records_path(run))
    assert written[0]["taxa_category"] == "farmed"


def test_load_category_records_reads_the_audit_index(tmp_path):
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    utils.append_jsonl({"record_id": "a", "taxa_category": "wild"},
                       pipeline.category_records_path(run))
    inp = pipeline.resolve_inputs(run)
    assert pipeline.load_category_records(inp)[0]["taxa_category"] == "wild"


# ---------------------------------------------------------------- analysis

def test_analyze_runs_registered_analyzers_over_tag_rows(tmp_path):
    tags = [{"record_id": "a", "taxa_category": "farmed", "language": "en"},
            {"record_id": "b", "taxa_category": "wild", "language": "en"}]
    out = pipeline.analyze(tags)
    assert out["analyses"]["distribution"]["taxa_category"] == {"farmed": 1, "wild": 1}


def test_analyze_gates_annotation_analyzers_on_availability(tmp_path):
    from evals.holistic import analyzers as A
    reg = A.AnalyzerRegistry()
    reg.add(A.Analyzer(name="needs_ann", requires=("tags", "annotations"),
                       fn=lambda ctx: {"ok": True}))
    tags = [{"record_id": "a", "taxa_category": "farmed"}]
    assert "needs_ann" in pipeline.analyze(tags, analyzers=reg)["skipped"]
    got = pipeline.analyze(tags, analyzers=reg, annotations={"a": {}})
    assert got["analyses"]["needs_ann"] == {"ok": True}


# ---------------------------------------------------------------- end to end

def test_run_tags_then_analyzes_and_reports(tmp_path, stub_claude):
    run = _make_run(tmp_path, with_verdicts=False)
    stub_claude([GOOD_JSON])
    report = pipeline.run(run)
    assert report["run_id"] == run.name
    assert report["records"] == 1
    assert "annotations" in report["inputs_present"]
    assert report["stats"]["analyses"]["distribution"]["taxa_category"] == {"farmed": 1}


def test_run_without_tagging_uses_existing_index_and_calls_no_api(tmp_path):
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    utils.append_jsonl({"record_id": "a", "taxa_category": "wild"},
                       pipeline.category_records_path(run))
    # No stub installed: any API call would raise, proving do_tag=False stays offline.
    report = pipeline.run(run, do_tag=False)
    assert report["stats"]["analyses"]["distribution"]["taxa_category"] == {"wild": 1}
    assert report["inputs_present"] == ["tags"]
