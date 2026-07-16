"""Tests for the judge-vs-generation drift lane (fully offline; the judge tag call
is stubbed).

Annotation alignment (welfare split + step-1 lift) lives in
evals/holistic/pipeline.py and runs at input loading; the multi-axis set overlap
lives in the drift analyzer; evals/drift_report.py is a thin renderer over both.
"""

from evals import drift_report
from evals.holistic import analyzers as analyzers_mod
from evals.holistic import fields as F
from evals.holistic import pipeline
from shared import utils


_JUDGE = ('{"visibility": "Explicit", "user_attitude": "Concerned", '
          '"conflict": "Divergent", "direction": "Mixed", "user_stakes": "Medium", '
          '"leverage": "Individual", "welfare_severity": "Severe", '
          '"welfare_scope": "Group", "taxa_category": "farmed", "systemic_ai": false, '
          '"domain": ["Food & Cooking"]}')


def _make_complete_run(tmp_path):
    run = tmp_path / "2026-01-01_00-00_drift-test"
    (run / "final").mkdir(parents=True)
    (run / "step3").mkdir()
    (run / "step1").mkdir()
    msgs = [{"role": "user", "content": "Switch to caged hens?"},
            {"role": "assistant", "content": "Weighing it..."}]
    utils.append_jsonl({"record_id": "r1", "messages": msgs},
                       run / "final" / "dad_corpus.jsonl")
    utils.append_jsonl({"record_id": "r1", "prompt_id": "AW-0001",
                        "annotation": {"visibility": "Explicit",
                                       "user_attitude": "Concerned",
                                       "conflict": "Divergent", "direction": "Mixed",
                                       "user_stakes": "Medium", "leverage": "Individual",
                                       "welfare_magnitude": "Severe x Group",
                                       "domain": ["Food & Cooking"]}},
                       run / "step3" / "rewrites.jsonl")
    utils.append_jsonl({"prompt_id": "AW-0001", "taxa_category": "farmed animals",
                        "systemic_ai": False}, run / "step1" / "dilemmas.jsonl")
    return run


class TestParseWelfareMagnitude:
    def test_splits_severity_and_scope(self):
        assert pipeline.parse_welfare_magnitude("Severe x Population") == ("Severe", "Population")
        assert pipeline.parse_welfare_magnitude("Mild x Individual") == ("Mild", "Individual")

    def test_tolerates_extra_spacing_and_case(self):
        assert pipeline.parse_welfare_magnitude("moderate   x   group") == ("Moderate", "Group")

    def test_returns_none_on_malformed(self):
        assert pipeline.parse_welfare_magnitude("garbage") == (None, None)
        assert pipeline.parse_welfare_magnitude("") == (None, None)
        assert pipeline.parse_welfare_magnitude(None) == (None, None)
        assert pipeline.parse_welfare_magnitude("Severe / Population") == (None, None)


class TestAugmentAnnotations:
    def test_splits_welfare_and_lifts_dilemma_axes(self):
        base = {"r1": {"visibility": "Explicit", "welfare_magnitude": "Severe x Group"}}
        step3 = [{"record_id": "r1", "prompt_id": "AW-0001"}]
        dilemmas = [{"prompt_id": "AW-0001", "taxa_category": "farmed animals",
                     "systemic_ai": False}]
        out = pipeline.augment_annotations(base, step3, dilemmas)
        assert out["r1"]["welfare_severity"] == "Severe"
        assert out["r1"]["welfare_scope"] == "Group"
        assert out["r1"]["taxa_category"] == "farmed"          # normalized
        assert out["r1"]["systemic_ai"] is False
        assert out["r1"]["visibility"] == "Explicit"           # preserved
        assert base["r1"] == {"visibility": "Explicit",        # input not mutated
                              "welfare_magnitude": "Severe x Group"}

    def test_keeps_record_when_welfare_malformed_or_no_dilemma_match(self):
        base = {"r2": {"welfare_magnitude": "garbage"}}
        out = pipeline.augment_annotations(base, [], [])
        assert "welfare_severity" not in out["r2"]             # malformed → not added
        assert out["r2"]["welfare_magnitude"] == "garbage"     # nothing dropped

    def test_resolve_inputs_aligns_annotations(self, tmp_path):
        run = _make_complete_run(tmp_path)
        inputs = pipeline.resolve_inputs(run)
        ann = inputs.annotations["r1"]
        assert ann["welfare_severity"] == "Severe"             # split applied on load
        assert ann["taxa_category"] == "farmed"                # step-1 lift applied


