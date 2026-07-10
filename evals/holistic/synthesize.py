"""Holistic synthesis — the LLM pass that reads the computed stats (never the raw
corpus) and writes a plain-English assessment plus a ranked ``top_issues`` list.

The prompt is an editable template: ``{{STATS}}`` is replaced with the stats JSON.
Edit ``prompts/tools/dad_holistic_synthesis.txt`` (or pass any template text) and
rerun to change how the run is assessed — no Python edits.
"""

from __future__ import annotations

import json

from shared import providers

from . import extract

STATS_TOKEN = "{{STATS}}"


def _require_template_tokens(template: str) -> None:
    if STATS_TOKEN not in template:
        raise ValueError(
            f"holistic synthesis prompt template missing required token: {STATS_TOKEN}")


def _shape_errors(parsed: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(parsed.get("prose"), str):
        errors.append("prose: missing or not a string")
    top_issues = parsed.get("top_issues")
    if not isinstance(top_issues, list):
        errors.append("top_issues: missing or not a list")
    elif not all(isinstance(issue, dict) for issue in top_issues):
        errors.append("top_issues: every item must be an object")
    return errors


def synthesize(stats: dict, *, template: str, model: str | None = None,
               max_tokens: int = 4000, temperature: float = 0.0) -> dict:
    """Run the editable holistic prompt over ``stats``. Returns
    ``{"prose": str, "top_issues": list, "raw": str, "errors": list}``. A response
    that does not parse yields empty prose/issues with an explicit error."""
    _require_template_tokens(template)
    prompt = template.replace(STATS_TOKEN, json.dumps(stats, indent=2, ensure_ascii=False))
    raw = providers.call_model(prompt, "", model,
                               max_tokens=max_tokens, temperature=temperature)
    parsed = extract.parse_json(raw)
    if not parsed:
        return {
            "prose": "",
            "top_issues": [],
            "raw": raw,
            "errors": ["unparseable synthesis model output"],
        }
    errors = _shape_errors(parsed)
    if errors:
        return {
            "prose": parsed.get("prose", "") if isinstance(parsed.get("prose"), str) else "",
            "top_issues": parsed.get("top_issues", [])
                          if isinstance(parsed.get("top_issues"), list) else [],
            "raw": raw,
            "errors": errors,
        }
    return {
        "prose": parsed.get("prose", ""),
        "top_issues": parsed.get("top_issues", []),
        "raw": raw,
        "errors": [],
    }
