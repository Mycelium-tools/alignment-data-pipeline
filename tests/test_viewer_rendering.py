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


class TestInlineWordDiff:
    def test_additions_highlighted_and_equal_text_plain(self):
        html = rendering.inline_word_diff_html(
            "Keep the shed clean.", "Keep the shed clean and reduce insect harm.")
        # the unchanged prefix stays plain (outside any span)
        assert html.startswith("Keep the shed ")
        # the added words are wrapped in a highlight span; the prefix is not
        assert "background:rgba" in html
        highlighted = html.split("background:rgba", 1)[1]
        assert "reduce insect harm." in highlighted
        assert "Keep the" not in highlighted

    def test_removed_words_struck_through(self):
        html = rendering.inline_word_diff_html("an obviously wrong claim", "an claim")
        assert "line-through" in html
        struck = html.split("line-through", 1)[1]
        assert "obviously wrong" in struck

    def test_text_is_escaped_and_newlines_become_breaks(self):
        html = rendering.inline_word_diff_html("a <b> start", "a <b> start\n\nnew para")
        assert "&lt;b&gt;" in html and "<b>" not in html.replace("<br>", "")
        assert "<br><br>" in html
