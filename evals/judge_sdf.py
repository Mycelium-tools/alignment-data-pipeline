"""SDF judge engine: document-shaped rubric -> prompt -> judge panel -> parsed
verdicts, aggregation. Composes the shared plumbing in evals/judge.py (provider
dispatch, JSON parsing, principle/dimension rendering); everything document-specific
lives here. The unit of judgment is a standalone pretraining-style document.

Rubric (data, not code): evals/rubric_sdf_v3.yaml
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

DEFAULT_RUBRIC_PATH = Path(__file__).parent / "rubric_sdf_v3.yaml"

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


def _schema_scalar_order(rubric: dict) -> list[str]:
    """Scalar dimensions in output-schema order: the pinned historical order while
    it covers every scalar (byte-identical v3 prompts), else derived criticals-first
    — a scalar added to the rubric but missing from the pinned list would otherwise
    be silently dropped from the schema the judge sees, and every document would
    gate-fail it as missing (the bug judge.schema_scalar_order fixed for DAD)."""
    dims = rubric["dimensions"]
    scalars = [n for n, d in dims.items() if d["type"] == "scalar"]
    if all(n in SCHEMA_SCALAR_ORDER for n in scalars):
        return [n for n in SCHEMA_SCALAR_ORDER if n in dims]
    crits = [n for n in scalars if dims[n].get("critical")]
    return crits + [n for n in scalars if not dims[n].get("critical")]


def output_schema_text(rubric: dict) -> str:
    dims = rubric["dimensions"]
    scalar_lines = []
    for name in _schema_scalar_order(rubric):
        na = ' | "NA"' if dims[name].get("na_when") else ""
        scalar_lines.append(f'    "{name}": 1-10{na}')
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
    return judge.call_and_parse(user, system, model,
                                temperature=temperature, max_tokens=max_tokens)


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

    # Malformed-verdict guard (mirrors judge.aggregate): a non-critical scalar the
    # judge omitted is a gate failure unless the dimension is NA-able — a sparse
    # verdict must not pass on its strongest dimensions alone.
    for dim, spec in dims.items():
        if spec["type"] != "scalar" or dim in agg["critical_floors"]:
            continue
        if dim not in scores and not spec.get("na_when"):
            failures.append(f"{dim} missing (non-NA dimension)")

    # depicted_ai_alignment must be PRESENT — "NA" is a legitimate explicit value
    # (no AI in the document), but omission is a malformed verdict and must not be
    # silently coerced to a passing "NA".
    dai = verdict.get("depicted_ai_alignment")
    if dai is None:
        failures.append("depicted_ai_alignment missing (malformed verdict)")
    elif dai not in agg["depicted_ai_gate"]:
        failures.append(f"depicted_ai_alignment {dai}")

    if agg["scaffolding_required"] and verdict.get("no_scaffolding_leak") is not True:
        failures.append("scaffolding leak — automatic reject")

    caps_applied = judge._apply_signal_caps(scores, verdict, agg)
    for dim, floor in agg["critical_floors"].items():  # a cap can pull a critical below its floor
        if (scores.get(dim) is not None and scores[dim] < floor
                and not any(f.startswith(f"{dim} ") for f in failures)):
            failures.append(f"{dim} {scores[dim]} < floor {floor} (after signal cap)")

    mean = round(sum(scores.values()) / len(scores), 3) if scores else None
    passing = not failures and mean is not None and mean >= agg["passing_threshold"]
    return {
        "mean": mean, "gate_failures": failures, "critical_gate": not failures,
        "passing": passing,
        "exemplar": judge._exemplar_tier(scores, passing, agg, rubric),
        "caps_applied": caps_applied,
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
