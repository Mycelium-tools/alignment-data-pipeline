#!/usr/bin/env python3
"""Adversarial review suite: run the judge on controlled same-issue variants and check
RELATIVE expectations between them (a judge blindspot should not move the score on the
axis being probed). Grows over time — every blindspot found in calibration adds a family.

  python evals/adversarial.py --judges gemini-2.5-flash [--family verbosity_padding]
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils
from evals import judge

DEFAULT_CASES_PATH = Path(__file__).parent / "adversarial_cases.yaml"


def _get(verdict: dict, field: str):
    """Resolve a field: scalars live under dimension_scores.*; else top-level/dotted."""
    if verdict is None:
        return None
    if "." in field:
        node = verdict
        for part in field.split("."):
            node = (node or {}).get(part)
        return node
    if field in (verdict.get("dimension_scores") or {}):
        val = verdict["dimension_scores"][field]
        return val if isinstance(val, (int, float)) else None
    return verdict.get(field)


def check_expectation(exp: dict, verdicts: dict[str, dict]) -> dict:
    """Evaluate one expectation against the {variant_id: verdict} map for a family."""
    op, field = exp["op"], exp.get("field")
    a = _get(verdicts.get(exp["a"]), field) if field else None
    result = {"op": op, "field": field, "a": exp["a"], "detail": ""}
    if op == "equals":
        result.update(passed=(a == exp["value"]), detail=f"{exp['a']}.{field}={a} vs {exp['value']}")
        return result
    b = _get(verdicts.get(exp["b"]), field)
    result["b"] = exp["b"]
    if a is None or b is None:
        result.update(passed=False, detail=f"missing value (a={a}, b={b})")
        return result
    if op == "higher":
        result.update(passed=a > b, detail=f"{a} > {b}")
    elif op == "gte":
        result.update(passed=a >= b, detail=f"{a} >= {b}")
    elif op == "approx":
        tol = exp.get("tolerance", 1)
        result.update(passed=abs(a - b) <= tol, detail=f"|{a}-{b}| <= {tol}")
    else:
        result.update(passed=False, detail=f"unknown op {op}")
    return result


def run_family(family: dict, model: str, rubric: dict, principles: list[dict],
               system: str) -> dict:
    verdicts, errors = {}, {}
    for variant in family["variants"]:
        res = judge.judge_record(variant["messages"], model, rubric, principles,
                                 system_prompt=system)
        if res.get("verdict"):
            verdicts[variant["id"]] = res["verdict"]
        else:
            errors[variant["id"]] = res.get("error")
    # expectations may live on any variant (they compare across variants)
    checks = []
    for variant in family["variants"]:
        for exp in variant.get("expect", []):
            checks.append(check_expectation(exp, verdicts))
    passed = bool(checks) and all(c["passed"] for c in checks) and not errors
    return {"family": family["id"], "model": model, "passed": passed,
            "checks": checks, "errors": errors}


def families_for(cases: dict, suite: str = "dad", only_family: str | None = None) -> list[dict]:
    """Families in a suite (default dad). Families default to suite 'dad' if untagged."""
    return [f for f in cases["families"]
            if f.get("suite", "dad") == suite
            and (not only_family or f["id"] == only_family)]


def run_suite(cases: dict, models: list[str], rubric: dict, principles: list[dict],
              suite: str = "dad", only_family: str | None = None) -> list[dict]:
    system = judge.build_system_prompt(rubric, principles)
    families = families_for(cases, suite, only_family)
    results = []
    for model in models:
        for family in families:
            results.append(run_family(family, model, rubric, principles, system))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the adversarial judge review suite.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--rubric", default=str(judge.DEFAULT_RUBRIC_PATH))
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH))
    parser.add_argument("--judges", nargs="+", default=["gemini-3.1-pro-preview"])
    parser.add_argument("--suite", default="dad", choices=["dad", "sdf"],
                        help="Which judge's suite to run (default dad)")
    parser.add_argument("--family", default=None, help="Run a single family by id")
    args = parser.parse_args()

    api.init(args.config)
    rubric = judge.load_rubric(args.rubric)
    principles = judge.load_principles()
    with open(args.cases) as f:
        cases = yaml.safe_load(f)

    results = run_suite(cases, args.judges, rubric, principles, args.suite, args.family)
    if not results:
        print(f"No families in suite '{args.suite}'.")
        return

    print(f"\n=== Adversarial review [{args.suite}] ({cases['version']}, rubric {rubric['version']}) ===")
    n_pass = 0
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        if r["passed"]:
            n_pass += 1
        print(f"\n[{mark}] {r['family']} · {r['model']}")
        for c in r["checks"]:
            cm = "ok " if c["passed"] else "XX "
            b = f" vs {c.get('b')}" if "b" in c else ""
            print(f"    {cm}{c['op']}({c['a']}{b}).{c['field']}: {c['detail']}")
        for vid, err in r["errors"].items():
            print(f"    !! judge error on {vid}: {err}")
    print(f"\n  {n_pass}/{len(results)} family-runs passed")

    out = Path("outputs") / "adversarial_review.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    utils.append_jsonl({"rubric_version": rubric["version"],
                        "cases_version": cases["version"], "results": results}, out)
    print(f"  logged to {out}")


if __name__ == "__main__":
    main()
