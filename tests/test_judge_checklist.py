"""Checklist judge engine (evals/judge_checklist.py + rubric_dad_checklist.yaml).

The judge emits binary criterion verdicts + red flags; ALL arithmetic is code-side.
Expectations are DERIVED from the live rubric (ids, weights, penalties, floors) —
never hardcoded — because the criteria set is actively edited.
"""

import json

import pytest

from evals import judge, judge_checklist as jc


@pytest.fixture(scope="module")
def rubric():
    return jc.load_rubric()


@pytest.fixture(scope="module")
def principles():
    return judge.load_principles()


def _all_true_verdict(rubric):
    return {
        "posture_class": "RAISE_AND_HELP",
        "criteria": {c["id"]: True for c in rubric["criteria"]},
        "quotes": {},
        "red_flags": [],
        "exceptional": [],
        "autonomy_behavior": "IDEAL_ASSIST",
        "value_stability": {"turn_moves": [], "outcome_held": "NA",
                            "rationale_held": "NA", "resistance_quality": "NA"},
        "metadata": {},
        "notes": "",
    }


class TestLoading:
    def test_loads_and_declares_format(self, rubric):
        assert rubric["format"] == "checklist"
        assert rubric["criteria"] and rubric["red_flags"] and rubric["exceptional"]

    def test_rejects_non_checklist_rubric(self):
        with pytest.raises(ValueError, match="not a checklist"):
            jc.load_rubric(judge.DEFAULT_RUBRIC_PATH)


class TestPromptRender:
    def test_every_unit_renders(self, rubric, principles):
        prompt = jc.build_system_prompt(rubric, principles)
        for c in rubric["criteria"]:
            assert c["id"] in prompt
        for f in rubric["red_flags"]:
            assert f["id"] in prompt
        for e in rubric["exceptional"]:
            assert e["id"] in prompt
        for posture in rubric["postures"]["classes"]:
            assert posture in prompt
        assert "VERDICT_JSON" in prompt

    def test_schema_lists_na_only_where_declared(self, rubric):
        schema = jc.output_schema_text(rubric)
        for c in rubric["criteria"]:
            line = next(ln for ln in schema.splitlines() if f'"{c["id"]}"' in ln)
            assert ('"NA"' in line) == bool(c.get("na_when"))


class TestPillarScores:
    def test_all_true_is_full_marks(self, rubric):
        out = jc.aggregate(_all_true_verdict(rubric), rubric)
        assert all(v == 1.0 for v in out["pillar_scores"].values())
        assert out["passing"] is True
        assert out["gate_failures"] == []

    def test_false_criterion_costs_its_weight(self, rubric):
        c = next(c for c in rubric["criteria"] if not c.get("fatal"))
        verdict = _all_true_verdict(rubric)
        verdict["criteria"][c["id"]] = False
        out = jc.aggregate(verdict, rubric)
        possible = sum(x.get("weight", 1) for x in rubric["criteria"] if x["pillar"] == c["pillar"])
        expected = round((possible - c.get("weight", 1)) / possible, 3)
        assert out["pillar_scores"][c["pillar"]] == expected

    def test_red_flag_subtracts_penalty(self, rubric):
        flag = rubric["red_flags"][0]
        verdict = _all_true_verdict(rubric)
        verdict["red_flags"] = [{"id": flag["id"], "quote": "quoted tell"}]
        out = jc.aggregate(verdict, rubric)
        possible = sum(x.get("weight", 1) for x in rubric["criteria"] if x["pillar"] == flag["pillar"])
        expected = round((possible - flag["penalty"]) / possible, 3)
        assert out["pillar_scores"][flag["pillar"]] == expected
        assert flag["id"] in out["red_flags_fired"]

    def test_penalties_floor_at_zero(self, rubric):
        verdict = _all_true_verdict(rubric)
        verdict["red_flags"] = [{"id": f["id"], "quote": "q"} for f in rubric["red_flags"]] * 3
        out = jc.aggregate(verdict, rubric)
        assert all(v == 0.0 for v in out["pillar_scores"].values())

    def test_na_shrinks_denominator(self, rubric):
        c = next(c for c in rubric["criteria"] if c.get("na_when"))
        verdict = _all_true_verdict(rubric)
        verdict["criteria"][c["id"]] = "NA"
        out = jc.aggregate(verdict, rubric)
        assert out["pillar_scores"][c["pillar"]] == 1.0  # excluded, not failed
        assert out["passing"] is True

    def test_stringified_booleans_normalize(self, rubric):
        verdict = _all_true_verdict(rubric)
        verdict["criteria"] = {k: "true" for k in verdict["criteria"]}
        out = jc.aggregate(verdict, rubric)
        assert out["passing"] is True


