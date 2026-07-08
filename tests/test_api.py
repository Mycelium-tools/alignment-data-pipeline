"""Tests for shared/api.py: the safety net itself, call assembly, cost tracking.

Nothing here (or anywhere in the suite) reaches the network: see conftest.py.
"""

import json
import socket
from pathlib import Path

import anthropic
import httpx
import pytest
import pytest_socket

from shared import api, utils

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestSafetyNet:
    def test_unstubbed_call_claude_is_blocked(self, tiny_config_file, tmp_path):
        api.init(str(tiny_config_file), cost_log_path=tmp_path / "cost.jsonl")
        with pytest.raises(AssertionError, match="API call attempted"):
            api.call_claude("hello")

    # pytest-socket warns as well as raises when it blocks name resolution.
    # The warning IS the guard working, so silence exactly it (and nothing
    # else) to keep the suite's warning summary clean.
    @pytest.mark.filterwarnings("ignore:A test tried to use socket.getaddrinfo:UserWarning")
    def test_sockets_are_blocked(self):
        with pytest.raises(pytest_socket.SocketBlockedError):
            socket.create_connection(("127.0.0.1", 9), timeout=0.1)

    def test_init_without_key_fails_loudly(self, tiny_config_file, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        with pytest.raises(KeyError):
            api.init(str(tiny_config_file))


@pytest.fixture
def recorded_api(monkeypatch, tmp_path, fake_message):
    """Exercise call_claude itself: record what reaches the transport layer.

    Replaces _call_with_retry (below call_claude, above the network) and gives
    the module a dummy client + tmp cost log so no init()/anthropic is needed.
    """
    calls = []
    canned = {"message": fake_message(text="response-text")}

    def record(client, model, max_tokens, system, messages, temperature):
        calls.append({"model": model, "max_tokens": max_tokens, "system": system,
                      "messages": messages, "temperature": temperature})
        return canned["message"]

    monkeypatch.setattr(api, "_call_with_retry", record)
    monkeypatch.setattr(api, "_client", object())
    monkeypatch.setattr(api, "_cost_log_path", tmp_path / "cost.jsonl")
    canned["calls"] = calls
    return canned


class TestCallClaude:
    def test_returns_response_text(self, recorded_api):
        assert api.call_claude("hi") == "response-text"

    def test_injection_appended_to_system_prompt(self, recorded_api):
        api.call_claude("hi", system_prompt="sys", injection="inj")
        assert recorded_api["calls"][0]["system"] == "sys\n\ninj"

    def test_injection_without_system_prompt_stands_alone(self, recorded_api):
        api.call_claude("hi", injection="inj")
        assert recorded_api["calls"][0]["system"] == "inj"

    def test_user_message_sent_as_single_user_turn(self, recorded_api):
        api.call_claude("hi")
        assert recorded_api["calls"][0]["messages"] == [{"role": "user", "content": "hi"}]

    def test_model_and_max_tokens_fall_back_to_config(self, recorded_api, monkeypatch):
        monkeypatch.setattr(api, "_config", {"model": "cfg-model", "max_tokens": 123})
        api.call_claude("hi")
        assert recorded_api["calls"][0]["model"] == "cfg-model"
        assert recorded_api["calls"][0]["max_tokens"] == 123

    def test_explicit_model_and_max_tokens_win(self, recorded_api, monkeypatch):
        monkeypatch.setattr(api, "_config", {"model": "cfg-model", "max_tokens": 123})
        api.call_claude("hi", model="override", max_tokens=9)
        assert recorded_api["calls"][0]["model"] == "override"
        assert recorded_api["calls"][0]["max_tokens"] == 9

    def test_temperature_falls_back_to_config(self, recorded_api, monkeypatch):
        monkeypatch.setattr(api, "_config", {"temperature": 0.3})
        api.call_claude("hi")
        assert recorded_api["calls"][0]["temperature"] == 0.3

    def test_temperature_defaults_to_one_without_config(self, recorded_api, monkeypatch):
        monkeypatch.setattr(api, "_config", {})
        api.call_claude("hi")
        assert recorded_api["calls"][0]["temperature"] == 1.0

    def test_explicit_temperature_wins_even_at_zero(self, recorded_api, monkeypatch):
        # 0.0 is falsy — the override must use an is-None check, not `or`
        monkeypatch.setattr(api, "_config", {"temperature": 0.3})
        api.call_claude("hi", temperature=0.0)
        assert recorded_api["calls"][0]["temperature"] == 0.0

    def test_return_stop_reason_tuple_contract(self, recorded_api, fake_message):
        recorded_api["message"] = fake_message(text="partial", stop_reason="max_tokens")
        text, stop = api.call_claude("hi", return_stop_reason=True)
        assert (text, stop) == ("partial", "max_tokens")
        # default return stays a bare string for backward compatibility
        assert api.call_claude("hi") == "partial"

    def test_suspect_stop_reason_warns(self, recorded_api, fake_message, capsys):
        recorded_api["message"] = fake_message(text="cut", stop_reason="max_tokens")
        api.call_claude("hi")
        assert "max_tokens" in capsys.readouterr().err

    def test_clean_stop_reason_is_silent(self, recorded_api, capsys):
        api.call_claude("hi")
        assert capsys.readouterr().err == ""


class TestRetryPredicate:
    def test_bad_request_is_not_retried(self, monkeypatch):
        """A 400 (e.g. exhausted credit balance) is deterministic: it must
        surface immediately, not after 8 exponential-backoff attempts. This
        drives the REAL tenacity-wrapped _call_with_retry — safe offline
        because a non-retryable error never sleeps."""
        attempts = []

        class FakeMessages:
            def create(self, **kwargs):
                attempts.append(1)
                raise anthropic.BadRequestError(
                    message="credit balance is too low",
                    response=httpx.Response(400, request=httpx.Request("POST", "https://api.invalid")),
                    body=None,
                )

        class FakeClient:
            messages = FakeMessages()

        # the autouse guard replaces _call_with_retry; restore the real one
        import importlib
        real = importlib.reload(api)._call_with_retry
        with pytest.raises(anthropic.BadRequestError):
            real(client=FakeClient(), model="m", max_tokens=5, system="", messages=[],
                 temperature=1.0)
        assert len(attempts) == 1  # exactly one attempt, no retries


class TestCostTracking:
    def test_cost_logged_with_known_model_pricing(self, recorded_api, tmp_path, fake_message):
        recorded_api["message"] = fake_message(input_tokens=1_000_000, output_tokens=0)
        api.call_claude("hi", model="claude-haiku-4-5-20251001")
        record = json.loads((tmp_path / "cost.jsonl").read_text().strip())
        assert record["cost_usd"] == pytest.approx(1.00)  # $1.00 / 1M input tokens
        assert record["model"] == "claude-haiku-4-5-20251001"
        assert record["input_tokens"] == 1_000_000

    def test_config_model_is_priced_without_warning(self, recorded_api, tmp_path, fake_message, capsys):
        # Contract from shared/api.py: _PRICING must cover every model id that
        # can appear in config.yaml. A warning here means the tables drifted.
        config_model = utils.load_config(str(REPO_ROOT / "config.yaml"))["model"]
        recorded_api["message"] = fake_message(input_tokens=1_000_000, output_tokens=0)
        api.call_claude("hi", model=config_model)
        assert "not in shared/api.py _PRICING" not in capsys.readouterr().err

    def test_unknown_model_falls_back_to_sonnet_rates_with_warning(self, recorded_api, tmp_path, fake_message, capsys):
        recorded_api["message"] = fake_message(input_tokens=1_000_000, output_tokens=0)
        api.call_claude("hi", model="claude-nonexistent-model")
        record = json.loads((tmp_path / "cost.jsonl").read_text().strip())
        assert record["cost_usd"] == pytest.approx(3.00)
        assert "not in shared/api.py _PRICING" in capsys.readouterr().err

    def test_unpriced_model_warns_only_once(self, recorded_api, fake_message, capsys):
        recorded_api["message"] = fake_message(input_tokens=1, output_tokens=1)
        api.call_claude("a", model="claude-nonexistent-model")
        api.call_claude("b", model="claude-nonexistent-model")
        assert capsys.readouterr().err.count("not in shared/api.py _PRICING") == 1

    def test_stage_written_to_cost_record(self, recorded_api, tmp_path):
        api.call_claude("hi", stage="prompt_draft")
        record = json.loads((tmp_path / "cost.jsonl").read_text().strip())
        assert record["stage"] == "prompt_draft"

    def test_untagged_call_writes_no_stage_key(self, recorded_api, tmp_path):
        # pre-tag consumers (and jq one-liners) must not meet a null field
        api.call_claude("hi")
        record = json.loads((tmp_path / "cost.jsonl").read_text().strip())
        assert "stage" not in record

    def test_get_total_cost_sums_all_calls(self, recorded_api, fake_message):
        recorded_api["message"] = fake_message(input_tokens=1_000_000, output_tokens=1_000_000)
        api.call_claude("a", model="claude-sonnet-4-6")  # $3 + $15
        api.call_claude("b", model="claude-sonnet-4-6")
        assert api.get_total_cost() == pytest.approx(36.0)

    def test_get_total_cost_without_log_is_zero(self):
        # autouse fixture resets _cost_log_path to None
        assert api.get_total_cost() == 0.0

    def test_get_total_cost_missing_file_is_zero(self, monkeypatch, tmp_path):
        monkeypatch.setattr(api, "_cost_log_path", tmp_path / "never-written.jsonl")
        assert api.get_total_cost() == 0.0
