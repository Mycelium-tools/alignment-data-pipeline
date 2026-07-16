"""Tests for the gemini backend in shared/api.py (offline, no Vertex calls).

The real Vertex seam (_call_gemini_with_retry) is blocked by the autouse
_api_guard in conftest. Two layers of coverage, per the CLAUDE.md money-path
rules: the call_claude-level tests stub that seam; the TestRunGeminiQuery /
TestGeminiRetryPredicate classes go one layer deeper and drive the REAL parse
(_run_gemini_query / _gemini_text) and retry classification against the true
external boundary — a stubbed client.models.generate_content and constructed
google.genai errors — so a wrong attribute name, an SDK schema change, or a
mis-scoped retry predicate is caught, not stubbed away.
"""

import json
from types import SimpleNamespace as NS

import pytest

from shared import api


# --- fake Vertex response builders (shape of google.genai's GenerateContentResponse) ---

class _Resp:
    """Minimal stand-in for a GenerateContentResponse. `.text` raises when
    text_raises=True, mimicking a blocked/textless candidate (the real property
    raises rather than returning None in that case)."""

    def __init__(self, text=None, text_raises=False, candidates=None, usage=None):
        self._text = text
        self._raises = text_raises
        self.candidates = candidates
        self.usage_metadata = usage

    @property
    def text(self):
        if self._raises:
            raise ValueError("no text: candidate was blocked")
        return self._text


def _cand(finish=None, parts_text=()):
    parts = [NS(text=t) for t in parts_text]
    return NS(
        finish_reason=(NS(name=finish) if finish else None),
        content=NS(parts=parts),
    )


def _usage(prompt=0, candidates=0, thoughts=0):
    return NS(
        prompt_token_count=prompt,
        candidates_token_count=candidates,
        thoughts_token_count=thoughts,
    )


def test_map_gemini_finish_normalizes_to_stop_reason_vocab():
    class FR:
        def __init__(self, name):
            self.name = name

    assert api._map_gemini_finish(FR("STOP")) == "end_turn"
    assert api._map_gemini_finish(None) == "end_turn"          # missing -> treat as clean
    assert api._map_gemini_finish(FR("MAX_TOKENS")) == "MAX_TOKENS"  # passes through -> trips guard
    assert api._map_gemini_finish(FR("SAFETY")) == "SAFETY"


def test_gemini_pricing_present_and_priced_without_warning(monkeypatch, tmp_path, capsys):
    """gemini-2.5-flash must be in _PRICING so cost logs aren't estimated at
    Sonnet rates (the mispricing that overreported a Haiku run 3x)."""
    assert "gemini-2.5-flash" in api._PRICING
    log = tmp_path / "cost.jsonl"
    monkeypatch.setattr(api, "_cost_log_path", log)
    monkeypatch.setattr(api, "_backend", "gemini")
    api._log_usage("gemini-2.5-flash", 1_000_000, 1_000_000, stage="layer3")
    rec = json.loads(log.read_text().strip())
    # 1M in @ $0.30 + 1M out @ $2.50 = $2.80
    assert rec["cost_usd"] == pytest.approx(2.80)
    assert "not in shared/api.py _PRICING" not in capsys.readouterr().err


def test_init_gemini_requires_project(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "backend: gemini\nmodel: gemini-2.5-flash\n"
        "outputs:\n  cost_log: " + str(tmp_path / "cost.jsonl") + "\n",
        encoding="utf-8",
    )
    with pytest.raises(KeyError, match="gemini.project"):
        api.init(str(cfg))

    cfg.write_text(
        "backend: gemini\nmodel: gemini-2.5-flash\n"
        "gemini:\n  project: my-proj\n  location: global\n"
        "outputs:\n  cost_log: " + str(tmp_path / "cost.jsonl") + "\n",
        encoding="utf-8",
    )
    api.init(str(cfg))  # project present -> no raise
    assert api._backend == "gemini"


def _make_gemini_call(monkeypatch, tmp_path, reply):
    """Wire call_claude onto the gemini backend with the Vertex seam stubbed to
    return `reply` (text, in_tok, out_tok, cost, stop_reason)."""
    monkeypatch.setattr(api, "_backend", "gemini")
    monkeypatch.setattr(api, "_config", {"model": "gemini-2.5-flash", "temperature": 1.0})
    monkeypatch.setattr(api, "_cost_log_path", tmp_path / "cost.jsonl")
    calls = {}

    def fake(**kwargs):
        calls.update(kwargs)
        return reply

    monkeypatch.setattr(api, "_call_gemini_with_retry", fake)
    return calls


def test_call_claude_gemini_returns_text_and_logs(monkeypatch, tmp_path):
    calls = _make_gemini_call(monkeypatch, tmp_path, ("hello", 10, 5, None, "end_turn"))
    out = api.call_claude("hi", system_prompt="SYS", stage="layer3", item_id="matrix_000000")
    assert out == "hello"
    # the seam saw the resolved model / system / limits
    assert calls["model"] == "gemini-2.5-flash"
    assert calls["system"] == "SYS"
    assert calls["max_tokens"] and calls["temperature"] == 1.0
    rec = json.loads((tmp_path / "cost.jsonl").read_text().strip())
    assert rec["stage"] == "layer3" and rec["item_id"] == "matrix_000000"
    assert rec["input_tokens"] == 10 and rec["output_tokens"] == 5


