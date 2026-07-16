"""Tests for shared/embeddings.py: the safety net, batching, cost tracking.

Mirrors tests/test_api.py — nothing here reaches the network (see conftest).
"""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from shared import embeddings


class TestSafetyNet:
    def test_unstubbed_embed_texts_is_blocked(self, monkeypatch, tmp_path):
        monkeypatch.setattr(embeddings, "_client", object())
        monkeypatch.setattr(embeddings, "_cost_log_path", tmp_path / "cost.jsonl")
        with pytest.raises(AssertionError, match="OpenAI API call attempted"):
            embeddings.embed_texts(["hello"])

    def test_init_without_key_fails_loudly(self, tiny_config_file, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY")
        with pytest.raises(KeyError):
            embeddings.init(str(tiny_config_file))


def _response(vectors, prompt_tokens=10, reverse_data=False):
    """An object shaped like an OpenAI CreateEmbeddingResponse."""
    data = [SimpleNamespace(index=i, embedding=list(v)) for i, v in enumerate(vectors)]
    if reverse_data:
        data = list(reversed(data))
    return SimpleNamespace(
        data=data,
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, total_tokens=prompt_tokens),
    )


@pytest.fixture
def recorded_embed(monkeypatch, tmp_path):
    """Exercise embed_texts itself: record what reaches the transport layer.

    Replaces _embed_with_retry (below embed_texts, above the network) with a
    recorder whose behavior tests override via canned["respond"].
    """
    calls = []
    canned = {"respond": lambda batch: _response([[1.0, 0.0]] * len(batch))}

    def record(client, model, batch):
        calls.append({"model": model, "batch": list(batch)})
        return canned["respond"](batch)

    monkeypatch.setattr(embeddings, "_embed_with_retry", record)
    monkeypatch.setattr(embeddings, "_client", object())
    monkeypatch.setattr(embeddings, "_cost_log_path", tmp_path / "cost.jsonl")
    canned["calls"] = calls
    return canned


class TestEmbedTexts:
    def test_rows_are_l2_normalized_float32(self, recorded_embed):
        recorded_embed["respond"] = lambda batch: _response([[3.0, 4.0]] * len(batch))
        X = embeddings.embed_texts(["a"])
        assert X.dtype == np.float32
        assert X.shape == (1, 2)
        assert np.allclose(X[0], [0.6, 0.8])

    def test_batches_split_at_max_batch(self, recorded_embed, monkeypatch):
        monkeypatch.setattr(embeddings, "MAX_BATCH", 2)
        X = embeddings.embed_texts(["a", "b", "c", "d", "e"])
        assert [len(c["batch"]) for c in recorded_embed["calls"]] == [2, 2, 1]
        assert X.shape == (5, 2)

    def test_batches_split_at_char_budget(self, recorded_embed, monkeypatch):
        # item count alone must not be the only bound: a batch also closes when
        # its cumulative chars would exceed MAX_BATCH_CHARS (the ~300k-token
        # request cap, char-bounded for worst-case 1-token/char scripts)
        monkeypatch.setattr(embeddings, "MAX_BATCH_CHARS", 10)
        embeddings.embed_texts(["aaaaaa", "bbbbbb", "cc"])
        assert [c["batch"] for c in recorded_embed["calls"]] == [["aaaaaa"], ["bbbbbb", "cc"]]

    def test_single_oversized_text_still_ships_alone(self, recorded_embed, monkeypatch):
        monkeypatch.setattr(embeddings, "MAX_BATCH_CHARS", 10)
        embeddings.embed_texts(["x" * 25])
        assert [len(c["batch"]) for c in recorded_embed["calls"]] == [1]

    def test_rows_follow_response_index_not_arrival_order(self, recorded_embed):
        recorded_embed["respond"] = lambda batch: _response(
            [[1.0, 0.0], [0.0, 1.0]], reverse_data=True
        )
        X = embeddings.embed_texts(["first", "second"])
        assert np.allclose(X[0], [1.0, 0.0])
        assert np.allclose(X[1], [0.0, 1.0])

    def test_empty_text_raises_before_any_call(self, recorded_embed):
        with pytest.raises(ValueError, match="empty text at index 1"):
            embeddings.embed_texts(["fine", "   "])
        assert recorded_embed["calls"] == []

    def test_empty_list_returns_empty_matrix_without_calls(self, recorded_embed):
        X = embeddings.embed_texts([])
        assert X.shape == (0, 0)
        assert recorded_embed["calls"] == []

    def test_model_passed_through(self, recorded_embed):
        embeddings.embed_texts(["a"], model="text-embedding-3-large")
        assert recorded_embed["calls"][0]["model"] == "text-embedding-3-large"


