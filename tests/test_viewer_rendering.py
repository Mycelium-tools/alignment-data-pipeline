"""Viewer prompt re-rendering across the curated-types migration: layer 1 is
no longer an LLM call for new runs (but old runs must still re-render), and
the layer-2 template variables changed shape (per-scenario roles, per-type
quota). rendering.py is streamlit-free by design, so it tests like any module."""

from pathlib import Path

from viewer import rendering

REPO_ROOT = Path(__file__).resolve().parent.parent


def _manifest(sdf_cfg):
    return {"manifest_version": 2, "git_commit": None,
            "config": {"sdf": sdf_cfg, "language_distribution": {"en": 1.0}}}


def _snapshot(run_dir, names):
    """Freeze the repo's live sdf templates into a fake run dir, like create_run_dir."""
    snap = run_dir / "inputs" / "prompts"
    snap.mkdir(parents=True)
    for name in names:
        src = REPO_ROOT / "prompts" / "sdf" / name
        (snap / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def test_layer1_curated_run_is_not_an_llm_call(tmp_path):
    r = rendering.render_prompt("sdf", "layer1", tmp_path, _manifest({"scenarios_total": 6}), {})
    assert r.is_llm_call is False
    assert r.user is None


def test_layer1_legacy_run_still_renders(tmp_path):
    # pre-curated runs (document_types_count in config) keep their snapshot's
    # layer1.txt; the viewer must still re-render it
    snap = tmp_path / "inputs" / "prompts"
    snap.mkdir(parents=True)
    (snap / "preamble.txt").write_text("PRE", encoding="utf-8")
    (snap / "layer1.txt").write_text(
        "{preamble} count={count} ai={min_ai_character} latent={latent_count}", encoding="utf-8")
    manifest = _manifest({"document_types_count": 3, "latent_fraction": 0.12})
    r = rendering.render_prompt("sdf", "layer1", tmp_path, manifest, {})
    assert r.is_llm_call is True
    assert r.user == "PRE count=3 ai=1 latent=1"


def test_layer2_new_type_record_formats_cleanly(tmp_path):
    _snapshot(tmp_path, ["preamble.txt", "layer2.txt"])
    doc_type = {"type_id": 0, "type_name": "Personal blog post", "description": "guidance",
                "register": "first-person", "tones": ["neutral", "skeptical"],
                "roles": ["welfare-topic"], "quota": 2,
                "role_allocation": {"welfare-topic": 2}}
    r = rendering.render_prompt("sdf", "layer2", tmp_path,
                                _manifest({"scenarios_total": 6}), {"doc_type": doc_type})
    assert not [w for w in r.warnings if "did not format cleanly" in w]
    assert "Generate 2 scenarios" in r.user
    assert "- welfare-topic: 2" in r.user
    assert "neutral, skeptical" in r.user


def test_layer2_old_type_record_still_formats(tmp_path):
    # records from pre-curated runs have role/tone but no quota/roles/tones;
    # the superset variables must not crash rendering the current template
    _snapshot(tmp_path, ["preamble.txt", "layer2.txt"])
    doc_type = {"type_id": 0, "type_name": "Field report", "description": "d",
                "role": "welfare-topic", "tone": "neutral"}
    manifest = _manifest({"document_types_count": 3, "subtypes_per_type": 2})
    r = rendering.render_prompt("sdf", "layer2", tmp_path, manifest, {"doc_type": doc_type})
    assert not [w for w in r.warnings if "did not format cleanly" in w]
    assert "Generate 2 scenarios" in r.user  # falls back to subtypes_per_type
