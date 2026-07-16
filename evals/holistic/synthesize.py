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
    sections = parsed.get("sections")
    if not isinstance(sections, list):
        errors.append("sections: missing or not a list")
    elif not all(isinstance(s, dict) and isinstance(s.get("title"), str)
                 and isinstance(s.get("body"), str) for s in sections):
        errors.append("sections: every item must be an object with string title and body")
    if "verdict" in parsed and not isinstance(parsed.get("verdict"), str):
        errors.append("verdict: present but not a string")
    top_issues = parsed.get("top_issues")
    if not isinstance(top_issues, list):
        errors.append("top_issues: missing or not a list")
    elif not all(isinstance(issue, dict) for issue in top_issues):
        errors.append("top_issues: every item must be an object")
    return errors


def synthesize(stats: dict, *, template: str, model: str | None = None,
               max_tokens: int = 8000, temperature: float = 0.0) -> dict:
    """Run the editable holistic prompt over ``stats`` (which may carry a bounded
    ``semantic`` summary). Returns ``{"verdict": str, "sections": list, "top_issues":
    list, "raw": str, "errors": list}``. Unparseable/mis-shaped output yields empty
    best-effort fields plus an explicit ``errors`` list."""
    _require_template_tokens(template)
    prompt = template.replace(STATS_TOKEN, json.dumps(stats, indent=2, ensure_ascii=False))
    raw = providers.call_model(prompt, "", model,
                               max_tokens=max_tokens, temperature=temperature)
    parsed = extract.parse_json(raw)
    if not parsed:
        return {"verdict": "", "sections": [], "top_issues": [], "raw": raw,
                "errors": ["unparseable synthesis model output"]}
    return {
        "verdict": parsed.get("verdict", "") if isinstance(parsed.get("verdict"), str) else "",
        "sections": parsed.get("sections", []) if isinstance(parsed.get("sections"), list) else [],
        "top_issues": parsed.get("top_issues", []) if isinstance(parsed.get("top_issues"), list) else [],
        "raw": raw,
        "errors": _shape_errors(parsed),
    }
