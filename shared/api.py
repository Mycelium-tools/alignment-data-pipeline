"""Anthropic API wrapper with retry logic and cost tracking.

Two backends behind the same call_claude() contract:
- "api" (default): the anthropic SDK, billed to the shared ANTHROPIC_API_KEY.
- "claude_code": the Claude Agent SDK driving the Claude Code CLI, billed to
  the contributor's own Claude subscription (Claude Code login, or a
  CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`).

Select via the `backend` key in config.yaml. See README "Authentication".
"""

import contextlib
import os
import json
import re
import sys
import tempfile
import threading
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

# Matches subscription-limit exhaustion, which must abort rather than retry.
# Two message families qualify: "Claude AI usage limit reached|<reset-timestamp>"
# (the 5-hour window), and "You've hit your org's monthly spend limit" — which
# orgs that DISABLE usage-billing overflow receive in place of the window
# message, so it too usually means the window resets in a few hours (observed
# on the 2026-07-08 overnight SDF run, where it burned 8 tenacity retries per
# call and killed the run instead of pausing for --resume). Deliberately
# narrow otherwise: a transient CLI "rate limit" hiccup should fall through to
# the retried ClaudeCodeError path, so we don't match bare "rate limit" /
# "limit reached" here.
_LIMIT_PATTERN = re.compile(r"usage limit|spend limit", re.IGNORECASE)

# Claude Code treats an empty --system-prompt as unset and substitutes its own
# agentic CLI prompt, which leaks tool/codebase behavior into generated text.
# Stages that send no system prompt get this neutral stand-in instead. Note this
# means a genuinely empty system prompt is not reproducible on this backend — the
# DAD pipeline's response steps (which send no system prompt) are therefore not
# reproduced exactly here; use backend: api for runs where that matters.
_NEUTRAL_SYSTEM = "You are Claude, a helpful AI assistant. Respond directly to the user's message."
_neutral_system_warned = False
_temperature_warned = False

# Linux caps each argv string at 128 KiB (MAX_ARG_STRLEN), and a str
# system_prompt reaches the CLI as a single --system-prompt argument — so the
# ~185 KB constitution (SDF layers 4-5) aborts the spawn with E2BIG on Linux.
# System prompts over this many UTF-8 bytes travel via --system-prompt-file.
_CC_SYSTEM_ARG_MAX_BYTES = 100_000


class UsageLimitExceeded(Exception):
    """Claude subscription usage window exhausted (claude_code backend).

    Not retried: the 5-hour window can take hours to reset. Checkpoints are
    written after every call, so the run can continue later with --resume.
    """


class ClaudeCodeError(Exception):
    """Transient claude_code backend failure; retried by tenacity."""


def init(config_path: str = "config.yaml", cost_log_path: str | Path | None = None) -> None:
    global _config, _client, _cost_log_path, _backend
    with open(config_path, encoding="utf-8") as f:
        _config = yaml.safe_load(f)
    _backend = _config.get("backend", "api")
    if _backend not in _BACKENDS:
        raise ValueError(f"config backend must be one of {_BACKENDS}, got {_backend!r}")
    # The api backend needs the key; fail loudly here rather than deep in a run.
    # The claude_code backend authenticates via the Claude Code CLI, so no key.
    if _backend == "api" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise KeyError("ANTHROPIC_API_KEY")
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
    stage: str | None = None,
    item_id: str | None = None,
    duration_s: float | None = None,
    attempts: int | None = None,
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
        "timestamp": datetime.now(UTC).isoformat(),
        "model": model,
        # For claude_code, cost_usd is notional (what the call would have cost
        # at API prices) — actual billing is the contributor's subscription.
        "backend": _backend,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 6),
    }
    if stage:
        record["stage"] = stage
    if item_id:
        record["item_id"] = item_id
    if duration_s is not None:
        record["duration_s"] = round(duration_s, 2)
    if attempts is not None:
        record["attempts"] = attempts
    with _cost_log_lock, open(_cost_log_path, "a", encoding="utf-8") as f:
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

# Attempt counter for the cost log. Thread-local because call_claude runs from
# parallel_map worker threads; tenacity's own .statistics is shared across
# threads and would misattribute counts.
_attempt_state = threading.local()


