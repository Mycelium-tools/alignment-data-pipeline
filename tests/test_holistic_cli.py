"""The CLI is a thin wrapper over the tested pipeline: it tags a run and writes the
report into the run's provenance bundle under holistic/ (legacy runs keep the flat
audit/ report). (API init is a no-op here; the tag call is stubbed.)"""

import json
import pytest

from evals import holistic_dad
from evals.holistic import pipeline
from shared import utils

MESSAGES = [{"role": "user", "content": "Switch to caged hens?"},
            {"role": "assistant", "content": "Weighing it..."}]
GOOD_JSON = '{"language": "en", "taxa_category": "farmed", "posture_class": "NO_RAISE"}'


def _make_run(tmp_path):
    run = tmp_path / "2026-01-01_00-00_test"
    (run / "final").mkdir(parents=True)
    utils.append_jsonl({"record_id": "a", "messages": MESSAGES},
                       run / "final" / "dad_corpus.jsonl")
    return run


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


def test_cli_analyze_only_warns_when_axes_differ_from_the_bundles_snapshot(
        tmp_path, stub_claude, monkeypatch, capsys):
    run = _make_run(tmp_path)
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    axes_a = tmp_path / "a.yaml"
    axes_a.write_text("fields:\n  - name: direction\n"
                      "    values: [Under-weighting, Over-weighting, Mixed]\n")
    axes_b = tmp_path / "b.yaml"
    axes_b.write_text("fields:\n  - name: direction\n"
                      "    values: [Under-weighting, Over-weighting, Balanced]\n")
    stub_claude(['{"direction": "Mixed"}'])
    holistic_dad.main(["--input", str(run), "--axes", str(axes_a), "--no-synthesize"])
    [bdir] = _bundle_dirs(run)

    capsys.readouterr()
    holistic_dad.main(["--input", str(run), "--analyze-only", "--no-synthesize",
                       "--bundle", bdir.name, "--axes", str(axes_b)])
    assert "WARNING" in capsys.readouterr().out

    holistic_dad.main(["--input", str(run), "--analyze-only", "--no-synthesize",
                       "--bundle", bdir.name, "--axes", str(axes_a)])
    assert "WARNING" not in capsys.readouterr().out


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


def test_cli_axes_file_drives_the_output_schema(tmp_path, stub_claude, monkeypatch):
    run = _make_run(tmp_path)
    axes = tmp_path / "axes.yaml"
    axes.write_text("fields:\n"
                    "  - name: direction\n    kind: single\n"
                    "    values: [Under-weighting, Over-weighting, Mixed]\n")
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    stub_claude(['{"direction": "Over-weighting"}'])

    report = holistic_dad.main(["--input", str(run), "--axes", str(axes), "--no-synthesize"])

    # Only the fields from the edited schema appear in the output.
    assert list(report["stats"]["analyses"]["distribution"].keys()) == ["direction"]
    assert report["stats"]["analyses"]["distribution"]["direction"] == {"Over-weighting": 1}


def test_cli_fails_loudly_on_a_missing_axes_file(tmp_path, monkeypatch):
    import pytest
    run = _make_run(tmp_path)
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    with pytest.raises(SystemExit):
        holistic_dad.main(["--input", str(run), "--axes", str(tmp_path / "nope.yaml")])


def test_summary_lines_render_good_bad_verdicts():
    report = {
        "run_id": "r", "records": 3, "inputs_present": ["tags"],
        "stats": {"analyses": {
            "distribution": {"taxa_category": {"farmed": 2, "wild": 1}},
            "evenness": {
                "taxa_category": {"richness": 2, "n": 3, "evenness": 0.918,
                                  "verdict": "GOOD", "note": "..."},
                "posture_class": {"richness": 0, "n": 0, "evenness": None,
                                  "verdict": "NA", "note": "..."}}},
                  "skipped": {}}}
    text = "\n".join(holistic_dad.summary_lines(report))
    assert "[GOOD]" in text
    assert "taxa_category" in text and "evenness" in text
    assert "posture_class" not in text          # NA (no data) axes are not listed


def test_summary_lines_render_bad_correlations():
    report = {
        "run_id": "r", "records": 10, "inputs_present": ["tags"],
        "stats": {"analyses": {
            "correlation": {
                "user_attitude x direction": {"n": 10, "cramers_v": 0.9,
                                              "verdict": "BAD", "note": "..."},
                "leverage x direction": {"n": 10, "cramers_v": 0.05,
                                         "verdict": "GOOD", "note": "..."}}},
                  "skipped": {}}}
    text = "\n".join(holistic_dad.summary_lines(report))
    assert "user_attitude x direction" in text and "[BAD]" in text and "0.9" in text
    assert "leverage x direction" not in text   # healthy correlations aren't listed


