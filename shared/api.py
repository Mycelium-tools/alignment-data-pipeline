"""Anthropic API wrapper with retry logic and cost tracking.

Two backends behind the same call_claude() contract:
- "api" (default): the anthropic SDK, billed to the shared ANTHROPIC_API_KEY.
- "claude_code": the Claude Agent SDK driving the Claude Code CLI, billed to
  the contributor's own Claude subscription (Claude Code login, or a
  CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`).

Select via the `backend` key in config.yaml. See README "Authentication".
"""

import os
import json
import re
import sys
import threading
from pathlib import Path
from datetime import datetime

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
_backend: str = "api"
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

_BACKENDS = ("api", "claude_code")

# Matches only subscription-window exhaustion (Claude Code reports this as
# "Claude AI usage limit reached|<reset-timestamp>"), which must abort rather
# than retry. Deliberately narrow: a transient CLI "rate limit" hiccup should
# fall through to the retried ClaudeCodeError path, so we don't match bare
# "rate limit" / "limit reached" here.
_LIMIT_PATTERN = re.compile(r"usage limit", re.IGNORECASE)

# Claude Code treats an empty --system-prompt as unset and substitutes its own
# agentic CLI prompt, which leaks tool/codebase behavior into generated text.
# Stages that send no system prompt get this neutral stand-in instead.
_NEUTRAL_SYSTEM = "You are Claude, a helpful AI assistant. Respond directly to the user's message."


class UsageLimitExceeded(Exception):
    """Claude subscription usage window exhausted (claude_code backend).

    Not retried: the 5-hour window can take hours to reset. Checkpoints are
    written after every call, so the run can continue later with --resume.
    """


class ClaudeCodeError(Exception):
    """Transient claude_code backend failure; retried by tenacity."""


def init(config_path: str = "config.yaml", cost_log_path: str | Path | None = None) -> None:
    global _config, _client, _cost_log_path, _backend
    with open(config_path) as f:
        _config = yaml.safe_load(f)
    _backend = _config.get("backend", "api")
    if _backend not in _BACKENDS:
        raise ValueError(f"config backend must be one of {_BACKENDS}, got {_backend!r}")
    _client = None  # constructed lazily; the claude_code backend needs no API key
    _cost_log_path = Path(cost_log_path or _config["outputs"]["cost_log"])
    _cost_log_path.parent.mkdir(parents=True, exist_ok=True)


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "backend 'api' requires ANTHROPIC_API_KEY in .env; "
                "set it, or switch config.yaml to backend: claude_code"
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _log_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None = None,
) -> None:
    # claude_code passes Claude Code's own reported cost; the api backend leaves
    # cost_usd=None, so we price it from _PRICING with a loud fallback on unknown
    # models (a mispriced run shouldn't hide in the log).
    if cost_usd is None:
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
        cost_usd = (input_tokens / 1_000_000) * prices[0] + (output_tokens / 1_000_000) * prices[1]
    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "model": model,
        # For claude_code, cost_usd is notional (what the call would have cost
        # at API prices) — actual billing is the contributor's subscription.
        "backend": _backend,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 6),
    }
    with _cost_log_lock, open(_cost_log_path, "a") as f:
        f.write(json.dumps(record) + "\n")


@retry(
    retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIStatusError)),
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


def _classify_claude_code_error(message: str) -> Exception:
    if _LIMIT_PATTERN.search(message):
        return UsageLimitExceeded(
            f"Claude subscription usage limit reached: {message}\n"
            "Progress is checkpointed — wait for your usage window to reset, "
            "then continue this run with --resume."
        )
    return ClaudeCodeError(message)


@retry(
    retry=retry_if_exception_type(ClaudeCodeError),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(8),
)
def _call_claude_code_with_retry(
    model: str,
    system: str,
    user_message: str,
) -> tuple[str, int, int, float | None]:
    """Single-turn text generation via the Claude Code CLI (subscription auth).

    Returns (text, input_tokens, output_tokens, notional_cost_usd).
    """
    try:
        import anyio
        from claude_agent_sdk import CLINotFoundError, ClaudeAgentOptions, query
        from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock
    except ImportError as e:
        raise RuntimeError(
            "backend 'claude_code' requires the claude-agent-sdk package; "
            "run: pip install -r requirements.txt"
        ) from e

    options = ClaudeAgentOptions(
        model=model,
        system_prompt=system or _NEUTRAL_SYSTEM,
        tools=[],  # pure text generation: no file/bash/web access
        max_turns=1,
        thinking={"type": "disabled"},  # training data must show user-facing reasoning only
        # Hermetic run: without these, the CLI loads the contributor's own
        # ~/.claude settings (custom agents, plan-by-default permission modes,
        # hooks), which leaks agentic scaffolding into generated text.
        setting_sources=[],
        permission_mode="default",
        # Blank out any key loaded from .env so the subprocess can't silently
        # bill the shared API key — Claude Code treats an empty value as unset
        # and falls back to its own login / CLAUDE_CODE_OAUTH_TOKEN.
        env={"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": ""},
    )

    async def _run() -> tuple[list[str], object | None]:
        text_parts: list[str] = []
        result_msg = None
        async for msg in query(prompt=user_message, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text_parts.append(block.text)
            elif isinstance(msg, ResultMessage):
                result_msg = msg
        return text_parts, result_msg

    try:
        text_parts, result_msg = anyio.run(_run)
    except CLINotFoundError as e:
        raise RuntimeError(
            "backend 'claude_code' requires the Claude Code CLI "
            "(https://claude.com/claude-code); install it, then log in "
            "or set CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`."
        ) from e
    except Exception as e:  # CLI failures surface as assorted exception types
        raise _classify_claude_code_error(str(e)) from e

    if result_msg is None:
        raise ClaudeCodeError("claude_code backend returned no result message")
    if result_msg.is_error:
        raise _classify_claude_code_error(result_msg.result or result_msg.subtype)

    text = result_msg.result if result_msg.result is not None else "".join(text_parts)
    usage = result_msg.usage or {}
    return (
        text,
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
        result_msg.total_cost_usd,
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
        max_tokens: Token limit override; falls back to config value. Enforced
            on the api backend only — Claude Code applies its own output cap,
            and the pipeline's caps exist to bound per-token API cost, which
            does not apply to subscription usage.

    Returns:
        The assistant's response text.
    """
    if not _config:
        init()
    resolved_model = model or _config.get("model", "claude-sonnet-4-6")
    resolved_max = max_tokens or _config.get("max_tokens", 4000)

    full_system = system_prompt
    if injection:
        full_system = (full_system + "\n\n" + injection).strip()

    if _backend == "claude_code":
        text, input_tokens, output_tokens, cost = _call_claude_code_with_retry(
            model=resolved_model,
            system=full_system,
            user_message=user_message,
        )
        _log_usage(resolved_model, input_tokens, output_tokens, cost_usd=cost)
        return text

    response = _call_with_retry(
        client=_get_client(),
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