class TestGates:
    def test_na_without_condition_is_malformed(self, rubric):
        c = next(c for c in rubric["criteria"] if not c.get("na_when"))
        verdict = _all_true_verdict(rubric)
        verdict["criteria"][c["id"]] = "NA"
        out = jc.aggregate(verdict, rubric)
        assert any(c["id"] in f and "NA" in f for f in out["gate_failures"])
        assert out["passing"] is False

    def test_missing_criterion_is_malformed_not_skipped(self, rubric):
        c = rubric["criteria"][0]
        verdict = _all_true_verdict(rubric)
        del verdict["criteria"][c["id"]]
        out = jc.aggregate(verdict, rubric)
        assert any("missing" in f and c["id"] in f for f in out["gate_failures"])

    def test_fatal_criterion_rejects(self, rubric):
        c = next(c for c in rubric["criteria"] if c.get("fatal"))
        verdict = _all_true_verdict(rubric)
        verdict["criteria"][c["id"]] = False
        out = jc.aggregate(verdict, rubric)
        assert any("automatic reject" in f for f in out["gate_failures"])
        assert out["passing"] is False

    def test_pillar_floor_binds(self, rubric):
        pillar, floor = next(iter(rubric["aggregation"]["pillar_floors"].items()))
        verdict = _all_true_verdict(rubric)
        for c in rubric["criteria"]:
            if c["pillar"] == pillar and not c.get("fatal"):
                verdict["criteria"][c["id"]] = False
        out = jc.aggregate(verdict, rubric)
        assert out["pillar_scores"][pillar] < floor
        assert any(pillar in f and "floor" in f for f in out["gate_failures"])

    def test_behavior_gate(self, rubric):
        verdict = _all_true_verdict(rubric)
        verdict["autonomy_behavior"] = "PREACHY"
        out = jc.aggregate(verdict, rubric)
        assert any("behavior" in f for f in out["gate_failures"])

    def test_fold_gate(self, rubric):
        verdict = _all_true_verdict(rubric)
        verdict["value_stability"] = {"turn_moves": [{"turn": 4, "move": "folded"}],
                                      "outcome_held": "false",
                                      "rationale_held": "abandoned",
                                      "resistance_quality": "none"}
        out = jc.aggregate(verdict, rubric)
        assert any("caved" in f for f in out["gate_failures"])
        assert any("abandoned" in f for f in out["gate_failures"])
        assert out["trajectory"] == "collapsed_at_turn_4"

    def test_unknown_red_flag_is_malformed(self, rubric):
        verdict = _all_true_verdict(rubric)
        verdict["red_flags"] = [{"id": "F_not_a_real_flag", "quote": "q"}]
        out = jc.aggregate(verdict, rubric)
        assert any("unknown red flag" in f for f in out["gate_failures"])


class TestExemplarCandidate:
    def test_requires_all_exceptional_marks(self, rubric):
        verdict = _all_true_verdict(rubric)
        out = jc.aggregate(verdict, rubric)
        assert out["exemplar_candidate"] is False  # no E marks
        verdict["exceptional"] = [{"id": e["id"], "quote": "q"} for e in rubric["exceptional"]]
        assert jc.aggregate(verdict, rubric)["exemplar_candidate"] is True

    def test_mark_without_quote_does_not_count(self, rubric):
        verdict = _all_true_verdict(rubric)
        verdict["exceptional"] = [{"id": e["id"], "quote": ""} for e in rubric["exceptional"]]
        assert jc.aggregate(verdict, rubric)["exemplar_candidate"] is False

    def test_pillar_minimum_binds(self, rubric):
        verdict = _all_true_verdict(rubric)
        verdict["exceptional"] = [{"id": e["id"], "quote": "q"} for e in rubric["exceptional"]]
        flag = min(rubric["red_flags"], key=lambda f: f["penalty"])
        verdict["red_flags"] = [{"id": flag["id"], "quote": "q"}] * 4
        out = jc.aggregate(verdict, rubric)
        minimum = rubric["aggregation"]["exemplar_candidate"]["pillar_minimums"][flag["pillar"]]
        if out["pillar_scores"][flag["pillar"]] < minimum:
            assert out["exemplar_candidate"] is False


class TestJudgeRecord:
    MESSAGES = [{"role": "user", "content": "should I worry about the crickets?"},
                {"role": "assistant", "content": "Here is a straight answer."}]

    def test_happy_path_parses_verdict(self, rubric, principles, stub_claude):
        verdict = _all_true_verdict(rubric)
        stub_claude([f"ANALYSIS: fine.\nVERDICT_JSON\n{json.dumps(verdict)}"])
        out = jc.judge_record(self.MESSAGES, "claude-test", rubric, principles)
        assert out["error"] is None
        assert out["verdict"]["posture_class"] == "RAISE_AND_HELP"
        assert out["verdict"]["analysis"].startswith("fine.")

    def test_malformed_response_returns_error_not_zeros(self, rubric, principles, stub_claude):
        stub_claude(["no json here at all", "still no json"])
        out = jc.judge_record(self.MESSAGES, "claude-test", rubric, principles)
        assert out["verdict"] is None
        assert "parse failure" in out["error"]
