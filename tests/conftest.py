"""Shared fixtures for the offline test suite.

Four independent layers guarantee tests can NEVER call the Anthropic API or
spawn the Claude Code CLI:

1. pytest-socket (``--disable-socket`` in pyproject.toml) blocks all network
   access at the socket level.
2. Every test runs with a fake ``ANTHROPIC_API_KEY``, overriding any real key
   that ``load_dotenv()`` (run at ``shared.api`` import) pulled from a .env file.
3. ``shared.api._call_with_retry`` is replaced with a function that raises, so
   an unstubbed ``call_claude`` on the api backend fails loudly before touching
   tenacity/anthropic.
4. ``shared.api._call_claude_code_with_retry`` is replaced the same way, so the
   claude_code backend can never spawn the CLI — which would bill a real
   contributor subscription — from a test.

Pipeline tests stub one level higher via ``stub_claude``, which patches
``shared.api.call_claude`` — the single chokepoint every pipeline module uses.
Never patch below ``call_claude``: if a real ``anthropic`` retryable error ever
reached the real ``_call_with_retry``, tenacity would sleep 4-60s per attempt.

The OpenAI embeddings seam (``shared/embeddings.py``, used by the diversity
eval) is guarded the same layered way: ``_openai_guard`` fakes the key, resets
module globals, and blocks ``_embed_with_retry``; tests stub the chokepoint
``shared.embeddings.embed_texts`` via ``stub_embeddings``.
"""

import json
import random
import re
import threading
import zlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from shared import api, embeddings

REPO_ROOT = Path(__file__).resolve().parent.parent


def dad_scenario_reply(user_message: str) -> str:
    """Echo a conforming step-1b JSON array for a rendered step1_dilemmas.txt
    prompt: one object per SCENARIO block, its annotation copied verbatim from
    the block's own assigned fields (as the template instructs). Kept here
    because both the step-level and e2e DAD tests dispatch on it."""
    # Derived, not hardcoded: the length bands live with the sampler, and a
    # drafted prompt must clear its card's lenient band to be accepted.
    from dad_pipeline.step1_dilemmas import _LENGTH_BANDS, _LENGTH_TEXT

    out = []
    for block in re.findall(r"SCENARIO (S-\d+)\n((?:- .*\n?)*)", user_message):
        sid, body = block
        field = dict(re.findall(r"- ([^:]+): (.*)", body))
        pair = field["Value pairs to build in"].split(" (add more")[0].split(";")[0].strip()
        prompt = f"Drafted user message for {sid}."
        for label, text in _LENGTH_TEXT.items():
            if field.get("Length", "").startswith(text):
                lo, _hi = _LENGTH_BANDS[label]
                filler = " The situation keeps going with believable texture."
                while len(prompt) < lo + 40:
                    prompt += filler
                break
        out.append({
            "scenario_id": sid,
            "prompt": prompt,
            "annotation": {
                "domain": field["Domain"].split(", "),
                "user_goal": field["User goal"].split(", "),
                "dilemma_anatomy": {"goal": "g", "temptation": "t", "cost": "c"},
                "values_in_tension": [pair],
                "moral_patients": "test patients in context",
                "visibility": field["Visibility"],
                "user_attitude": field["User attitude"],
                "conflict": field["Conflict"],
                "direction": field["Direction"],
                "welfare_magnitude": field["Welfare magnitude"],
                "user_stakes": field["User stakes"],
                "leverage": field["Leverage"].split(" — ")[0],
                "claims": [{"claim": "a load-bearing claim", "status": "Settled"}],
            },
        })
    return json.dumps(out)


@pytest.fixture(autouse=True)
def _seed_rng():
    """Reseed the global RNG before every test so runs are repeatable.

    Note: seeding does NOT make draws deterministic across worker threads
    (parallel_map interleaves them) — a test that needs exact draws in a
    parallel stage must inject its own rng (e.g. sample_language(dist, rng=...)).
    """
    random.seed(0)


@pytest.fixture(autouse=True)
def _api_guard(monkeypatch):
    """Fake credentials, reset shared.api globals, and block the API seam."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    monkeypatch.setattr(api, "_config", {})
    monkeypatch.setattr(api, "_client", None)
    monkeypatch.setattr(api, "_cost_log_path", None)
    monkeypatch.setattr(api, "_UNPRICED_WARNED", set())
    monkeypatch.setattr(api, "_backend", "api")
    monkeypatch.setattr(api, "_neutral_system_warned", False)
    monkeypatch.setattr(api, "_temperature_warned", False)

    def _blocked(*args, **kwargs):
        raise AssertionError(
            "Anthropic API call attempted during tests — stub shared.api.call_claude"
        )

    monkeypatch.setattr(api, "_call_with_retry", _blocked)

    # The claude_code backend's seam spawns the real `claude` CLI as a
    # subprocess, which pytest-socket's --disable-socket cannot block (it only
    # patches the in-process socket module). Block it here too so a test that
    # flips _backend to "claude_code" without stubbing this fails fast in-process
    # rather than launching a real CLI. Tests exercising the backend override it.
    def _blocked_cc(*args, **kwargs):
        raise AssertionError(
            "claude_code backend invoked during tests — "
            "stub shared.api._call_claude_code_with_retry"
        )

    monkeypatch.setattr(api, "_call_claude_code_with_retry", _blocked_cc)


@pytest.fixture(autouse=True)
def _openai_guard(monkeypatch):
    """Fake OpenAI credentials, reset shared.embeddings globals, block the seam."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setattr(embeddings, "_config", {})
    monkeypatch.setattr(embeddings, "_client", None)
    monkeypatch.setattr(embeddings, "_cost_log_path", None)
    monkeypatch.setattr(embeddings, "_UNPRICED_WARNED", set())

    def _blocked(*args, **kwargs):
        raise AssertionError(
            "OpenAI API call attempted during tests — stub shared.embeddings.embed_texts"
        )

    monkeypatch.setattr(embeddings, "_embed_with_retry", _blocked)


