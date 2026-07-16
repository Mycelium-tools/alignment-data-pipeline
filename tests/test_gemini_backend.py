"""Tests for the gemini backend in shared/api.py (offline, no Vertex calls).

The real Vertex seam (_call_gemini_with_retry) is blocked by the autouse
_api_guard in conftest; these tests either exercise pure helpers or stub that
seam, exactly as the CLAUDE.md testing rules require for a money path.
"""

import json

import pytest

from shared import api


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
