"""Provider dispatch for eval-lane model calls.

``call_model`` routes ``gemini-*`` model names to the Gemini API (AI Studio key or
Vertex AI) and everything else — including ``None``, the config default — to
``shared.api.call_claude``. Moved out of ``evals/judge.py`` so the quality judge,
the holistic extraction judge, and the synthesis pass share one dispatch; a future
provider (OpenAI, ...) is one client function + one prefix here. Gemini usage is
logged through the same ``shared.api`` cost log as Anthropic calls.

Deliberately eval-lane only: the generation pipelines call ``shared.api.call_claude``
directly and are out of scope (training-data provenance stays Claude).
"""

from __future__ import annotations

import os

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from shared import api

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
VERTEX_URL = ("https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/"
              "publishers/google/models/{model}:generateContent")


_vertex_creds = None  # cached ADC credentials; refreshed per call when expired


def _vertex_token() -> str:
    """OAuth bearer token via Application Default Credentials — Vertex AI rejects
    plain API keys. Point GOOGLE_APPLICATION_CREDENTIALS at a service-account JSON
    (role: Vertex AI User) in the billed project."""
    global _vertex_creds
    try:
        import google.auth
        import google.auth.transport.requests
    except ImportError:
        raise RuntimeError("VERTEX_PROJECT is set but google-auth is not installed — "
                           "pip install google-auth (it is in requirements.txt).")
    if _vertex_creds is None:
        _vertex_creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not _vertex_creds.valid:
        _vertex_creds.refresh(google.auth.transport.requests.Request())
    return _vertex_creds.token


def _gemini_endpoint(model: str) -> tuple[str, dict]:
    """(url, auth headers). With VERTEX_PROJECT set, calls route through Vertex AI
    and bill that Cloud project (so free-trial credits apply); otherwise the
    AI Studio GEMINI_API_KEY path is used. Request/response bodies are identical."""
    project = os.environ.get("VERTEX_PROJECT")
    if project:
        return (VERTEX_URL.format(project=project, model=model),
                {"Authorization": f"Bearer {_vertex_token()}"})
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("Neither GEMINI_API_KEY nor VERTEX_PROJECT is set — "
                           "add one to .env to use Gemini models.")
    return GEMINI_URL.format(model=model), {"x-goog-api-key": key}


class _GeminiRetryable(Exception):
    pass


@retry(retry=retry_if_exception_type(_GeminiRetryable),
       wait=wait_exponential(multiplier=2, min=4, max=60), stop=stop_after_attempt(6))
def _call_gemini(user_message: str, system_prompt: str, model: str,
                 temperature: float, max_tokens: int) -> str:
    url, headers = _gemini_endpoint(model)
    body = {
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system_prompt:
        # an empty systemInstruction part is rejected by the API — omit it entirely
        body["systemInstruction"] = {"parts": [{"text": system_prompt}]}
    resp = httpx.post(url, headers=headers, json=body, timeout=300)
    if resp.status_code in (429, 500, 502, 503, 504):
        raise _GeminiRetryable(f"HTTP {resp.status_code}: {resp.text[:200]}")
    resp.raise_for_status()
    data = resp.json()
    candidate = data["candidates"][0]
    text = "".join(p.get("text", "")
                   for p in candidate.get("content", {}).get("parts", []))
    if not text.strip():
        # Gemini 3 thinking models can burn the whole output budget on thoughts and
        # emit nothing visible — surface the reason instead of a bare parse failure.
        usage = data.get("usageMetadata", {})
        raise ValueError(
            f"empty response (finishReason={candidate.get('finishReason')}, "
            f"thoughts={usage.get('thoughtsTokenCount', 0)} of max {max_tokens} tokens)")
    usage = data.get("usageMetadata", {})
    # thoughts bill at the output rate too — for thinking-default models they are
    # most of the output spend, so omitting them would badly undercount the log
    api._log_usage(model, usage.get("promptTokenCount", 0),
                   usage.get("candidatesTokenCount", 0)
                   + usage.get("thoughtsTokenCount", 0))
    return text


def call_model(user_message: str, system_prompt: str, model: str | None,
               temperature: float = 0.0, max_tokens: int = 4000) -> str:
    """Provider dispatch: gemini-* via the Gemini API, everything else — including
    ``None`` (the config-default model) — via shared.api."""
    if model and model.startswith("gemini"):
        # Gemini caches large repeated prefixes implicitly; no explicit marker needed.
        return _call_gemini(user_message, system_prompt, model, temperature, max_tokens)
    # Anthropic system prompts repeated across a run (rubrics, extraction schemas)
    # are byte-identical — mark them as a cache breakpoint for the 0.1x input rate.
    return api.call_claude(user_message=user_message, system_prompt=system_prompt,
                           model=model, max_tokens=max_tokens, temperature=temperature,
                           cache_system=True)
