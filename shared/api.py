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
    # Gemini judges (evals): logged through the same cost log.
    # Rates from ai.google.dev/gemini-api/docs/pricing (paid tier, prompts <= 200k tokens).
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.1-pro-preview": (2.00, 12.00),
}
_UNPRICED_WARNED: set = set()


def init(config_path: str = "config.yaml", cost_log_path: str | Path | None = None) -> None:
    global _config, _client, _cost_log_path
    with open(config_path) as f:
        _config = yaml.safe_load(f)
    # Tolerate a missing Anthropic key: non-Anthropic judges (Gemini) can still run
    # and log costs; call_claude raises a clear error only when actually called.
    key = os.environ.get("ANTHROPIC_API_KEY")
    _client = anthropic.Anthropic(api_key=key) if key else None
    _cost_log_path = Path(cost_log_path or _config["outputs"]["cost_log"])
    _cost_log_path.parent.mkdir(parents=True, exist_ok=True)


def resolve_model(model: str | None = None) -> str:
    """The effective model for a call: the explicit override, else the config
    default (``claude-sonnet-4-6`` when unset). Single source of truth so callers
    that need to record which model actually ran (e.g. bundle fingerprints) agree
    with what ``call_claude`` dispatches."""
    return model or _config.get("model", "claude-sonnet-4-6")


def _get_client() -> anthropic.Anthropic:
    if _client is None:
        init()
    return _client


def _log_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> None:
    if _cost_log_path is None:  # init() not called — skip logging rather than crash
        return
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
    # Cache pricing (Anthropic): 5m-TTL writes bill at 1.25x base input, reads at 0.1x.
    # input_tokens from the API already EXCLUDES cached tokens, so the terms sum cleanly.
    cost = (
        (input_tokens / 1_000_000) * prices[0]
        + (cache_creation_tokens / 1_000_000) * prices[0] * 1.25
        + (cache_read_tokens / 1_000_000) * prices[0] * 0.10
        + (output_tokens / 1_000_000) * prices[1]
    )
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
    }
    if cache_creation_tokens or cache_read_tokens:
        record["cache_creation_input_tokens"] = cache_creation_tokens
        record["cache_read_input_tokens"] = cache_read_tokens
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
    system: str | list[dict],  # str, or content blocks when cache_system is set
    messages: list[dict],
    temperature: float | None = None,
) -> anthropic.types.Message:
    kwargs = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    return client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        **kwargs,
    )


def call_claude(
    user_message: str,
    system_prompt: str = "",
    injection: str = "",
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    cache_system: bool = False,
) -> str:
    """Call Claude and return the response text.

    Args:
        user_message: The user turn content.
        system_prompt: Optional system prompt.
        injection: Optional text appended to the system prompt (e.g. injection type for DAD).
        model: Model override; falls back to config value.
        max_tokens: Token limit override; falls back to config value.
        temperature: Sampling temperature override.
        cache_system: Mark the system prompt as a prompt-cache breakpoint. Use for
            large system prompts reused verbatim across many calls (e.g. the judge
            rubric): cache reads bill at 0.1x input rate. Prompts under the model's
            ~1024-token cache minimum are cached as a no-op by the API.

    Returns:
        The assistant's response text.
    """
    client = _get_client()
    if client is None:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set — Anthropic models are unavailable. "
            "Set it in .env, or use a Gemini judge (GEMINI_API_KEY)."
        )
    resolved_model = resolve_model(model)
    resolved_max = max_tokens or _config.get("max_tokens", 4000)

    full_system = system_prompt
    if injection:
        full_system = (full_system + "\n\n" + injection).strip()

    system: str | list = full_system
    if cache_system and full_system:
        system = [{"type": "text", "text": full_system, "cache_control": {"type": "ephemeral"}}]

    response = _call_with_retry(
        client=client,
        model=resolved_model,
        max_tokens=resolved_max,
        system=system,
        messages=[{"role": "user", "content": user_message}],
        temperature=temperature,
    )

    _log_usage(
        resolved_model,
        response.usage.input_tokens,
        response.usage.output_tokens,
        cache_creation_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
    )
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
