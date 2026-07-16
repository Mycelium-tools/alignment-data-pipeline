"""Editable-without-Python surfaces: the JSON schema (fields) loads from a YAML file,
the extraction prompt and the holistic-synthesis prompt load from editable templates.
Edit a file, rerun, see what changes."""

from evals.holistic import extract, fields as F, synthesize, pipeline
from shared import utils
import pytest

AXES_YAML = """
fields:
  - name: direction
    kind: single
    derived_from: response
    prompt_hint: which way the response corrected
    values: [Under-weighting, Over-weighting, Mixed]
  - name: language
    kind: free
    derived_from: meta
"""

MESSAGES = [{"role": "user", "content": "Switch to caged hens?"},
            {"role": "assistant", "content": "Weighing it..."}]


# ---------------------------------------------------------------- fields from YAML

def test_load_fields_from_yaml_builds_the_registry(tmp_path):
    p = tmp_path / "dad_axes.yaml"
    p.write_text(AXES_YAML)
    reg = F.load_fields(p)
    assert reg.names() == ["direction", "language"]
    assert reg.get("direction").values == ("Under-weighting", "Over-weighting", "Mixed")
    assert reg.get("direction").derived_from == "response"
    assert reg.get("language").kind == "free"


def test_load_fields_rejects_missing_required_name(tmp_path):
    p = tmp_path / "dad_axes.yaml"
    p.write_text("fields:\n  - kind: single\n    values: [x]\n")

    with pytest.raises(ValueError, match="fields\\[0\\] missing required key 'name'"):
        F.load_fields(p)


def test_load_fields_rejects_unknown_kind_with_context(tmp_path):
    p = tmp_path / "dad_axes.yaml"
    p.write_text("fields:\n  - name: direction\n    kind: sideways\n")

    with pytest.raises(ValueError, match="fields\\[0\\].*unknown kind 'sideways'"):
        F.load_fields(p)


def test_load_fields_parses_per_field_target_quotas(tmp_path):
    p = tmp_path / "dad_axes.yaml"
    p.write_text(
        "fields:\n"
        "  - name: visibility\n    kind: single\n    values: [Explicit, Implicit, Hidden]\n"
        "    target:\n      min_share: {Hidden: 0.2}\n"
        "  - name: language\n    kind: free\n")
    reg = F.load_fields(p)
    assert reg.get("visibility").target == {"min_share": {"Hidden": 0.2}}
    assert reg.get("language").target == {}          # no target = empty dict


def test_load_analysis_config_reads_the_analysis_block(tmp_path):
    p = tmp_path / "dad_axes.yaml"
    p.write_text(
        "fields: []\n"
        "analysis:\n"
        "  analyzers: [distribution, coverage_vs_target]\n"
        "  params:\n    important_pairs: [[user_attitude, direction]]\n")
    cfg = F.load_analysis_config(p)
    assert cfg["analyzers"] == ["distribution", "coverage_vs_target"]
    assert cfg["params"]["important_pairs"] == [["user_attitude", "direction"]]


def test_load_analysis_config_defaults_to_empty_when_absent(tmp_path):
    p = tmp_path / "dad_axes.yaml"
    p.write_text("fields: []\n")
    assert F.load_analysis_config(p) == {}


def test_load_analysis_config_rejects_a_non_mapping_block(tmp_path):
    p = tmp_path / "dad_axes.yaml"
    p.write_text("fields: []\nanalysis:\n  - distribution\n")
    with pytest.raises(ValueError, match="analysis"):
        F.load_analysis_config(p)


def test_load_fields_rejects_a_target_value_outside_the_vocabulary(tmp_path):
    p = tmp_path / "dad_axes.yaml"
    p.write_text("fields:\n  - name: visibility\n    kind: single\n"
                 "    values: [Explicit]\n    target: {min_share: {Hidden: 0.2}}\n")
    with pytest.raises(ValueError, match="Hidden"):
        F.load_fields(p)


def test_load_fields_rejects_a_malformed_band_each(tmp_path):
    p = tmp_path / "dad_axes.yaml"
    p.write_text("fields:\n  - name: direction\n    kind: single\n"
                 "    values: [A, B]\n    target: {band_each: [0.25]}\n")
    with pytest.raises(ValueError, match="band_each"):
        F.load_fields(p)


def test_editing_the_yaml_changes_the_extraction_prompt(tmp_path):
    p = tmp_path / "dad_axes.yaml"
    p.write_text(AXES_YAML)
    prompt = extract.build_system_prompt(F.load_fields(p))
    assert "direction" in prompt and "Over-weighting" in prompt
    assert "taxa_category" not in prompt          # not in this edited schema


# ---------------------------------------------------------------- editable prompt template

