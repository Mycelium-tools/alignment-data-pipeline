"""Viewer prompt reconstruction: the system/user split is honored.

rendering.py is streamlit-free, so _format_split is testable directly. It must
mirror shared.utils.load_split_prompt: cut on the ===USER=== marker, or treat a
marker-less template as user-only (so pre-split run snapshots reconstruct as
they actually ran)."""

from viewer import rendering


def _mk(text):
    tpl = rendering.Template("t.txt", text, "snapshot")
    r = rendering.RenderedPrompt(stage="x", is_llm_call=True)
    return tpl, r


def test_format_split_cuts_on_marker_and_formats_each_half():
    tpl, r = _mk("SYS {a}\n===USER===\nUSR {b}")
    system, user = rendering._format_split(tpl, {"a": "A", "b": "B"}, r)
    assert system == "SYS A"
    assert user == "USR B"


def test_format_split_no_marker_is_user_only():
    tpl, r = _mk("just the user prompt {a}")
    system, user = rendering._format_split(tpl, {"a": "A"}, r)
    assert system is None
    assert user == "just the user prompt A"


def test_format_split_missing_template_returns_none():
    tpl = rendering.Template("t.txt", None, "missing")
    r = rendering.RenderedPrompt(stage="x", is_llm_call=True)
    assert rendering._format_split(tpl, {}, r) == (None, None)
    assert r.warnings  # unavailable-template warning recorded