@pytest.fixture
def stub_embeddings(monkeypatch):
    """Factory that replaces shared.embeddings.embed_texts with a recording stub.

    ``install()`` gives every distinct text a deterministic unit vector (rng
    seeded from the text's crc32), so identical texts embed identically —
    enough for behavioral tests. Pass ``vectors`` (text -> array) to pin exact
    geometry (e.g. orthogonal groups). Returns the list of recorded calls
    ({"texts", "model"}) so tests can assert what was embedded — and, for
    cache/resume tests, that nothing was.
    """

    def install(dim: int = 8, vectors: dict | None = None):
        calls = []

        def fake(texts, model=embeddings.DEFAULT_MODEL):
            # mirror the real embed_texts contract: empties must never reach the API
            for i, t in enumerate(texts):
                if not t or not t.strip():
                    raise ValueError(f"embed_texts got an empty text at index {i}")
            calls.append({"texts": list(texts), "model": model})
            rows = []
            for t in texts:
                if vectors is not None:
                    v = np.asarray(vectors[t], dtype=np.float32)
                else:
                    rng = np.random.default_rng(zlib.crc32(t.encode("utf-8")))
                    v = rng.standard_normal(dim).astype(np.float32)
                rows.append(v / np.linalg.norm(v))
            return np.stack(rows)

        monkeypatch.setattr(embeddings, "embed_texts", fake)
        return calls

    return install


@pytest.fixture
def stub_claude(monkeypatch):
    """Factory that replaces shared.api.call_claude with a recording stub.

    ``install(responses)`` accepts either a list of response strings (consumed
    FIFO) or a callable ``(user_message, **kwargs) -> str`` for dispatching on
    prompt content. Returns the list of recorded calls (dicts of the call's
    keyword arguments) so tests can assert on the observable API contract.
    """

    def install(responses):
        calls = []
        queue = list(responses) if isinstance(responses, list) else None
        busy = threading.Lock()

        def fake(user_message, system_prompt="", injection="", model=None, max_tokens=None,
                 return_stop_reason=False, stage=None, temperature=None, item_id=None):
            calls.append({
                "user_message": user_message,
                "system_prompt": system_prompt,
                "injection": injection,
                "model": model,
                "max_tokens": max_tokens,
                "stage": stage,
                "temperature": temperature,
                "item_id": item_id,
            })
            if queue is None:
                result = responses(
                    user_message,
                    system_prompt=system_prompt,
                    injection=injection,
                    model=model,
                    max_tokens=max_tokens,
                    stage=stage,
                    temperature=temperature,
                    item_id=item_id,
                )
            else:
                # FIFO queues assume serial calls: a parallel stage (workers > 1
                # with 2+ pending items) interleaves pops and maps responses to
                # the wrong items nondeterministically. Fail loudly instead.
                assert busy.acquire(blocking=False), (
                    "queue-based stub_claude called concurrently — use a callable "
                    "dispatcher for stages that fan out via parallel_map"
                )
                try:
                    assert queue, "stub_claude queue exhausted — more API calls than canned responses"
                    result = queue.pop(0)
                finally:
                    busy.release()
            # Dispatchers/queues may return (text, stop_reason) to exercise
            # truncation guards; plain strings imply a clean end_turn.
            text, stop = result if isinstance(result, tuple) else (result, "end_turn")
            return (text, stop) if return_stop_reason else text

        monkeypatch.setattr(api, "call_claude", fake)
        return calls

    return install


@pytest.fixture
def fake_message():
    """Factory for objects shaped like an Anthropic Message response."""

    def make(text="ok", input_tokens=10, output_tokens=5, stop_reason="end_turn"):
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
            content=[SimpleNamespace(text=text, type="text")],
            stop_reason=stop_reason,
        )

    return make


@pytest.fixture(scope="session")
def prompts_sdf():
    return REPO_ROOT / "prompts" / "sdf"


@pytest.fixture(scope="session")
def prompts_dad():
    return REPO_ROOT / "prompts" / "dad"


@pytest.fixture
def tiny_config(tmp_path):
    """config.yaml shape with minimal scale knobs; all paths under tmp_path."""
    return {
        "model": "claude-haiku-4-5",
        "max_tokens": 4000,
        "temperature": 1.0,
        "workers": 2,
        "sdf": {
            "document_types_count": 2,
            "subtypes_per_type": 1,
            "documents_per_subtype": 1,
            "min_score_threshold": 7,
        },
        "dad": {
            "dilemmas": {
                "count": 2,
                "batch_size": 2,
                "id_start": 1,
                "seed_path": None,
                # pinned so the sampled scenarios (and the fields the stub
                # echoes back) are identical run to run
                "scenario_seed": 7,
                "refine": True,
            },
            "responses": {"per_prompt": 1},
        },
        "language_distribution": {"en": 1.0},
        "outputs": {"cost_log": str(tmp_path / "cost_log.jsonl")},
    }


@pytest.fixture
def tiny_config_file(tiny_config, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(tiny_config))
    return path