def test_build_system_prompt_uses_an_editable_template_with_tokens():
    reg = F.default_fields()
    tmpl = "MY PREAMBLE\n\n{{FIELDS}}\n\nReturn keys: {{KEYS}}\nMY FOOTER"
    out = extract.build_system_prompt(reg, template=tmpl)
    assert out.startswith("MY PREAMBLE")
    assert out.rstrip().endswith("MY FOOTER")
    assert "taxa_category" in out                 # field block injected
    assert '"taxa_category"' in out               # keys token expanded


def test_extraction_prompt_template_requires_both_tokens():
    with pytest.raises(ValueError, match=r"\{\{FIELDS\}\}"):
        extract.build_system_prompt(F.default_fields(), template="keys {{KEYS}}")
    with pytest.raises(ValueError, match=r"\{\{KEYS\}\}"):
        extract.build_system_prompt(F.default_fields(), template="fields {{FIELDS}}")


# ---------------------------------------------------------------- synthesis prompt

def test_synthesize_runs_the_editable_holistic_prompt_over_the_stats(stub_claude):
    calls = stub_claude(['{"verdict": "Skewed but usable.", '
                         '"sections": [{"title": "Categorical balance & coverage", '
                         '"body": "Domain is skewed."}], '
                         '"top_issues": [{"axis": "domain", "kind": "balance", "severity": "high"}]}'])
    out = synthesize.synthesize({"analyses": {"distribution": {}}},
                                template="Assess this run:\n{{STATS}}")
    assert out["verdict"] == "Skewed but usable."
    assert out["sections"][0]["title"] == "Categorical balance & coverage"
    assert out["sections"][0]["body"] == "Domain is skewed."
    assert out["top_issues"][0]["axis"] == "domain"
    assert out["errors"] == []
    assert "{{STATS}}" not in calls[0]["user_message"]   # token was expanded
    assert "distribution" in calls[0]["user_message"]    # stats were injected


def test_synthesis_prompt_template_requires_stats_token():
    with pytest.raises(ValueError, match=r"\{\{STATS\}\}"):
        synthesize.synthesize({"analyses": {}}, template="No stats token")


def test_synthesize_marks_unparseable_output_explicitly(stub_claude):
    stub_claude(["not json at all"])
    out = synthesize.synthesize({"analyses": {}}, template="Stats:\n{{STATS}}")
    assert out["errors"] == ["unparseable synthesis model output"]
    assert out["verdict"] == ""
    assert out["sections"] == []
    assert out["top_issues"] == []


def test_synthesize_marks_wrong_shape_explicitly(stub_claude):
    # sections must be a list of {title, body}; top_issues must be a list
    stub_claude(['{"verdict": "x", "sections": [{"title": "t"}], "top_issues": {}}'])
    out = synthesize.synthesize({"analyses": {}}, template="Stats:\n{{STATS}}")
    assert any("sections" in e for e in out["errors"])
    assert any("top_issues" in e for e in out["errors"])


# ---------------------------------------------------------------- end to end with synthesis

def test_run_includes_synthesis_when_a_template_is_supplied(tmp_path, stub_claude):
    run = tmp_path / "2026-01-01_00-00_test"
    (run / "final").mkdir(parents=True)
    utils.append_jsonl({"record_id": "a", "messages": MESSAGES},
                       run / "final" / "dad_corpus.jsonl")
    # First call tags; second call synthesizes.
    stub_claude(['{"language": "en", "taxa_category": "farmed", "posture_class": "NO_RAISE"}',
                 '{"verdict": "Looks fine.", "sections": [], "top_issues": []}'])
    report = pipeline.run(run, synthesis_template="S:\n{{STATS}}")
    assert report["synthesis"]["verdict"] == "Looks fine."


def test_synthesize_routes_gemini_models_to_the_provider_dispatch(monkeypatch):
    monkeypatch.setattr(
        "shared.providers._call_gemini",
        lambda um, sp, model, t, mt: '{"verdict": "fine", "sections": [], "top_issues": []}')
    out = synthesize.synthesize({"analyses": {}}, template="Stats:\n{{STATS}}",
                                model="gemini-2.5-flash")
    assert out["errors"] == [] and out["verdict"] == "fine"


def test_repo_dad_axes_selects_the_structural_analyzer():
    """Guard: the response-form ``structural`` analyzer must stay listed in the real
    evals/dad_axes.yaml ``analysis.analyzers`` selection. The CLI and the viewer's
    Analyze button run ``select(default_analyzers(), analysis.analyzers)``, so an
    analyzer absent from that list is silently dropped even though it is registered —
    exactly how structural was invisible until it was added here. Also asserts the name
    resolves against the registry (``select`` raises on an unknown name)."""
    from evals import holistic_dad
    from evals.holistic import analyzers as A

    cfg = F.load_analysis_config(holistic_dad.DEFAULT_AXES)
    assert "structural" in cfg["analyzers"]
    chosen = A.select(A.default_analyzers(), cfg["analyzers"])
    assert "structural" in chosen.names()