class TestTokenTruncation:
    def test_truncate_to_tokens_leaves_short_text_untouched(self):
        assert embeddings.truncate_to_tokens("a short line", max_tokens=100) == "a short line"

    def test_truncate_to_tokens_caps_long_text(self):
        enc = embeddings._encoding_for(embeddings.DEFAULT_MODEL)
        out = embeddings.truncate_to_tokens("word " * 500, max_tokens=20)
        assert len(enc.encode(out)) <= 20

    def test_cjk_within_char_cap_still_exceeds_token_cap(self):
        """The bug's root cause: a CJK string short in CHARS can blow the TOKEN
        window (CJK is >1 token/char), so a char cap alone is not safe."""
        enc = embeddings._encoding_for(embeddings.DEFAULT_MODEL)
        s = "今天天气很好我们去公园散步吧" * 800  # ~11k chars, but more tokens
        assert len(enc.encode(s)) > embeddings.MAX_INPUT_TOKENS

    def test_embed_texts_truncates_oversized_input_to_token_window(self, recorded_embed):
        """The safety net: an over-window input reaches the transport truncated
        to MAX_INPUT_TOKENS, so the real API would not 400 the batch."""
        enc = embeddings._encoding_for(embeddings.DEFAULT_MODEL)
        huge = "今天天气很好我们去公园散步吧" * 2000
        assert len(enc.encode(huge)) > embeddings.MAX_INPUT_TOKENS  # precondition
        embeddings.embed_texts([huge])
        sent = recorded_embed["calls"][0]["batch"][0]
        assert len(enc.encode(sent)) <= embeddings.MAX_INPUT_TOKENS


class TestCostTracking:
    def test_cost_logged_with_known_model_pricing(self, recorded_embed, tmp_path):
        recorded_embed["respond"] = lambda batch: _response(
            [[1.0, 0.0]] * len(batch), prompt_tokens=1_000_000
        )
        embeddings.embed_texts(["a"])
        record = json.loads((tmp_path / "cost.jsonl").read_text().strip())
        assert record["cost_usd"] == pytest.approx(0.02)  # $0.02 / 1M input tokens
        assert record["model"] == "text-embedding-3-small"
        assert record["input_tokens"] == 1_000_000
        assert record["output_tokens"] == 0  # embeddings bill input only

    def test_each_batch_logs_its_own_usage(self, recorded_embed, monkeypatch, tmp_path):
        monkeypatch.setattr(embeddings, "MAX_BATCH", 1)
        embeddings.embed_texts(["a", "b"])
        lines = (tmp_path / "cost.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2

    def test_unknown_model_falls_back_with_warning_once(self, recorded_embed, tmp_path, capsys):
        recorded_embed["respond"] = lambda batch: _response(
            [[1.0, 0.0]] * len(batch), prompt_tokens=1_000_000
        )
        embeddings.embed_texts(["a"], model="text-embedding-nonexistent")
        embeddings.embed_texts(["b"], model="text-embedding-nonexistent")
        err = capsys.readouterr().err
        assert err.count("not in shared/embeddings.py _PRICING") == 1
        first = json.loads((tmp_path / "cost.jsonl").read_text().splitlines()[0])
        assert first["cost_usd"] == pytest.approx(0.02)  # 3-small fallback rate