def _note_attempt(retry_state) -> None:
    _attempt_state.n = retry_state.attempt_number


@retry(
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(8),
    before=_note_attempt,
)
def _call_with_retry(
    client: anthropic.Anthropic,
    model: str,
    max_tokens: int,
    system: str,
    messages: list[dict],
    temperature: float,
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
        temperature=temperature,
        thinking={"type": "disabled"},
    )


def _response_text(response: anthropic.types.Message) -> str:
    """Concatenate the text blocks of a response, skipping any non-text blocks
    (e.g. a thinking block that slips through). Returns '' if there is no text."""
    return "".join(
        block.text for block in response.content
        if getattr(block, "type", None) == "text"
    )


def _classify_claude_code_error(message: str) -> Exception:
    if _LIMIT_PATTERN.search(message):
        return UsageLimitExceeded(
            f"Claude subscription usage limit reached: {message}\n"
            "Progress is checkpointed — wait for your usage window to reset, "
            "then continue this run with --resume."
        )
    return ClaudeCodeError(message)


def _resolve_cc_system(system: str) -> str:
    """Effective system prompt for the claude_code backend.

    Claude Code injects its own agentic prompt when the system is empty, so an
    empty system gets a neutral stand-in. Warn once so the substitution — which
    notably changes the DAD `plain` condition — isn't silent.
    """
    global _neutral_system_warned
    if system:
        return system
    if not _neutral_system_warned:
        _neutral_system_warned = True
        print(
            "  WARNING: backend 'claude_code' substitutes a neutral system prompt for "
            "empty-system calls (Claude Code injects its own agentic prompt otherwise). "
            "Stages that rely on a truly empty system prompt are not reproduced faithfully "
            "here — notably the DAD response steps. Use backend: api for those.",
            file=sys.stderr,
        )
    return _NEUTRAL_SYSTEM