def test_call_claude_gemini_returns_stop_reason_for_truncation(monkeypatch, tmp_path, capsys):
    _make_gemini_call(monkeypatch, tmp_path, ("partial", 10, 4000, None, "MAX_TOKENS"))
    text, stop = api.call_claude("hi", return_stop_reason=True)
    assert (text, stop) == ("partial", "MAX_TOKENS")
    # a non-clean stop reason warns so it isn't silently written into a corpus
    assert "truncated or refused" in capsys.readouterr().err


class TestRunGeminiQuery:
    """Exercise the gemini money path (_run_gemini_query -> _gemini_text) at the
    true external boundary — a stubbed client.models.generate_content returning
    a fake response — so a wrong usage/candidate attribute name or an SDK schema
    change is caught. The inner is un-retried, so no tenacity backoff here."""

    @staticmethod
    def _install(monkeypatch, response):
        pytest.importorskip("google.genai")
        calls = {}

        class _Models:
            def generate_content(self, **kw):
                calls.update(kw)
                return response

        class _Client:
            models = _Models()

        monkeypatch.setattr(api, "_get_gemini_client", lambda: _Client())
        return calls

    def test_happy_path_parses_text_tokens_stop_reason(self, monkeypatch):
        resp = _Resp(text="draft answer", candidates=[_cand(finish="STOP")],
                     usage=_usage(prompt=120, candidates=34))
        calls = self._install(monkeypatch, resp)
        text, in_tok, out_tok, cost, stop = api._run_gemini_query(
            "gemini-2.5-flash", "sys", "hi", 1024, 1.0)
        assert text == "draft answer"
        assert (in_tok, out_tok, cost, stop) == (120, 34, None, "end_turn")
        # thinking is disabled at the boundary (user-facing-reasoning-only rule)
        assert calls["model"] == "gemini-2.5-flash"
        assert calls["config"].thinking_config.thinking_budget == 0

    def test_thoughts_tokens_added_to_output(self, monkeypatch):
        resp = _Resp(text="x", candidates=[_cand(finish="STOP")],
                     usage=_usage(prompt=1, candidates=10, thoughts=5))
        self._install(monkeypatch, resp)
        _, _, out_tok, _, _ = api._run_gemini_query("gemini-2.5-flash", "s", "h", 10, 1.0)
        assert out_tok == 15  # candidate + thoughts tokens both billed as output

    def test_blocked_candidate_falls_back_to_parts(self, monkeypatch):
        # response.text raises (blocked); text is recovered from candidate parts,
        # and the non-STOP finish reason passes through to trip the truncation guard
        resp = _Resp(text_raises=True,
                     candidates=[_cand(finish="SAFETY", parts_text=("part1 ", "part2"))],
                     usage=_usage(prompt=3, candidates=2))
        self._install(monkeypatch, resp)
        text, _, _, _, stop = api._run_gemini_query("gemini-2.5-flash", "s", "h", 10, 1.0)
        assert text == "part1 part2"
        assert stop == "SAFETY"

    def test_no_text_anywhere_returns_empty_string(self, monkeypatch):
        resp = _Resp(text_raises=True, candidates=[], usage=_usage())
        self._install(monkeypatch, resp)
        text, in_tok, out_tok, _, stop = api._run_gemini_query("gemini-2.5-flash", "s", "h", 10, 1.0)
        assert text == "" and (in_tok, out_tok) == (0, 0) and stop is None

    def test_missing_usage_metadata_defaults_tokens_to_zero(self, monkeypatch):
        resp = _Resp(text="ok", candidates=[_cand(finish="STOP")], usage=None)
        self._install(monkeypatch, resp)
        _, in_tok, out_tok, _, _ = api._run_gemini_query("gemini-2.5-flash", "s", "h", 10, 1.0)
        assert (in_tok, out_tok) == (0, 0)


class TestGeminiRetryPredicate:
    """Drive the real _is_retryable_gemini classification and prove a
    non-retryable ClientError surfaces after exactly one attempt through the
    REAL tenacity-wrapped _call_gemini_with_retry — mirroring
    TestRetryPredicate.test_bad_request_is_not_retried for the api backend.
    Safe offline: a non-retryable error never sleeps."""

    def test_server_error_is_retryable(self):
        ge = pytest.importorskip("google.genai.errors")
        assert api._is_retryable_gemini(ge.ServerError(503, {"error": {"message": "boom"}}, None)) is True

    def test_rate_limit_is_retryable(self):
        ge = pytest.importorskip("google.genai.errors")
        assert api._is_retryable_gemini(ge.ClientError(429, {"error": {"message": "slow down"}}, None)) is True

    def test_bad_request_is_not_retryable(self):
        ge = pytest.importorskip("google.genai.errors")
        assert api._is_retryable_gemini(ge.ClientError(400, {"error": {"message": "bad"}}, None)) is False

    def test_connection_error_is_retryable(self):
        assert api._is_retryable_gemini(ConnectionError("reset")) is True

    def test_unrelated_error_is_not_retryable(self):
        assert api._is_retryable_gemini(ValueError("parse")) is False

    def test_bad_request_surfaces_after_one_attempt(self, monkeypatch):
        ge = pytest.importorskip("google.genai.errors")
        attempts = []

        def boom(*args, **kwargs):
            attempts.append(1)
            raise ge.ClientError(400, {"error": {"message": "bad request"}}, None)

        # the autouse guard replaces _call_gemini_with_retry; reload to get the real one
        import importlib
        real = importlib.reload(api)._call_gemini_with_retry
        monkeypatch.setattr(api, "_run_gemini_query", boom)
        with pytest.raises(ge.ClientError):
            real("gemini-2.5-flash", "sys", "hi", 10, 1.0)
        assert len(attempts) == 1  # non-retryable -> exactly one attempt, no backoff
