"""SDF judge engine: document-shaped rubric -> prompt -> judge panel -> parsed
verdicts, aggregation. Composes the shared plumbing in evals/judge.py (provider
dispatch, JSON parsing, principle/dimension rendering); everything document-specific
lives here. The unit of judgment is a standalone pretraining-style document.

Spec: docs/superpowers/specs/2026-07-06-sdf-judge-rubric-v1-design.md
Rubric (data, not code): evals/rubric_sdf_v1.yaml
"""

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from evals import judge
from evals.judge import (  # shared plumbing — one copy only, owned by judge.py
    _render_dimension,
    _render_metadata_schema,
    _render_principles,
    call_model,
    load_principles,
    parse_judge_json,
)

DEFAULT_RUBRIC_PATH = Path(__file__).parent / "rubric_sdf_v1.yaml"

SCHEMA_SCALAR_ORDER = [  # criticals first: later fields in long outputs get judged lazier
    "no_outside_world_facts", "epistemic_calibration", "reasoning_fidelity",
    "realism", "teaching_value", "constitution_grounding",
]

CELL_FIELDS = ("type_name", "subtype_name", "description", "role", "tone", "language")


def load_rubric(path: str | Path = DEFAULT_RUBRIC_PATH) -> dict:
    return judge.load_rubric(path)


# ---------------------------------------------------------------- prompt rendering

def _render_roles(rubric: dict) -> str:
    r = rubric["roles"]
    lines = [r["intro"].strip(), ""]
    for name, c in r["classes"].items():
        lines.append(f"{name}: {c['definition'].strip()}")
        lines.append(f"  What good means here: {c['expected'].strip()}")
    lines += ["", r["observed_rule"].strip()]
    return "\n".join(lines)


def output_schema_text(rubric: dict) -> str:
    dims = rubric["dimensions"]
    scalar_lines = []
    for name in SCHEMA_SCALAR_ORDER:
        if name not in dims:
            continue
        na = ' | "NA"' if dims[name].get("na_when") else ""
        scalar_lines.append(f'    "{name}": 1-5{na}')
    dai = " | ".join(list(dims["depicted_ai_alignment"]["verdicts"]) + ["NA"])
    cell = " | ".join(list(dims["cell_adherence"]["verdicts"]) + ["NA"])
    return (
        "{\n"
        + '  "dimension_scores": {\n' + ",\n".join(scalar_lines) + "\n  },\n"
        + f'  "depicted_ai_alignment": "{dai}",\n'
        + f'  "cell_adherence": "{cell}",\n'
        + '  "no_scaffolding_leak": true | false,\n'
        + '  "signals_triggered": [ {"dimension": "...", "signal": "...", "quote": "..."} ],\n'
        + '  "metadata": {\n' + _render_metadata_schema(rubric) + "\n  },\n"
        + '  "notes": "1-2 sentences a rewrite could act on; name any recognized formulaic pattern"\n'
        + "}"
    )


def build_system_prompt(rubric: dict, principles: list[dict], include_quotes: bool = True) -> str:
    parts = [
        rubric["role"].strip(),
        "DOCUMENT ROLES.\n" + _render_roles(rubric),
        _render_principles(principles, include_quotes),
        "THE RUBRIC. Score each dimension using its definition, evaluation steps,"
        " anchors or verdict options, and signals. A dimension whose N/A condition"
        " applies is marked \"NA\", not scored.\n\n"
        + "\n\n".join(_render_dimension(n, d) for n, d in rubric["dimensions"].items()),
    ]
    analysis = rubric.get("analysis", {})
    rules = "".join(f"\n- {r}" for r in rubric.get("output_rules", []))
    if analysis.get("enabled"):
        parts.append(
            "OUTPUT. Respond in exactly two parts.\n\n"
            "PART 1 — ANALYSIS (plain text, no JSON). "
            + analysis["instruction"].strip().format(word_cap=analysis.get("word_cap", 300))
            + "\n\nPART 2 — VERDICT. On a new line write the marker VERDICT_JSON, then"
            " exactly one JSON object — no markdown fences, nothing after it. Fill the"
            " fields in the order given. Schema:\n\n"
            + output_schema_text(rubric)
            + ("\n\nRules:" + rules if rules else "")
        )
    else:
        parts.append(
            "OUTPUT. Return exactly one JSON object and nothing else — no preamble, no"
            " commentary, no markdown fences. Fill the fields in the order given. Schema:\n\n"
            + output_schema_text(rubric)
            + ("\n\nRules:" + rules if rules else "")
        )
    return "\n\n---\n\n".join(parts)


def build_user_message(document: str, cell: dict | None = None) -> str:
    parts = []
    if cell:
        lines = [f"  {f}: {cell[f]}" for f in CELL_FIELDS if cell.get(f)]
        parts.append("THE GENERATION CELL (what this document was generated to be):\n"
                     + "\n".join(lines))
    else:
        parts.append('No generation cell is available for this document — '
                     'cell_adherence is "NA".')
    parts.append("THE DOCUMENT TO EVALUATE:\n\n<document>\n" + document.strip()
                 + "\n</document>")
    parts.append("Apply the procedure from your instructions and return the single JSON object.")
    return "\n\n".join(parts)


# ---------------------------------------------------------------- judging

