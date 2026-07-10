"""Provider dispatch for eval-lane model calls (shared/providers.py): gemini-*
models route to the Gemini API (AI Studio or Vertex), everything else — including
the None config-default — routes to shared.api.call_claude. Moved out of
evals/judge.py so the holistic extraction judge and synthesis share it; future
providers add one function + one prefix here. Fully offline: the Anthropic path is
stubbed at call_claude, the Gemini path at the HTTP client."""

from types import SimpleNamespace

from shared import providers


# ---------------------------------------------------------------- routing

def test_none_and_claude_models_route_to_call_claude(stub_claude):
    calls = stub_claude(["from-claude", "from-claude-2"])
    assert providers.call_model("hi", "sys", None) == "from-claude"
    assert providers.call_model("hi", "sys", "claude-x") == "from-claude-2"
    assert [c["model"] for c in calls] == [None, "claude-x"]
    assert calls[0]["cache_system"] is True     # repeated system prompts cache


def test_gemini_models_route_to_the_gemini_client(monkeypatch):
    seen = []
    monkeypatch.setattr(providers, "_call_gemini",
                        lambda *a: seen.append(a) or "from-gemini")
    out = providers.call_model("hi", "sys", "gemini-2.5-flash",
                               temperature=0.5, max_tokens=99)
    assert out == "from-gemini"
    assert seen == [("hi", "sys", "gemini-2.5-flash", 0.5, 99)]


def test_judge_still_exposes_call_model():
    from evals import judge
    assert judge.call_model is providers.call_model


# ---------------------------------------------------------------- gemini body

def _fake_post(captured):
    def post(url, headers=None, json=None, timeout=None):
        captured.update({"url": url, "headers": headers, "body": json})
        return SimpleNamespace(
            status_code=200, raise_for_status=lambda: None,
            json=lambda: {"candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                          "usageMetadata": {"promptTokenCount": 1,
                                            "candidatesTokenCount": 1}})
    return post


def test_gemini_body_omits_an_empty_system_instruction(monkeypatch):
    # synthesis calls with no system prompt; Gemini must not get an empty part
    captured: dict = {}
    monkeypatch.setattr(providers.httpx, "post", _fake_post(captured))
    monkeypatch.setattr(providers.api, "_log_usage", lambda *a, **k: None)
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)

    assert providers._call_gemini("hi", "", "gemini-x", 0.0, 10) == "ok"
    assert "systemInstruction" not in captured["body"]

    providers._call_gemini("hi", "sys", "gemini-x", 0.0, 10)
    assert captured["body"]["systemInstruction"] == {"parts": [{"text": "sys"}]}


# ---------------------------------------------------------------- endpoint selection

def test_vertex_project_takes_precedence_and_uses_a_bearer_token(monkeypatch):
    monkeypatch.setenv("VERTEX_PROJECT", "proj-1")
    monkeypatch.setenv("GEMINI_API_KEY", "unused-when-vertex-set")
    monkeypatch.setattr(providers, "_vertex_token", lambda: "tok")
    url, headers = providers._gemini_endpoint("gemini-x")
    assert "aiplatform.googleapis.com" in url and "proj-1" in url
    assert headers == {"Authorization": "Bearer tok"}


def test_ai_studio_key_is_used_without_vertex(monkeypatch):
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "k1")
    url, headers = providers._gemini_endpoint("gemini-x")
    assert "generativelanguage.googleapis.com" in url
    assert headers == {"x-goog-api-key": "k1"}


def test_missing_gemini_credentials_fail_with_a_clear_message(monkeypatch):
    import pytest
    for var in ("VERTEX_PROJECT", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        providers._gemini_endpoint("gemini-x")
