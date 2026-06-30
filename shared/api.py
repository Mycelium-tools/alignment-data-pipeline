"""API wrapper with retry logic and cost tracking. Supports Anthropic and Gemini."""

import os
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Any

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
_anthropic_client: anthropic.Anthropic | None = None
_gemini_client: Any | None = None
_cost_log_path: Path | None = None

_ANTHROPIC_PRICING = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-8": (15.00, 75.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
}

# Pricing per million tokens (input, output)
_GEMINI_PRICING = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
}


def _provider_for_model(model: str) -> str:
    return "gemini" if model.startswith("gemini") else "anthropic"


def init(config_path: str = "config.yaml") -> None:
    global _config, _anthropic_client, _gemini_client, _cost_log_path
    with open(config_path) as f:
        _config = yaml.safe_load(f)

    if os.environ.get("ANTHROPIC_API_KEY"):
        _anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    if os.environ.get("GEMINI_API_KEY"):
        try:
            from google import genai as _genai
            _gemini_client = _genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        except ImportError as e:
            raise ImportError(
                "google-genai package required for Gemini support. Run: pip install google-genai"
            ) from e

    _cost_log_path = Path(_config["outputs"]["cost_log"])
    _cost_log_path.parent.mkdir(parents=True, exist_ok=True)


def _get_anthropic_client() -> anthropic.Anthropic:
    if _anthropic_client is None:
        init()
    return _anthropic_client


def _get_gemini_client() -> Any:
    if _gemini_client is None:
        raise RuntimeError(
            "Gemini client not initialized. Set GEMINI_API_KEY in your .env file."
        )
    return _gemini_client


def _log_usage(model: str, input_tokens: int, output_tokens: int) -> None:
    if model.startswith("gemini"):
        prices = _GEMINI_PRICING.get(model, (0.30, 2.50))
    else:
        prices = _ANTHROPIC_PRICING.get(model, (3.00, 15.00))
    cost = (input_tokens / 1_000_000) * prices[0] + (output_tokens / 1_000_000) * prices[1]
    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
    }
    with open(_cost_log_path, "a") as f:
        f.write(json.dumps(record) + "\n")


@retry(
    retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIStatusError)),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(8),
)
def _call_anthropic_with_retry(
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


def _call_gemini(
    model: str,
    max_tokens: int,
    system: str,
    user_message: str,
) -> tuple[str, int, int]:
    """Call Gemini and return (text, input_tokens, output_tokens)."""
    from google.genai import types as _gtypes
    from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable

    client = _get_gemini_client()
    config = _gtypes.GenerateContentConfig(
        system_instruction=system or None,
        max_output_tokens=max_tokens,
    )

    last_exc: Exception | None = None
    for attempt in range(8):
        try:
            response = client.models.generate_content(
                model=model,
                contents=user_message,
                config=config,
            )
            usage = response.usage_metadata
            return (
                response.text,
                usage.prompt_token_count or 0,
                usage.candidates_token_count or 0,
            )
        except (ResourceExhausted, ServiceUnavailable) as e:
            last_exc = e
            wait = min(4 * (2 ** attempt), 60)
            time.sleep(wait)
    raise last_exc


def call_model(
    user_message: str,
    system_prompt: str = "",
    injection: str = "",
    model: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """Call the configured model and return the response text.

    Provider is inferred from the model name: gemini-* uses Gemini, claude-* uses Anthropic.
    """
    resolved_model = model or _config.get("model", "claude-sonnet-4-6")
    resolved_max = max_tokens or _config.get("max_tokens", 4000)

    full_system = system_prompt
    if injection:
        full_system = (full_system + "\n\n" + injection).strip()

    provider = _provider_for_model(resolved_model)

    if provider == "gemini":
        text, input_tokens, output_tokens = _call_gemini(
            model=resolved_model,
            max_tokens=resolved_max,
            system=full_system,
            user_message=user_message,
        )
    else:
        client = _get_anthropic_client()
        response = _call_anthropic_with_retry(
            client=client,
            model=resolved_model,
            max_tokens=resolved_max,
            system=full_system,
            messages=[{"role": "user", "content": user_message}],
        )
        text = response.content[0].text
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

    _log_usage(resolved_model, input_tokens, output_tokens)
    return text


# Backward-compatible alias
call_claude = call_model


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