def test_summary_lines_render_missing_combination_cells():
    report = {
        "run_id": "r", "records": 10, "inputs_present": ["tags"],
        "stats": {"analyses": {
            "combination_coverage": {
                "leverage x direction": {"cells": 6, "filled": 2, "n": 10,
                                         "coverage": 0.33, "verdict": "BAD",
                                         "missing": ["Systemic×Over-weighting",
                                                     "Systemic×Under-weighting"],
                                         "note": "..."},
                "taxa_category x direction": {"cells": 20, "filled": 19, "n": 30,
                                              "coverage": 0.95, "verdict": "GOOD",
                                              "missing": ["wild×Mixed"], "note": "..."}}},
                  "skipped": {}}}
    text = "\n".join(holistic_dad.summary_lines(report))
    assert "leverage x direction" in text and "[BAD]" in text
    assert "Systemic×Over-weighting" in text
    assert "taxa_category x direction" not in text   # GOOD coverage isn't listed


def test_summary_lines_render_drift_axes():
    report = {
        "run_id": "r", "records": 10, "inputs_present": ["tags", "annotations"],
        "stats": {"analyses": {
            "drift": {
                "direction": {"n": 10, "agreement": 0.3, "verdict": "BAD",
                              "disagreements": [{"intended": "Over-weighting",
                                                 "realized": "Under-weighting",
                                                 "count": 7}], "note": "..."},
                "taxa_category": {"n": 10, "agreement": 0.95, "verdict": "GOOD",
                                  "disagreements": [], "note": "..."}}},
                  "skipped": {}}}
    text = "\n".join(holistic_dad.summary_lines(report))
    assert "direction" in text and "[BAD]" in text and "0.3" in text
    assert "Over-weighting" in text and "Under-weighting" in text   # the confusion pair
    assert "taxa_category" not in text               # GOOD agreement isn't listed


def test_cli_analysis_block_selects_analyzers_and_runs_coverage(tmp_path, stub_claude, monkeypatch):
    run = _make_run(tmp_path)
    axes = tmp_path / "axes.yaml"
    axes.write_text(
        "fields:\n"
        "  - name: taxa_category\n    kind: single\n    values: [farmed, wild]\n"
        "    target: {require_all_values: true}\n"
        "analysis:\n  analyzers: [coverage_vs_target]\n")
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    stub_claude(['{"taxa_category": "farmed"}'])          # only 'farmed' → 'wild' missing

    report = holistic_dad.main(["--input", str(run), "--axes", str(axes), "--no-synthesize"])

    analyses = report["stats"]["analyses"]
    assert list(analyses.keys()) == ["coverage_vs_target"]        # selection took effect
    assert analyses["coverage_vs_target"]["taxa_category"]["verdict"] == "BAD"
    assert any("wild" in v for v in
               analyses["coverage_vs_target"]["taxa_category"]["violations"])


def test_cli_runs_the_synthesis_pass_by_default(tmp_path, stub_claude, monkeypatch):
    run = _make_run(tmp_path)
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    # 1st call tags, 2nd call is the default synthesis pass over the stats.
    stub_claude([GOOD_JSON, '{"verdict": "Fine.", "sections": [], "top_issues": []}'])

    report = holistic_dad.main(["--input", str(run)])
    assert report["synthesis"]["verdict"] == "Fine."


def test_cli_analyze_only_fails_loudly_without_an_index(tmp_path, monkeypatch):
    run = _make_run(tmp_path)
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)

    with pytest.raises(SystemExit, match="No tag index"):
        holistic_dad.main(["--input", str(run), "--analyze-only", "--no-synthesize"])


def _make_run_with(tmp_path, rids):
    run = tmp_path / "2026-01-01_00-00_test"
    (run / "final").mkdir(parents=True)
    for rid in rids:
        utils.append_jsonl(
            {"record_id": rid,
             "messages": [{"role": "user", "content": f"Dilemma {rid}"},
                          {"role": "assistant", "content": f"Reply {rid}"}]},
            run / "final" / "dad_corpus.jsonl")
    return run


