"""OpenAI embeddings wrapper with retry logic and cost tracking.

Structured exactly like shared/api.py: a lazily-initialized module client, a
tenacity-wrapped transport call that retries only transient failures, and
per-call records appended to the same cost-log JSONL schema (output_tokens is
always 0 — embeddings bill input only). ``embed_texts`` is the single
chokepoint every caller uses; tests stub it the same way they stub
``shared.api.call_claude`` (see tests/conftest.py).

This is the embedding-based complement to the lexical word-shingle scan in
shared/textstats.py, whose docstring defers paraphrase-level semantic
duplication to embeddings. Requires OPENAI_API_KEY in the environment/.env;
the Anthropic-driven pipelines never import this module.
"""

import os
import json
import threading
import sys
from pathlib import Path
from datetime import datetime, UTC

import numpy as np
import openai
import yaml
from dotenv import load_dotenv
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

load_dotenv()

DEFAULT_MODEL = "text-embedding-3-small"

# Local (in-process) embedding lane: model ids "local:<sentence-transformers name>"
# never touch the network beyond a one-time model download, need no key, and log
# no cost (there is none). NOT comparable with API-embedded reports — the
# diversity report records its embed_model so lanes can't silently mix.
LOCAL_PREFIX = "local:"
DEFAULT_LOCAL_MODEL = "local:sentence-transformers/all-MiniLM-L6-v2"
_local_models: dict = {}

# The embeddings endpoint caps each request at 2048 inputs and ~300k total
# tokens. A batch closes at MAX_BATCH items or MAX_BATCH_CHARS characters,
# whichever comes first: item count alone can bust the token cap (128 full
# SDF documents at ~4k tokens each is ~512k tokens). Chars bound tokens at
# worst ~1 token/char (CJK), so 250k chars stays under the cap for any script.
MAX_BATCH = 128
MAX_BATCH_CHARS = 250_000

_config: dict = {}
_client: openai.OpenAI | None = None
_cost_log_path: Path | None = None
_cost_log_lock = threading.Lock()

# $ per million input tokens. Unknown models fall back to the 3-small rate
# WITH A WARNING — embedding spend is cents, but the log should stay honest.
_PRICING = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
}
_UNPRICED_WARNED: set = set()


def init(config_path: str = "config.yaml", cost_log_path: str | Path | None = None) -> None:
    global _config, _client, _cost_log_path
    with open(config_path, encoding="utf-8") as f:
        _config = yaml.safe_load(f)
    _client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    _cost_log_path = Path(cost_log_path or _config["outputs"]["cost_log"])
    _cost_log_path.parent.mkdir(parents=True, exist_ok=True)


def _get_client() -> openai.OpenAI:
    if _client is None:
        init()
    return _client


def _log_usage(model: str, input_tokens: int) -> None:
    price = _PRICING.get(model)
    if price is None:
        if model not in _UNPRICED_WARNED:
            _UNPRICED_WARNED.add(model)
            print(
                f"  WARNING: model {model!r} is not in shared/embeddings.py _PRICING — "
                f"estimating cost at {DEFAULT_MODEL} rates ($0.02 per MTok). Add the "
                "model to _PRICING for accurate cost logs.",
                file=sys.stderr,
            )
        price = _PRICING[DEFAULT_MODEL]
    cost = (input_tokens / 1_000_000) * price
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": 0,
        "cost_usd": round(cost, 6),
    }
    with _cost_log_lock, open(_cost_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# Same predicate rationale as shared/api.py: retrying a deterministic 4xx (bad
# request, auth, over-context input) burns 8 exponential-backoff attempts
# before surfacing the real error — retry only rate limits, 5xx, and
# connection/timeout.
_RETRYABLE_ERRORS = (
    openai.RateLimitError,
    openai.InternalServerError,
    openai.APIConnectionError,
)


@retry(
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(8),
)
def _embed_with_retry(client: openai.OpenAI, model: str, batch: list[str]):
    return client.embeddings.create(model=model, input=batch)


def _embed_local(model_name: str, texts: list[str]) -> np.ndarray:
    """Encode with a sentence-transformers model loaded in this process. Separate
    seam (like _embed_with_retry) so tests can block/stub it — the real call would
    download the model. Loaded models are cached for the process lifetime."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise RuntimeError(
            "local embeddings need the sentence-transformers package — run: "
            "pip install sentence-transformers (first use also downloads the "
            f"model {model_name!r}, ~90MB)"
        ) from e
    st_model = _local_models.get(model_name)
    if st_model is None:
        st_model = _local_models[model_name] = SentenceTransformer(model_name)
    return st_model.encode(texts, show_progress_bar=False)


def _batches(texts: list[str]):
    """Split texts into API batches: at most MAX_BATCH items and (except for a
    single oversized text, which still goes alone) MAX_BATCH_CHARS chars each."""
    batch: list[str] = []
    chars = 0
    for t in texts:
        if batch and (len(batch) >= MAX_BATCH or chars + len(t) > MAX_BATCH_CHARS):
            yield batch
            batch, chars = [], 0
        batch.append(t)
        chars += len(t)
    if batch:
        yield batch


def embed_texts(texts: list[str], model: str = DEFAULT_MODEL) -> np.ndarray:
    """Embed texts and return an L2-normalized float32 matrix, one row per text.

    Batching happens here (MAX_BATCH items / MAX_BATCH_CHARS chars per
    request); callers that want to checkpoint paid work between requests
    should chunk their own input and call this per chunk.

    Raises ValueError on empty/whitespace-only texts — the API rejects them
    mid-batch, so the caller must filter (and report) empties first. Texts
    longer than the model's token window (8192 tokens for 3-small) also fail
    the whole request: truncate before calling.
    """
    for i, t in enumerate(texts):
        if not t or not t.strip():
            raise ValueError(
                f"embed_texts got an empty text at index {i} — filter empties out "
                "(and report them) before embedding."
            )
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)

    if model.startswith(LOCAL_PREFIX):
        # In-process lane: no client, no init(), no cost log (compute is free).
        X = np.asarray(_embed_local(model[len(LOCAL_PREFIX):], texts), dtype=np.float32)
    else:
        client = _get_client()
        rows: list[list[float]] = []
        for batch in _batches(texts):
            response = _embed_with_retry(client, model, batch)
            _log_usage(model, response.usage.prompt_tokens)
            # the API preserves order, but each item carries its index — trust that
            ordered = sorted(response.data, key=lambda d: d.index)
            rows.extend(d.embedding for d in ordered)
        X = np.asarray(rows, dtype=np.float32)
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return X / norms
