"""The orchestrator resolves a run directory (or a bare corpus file) into the three
inputs — corpus, annotations, verdicts — reads/writes the tag index in the run's
provenance bundles under holistic/ (legacy audit/ fallback), and runs the registered
analyzers. It reads run layout via plain file I/O (no viewer/streamlit dependency)."""

import json

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


def test_run_on_a_bare_corpus_file_tags_into_a_sibling_holistic_bundle(tmp_path, stub_claude):
    # the sibling is now <stem>.holistic/<bundle>/, not a flat sibling file
    corpus = tmp_path / "dad_corpus.jsonl"
    utils.append_jsonl({"record_id": "a", "messages": MESSAGES}, corpus)
    stub_claude([GOOD_JSON])
    report = pipeline.run(corpus)
    assert report["records"] == 1
    assert report["inputs_present"] == ["tags", "texts"]        # no annotations/verdicts
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


# ---------------------------------------------------------------- tagging into bundles

def test_tag_writes_the_index_into_a_run_bundle(tmp_path, stub_claude):
    run = _make_run(tmp_path, with_verdicts=False)
    stub_claude([GOOD_JSON])
    inp = pipeline.resolve_inputs(run)
    rows = pipeline.tag(inp, F.default_fields())
    assert rows[0]["record_id"] == "a"
    assert inp.index_path.parent.parent == run / "holistic"
    written = utils.load_jsonl(inp.index_path)
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
    assert report["inputs_present"] == ["tags", "texts"]


# ---------------------------------------------------------------- clusters input (§18.1)

def _write_diversity_report(base_dir, assignments):
    import json
    (base_dir / "audit").mkdir(parents=True, exist_ok=True)
    (base_dir / "audit" / "diversity_report.json").write_text(
        json.dumps({"embed_model": "stub", "clusters": {"k": 2, "assignments": assignments}}))


def test_resolve_run_dir_loads_cluster_assignments_from_diversity_report(tmp_path):
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    _write_diversity_report(run, {"a": 1})
    assert pipeline.resolve_inputs(run).clusters == {"a": 1}


def test_resolve_without_diversity_report_leaves_clusters_none(tmp_path):
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    assert pipeline.resolve_inputs(run).clusters is None


def test_resolve_bare_corpus_reads_the_sibling_audit_diversity_report(tmp_path):
    corpus = tmp_path / "dad_corpus.jsonl"
    utils.append_jsonl({"record_id": "a", "messages": MESSAGES}, corpus)
    _write_diversity_report(tmp_path, {"a": 0})
    assert pipeline.resolve_inputs(corpus).clusters == {"a": 0}


def test_run_gates_the_cluster_bridge_on_the_clusters_input(tmp_path, stub_claude):
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    stub_claude([GOOD_JSON])
    without = pipeline.run(run)
    assert "cluster_bridge" in without["stats"]["skipped"]

    _write_diversity_report(run, {"a": 0})
    with_clusters = pipeline.run(run, do_tag=False)   # index already built above
    assert "cluster_bridge" in with_clusters["stats"]["analyses"]
    assert "clusters" in with_clusters["inputs_present"]


def test_corrupt_diversity_report_degrades_to_no_clusters(tmp_path):
    # clusters are OPTIONAL gated input — a truncated sidecar must not take down
    # the non-cluster analyzers
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    (run / "audit").mkdir(parents=True, exist_ok=True)
    (run / "audit" / "diversity_report.json").write_text('{"clusters": {"assignm')
    assert pipeline.resolve_inputs(run).clusters is None


def test_wrong_shape_diversity_report_also_degrades_to_no_clusters(tmp_path):
    # valid JSON that isn't a report object (e.g. []) must degrade the same way
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    (run / "audit").mkdir(parents=True, exist_ok=True)
    (run / "audit" / "diversity_report.json").write_text("[]")
    assert pipeline.resolve_inputs(run).clusters is None


