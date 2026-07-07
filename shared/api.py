"""Anthropic API wrapper with retry logic and cost tracking."""

import os
import json
import threading
import sys
import time
from pathlib import Path
from datetime import datetime, UTC

import anthropic
import yaml
from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_all,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    retry_if_not_exception_type,
)

load_dotenv()

_config: dict = {}
_client: anthropic.Anthropic | None = None
_cost_log_path: Path | None = None
# call_claude may run from worker threads (utils.parallel_map); the Anthropic
# client is thread-safe, but appends to the cost log must be serialized.
_cost_log_lock = threading.Lock()

# Pricing per million tokens (input, output) for known models
# Prices per million tokens (input, output). Keys must cover every model id
# (or alias) that can appear in config.yaml — unknown models fall back to
# Sonnet rates WITH A WARNING, which can badly misstate real spend (a Haiku
# run was overreported 3x this way). The Anthropic console is the source of
# truth for billing; this log is for per-stage breakdowns.
_PRICING = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-fable-5": (10.00, 50.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}
_UNPRICED_WARNED: set = set()


def init(config_path: str = "config.yaml", cost_log_path: str | Path | None = None) -> None:
    global _config, _client, _cost_log_path
    with open(config_path) as f:
        _config = yaml.safe_load(f)
    _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    _cost_log_path = Path(cost_log_path or _config["outputs"]["cost_log"])
    _cost_log_path.parent.mkdir(parents=True, exist_ok=True)


def _get_client() -> anthropic.Anthropic:
    if _client is None:
        init()
    return _client


def _log_usage(model: str, input_tokens: int, output_tokens: int) -> None:
    prices = _PRICING.get(model)
    if prices is None:
        if model not in _UNPRICED_WARNED:
            _UNPRICED_WARNED.add(model)
            print(
                f"  WARNING: model {model!r} is not in shared/api.py _PRICING — "
                "estimating cost at Sonnet rates ($3/$15 per MTok). Add the model "
                "to _PRICING for accurate cost logs.",
                file=sys.stderr,
            )
        prices = (3.00, 15.00)
    cost = (input_tokens / 1_000_000) * prices[0] + (output_tokens / 1_000_000) * prices[1]
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
    }
    with _cost_log_lock, open(_cost_log_path, "a") as f:
        f.write(json.dumps(record) + "\n")


# Retry transient failures (429, 5xx, overload) but NOT deterministic 4xx
# client errors — a 400 (exhausted credit balance, malformed request), 401,
# 403, or 404 fails identically on every attempt, and retrying one used to
# burn ~5 minutes of exponential backoff per call before surfacing the error.
@retry(
    retry=retry_all(
        retry_if_exception_type((anthropic.RateLimitError, anthropic.APIStatusError)),
        retry_if_not_exception_type((
            anthropic.BadRequestError,
            anthropic.AuthenticationError,
            anthropic.PermissionDeniedError,
            anthropic.NotFoundError,
        )),
    ),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(8),
)
def _call_with_retry(
    client: anthropic.Anthropic,
    model: str,
    max_tokens: int,
    system: str,
    messages: list[dict],
) -> anthropic.types.Message:
    return client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )


def call_claude(
    user_message: str,
    system_prompt: str = "",
    injection: str = "",
    model: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """Call Claude and return the response text.

    Args:
        user_message: The user turn content.
        system_prompt: Optional system prompt.
        injection: Optional text appended to the system prompt (e.g. injection type for DAD).
        model: Model override; falls back to config value.
        max_tokens: Token limit override; falls back to config value.

    Returns:
        The assistant's response text.
    """
    client = _get_client()
    resolved_model = model or _config.get("model", "claude-sonnet-4-6")
    resolved_max = max_tokens or _config.get("max_tokens", 4000)

    full_system = system_prompt
    if injection:
        full_system = (full_system + "\n\n" + injection).strip()

    response = _call_with_retry(
        client=client,
        model=resolved_model,
        max_tokens=resolved_max,
        system=full_system,
        messages=[{"role": "user", "content": user_message}],
    )

    _log_usage(resolved_model, response.usage.input_tokens, response.usage.output_tokens)
    return response.content[0].text


def get_total_cost() -> float:
    """Sum cost_usd from the cost log and return total."""
    if _cost_log_path is None or not _cost_log_path.exists():
        return 0.0
    total = 0.0
    with open(_cost_log_path) as f:
        for line in f:
            line = line.strip()
            if line:
                total += json.loads(line).get("cost_usd", 0.0)
    return round(total, 4)