def test_cli_extract_only_tags_without_analyzing_or_reporting(tmp_path, stub_claude,
                                                              monkeypatch):
    run = _make_run(tmp_path)
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    calls = stub_claude([GOOD_JSON])

    result = holistic_dad.main(["--input", str(run), "--extract-only"])

    assert len(calls) == 1                       # tagging only — no synthesis call
    index = utils.load_jsonl(pipeline.resolve_inputs(run).index_path)
    assert [r["record_id"] for r in index] == ["a"]
    assert not (run / "audit" / "holistic_dad_report.json").exists()
    assert result["tagged"] == 1


def test_cli_extract_only_conflicts_with_analyze_only(tmp_path, monkeypatch):
    run = _make_run(tmp_path)
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="extract-only"):
        holistic_dad.main(["--input", str(run), "--extract-only", "--analyze-only"])


def test_cli_selection_flags_conflict_with_analyze_only(tmp_path, monkeypatch):
    # Selection narrows which records get TAGGED; --analyze-only never tags, so a
    # silent no-op would mislead — fail loudly instead.
    run = _make_run(tmp_path)
    utils.append_jsonl({"record_id": "a", "taxa_category": "farmed"},
                       pipeline.category_records_path(run))
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="analyze-only"):
        holistic_dad.main(["--input", str(run), "--analyze-only", "--no-synthesize",
                           "--where", "taxa_category=farmed"])


def test_cli_limit_tags_only_the_first_n_records(tmp_path, stub_claude, monkeypatch):
    run = _make_run_with(tmp_path, ["a", "b", "c"])
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    calls = stub_claude([GOOD_JSON, GOOD_JSON])

    holistic_dad.main(["--input", str(run), "--limit", "2", "--extract-only"])

    assert len(calls) == 2
    index = utils.load_jsonl(pipeline.resolve_inputs(run).index_path)
    assert [r["record_id"] for r in index] == ["a", "b"]


def test_cli_ids_tags_exactly_the_named_records(tmp_path, stub_claude, monkeypatch):
    run = _make_run_with(tmp_path, ["a", "b", "c"])
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    calls = stub_claude([GOOD_JSON, GOOD_JSON])

    holistic_dad.main(["--input", str(run), "--ids", "a,c", "--extract-only"])

    assert len(calls) == 2
    index = utils.load_jsonl(pipeline.resolve_inputs(run).index_path)
    assert [r["record_id"] for r in index] == ["a", "c"]


def test_cli_sample_is_seed_deterministic(tmp_path, stub_claude, monkeypatch):
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    tagged = []
    for sub in ("one", "two"):
        run = _make_run_with(tmp_path / sub, ["a", "b", "c", "d"])
        calls = stub_claude([GOOD_JSON, GOOD_JSON])
        holistic_dad.main(["--input", str(run), "--sample", "2", "--seed", "7",
                           "--extract-only"])
        assert len(calls) == 2
        index = utils.load_jsonl(pipeline.category_records_path(run))
        tagged.append([r["record_id"] for r in index])
    assert tagged[0] == tagged[1]


def test_cli_sample_with_duplicate_corpus_ids_tags_exactly_n(tmp_path, stub_claude,
                                                             monkeypatch):
    # Duplicate record_ids (a corrupt corpus) must not re-expand a positional sample
    # back into every row sharing the chosen id.
    run = tmp_path / "2026-01-01_00-00_test"
    (run / "final").mkdir(parents=True)
    for rid in ("a", "a", "b"):
        utils.append_jsonl({"record_id": rid, "messages": MESSAGES},
                           run / "final" / "dad_corpus.jsonl")
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    calls = stub_claude([GOOD_JSON])

    holistic_dad.main(["--input", str(run), "--sample", "1", "--seed", "1",
                       "--extract-only"])
    assert len(calls) == 1


def test_cli_where_selects_via_the_existing_tag_index(tmp_path, stub_claude, monkeypatch):
    # a and b were tagged in a prior pass; c never was. --where matches the index,
    # so only 'a' (farmed) is re-tagged; the untagged 'c' drops out of the selection;
    # b's existing row survives even though --no-resume forces the re-tag.
    run = _make_run_with(tmp_path, ["a", "b", "c"])
    utils.append_jsonl({"record_id": "a", "taxa_category": "farmed"},
                       pipeline.category_records_path(run))
    utils.append_jsonl({"record_id": "b", "taxa_category": "wild"},
                       pipeline.category_records_path(run))
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    calls = stub_claude([GOOD_JSON])

    holistic_dad.main(["--input", str(run), "--where", "taxa_category=farmed",
                       "--extract-only", "--no-resume"])

    assert len(calls) == 1
    assert "Dilemma a" in calls[0]["user_message"]
    index = {r["record_id"]: r for r in utils.load_jsonl(pipeline.category_records_path(run))}
    assert set(index) == {"a", "b"}              # b's prior row preserved
    assert index["a"]["taxa_category"] == "farmed"


