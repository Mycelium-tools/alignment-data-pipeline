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


class TestLocalLane:
    def test_local_prefix_routes_to_the_local_seam_not_the_api(self, monkeypatch, tmp_path):
        seen = {}

        def fake_local(model_name, texts):
            seen["model"] = model_name
            seen["texts"] = list(texts)
            return np.asarray([[3.0, 4.0], [0.0, 2.0]], dtype=np.float32)

        monkeypatch.setattr(embeddings, "_embed_local", fake_local)
        log = tmp_path / "cost.jsonl"
        monkeypatch.setattr(embeddings, "_cost_log_path", log)
        X = embeddings.embed_texts(["a", "b"], model="local:some/model")
        assert seen == {"model": "some/model", "texts": ["a", "b"]}
        # normalized like the API lane, and nothing was billed or logged
        assert np.allclose(np.linalg.norm(X, axis=1), 1.0)
        assert not log.exists()

    def test_local_lane_needs_no_openai_key_or_init(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY")
        monkeypatch.setattr(embeddings, "_embed_local",
                            lambda name, texts: np.eye(len(texts), 4, dtype=np.float32))
        X = embeddings.embed_texts(["a"], model=embeddings.DEFAULT_LOCAL_MODEL)
        assert X.shape == (1, 4)