def test_wrong_shape_clusters_sections_also_degrade_to_none(tmp_path):
    # nested wrong shapes: a truthy non-dict clusters value, or non-dict assignments
    import json
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    (run / "audit").mkdir(parents=True, exist_ok=True)
    report_path = run / "audit" / "diversity_report.json"
    for payload in ({"clusters": [1]}, {"clusters": {"assignments": "oops"}}):
        report_path.write_text(json.dumps(payload))
        assert pipeline.resolve_inputs(run).clusters is None


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


def test_tag_fingerprints_the_resolved_config_model_not_none(tmp_path, stub_claude,
                                                             monkeypatch):
    # #1 fix: tagging without an explicit model must fingerprint the EFFECTIVE
    # model (the config default), not "" — otherwise changing config.yaml's model
    # silently resumes tags produced by the previous model, mixing two models in
    # one bundle.
    from shared import api
    from evals.holistic import bundle
    monkeypatch.setattr(api, "_config", {"model": "cfg-default-x"})
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    stub_claude([GOOD_JSON])
    inp = pipeline.resolve_inputs(run)
    pipeline.tag(inp, F.default_fields())            # no model= → resolves to config
    manifest = json.loads((inp.index_path.parent / "manifest.json").read_text())
    assert manifest["model"] == "cfg-default-x"
    # the bundle is keyed by the resolved model: an explicit cfg-default-x tag lands
    # in the same bundle (no silent re-tag when the config default is made explicit)
    assert manifest["tag_fingerprint"] == \
        bundle.tag_fingerprint(F.default_fields(), "cfg-default-x", None)


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


def test_resolve_inputs_rejects_a_path_shaped_bundle_id(tmp_path):
    import pytest
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    with pytest.raises(SystemExit, match="invalid bundle id"):
        pipeline.resolve_inputs(run, bundle_id="../outside")


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


def test_run_derives_assistant_texts_and_runs_structural(tmp_path, stub_claude):
    stub_claude([GOOD_JSON])
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    report = pipeline.run(run)
    assert "texts" in report["inputs_present"]
    assert "structural" in report["stats"]["analyses"]
    assert report["stats"]["analyses"]["structural"]["n"] == 1


# ---------------------------------------------------------------- semantic summary


def test_run_feeds_bounded_semantic_summary_to_synthesis(tmp_path, stub_claude):
    run = _make_run(tmp_path)
    audit = run / "audit"
    audit.mkdir()
    (audit / "diversity_report.json").write_text(json.dumps({
        "embed_model": "stub-embed",
        "n_embedded": 3, "n_empty": 0,
        "vendi": {"score": 2.5},
        "mean_pairwise_cosine": 0.21,
        "nn": {"over_0.90": 0.0},
        "clusters": {"k": 2, "clusters": 2, "evenness": 0.9, "verdict": "GOOD",
                     "assignments": {"a": 0, "b": 1}},
        "top_pairs": [{"similarity": 0.9, "a": "a", "b": "b"}] * 7,   # >5
        "projection": [{"id": "ZZZPROJVAL", "x": 0.1, "y": 0.2, "cluster": 0}],
    }))
    # run(): one tag call (GOOD_JSON) then one synthesis call.
    calls = stub_claude([GOOD_JSON,
                         '{"verdict": "ok", "sections": [], "top_issues": []}'])
    report = pipeline.run(run, synthesis_template="S:\n{{STATS}}")

    synth_prompt = calls[1]["user_message"]
    assert "stub-embed" in synth_prompt          # bounded summary reached the judge
    assert "mean_pairwise_cosine" in synth_prompt
    assert '"projection"' not in synth_prompt     # O(records) array excluded
    assert "ZZZPROJVAL" not in synth_prompt
    assert "assignments" not in synth_prompt      # O(records) cluster map excluded
    assert synth_prompt.count('"similarity"') == 5   # top_pairs capped at 5
    assert "semantic" not in report["stats"]      # persisted stats stay pure


def test_run_semantic_summary_is_null_without_an_audit(tmp_path, stub_claude):
    run = _make_run(tmp_path)   # no audit/diversity_report.json
    calls = stub_claude([GOOD_JSON,
                         '{"verdict": "ok", "sections": [], "top_issues": []}'])
    pipeline.run(run, synthesis_template="S:\n{{STATS}}")
    assert '"semantic": null' in calls[1]["user_message"]
