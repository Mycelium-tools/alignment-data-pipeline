"""Tests for the adversarial review suite (evals/adversarial.py + adversarial_cases.yaml).

Two layers: schema validation of the cases file (every family runnable, every
expectation resolvable against the right rubric — a typo'd dimension name would
otherwise only fail at API-spend time), and a stubbed end-to-end run of an SDF
family proving the suite dispatches documents to the SDF judge engine.
"""

import json

import pytest
import yaml

from evals import adversarial, judge, judge_sdf

VALID_OPS = {"higher", "gte", "approx", "equals"}


@pytest.fixture(scope="module")
def cases():
    with open(adversarial.DEFAULT_CASES_PATH) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def rubrics():
    return {suite: judge.load_rubric(spec["rubric_path"])
            for suite, spec in adversarial.ENGINES.items()}


class TestCasesSchema:
    def test_every_family_is_runnable(self, cases):
        """Each family: known suite, right unit key per variant, >=1 expectation
        (a family with no expectations silently tests nothing)."""
        unit_key = {"dad": "messages", "sdf": "document"}
        for fam in cases["families"]:
            suite = fam.get("suite", "dad")
            assert suite in adversarial.ENGINES, f"{fam['id']}: unknown suite {suite}"
            for v in fam["variants"]:
                assert unit_key[suite] in v, f"{fam['id']}/{v['id']}: missing {unit_key[suite]}"
            n_exp = sum(len(v.get("expect", [])) for v in fam["variants"])
            assert n_exp >= 1, f"{fam['id']}: no expectations — tests nothing"

    def test_expectations_resolve(self, cases, rubrics):
        """Every expect references real variant ids and a field the suite's rubric
        (or verdict shape) actually produces — derived, never hardcoded."""
        for fam in cases["families"]:
            suite = fam.get("suite", "dad")
            dims = rubrics[suite]["dimensions"]
            valid_fields = set(dims) | {"posture_class"}
            ids = {v["id"] for v in fam["variants"]}
            for v in fam["variants"]:
                for exp in v.get("expect", []):
                    assert exp["op"] in VALID_OPS, f"{fam['id']}: op {exp['op']}"
                    assert exp["a"] in ids, f"{fam['id']}: unknown variant {exp['a']}"
                    if exp["op"] != "equals":
                        assert exp["b"] in ids, f"{fam['id']}: unknown variant {exp['b']}"
                    root = exp["field"].split(".")[0]
                    assert root in valid_fields, \
                        f"{fam['id']}: field {exp['field']} not in {suite} rubric"

    def test_equals_values_are_real_verdict_labels(self, cases, rubrics):
        """An `equals` on a verdict-type dimension must use a label the rubric
        defines — MISALIGNED_ENDORSED misspelled would never match, and the family
        would fail forever looking like a judge problem."""
        for fam in cases["families"]:
            dims = rubrics[fam.get("suite", "dad")]["dimensions"]
            for v in fam["variants"]:
                for exp in v.get("expect", []):
                    if exp["op"] != "equals":
                        continue
                    spec = dims.get(exp["field"])
                    if spec and spec["type"] == "verdict":
                        allowed = set(spec["verdicts"]) | {"NA"}
                        assert exp["value"] in allowed, \
                            f"{fam['id']}: {exp['value']} not a {exp['field']} label"


class TestSdfSuiteDispatch:
    def test_sdf_family_runs_through_sdf_engine(self, cases, rubrics, stub_claude):
        """Stubbed end-to-end: the SDF suite must judge DOCUMENTS with the SDF
        prompt (not fall through to the DAD conversation judge), evaluate the
        family's expectations, and use the cached-system-prompt call path."""
        sdf_rubric = rubrics["sdf"]

        def dispatch(user_message, **kwargs):
            # The trap variant fabricates specifics; the honest one does not.
            fabricated = "Wageningen" in user_message
            verdict = {
                "dimension_scores": {
                    "no_outside_world_facts": 3 if fabricated else 9,
                    "epistemic_calibration": 8,
                    "realism": 8, "teaching_value": 8,
                    "reasoning_fidelity": 8, "constitution_grounding": "NA",
                },
                "depicted_ai_alignment": "NA",
                "cell_adherence": "MATCHES",
                "no_scaffolding_leak": True,
                "notes": "stub verdict",
            }
            return json.dumps(verdict)

        calls = stub_claude(dispatch)
        principles = judge.load_principles()
        results = adversarial.run_suite(
            cases, ["claude-stub-judge"], sdf_rubric, principles,
            suite="sdf", only_family="sdf_fabricated_specificity")

        assert len(results) == 1
        assert results[0]["passed"] is True, results[0]
        assert len(calls) == 2  # one per variant
        for call in calls:
            assert "<document>" in call["user_message"]  # SDF engine, not DAD
            assert call["cache_system"] is True  # judge path caches the rubric

    def test_failed_expectation_fails_family(self, cases, rubrics, stub_claude):
        """A judge blind to the trap (same score for both variants) must FAIL the
        family — the suite's whole point is that blindness is loud."""
        blind = {
            "dimension_scores": {"no_outside_world_facts": 9, "epistemic_calibration": 8,
                                 "realism": 8, "teaching_value": 8,
                                 "reasoning_fidelity": 8, "constitution_grounding": "NA"},
            "depicted_ai_alignment": "NA", "cell_adherence": "MATCHES",
            "no_scaffolding_leak": True, "notes": "blind stub",
        }
        stub_claude(lambda user_message, **kwargs: json.dumps(blind))
        principles = judge.load_principles()
        results = adversarial.run_suite(
            cases, ["claude-stub-judge"], rubrics["sdf"], principles,
            suite="sdf", only_family="sdf_fabricated_specificity")
        assert results[0]["passed"] is False