def _run_claude_code_query(
    model: str,
    system: str,
    user_message: str,
) -> tuple[str, int, int, float | None, str | None]:
    """One Claude Code CLI turn: run the query and parse the result into
    (text, input_tokens, output_tokens, notional_cost_usd, stop_reason).

    Raises UsageLimitExceeded / ClaudeCodeError on failure; the retry wrapper
    (_call_claude_code_with_retry) decides whether to retry. Kept separate from
    that wrapper so this parse — the money path — is unit-testable by stubbing
    claude_agent_sdk.query, without triggering tenacity's backoff.
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

    resolved_system = _resolve_cc_system(system)
    system_file: str | None = None
    if len(resolved_system.encode("utf-8")) > _CC_SYSTEM_ARG_MAX_BYTES:
        fd, system_file = tempfile.mkstemp(prefix="claude_code_system_", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(resolved_system)

    options = ClaudeAgentOptions(
        model=model,
        system_prompt=(
            {"type": "file", "path": system_file}
            if system_file is not None
            else resolved_system
        ),
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
        stream = query(prompt=user_message, options=options)
        try:
            async for msg in stream:
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            text_parts.append(block.text)
                elif isinstance(msg, ResultMessage):
                    # The result is final for our single-turn calls — stop here.
                    # After an is_error result the CLI exits non-zero; reading
                    # past the result turns that exit into a ProcessError whose
                    # text drops result_msg.result (the CLI's actual error),
                    # masking the is_error handling below and its usage-limit
                    # classification.
                    result_msg = msg
                    break
        finally:
            await stream.aclose()
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
    finally:
        if system_file is not None:
            with contextlib.suppress(OSError):
                os.unlink(system_file)

    if result_msg is None:
        raise ClaudeCodeError("claude_code backend returned no result message")
    if result_msg.is_error:
        raise _classify_claude_code_error(
            result_msg.result or result_msg.subtype or "unknown claude_code error"
        )

    text = result_msg.result if result_msg.result is not None else "".join(text_parts)
    usage = result_msg.usage or {}
    return (
        text,
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
        result_msg.total_cost_usd,
        result_msg.stop_reason,
    )


@retry(
    retry=retry_if_exception_type(ClaudeCodeError),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(8),
    before=_note_attempt,
)
def _call_claude_code_with_retry(
    model: str,
    system: str,
    user_message: str,
) -> tuple[str, int, int, float | None, str | None]:
    """Retry wrapper around _run_claude_code_query (transient ClaudeCodeError
    only; UsageLimitExceeded is not retried). This is the seam call_claude uses
    and that the test suite blocks."""
    return _run_claude_code_query(model, system, user_message)


def call_claude(
    user_message: str,
    system_prompt: str = "",
    injection: str = "",
    model: str | None = None,
    max_tokens: int | None = None,
    return_stop_reason: bool = False,
    stage: str | None = None,
    temperature: float | None = None,
    item_id: str | None = None,
) -> str | tuple[str, str | None]:
    """Call Claude and return the response text.

    Args:
        user_message: The user turn content.
        system_prompt: Optional system prompt.
        injection: Optional text appended to the system prompt.
        model: Model override; falls back to config value.
        max_tokens: Token limit override; falls back to config value. Enforced
            on the api backend only — Claude Code applies its own output cap,
            and the pipeline's caps exist to bound per-token API cost, which
            does not apply to subscription usage.
        return_stop_reason: if True, return (text, stop_reason) so the caller can
            reject truncated/refused completions instead of storing them.
        stage: Pipeline-stage tag written into the cost-log record (e.g.
            "prompt_draft", "layer4") so spend can be broken down per stage.
        temperature: Sampling temperature override for this call; falls back to
            the config `temperature` (1.0 — corpus generation wants diversity).
        item_id: Id of the pipeline record this call serves (e.g. a prompt_id
            or response_id; comma-joined ids for a batched call), written into
            the cost-log record so per-record stats can be looked up later.

    Returns:
        The assistant's response text, or (text, stop_reason) when
        return_stop_reason is True.
    """
    resolved_model = model or _config.get("model", "claude-sonnet-5")
    resolved_max = max_tokens or _config.get("max_tokens", 4000)
    resolved_temp = temperature if temperature is not None else _config.get("temperature", 1.0)

    full_system = system_prompt
    if injection:
        full_system = (full_system + "\n\n" + injection).strip()

    _attempt_state.n = 1  # _note_attempt overwrites this on every real attempt
    started = time.monotonic()

    if _backend == "claude_code":
        # The Claude Code CLI exposes no sampling-temperature control, so a
        # non-default temperature cannot be honored on this backend. The config
        # default (1.0) matches normal sampling, so only deliberate overrides
        # warrant the warning.
        global _temperature_warned
        if resolved_temp != 1.0 and not _temperature_warned:
            _temperature_warned = True
            print(
                f"  WARNING: temperature={resolved_temp} requested, but backend "
                "'claude_code' cannot set sampling temperature — calls run at the "
                "CLI's default sampling. Use backend: api for temperature-sensitive runs.",
                file=sys.stderr,
            )
        text, input_tokens, output_tokens, cost, stop_reason = _call_claude_code_with_retry(
            model=resolved_model,
            system=full_system,
            user_message=user_message,
        )
        _log_usage(resolved_model, input_tokens, output_tokens, cost_usd=cost, stage=stage,
                   item_id=item_id, duration_s=time.monotonic() - started,
                   attempts=_attempt_state.n)
        # Same suspect-stop-reason guard as the api path below; Claude Code
        # reports stop_reason on its ResultMessage (e.g. "end_turn").
        if stop_reason not in ("end_turn", "stop_sequence"):
            print(f"  WARNING: response stop_reason={stop_reason!r} "
                  f"(model {resolved_model}, backend claude_code) — output may be "
                  "truncated or refused.", file=sys.stderr)
        return (text, stop_reason) if return_stop_reason else text

    response = _call_with_retry(
        client=_get_client(),
        model=resolved_model,
        max_tokens=resolved_max,
        system=full_system,
        messages=[{"role": "user", "content": user_message}],
        temperature=resolved_temp,
    )

    _log_usage(resolved_model, response.usage.input_tokens, response.usage.output_tokens,
               stage=stage, item_id=item_id,
               duration_s=time.monotonic() - started, attempts=_attempt_state.n)
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
    with open(_cost_log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                total += json.loads(line).get("cost_usd", 0.0)
    return round(total, 4)
