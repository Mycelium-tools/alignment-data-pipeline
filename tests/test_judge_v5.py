"""Tests for the v5 engine wiring in evals/judge.py: per-rubric schema scalar
order, C1 clause-card inlining, the tracks_attitude auto-reject gate, and the
top_tier (v5 name for exemplar) aggregation key.

Expectations are DERIVED from the live rubric files and constitution CSV, never
hardcoded — both are actively edited. The v4 rubric acts as the regression
control: its rendered schema order and aggregation behavior must not change.
"""

import json

import pytest

from evals import judge


@pytest.fixture(scope="module")
def principles():
    return judge.load_principles()


@pytest.fixture(scope="module")
def v4_rubric():
    return judge.load_rubric(judge.DEFAULT_RUBRIC_PATH)


@pytest.fixture(scope="module", params=["a", "b"])
def v5_rubric(request):
    return judge.load_rubric(judge.DEFAULT_RUBRIC_PATH.parent / f"rubric_dad_v5{request.param}.yaml")


def _scalar_dims(rubric):
    return [d for d, spec in rubric["dimensions"].items() if spec["type"] == "scalar"]


def _full_verdict(rubric, score=8):
    """Well-formed verdict: every non-NA scalar present, gates satisfied."""
    agg = rubric["aggregation"]
    posture = next(iter(agg["behavior_gate"]))
    return {
        "dimension_scores": {d: score for d in _scalar_dims(rubric)
                             if not rubric["dimensions"][d].get("na_when")},
        "posture_class": posture,
        "autonomy_behavior": agg["behavior_gate"][posture],
        "value_stability": {"outcome_held": True, "rationale_held": "welfare_as_reason",
                            "turn_moves": []},
        "self_contained": True,
        "metadata": {"tracks_attitude": False},
    }


# ---------------------------------------------------------------- schema scalar order

class TestSchemaScalarOrder:
    def test_v5_order_covers_every_scalar_criticals_first(self, v5_rubric):
        order = judge.schema_scalar_order(v5_rubric)
        assert sorted(order) == sorted(_scalar_dims(v5_rubric))
        dims = v5_rubric["dimensions"]
        crit_count = sum(1 for d in order if dims[d].get("critical"))
        assert all(dims[d].get("critical") for d in order[:crit_count])
        assert not any(dims[d].get("critical") for d in order[crit_count:])

    def test_v4_order_is_the_pinned_historical_order(self, v4_rubric):
        # v4 prompts must stay byte-identical: the pinned list interleaves criticals
        # and non-criticals (helpfulness 3rd, epistemic_calibration 5th) in a way
        # pure criticals-first derivation would not reproduce.
        order = judge.schema_scalar_order(v4_rubric)
        assert order == [n for n in judge.SCHEMA_SCALAR_ORDER if n in v4_rubric["dimensions"]]
        assert order[2] == "helpfulness"
        assert order[4] == "epistemic_calibration"

    def test_v5_schema_text_includes_every_scalar(self, v5_rubric):
        # The v4-hardcoded order silently dropped v5-only dims from the schema.
        text = judge.output_schema_text(v5_rubric)
        for dim in _scalar_dims(v5_rubric):
            assert f'"{dim}"' in text


# ---------------------------------------------------------------- clause cards (C1)

def _dimension_section(prompt: str, name: str) -> str:
    start = prompt.index(f"#### {name}")
    end = prompt.find("####", start + 1)
    return prompt[start:end if end != -1 else len(prompt)]


class TestClauseCards:
    def test_mapped_dimension_carries_its_clauses(self, v5_rubric, principles):
        prompt = judge.build_system_prompt(v5_rubric, principles, include_constitution=False)
        by_number = {int(r["number"]): r for r in principles}
        for name, dim in v5_rubric["dimensions"].items():
            if not dim.get("principles") or dim["type"] not in ("scalar", "verdict"):
                continue
            section = _dimension_section(prompt, name)
            for pid in dim["principles"]:
                assert by_number[pid]["principle"] in section, (name, pid)

    def test_unmapped_dimension_gets_no_card(self, v5_rubric, principles):
        prompt = judge.build_system_prompt(v5_rubric, principles, include_constitution=False)
        section = _dimension_section(prompt, "scenario_genuineness")
        assert "Constitution clauses" not in section

    def test_v5_drops_the_flat_standard_block(self, v5_rubric, principles):
        # C1: clauses live next to their dimensions; the flat list is the C0 arm.
        prompt = judge.build_system_prompt(v5_rubric, principles, include_constitution=False)
        assert "THE STANDARD." not in prompt

    def test_v4_prompt_unchanged_flat_block_no_cards(self, v4_rubric, principles):
        prompt = judge.build_system_prompt(v4_rubric, principles, include_constitution=False)
        assert "THE STANDARD." in prompt
        assert "Constitution clauses" not in prompt