def judge_document(
    document: str,
    cell: dict | None,
    model: str,
    rubric: dict,
    principles: list[dict],
    temperature: float = 0.0,
    max_tokens: int = 4000,
    system_prompt: str | None = None,
) -> dict:
    """One judge call on one document. Returns {"model", "verdict"|None, "error"|None,
    "raw"}. Never raises — same contract as judge.judge_record."""
    system = system_prompt or build_system_prompt(rubric, principles)
    user = build_user_message(document, cell)
    raw, err = "", None
    for attempt in (1, 2):  # one retry on parse failure
        try:
            raw = call_model(user, system, model, temperature=temperature,
                             max_tokens=max_tokens)
        except Exception as e:  # noqa: BLE001 — API/retry errors must not crash a batch
            cause = e
            last = getattr(getattr(e, "last_attempt", None), "exception", None)
            if callable(last) and last():  # unwrap tenacity RetryError to the real cause
                cause = last()
            return {"model": model, "verdict": None,
                    "error": f"api error: {type(cause).__name__}: {str(cause)[:300]}", "raw": ""}
        try:
            return {"model": model, "verdict": parse_judge_json(raw), "error": None, "raw": raw}
        except (ValueError, json.JSONDecodeError) as e:
            err = f"parse failure (attempt {attempt}): {e}"
    return {"model": model, "verdict": None, "error": err, "raw": raw}


# ---------------------------------------------------------------- aggregation (code, not judge)

def aggregate(verdict: dict, rubric: dict) -> dict:
    """Gate + grade for one judge's verdict. Never trusts judge arithmetic.
    cell_adherence is a FLAG, never a gate failure (spec section 5)."""
    agg = rubric["aggregation"]
    dims = rubric["dimensions"]
    scores = {d: int(v) for d, v in (verdict.get("dimension_scores") or {}).items()
              if isinstance(v, (int, float))}
    failures = []

    for dim, floor in agg["critical_floors"].items():
        val = scores.get(dim)
        if val is None:
            if not dims.get(dim, {}).get("na_when"):  # NA-able criticals may sit out
                failures.append(f"{dim} missing")
        elif val < floor:
            failures.append(f"{dim} {val} < floor {floor}")

    dai = verdict.get("depicted_ai_alignment") or "NA"
    if dai not in agg["depicted_ai_gate"]:
        failures.append(f"depicted_ai_alignment {dai}")

    if agg["scaffolding_required"] and verdict.get("no_scaffolding_leak") is not True:
        failures.append("scaffolding leak — automatic reject")

    mean = round(sum(scores.values()) / len(scores), 3) if scores else None
    passing = not failures and mean is not None and mean >= agg["passing_threshold"]
    return {
        "mean": mean, "gate_failures": failures, "critical_gate": not failures,
        "passing": passing,
        "cell_mismatch": verdict.get("cell_adherence") == "MISMATCH",
    }


def consensus(results: list[dict], rubric: dict) -> dict:
    """Panel consensus: median of scalars, majority of verdicts; instability flags."""
    verdicts = [r["verdict"] for r in results if r.get("verdict")]
    if not verdicts:
        return {"judge_error": True}

    def majority(values):
        values = [v for v in values if v is not None]
        if not values:
            return None
        counts = {}
        for v in values:
            counts[v] = counts.get(v, 0) + 1
        return max(counts, key=counts.get)

    scalar_cons = {}
    dims = [d for d, spec in rubric["dimensions"].items() if spec["type"] == "scalar"]
    for dim in dims:
        vals = [v for v in ((x.get("dimension_scores") or {}).get(dim) for x in verdicts)
                if isinstance(v, (int, float))]
        scalar_cons[dim] = int(statistics.median(vals)) if vals else "NA"

    dai = majority([v.get("depicted_ai_alignment") for v in verdicts])
    cell = majority([v.get("cell_adherence") for v in verdicts])
    leak_clean = all(v.get("no_scaffolding_leak") is True for v in verdicts)

    per_model_pass = {r["model"]: aggregate(r["verdict"], rubric)["passing"]
                      for r in results if r.get("verdict")}
    unstable = (
        len({v.get("depicted_ai_alignment") for v in verdicts}) > 1
        or len({v.get("no_scaffolding_leak") for v in verdicts}) > 1
        or len(set(per_model_pass.values())) > 1
    )
    cons_verdict = {
        "dimension_scores": scalar_cons,
        "depicted_ai_alignment": dai,
        "cell_adherence": cell,
        "no_scaffolding_leak": leak_clean,
    }
    return {
        "consensus_verdict": cons_verdict,
        "consensus_aggregate": aggregate(cons_verdict, rubric),
        "per_model_passing": per_model_pass,
        "judge_unstable": unstable,
        "judge_error": False,
    }


def panel_judge(
    document: str,
    cell: dict | None,
    models: list[str],
    rubric: dict,
    principles: list[dict],
    temperature: float = 0.0,
) -> dict:
    """Judge one document with every model on the panel."""
    system = build_system_prompt(rubric, principles)
    results = [
        judge_document(document, cell, m, rubric, principles, temperature,
                       system_prompt=system)
        for m in models
    ]
    out = consensus(results, rubric)
    out["results"] = results
    out["document_words"] = len(document.split())
    for r in results:
        if r.get("verdict"):
            r["aggregate"] = aggregate(r["verdict"], rubric)
    return out
