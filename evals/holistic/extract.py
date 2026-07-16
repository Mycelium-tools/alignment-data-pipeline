"""Extraction runner — tags each conversation with its categorical axes.

Everything here is driven by a ``FieldRegistry`` (``evals.holistic.fields``): the
system prompt is rendered from the registered fields, and model output is validated
against them. Swap the registry and the whole extraction behaviour changes with no
edits here. The only external dependency is ``shared.providers.call_model``
(gemini-* models route to the Gemini API; everything else — including the config
default — to the single stubbable ``shared.api.call_claude`` chokepoint); the
runner never raises — a bad model response becomes an explicit error row, never a
silent default.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared import providers, utils

from .fields import Field, FieldRegistry

MODEL_DEFAULT = None       # falls back to config's model
MAX_TOKENS = 8192         # generous ceiling; thinking judges (e.g. gemini-*-pro)
                          # spend most of the budget on reasoning before the JSON
TEMPERATURE = 0.0


# ---------------------------------------------------------------- prompt

def _render_field(fld: Field) -> str:
    vocab = f"  one of: {', '.join(fld.values)}" if fld.values else "  (free text)"
    req = "required" if fld.required else "optional"
    return (f"- {fld.name} [{fld.kind}, {req}, from {fld.derived_from}]: "
            f"{fld.prompt_hint}\n{vocab}")


# Tokens an editable prompt template may use (replaced, not str.format'd, so the
# template can contain literal JSON braces freely).
FIELDS_TOKEN = "{{FIELDS}}"
KEYS_TOKEN = "{{KEYS}}"


def _require_template_tokens(template: str, tokens: tuple[str, ...]) -> None:
    missing = [token for token in tokens if token not in template]
    if missing:
        raise ValueError(
            "extraction prompt template missing required token(s): "
            + ", ".join(missing))


def build_system_prompt(fields: FieldRegistry, template: str | None = None) -> str:
    """Render the extractor's system prompt from the current registry. Adding a field
    to the registry adds it here automatically — nothing about the schema is hardcoded.

    If ``template`` is given (an editable prompt file's text), ``{{FIELDS}}`` is
    replaced with the rendered field block and ``{{KEYS}}`` with the JSON key list;
    otherwise a built-in default wrapper is used."""
    field_block = "\n".join(_render_field(f) for f in fields.all())
    keys = ", ".join(f'"{f.name}"' for f in fields.all())
    if template is not None:
        _require_template_tokens(template, (FIELDS_TOKEN, KEYS_TOKEN))
        return template.replace(FIELDS_TOKEN, field_block).replace(KEYS_TOKEN, keys)
    return "\n".join([
        "You tag one animal-welfare dilemma conversation with categorical metadata.",
        "Read the conversation and assign each field below from the finished text alone.",
        "",
        "FIELDS:",
        field_block,
        "",
        "Output ONLY a single JSON object with exactly these keys: " + keys + ".",
        "Use the exact vocabulary strings given. Do not add commentary.",
    ])


def render_conversation(messages: list[dict]) -> str:
    return "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)


# ---------------------------------------------------------------- parsing

def _iter_brace_objects(text: str):
    """Yield each ``{...}`` substring with balanced braces, in start order. Naive
    (does not exclude braces inside strings) but good enough for tag JSON, and it
    tries candidates in order so a stray ``{...}`` before the real object is skipped."""
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                yield text[start:i + 1]


def parse_json(text: str) -> dict:
    """Best-effort extraction of a single JSON object from model output; tolerates
    markdown fences and surrounding prose (including a stray ``{...}`` before the real
    object). Returns ``{}`` when nothing parses."""
    if not text:
        return {}
    try:
        val = json.loads(text)
        if isinstance(val, dict):
            return val
    except json.JSONDecodeError:
        pass
    for candidate in _iter_brace_objects(text):
        try:
            val = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(val, dict):
            return val
    return {}


# ---------------------------------------------------------------- validation

def validate(raw: dict, fields: FieldRegistry) -> tuple[dict, list[str]]:
    """Validate a parsed record against the registry. Returns ``(tags, errors)``:
    ``tags`` holds the coerced value for every field present; ``errors`` names each
    missing-required or out-of-vocabulary field (empty list = clean)."""
    tags: dict[str, Any] = {}
    errors: list[str] = []
    for fld in fields.all():
        if fld.name not in raw:
            if fld.required:
                errors.append(f"{fld.name}: missing")
            continue
        ok, coerced = fld.validate(raw[fld.name])
        tags[fld.name] = coerced
        if not ok:
            errors.append(f"{fld.name}: invalid value {raw[fld.name]!r}")
    return tags, errors


# ---------------------------------------------------------------- per-record

def extract_record(messages: list[dict], fields: FieldRegistry, *,
                   record_id: str | None = None, model: str | None = MODEL_DEFAULT,
                   temperature: float = TEMPERATURE, max_tokens: int = MAX_TOKENS,
                   system_prompt: str | None = None) -> dict:
    """Tag one conversation. Returns ``{record_id, tags|None, errors, raw}``. On an
    unparseable response ``tags`` is None and ``errors`` says so; on an in-vocabulary
    response ``errors`` is empty; on a parseable-but-off-vocabulary response ``tags``
    carries the coerced values and ``errors`` lists the offending fields."""
    sp = system_prompt if system_prompt is not None else build_system_prompt(fields)
    raw_text = providers.call_model(
        render_conversation(messages), sp, model,
        temperature=temperature, max_tokens=max_tokens)
    parsed = parse_json(raw_text)
    if not parsed:
        return {"record_id": record_id, "tags": None,
                "errors": ["unparseable model output"], "raw": raw_text}
    tags, errors = validate(parsed, fields)
    return {"record_id": record_id, "tags": tags, "errors": errors, "raw": raw_text}


def _row(record_id: str, res: dict) -> dict:
    """Flatten an extract_record result into a category_records.jsonl row."""
    if res["tags"] is None:
        return {"record_id": record_id, "extract_error": res["errors"][0]}
    row = {"record_id": record_id, **res["tags"]}
    if res["errors"]:
        row["_errors"] = res["errors"]   # coerced but imperfect; kept for telemetry
    return row


# ---------------------------------------------------------------- corpus

def extract_corpus(records: list[dict], fields: FieldRegistry, out_path: str | Path, *,
                   model: str | None = MODEL_DEFAULT, resume: bool = True,
                   temperature: float = TEMPERATURE, template: str | None = None) -> list[dict]:
    """Tag every record, writing one row per record to ``out_path``. Resume-safe:
    successfully-tagged record_ids are skipped (zero API calls); prior ``extract_error``
    rows for records in this corpus are dropped and retried. ``resume=False`` re-tags
    every record in *this* corpus but keeps rows for records outside it (so a CLI
    selection can force-re-tag a subset without destroying the rest of the index).
    The index is rewritten once with the surviving prior rows (so no duplicate
    record_ids accumulate), then new rows are appended as they complete.
    Returns the rows written *this* invocation."""
    out_path = Path(out_path)
    corpus_ids = {rec["record_id"] for rec in records}
    prior = utils.load_jsonl(out_path)
    if resume:
        # Keep prior rows except error rows for records we are about to re-attempt.
        kept = [r for r in prior
                if not (r.get("record_id") in corpus_ids and "extract_error" in r)]
    else:
        kept = [r for r in prior if r.get("record_id") not in corpus_ids]
    done = {r["record_id"] for r in kept
            if "record_id" in r and "extract_error" not in r}
    utils.save_jsonl(kept, out_path)   # rewrite (drops retryable-error / re-tagged rows)

    system_prompt = build_system_prompt(fields, template)
    written: list[dict] = []
    for rec in records:
        rid = rec["record_id"]
        if rid in done:
            continue
        res = extract_record(rec["messages"], fields, record_id=rid, model=model,
                             temperature=temperature, system_prompt=system_prompt)
        row = _row(rid, res)
        utils.append_jsonl(row, out_path)
        written.append(row)
    return written