class TestMultiAxisDrift:
    def test_set_overlap_is_order_insensitive_and_scores_partial(self):
        reg = F.registry_from_data(
            {"fields": [{"name": "domain", "kind": "multi", "values": ["A", "B", "C"]}]})
        ann = {"r1": {"domain": ["A", "B"]}, "r2": {"domain": ["A"]}}
        recs = [{"record_id": "r1", "domain": ["B", "A"]},   # same set, diff order → exact
                {"record_id": "r2", "domain": ["A", "C"]}]    # overlap 1/2 → jaccard 0.5
        ctx = analyzers_mod.AnalysisContext(records=recs, fields=reg, annotations=ann)
        out = analyzers_mod.run_analyzers(
            ctx, analyzers_mod.select(analyzers_mod.default_analyzers(), ["drift"]))
        m = out["analyses"]["drift"]["domain"]
        assert m["n"] == 2
        assert m["agreement"] == 0.5                          # exact-set rate
        assert m["mean_jaccard"] == round((1.0 + 0.5) / 2, 3)
        assert m["disagreements"] == [
            {"intended": "A", "realized": "A, C", "count": 1}]


class TestRenderReport:
    def test_lists_each_axis_agreement_and_headline(self):
        drift = {
            "visibility": {"n": 5, "agreement": 0.8,
                           "disagreements": [{"intended": "Explicit",
                                              "realized": "Implicit", "count": 1}],
                           "verdict": "OK"},
            "welfare_severity": {"n": 5, "agreement": 0.6,
                                 "disagreements": [], "verdict": "BAD"},
            "domain": {"n": 5, "agreement": 0.4, "mean_jaccard": 0.7,
                       "disagreements": [], "verdict": "OK"},
        }
        md, html = drift_report.render_report(drift, "length-dice-smoke")
        assert "length-dice-smoke" in md
        assert "visibility" in md and "welfare_severity" in md
        assert "80%" in md and "60%" in md                     # agreement rendered as pct
        assert "Explicit" in md and "Implicit" in md           # confusion pair shown
        assert "0.70" in md                                    # multi axis jaccard shown
        # worst axis first: domain (0.40) before welfare_severity (0.60) before visibility
        assert md.index("domain") < md.index("welfare_severity") < md.index("visibility")
        assert "<table" in html and "welfare_severity" in html

    def test_handles_empty_drift(self):
        md, html = drift_report.render_report({}, "empty")
        assert "empty" in md
        assert "<table" in html


class TestMainCLI:
    def test_writes_report_and_computes_drift(self, tmp_path, stub_claude, monkeypatch):
        monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
        stub_claude([_JUDGE])                                   # one judge tag for r1
        run = _make_complete_run(tmp_path)
        report = drift_report.main(["--input", str(run)])
        assert (run / "drift_report.md").exists()
        assert (run / "drift_report.html").exists()
        drift = report["stats"]["analyses"]["drift"]
        # welfare split + lifted axes are compared and agree (annotation == judge tag)
        assert drift["welfare_severity"]["agreement"] == 1.0
        assert drift["taxa_category"]["agreement"] == 1.0      # both normalized to "farmed"
        assert drift["visibility"]["agreement"] == 1.0
        assert drift["domain"]["mean_jaccard"] == 1.0          # multi axis, set-compared
        assert "welfare_severity" in (run / "drift_report.md").read_text()

    def test_reuses_existing_bundle_without_new_api_calls(self, tmp_path, stub_claude,
                                                          monkeypatch):
        # The whole point of the single-pass design: a corpus already tagged with
        # the default axes (e.g. from the viewer) is not re-tagged by drift.
        monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
        calls = stub_claude([_JUDGE])
        run = _make_complete_run(tmp_path)
        drift_report.main(["--input", str(run)])
        assert len(calls) == 1                                  # tagged once
        drift_report.main(["--input", str(run)])                # second report pass
        assert len(calls) == 1                                  # zero new API calls