def test_cli_where_without_an_index_fails_loudly(tmp_path, monkeypatch):
    # --where matches tag-index rows; with no index it can only ever select nothing,
    # so fail with a build-the-index hint instead of silently tagging zero records.
    run = _make_run(tmp_path)
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="tag index"):
        holistic_dad.main(["--input", str(run), "--extract-only",
                           "--where", "taxa_category=farmed"])


def test_cli_malformed_where_fails_loudly(tmp_path, monkeypatch):
    run = _make_run(tmp_path)
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="--where"):
        holistic_dad.main(["--input", str(run), "--extract-only",
                           "--where", "taxa_category"])


def test_cli_negative_limit_fails_loudly(tmp_path, monkeypatch, capsys):
    # A typo like --limit -1 must error at argparse, not silently tag 0 records.
    run = _make_run(tmp_path)
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    with pytest.raises(SystemExit):
        holistic_dad.main(["--input", str(run), "--extract-only", "--limit", "-1"])
    assert "non-negative" in capsys.readouterr().err


def test_cli_selection_subsets_tagging_but_analysis_reads_the_whole_index(
        tmp_path, stub_claude, monkeypatch):
    # A full (non --extract-only) run with --limit: only the subset is tagged this
    # invocation, but the report analyzes every row in the index, old and new.
    from evals.holistic import bundle as bundle_mod
    from shared import api

    run = _make_run_with(tmp_path, ["a", "b"])
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
    # Bootstrap the bundle the CLI call below will resume (same fields/model/prompt
    # fingerprint), seeded with a 'z-prior' record from an earlier tagging pass.
    # The CLI resolves the model to the config default before fingerprinting, so the
    # bootstrap must key off that same resolved model (else it lands in a sibling bundle).
    fields = holistic_dad._load_fields(holistic_dad.DEFAULT_AXES)
    extract_template = holistic_dad._read_if_exists(holistic_dad.DEFAULT_EXTRACT_PROMPT)
    inputs = pipeline.resolve_inputs(run)
    paths = bundle_mod.resolve_bundle(inputs.holistic_root, fields,
                                      model=api.resolve_model(None),
                                      extract_template=extract_template, create=True)
    utils.append_jsonl({"record_id": "z-prior", "taxa_category": "wild"}, paths.index_path)
    calls = stub_claude([GOOD_JSON])

    report = holistic_dad.main(["--input", str(run), "--limit", "1", "--no-synthesize"])

    assert len(calls) == 1                       # only 'a' tagged
    assert report["records"] == 2                # analysis saw z-prior + a
    dist = report["stats"]["analyses"]["distribution"]["taxa_category"]
    assert dist == {"farmed": 1, "wild": 1}


def test_cli_judge_version_selects_between_multiple_verdict_dirs(tmp_path, monkeypatch):
    run = _make_run(tmp_path)
    utils.append_jsonl({"record_id": "a", "taxa_category": "wild"},
                       pipeline.category_records_path(run))
    for version in ("dad-v4.9", "dad-v4.10"):
        vdir = run / "final" / "judge" / version
        vdir.mkdir(parents=True)
        utils.append_jsonl({"record_id": "a", "which": version}, vdir / "verdicts.jsonl")
    monkeypatch.setattr("shared.api.init", lambda *a, **k: None)

    report = holistic_dad.main([
        "--input", str(run), "--analyze-only", "--no-synthesize",
        "--judge-version", "dad-v4.9",
    ])

    assert report["inputs_present"] == ["tags", "verdicts", "texts"]


def test_summary_lines_render_bad_bridge_axes():
    report = {
        "run_id": "r", "records": 10, "inputs_present": ["tags", "clusters"],
        "stats": {"analyses": {
            "cluster_bridge": {
                "taxa_category": {"n": 10, "cramers_v": 0.05,
                                  "verdict": "BAD", "note": "..."},
                "direction": {"n": 10, "cramers_v": 0.8,
                              "verdict": "GOOD", "note": "..."}}},
                  "skipped": {}}}
    text = "\n".join(holistic_dad.summary_lines(report))
    assert "taxa_category" in text and "[BAD]" in text and "0.05" in text
    assert "direction" not in text              # semantically-realized axes aren't listed
