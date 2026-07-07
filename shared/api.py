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
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
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


# Only transient failures are worth retrying. APIStatusError is the base for
# 4xx too, and retrying a non-retryable 4xx (bad request, auth, not-found) just
# burns 8 exponential-backoff attempts before surfacing the real error — so
# retry only rate limits, 5xx, and connection/timeout (APITimeoutError
# subclasses APIConnectionError).
_RETRYABLE_ERRORS = (
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.APIConnectionError,
)


@retry(
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
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
    # Extended thinking OFF everywhere — training data should show user-facing
    # reasoning, not internal scratchpads (see CLAUDE.md). Models in the Claude 5
    # family emit a thinking block by default, so disable it explicitly rather
    # than parse around it. NOTE: `thinking={"type": "disabled"}` 400s on
    # claude-fable-5 (which requires adaptive thinking); that model is therefore
    # unsupported here, since omitting the flag would violate the no-scratchpads
    # rule. The pipeline defaults to claude-sonnet-5, which supports disabling.
    return client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        thinking={"type": "disabled"},
    )


def _response_text(response: anthropic.types.Message) -> str:
    """Concatenate the text blocks of a response, skipping any non-text blocks
    (e.g. a thinking block that slips through). Returns '' if there is no text."""
    return "".join(
        block.text for block in response.content
        if getattr(block, "type", None) == "text"
    )


def call_claude(
    user_message: str,
    system_prompt: str = "",
    injection: str = "",
    model: str | None = None,
    max_tokens: int | None = None,
    return_stop_reason: bool = False,
) -> str | tuple[str, str | None]:
    """Call Claude and return the response text.

    Args:
        user_message: The user turn content.
        system_prompt: Optional system prompt.
        injection: Optional text appended to the system prompt.
        model: Model override; falls back to config value.
        max_tokens: Token limit override; falls back to config value.
        return_stop_reason: if True, return (text, stop_reason) so the caller can
            reject truncated/refused completions instead of storing them.

    Returns:
        The assistant's response text, or (text, stop_reason) when
        return_stop_reason is True.
    """
    client = _get_client()
    resolved_model = model or _config.get("model", "claude-sonnet-5")
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
    # A completion that stopped for any reason other than end_turn/stop_sequence
    # is suspect — max_tokens truncates mid-text, refusal yields little or none.
    # Warn loudly so it isn't silently written into a corpus; callers that build
    # training records should also reject on stop_reason via return_stop_reason.
    if response.stop_reason not in ("end_turn", "stop_sequence"):
        print(f"  WARNING: response stop_reason={response.stop_reason!r} "
              f"(model {resolved_model}, max_tokens {resolved_max}) — output may be "
              "truncated or refused.", file=sys.stderr)
    text = _response_text(response)
    return (text, response.stop_reason) if return_stop_reason else text


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
