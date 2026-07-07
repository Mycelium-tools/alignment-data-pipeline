"""Shared fixtures for the offline test suite.

Three independent layers guarantee tests can NEVER call the Anthropic API:

1. pytest-socket (``--disable-socket`` in pyproject.toml) blocks all network
   access at the socket level.
2. Every test runs with a fake ``ANTHROPIC_API_KEY``, overriding any real key
   that ``load_dotenv()`` (run at ``shared.api`` import) pulled from a .env file.
3. ``shared.api._call_with_retry`` is replaced with a function that raises, so
   an unstubbed ``call_claude`` fails loudly before touching tenacity/anthropic.

Pipeline tests stub one level higher via ``stub_claude``, which patches
``shared.api.call_claude`` — the single chokepoint every pipeline module uses.
Never patch below ``call_claude``: if a real ``anthropic`` retryable error ever
reached the real ``_call_with_retry``, tenacity would sleep 4-60s per attempt.
"""

import random
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from shared import api

REPO_ROOT = Path(__file__).resolve().parent.parent


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

        def fake(user_message, system_prompt="", injection="", model=None, max_tokens=None):
            calls.append({
                "user_message": user_message,
                "system_prompt": system_prompt,
                "injection": injection,
                "model": model,
                "max_tokens": max_tokens,
            })
            if queue is None:
                return responses(
                    user_message,
                    system_prompt=system_prompt,
                    injection=injection,
                    model=model,
                    max_tokens=max_tokens,
                )
            # FIFO queues assume serial calls: a parallel stage (workers > 1
            # with 2+ pending items) interleaves pops and maps responses to
            # the wrong items nondeterministically. Fail loudly instead.
            assert busy.acquire(blocking=False), (
                "queue-based stub_claude called concurrently — use a callable "
                "dispatcher for stages that fan out via parallel_map"
            )
            try:
                assert queue, "stub_claude queue exhausted — more API calls than canned responses"
                return queue.pop(0)
            finally:
                busy.release()

        monkeypatch.setattr(api, "call_claude", fake)
        return calls

    return install


@pytest.fixture
def fake_message():
    """Factory for objects shaped like an Anthropic Message response."""

    def make(text="ok", input_tokens=10, output_tokens=5):
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
            content=[SimpleNamespace(text=text)],
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
            "scenarios_per_principle": 1,
            "injections": ["deference", "plain"],
            # fraction 1.0 keeps step 7 deterministic (uuid record_ids would make
            # a partial fraction select a random-looking subset per run)
            "pushback": {"enabled": True, "fraction": 1.0},
        },
        "manta": {"csv_path": str(tmp_path / "manta.csv"), "max_rows": 3},
        "language_distribution": {"en": 1.0},
        "outputs": {"cost_log": str(tmp_path / "cost_log.jsonl")},
    }


@pytest.fixture
def tiny_config_file(tiny_config, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(tiny_config))
    return path


@pytest.fixture
def manta_csv(tmp_path):
    """Fixture MANTA CSV at the path tiny_config points to.

    Questions avoid any accidental "ai" substring (a principle-10 keyword)
    except where a keyword match is intended.
    """
    path = tmp_path / "manta.csv"
    path.write_text(
        "id,question,pressure\n"
        "0,Is it wrong to boil crustaceans alive in restaurant kitchens?,epistemic\n"
        "1,Should our firm keep using battery cages if switching costs too much?,economic\n"
        "2,Do robot minds deserve moral status once they show consciousness?,novel entity\n"
        "3,My town holds an annual pig chase; should the customs continue?,cultural\n"
        "4,Should we stock the pond so kids can go fishing on weekends?,recreational\n"
    )
    return path