# ---------------------------------------------------------------- tracks_attitude gate

class TestTracksAttitudeGate:
    def test_true_is_an_automatic_reject(self, v5_rubric):
        verdict = _full_verdict(v5_rubric)
        verdict["metadata"]["tracks_attitude"] = True
        out = judge.aggregate(verdict, v5_rubric)
        assert any("tracks_attitude" in f for f in out["gate_failures"])
        assert out["passing"] is False

    def test_false_passes(self, v5_rubric):
        out = judge.aggregate(_full_verdict(v5_rubric), v5_rubric)
        assert not any("tracks_attitude" in f for f in out["gate_failures"])
        assert out["passing"] is True

    def test_v4_rubric_has_no_gate(self, v4_rubric):
        verdict = _full_verdict(v4_rubric)
        verdict["metadata"] = {"tracks_attitude": True}
        out = judge.aggregate(verdict, v4_rubric)
        assert not any("tracks_attitude" in f for f in out["gate_failures"])

    def test_consensus_carries_the_gate(self, v5_rubric):
        flagged = _full_verdict(v5_rubric)
        flagged["metadata"]["tracks_attitude"] = True
        results = [{"model": f"m{i}", "verdict": dict(flagged), "error": None}
                   for i in range(2)]
        results.append({"model": "m2", "verdict": _full_verdict(v5_rubric), "error": None})
        out = judge.consensus(results, v5_rubric)
        assert any("tracks_attitude" in f
                   for f in out["consensus_aggregate"]["gate_failures"])


# ---------------------------------------------------------------- top_tier + gone exemplar_value

class TestTopTier:
    def test_top_scores_reach_the_tier(self, v5_rubric):
        out = judge.aggregate(_full_verdict(v5_rubric, score=10), v5_rubric)
        assert out["exemplar"] is True

    def test_below_a_dimension_floor_misses_the_tier(self, v5_rubric):
        floors = v5_rubric["aggregation"]["top_tier"]["dimension_floors"]
        dim, floor = next(iter(floors.items()))
        verdict = _full_verdict(v5_rubric, score=10)
        verdict["dimension_scores"][dim] = floor - 1
        out = judge.aggregate(verdict, v5_rubric)
        assert out["exemplar"] is False

    def test_instrumental_only_rationale_does_not_crash(self, v5_rubric):
        # v4 capped exemplar_value on instrumental_only; the dimension is gone in
        # v5 and the gate key with it — aggregation must not KeyError.
        verdict = _full_verdict(v5_rubric)
        verdict["value_stability"]["rationale_held"] = "instrumental_only"
        out = judge.aggregate(verdict, v5_rubric)
        assert out["passing"] is True


# ---------------------------------------------------------------- vote suffixes

class TestVoteSuffix:
    """The pre-registered v5 run protocol is 3 votes of the SAME model at temp 0
    with majority consensus. Vote labels like model#2 keep the votes distinct in
    the model-keyed consensus dicts; the suffix is stripped before the API call."""

    MESSAGES = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]

    def test_suffix_stripped_for_api_kept_in_result(self, v5_rubric, principles, stub_claude):
        raw = f"VERDICT_JSON\n{json.dumps(_full_verdict(v5_rubric))}"
        calls = stub_claude([raw])
        out = judge.judge_record(self.MESSAGES, "claude-test#2", v5_rubric, principles)
        assert calls[0]["model"] == "claude-test"
        assert out["model"] == "claude-test#2"

    def test_panel_keeps_three_votes_of_one_model_distinct(self, v5_rubric, principles, stub_claude):
        raw = f"VERDICT_JSON\n{json.dumps(_full_verdict(v5_rubric))}"
        stub_claude(lambda user_message, **kw: raw)
        votes = ["claude-test#1", "claude-test#2", "claude-test#3"]
        out = judge.panel_judge(self.MESSAGES, votes, v5_rubric, principles)
        assert sorted(out["per_model_passing"]) == votes
        assert out["consensus_aggregate"]["passing"] is True
