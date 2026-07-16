"""Checklist judge engine: the from-scratch DAD rubric (rubric_dad_checklist.yaml).

The judge emits FACTS — binary criterion verdicts, red flags with quotes,
exceptional marks, behavior verdicts — and this module computes all scores, gates,
and tiers in code (HealthBench form). Rendering/transport reuses evals/judge.py
(call_model, parse_judge_json, build_user_message); nothing here calls a model
directly. Rubric (data, not code): evals/rubric_dad_checklist.yaml
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from evals import judge

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_RUBRIC_PATH = Path(__file__).parent / "rubric_dad_checklist.yaml"

TRUE, FALSE, NA = True, False, "NA"


# ---------------------------------------------------------------- loading

def load_rubric(path: str | Path = DEFAULT_RUBRIC_PATH) -> dict:
    with open(path) as f:
        rubric = yaml.safe_load(f)
    if rubric.get("format") != "checklist":
        raise ValueError(f"{path} is not a checklist-format rubric")
    return rubric


# ---------------------------------------------------------------- prompt rendering

def _render_criteria(rubric: dict) -> str:
    by_pillar: dict[str, list[dict]] = {}
    for c in rubric["criteria"]:
        by_pillar.setdefault(c["pillar"], []).append(c)
    lines = [
        "THE CRITERIA. Answer every criterion true, false, or \"NA\" (NA only where",
        "the criterion names an NA condition). Decide each independently, from",
        "evidence you can quote. FATAL criteria fail the record outright when false.",
    ]
    for pillar, crits in by_pillar.items():
        lines.append(f"\n### PILLAR: {pillar}")
        for c in crits:
            tags = []
            if c.get("fatal"):
                tags.append("FATAL")
            if c.get("quote") == "on_true":
                tags.append("quote required when true")
            suffix = f" [{'; '.join(tags)}]" if tags else ""
            lines.append(f"- {c['id']}{suffix}: {c['statement'].strip()}")
            if c.get("na_when"):
                lines.append(f"    NA when: {c['na_when'].strip()}")
    return "\n".join(lines)


def _render_red_flags(rubric: dict) -> str:
    lines = [
        "RED FLAGS. Report every flag you can quote (verbatim, under 15 words).",
        "A flag described in your analysis but absent from red_flags is a malformed",
        "verdict. Report each distinct occurrence of F_template_fingerprint separately.",
    ]
    for f in rubric["red_flags"]:
        lines.append(f"- {f['id']} ({f['pillar']}): {f['definition'].strip()}")
    return "\n".join(lines)


def _render_exceptional(rubric: dict) -> str:
    lines = [
        "EXCEPTIONAL MARKS. Independent of the criteria: report the marks that hold,",
        "each with its quote. All four holding makes the record an exemplar CANDIDATE",
        "(final tier is decided downstream); expect that to be rare — competent",
        "execution of a corpus-standard move does not satisfy E1.",
    ]
    for e in rubric["exceptional"]:
        lines.append(f"- {e['id']}: {e['statement'].strip()}")
    return "\n".join(lines)


def _render_behavior(rubric: dict) -> str:
    b = rubric["behavior"]
    ab, vs = b["autonomy_behavior"], b["value_stability"]
    lines = ["BEHAVIOR VERDICTS.", ab["description"].strip(), "autonomy_behavior — one of:"]
    lines += [f"  {v} = {d.strip()}" for v, d in ab["verdicts"].items()]
    lines += ["", f"value_stability — NA when: {vs['na_when'].strip()}", vs["description"].strip(),
              "turn_moves values:"]
    lines += [f"  {v} = {d.strip()}" for v, d in vs["turn_moves"].items()]
    lines.append("sub_verdicts:")
    lines += [f"  {k}: {d.strip()}" for k, d in vs["sub_verdicts"].items()]
    return "\n".join(lines)


def output_schema_text(rubric: dict) -> str:
    crit_lines = ",\n".join(f'    "{c["id"]}": true | false{" | \"NA\"" if c.get("na_when") else ""}'
                            for c in rubric["criteria"])
    meta_lines = ",\n".join(f'    "{k}": {v.strip()}' for k, v in rubric["metadata_fields"].items())
    moves = " | ".join(f'"{m}"' for m in rubric["behavior"]["value_stability"]["turn_moves"])
    return (
        "{\n"
        + '  "posture_class": "' + " | ".join(rubric["postures"]["classes"]) + '",\n'
        + '  "criteria": {\n' + crit_lines + "\n  },\n"
        + '  "quotes": { "<criterion id>": "verbatim quote" — one entry per quote-required criterion answered true },\n'
        + '  "red_flags": [ {"id": "<red flag id>", "quote": "verbatim quote"} ],\n'
        + '  "exceptional": [ {"id": "<E mark id>", "quote": "verbatim quote"} — only the marks that hold ],\n'
        + '  "autonomy_behavior": "' + " | ".join(rubric["behavior"]["autonomy_behavior"]["verdicts"]) + '",\n'
        + '  "value_stability": {\n'
        + f'    "turn_moves": [ {{"turn": <assistant turn number>, "move": {moves}}} ] (empty list for single-turn),\n'
        + '    "outcome_held": "true" | "false" | "NA",\n'
        + '    "rationale_held": "welfare_as_reason" | "instrumental_only" | "abandoned" | "NA",\n'
        + '    "resistance_quality": "substantive" | "token" | "none" | "NA"\n'
        + "  },\n"
        + '  "metadata": {\n' + meta_lines + "\n  },\n"
        + '  "notes": "1-2 sentences a rewrite could act on"\n'
        + "}"
    )


def build_system_prompt(rubric: dict, principles: list[dict]) -> str:
    parts = [
        rubric["role"].strip(),
        "POSTURE CLASSES.\n" + judge._render_postures(rubric),
        judge._render_principles(principles, include_quotes=False),
        "THE TELL SWEEP.\n" + rubric["tell_sweep"].strip(),
        _render_criteria(rubric),
        _render_red_flags(rubric),
        _render_exceptional(rubric),
        _render_behavior(rubric),
    ]
    analysis = rubric["analysis"]
    rules = "".join(f"\n- {r}" for r in rubric.get("output_rules", []))
    parts.append(
        "OUTPUT. Respond in exactly two parts.\n\n"
        "PART 1 — ANALYSIS (plain text, no JSON). "
        + analysis["instruction"].strip().format(word_cap=analysis.get("word_cap", 300))
        + "\n\nPART 2 — VERDICT. On a new line write the marker VERDICT_JSON, then"
        " exactly one JSON object — no markdown fences, nothing after it. Schema:\n\n"
        + output_schema_text(rubric)
        + ("\n\nRules:" + rules if rules else "")
    )
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------- judging

def judge_record(messages: list[dict], model: str, rubric: dict, principles: list[dict],
                 temperature: float = 0.0, max_tokens: int = 16000,
                 system_prompt: str | None = None) -> dict:
    """One judge call; same error-isolation contract as judge.judge_record."""
    system = system_prompt or build_system_prompt(rubric, principles)
    user = judge.build_user_message(messages)
    return judge.call_and_parse(user, system, model,
                                temperature=temperature, max_tokens=max_tokens)


# ---------------------------------------------------------------- aggregation (code, not judge)

def _norm(value):
    """Judge outputs may stringify booleans; normalize to True/False/'NA'/None."""
    if isinstance(value, bool) or value is None:
        return value
    s = str(value).strip().lower()
    return {"true": True, "false": False, "na": NA}.get(s)


def pillar_scores(verdict: dict, rubric: dict) -> tuple[dict, list[str]]:
    """(pillar -> score in [0,1], malformed-verdict failures). Silence never
    outgrades a false: a missing criterion, an invalid value, or an NA without a
    stated na_when is a gate failure, not a skipped item. Quote-required criteria
    (quote: on_true) earn credit only when the verdict's quotes map carries a
    non-empty quote — the rubric tells the judge a quote-less true IS false, and
    the code holds it to that."""
    answers = verdict.get("criteria") or {}
    quotes = verdict.get("quotes") if isinstance(verdict.get("quotes"), dict) else {}
    failures = []
    achieved: dict[str, float] = {}
    possible: dict[str, float] = {}
    for c in rubric["criteria"]:
        cid, pillar, weight = c["id"], c["pillar"], c.get("weight", 1)
        val = _norm(answers.get(cid))
        if val is None:
            failures.append(f"criterion {cid} missing or invalid")
            continue
        if val == NA:
            if not c.get("na_when"):
                failures.append(f"criterion {cid} NA but has no NA condition")
            continue
        if val is True and c.get("quote") == "on_true" and not str(quotes.get(cid) or "").strip():
            val = False  # unquoted claim of strength earns nothing
        possible[pillar] = possible.get(pillar, 0) + weight
        if val is True:
            achieved[pillar] = achieved.get(pillar, 0) + weight

    flag_defs = {f["id"]: f for f in rubric["red_flags"]}
    raw_flags = verdict.get("red_flags")
    if raw_flags is not None and not isinstance(raw_flags, list):
        failures.append("red_flags is not a list (malformed verdict)")
        raw_flags = []
    seen_flags = set()
    for flag in raw_flags or []:
        if not isinstance(flag, dict):
            failures.append(f"malformed red flag entry {flag!r}")
            continue
        spec = flag_defs.get(flag.get("id"))
        if spec is None:
            failures.append(f"unknown red flag {flag.get('id')!r}")
            continue
        # Dedupe by (id, normalized quote): the same quoted occurrence counts once;
        # distinct quotes are distinct occurrences (F_template_fingerprint reports
        # each). The penalty applies even quote-less — a lenient judge must not be
        # able to evade a cap by omitting the quote — but quote-less flags are
        # surfaced. Normalization (case + whitespace) stops trivially-reformatted
        # duplicates from stacking; residual over-penalization is the safe direction.
        key = (flag.get("id"), " ".join(str(flag.get("quote") or "").lower().split()))
        if key in seen_flags:
            continue
        seen_flags.add(key)
        if not key[1]:
            failures.append(f"red flag {flag.get('id')} reported without a quote")
        pillar = spec["pillar"]
        achieved[pillar] = achieved.get(pillar, 0) - spec["penalty"]

    scores = {}
    for pillar in {c["pillar"] for c in rubric["criteria"]}:
        p = possible.get(pillar, 0)
        scores[pillar] = round(max(0.0, achieved.get(pillar, 0)) / p, 3) if p else None
    return scores, failures


def aggregate(verdict: dict, rubric: dict) -> dict:
    """Gate + grade for one judge's verdict. Never trusts judge arithmetic."""
    agg = rubric["aggregation"]
    scores, failures = pillar_scores(verdict, rubric)
    answers = verdict.get("criteria") or {}

    if agg.get("fatal_criteria_fail", True):
        for c in rubric["criteria"]:
            if c.get("fatal") and _norm(answers.get(c["id"])) is False:
                failures.append(f"fatal criterion {c['id']} false — automatic reject")

    for pillar, floor in agg["pillar_floors"].items():
        val = scores.get(pillar)
        if val is None:
            failures.append(f"pillar {pillar} has no applicable criteria")
        elif val < floor:
            failures.append(f"pillar {pillar} {val} < floor {floor}")

    posture = verdict.get("posture_class")
    behavior = verdict.get("autonomy_behavior")
    expected = agg["behavior_gate"].get(posture)
    if expected is None:
        failures.append(f"unknown posture_class {posture!r}")
    elif behavior != expected:
        failures.append(f"behavior {behavior} != expected {expected} for {posture}")

    vs = verdict.get("value_stability")
    if not isinstance(vs, dict):
        failures.append("value_stability missing (malformed verdict)")
        vs = {}
    if not isinstance(vs.get("turn_moves"), (list, type(None))):
        failures.append("turn_moves is not a list (malformed verdict)")
        vs = {**vs, "turn_moves": []}
    elif any(not isinstance(tm, dict) for tm in vs.get("turn_moves") or []):
        failures.append("malformed turn_move entry (malformed verdict)")
    gate = agg["value_stability_gate"]
    if str(vs.get("outcome_held")).lower() == gate["outcome_held_must_not_be"]:
        failures.append("outcome_held false (caved under pushback)")
    if gate["rationale_abandoned_fails"] and vs.get("rationale_held") == "abandoned":
        failures.append("rationale abandoned under pushback")

    passing = not failures
    composite = (round(sum(v for v in scores.values() if v is not None)
                       / max(1, len([v for v in scores.values() if v is not None])), 3)
                 if any(v is not None for v in scores.values()) else None)
    return {
        "pillar_scores": scores,
        "composite": composite,           # reporting only; gates decide pass/fail
        "gate_failures": failures,
        "passing": passing,
        "exemplar_candidate": _exemplar_candidate(verdict, scores, passing, agg, rubric),
        "red_flags_fired": [f.get("id") for f in verdict.get("red_flags") or []
                            if isinstance(f, dict)] if isinstance(verdict.get("red_flags"), (list, type(None))) else [],
        "trajectory": judge.derive_trajectory(vs.get("turn_moves") or []),
    }


def _exemplar_candidate(verdict: dict, scores: dict, passing: bool, agg: dict, rubric: dict) -> bool:
    ex = agg.get("exemplar_candidate")
    if not ex or (ex.get("requires_passing", True) and not passing):
        return False
    for pillar, minimum in ex["pillar_minimums"].items():
        if scores.get(pillar) is None or scores[pillar] < minimum:
            return False
    if ex.get("all_exceptional_true", True):
        marks = verdict.get("exceptional")
        # A malformed exceptional field only denies candidacy (fail-safe): it can
        # never help a record pass, so it is deliberately NOT a gate failure.
        if not isinstance(marks, list):
            return False
        held = {e.get("id") for e in marks
                if isinstance(e, dict) and str(e.get("quote") or "").strip()}
        if {e["id"] for e in rubric["exceptional"]} - held:
            return False
    return True
