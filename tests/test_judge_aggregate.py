"""Tests for the judge aggregators (evals/judge.py, evals/judge_sdf.py).

The aggregators are the "never trust judge arithmetic" layer: deterministic code
that turns one judge verdict into gate failures + pass/exemplar tiers. The money
path here is the malformed-verdict guard — a sparse verdict (judge JSON missing
scalar dimensions) must FAIL the gate, not pass on its strongest dimensions alone
(found by adversarial review: a 4-dimension verdict could reach exemplar=True).

Dimension expectations are DERIVED from the live rubrics, never hardcoded — the
rubrics are actively edited and dimensions renumber/rename.
"""

import pytest

from evals import judge, judge_sdf


@pytest.fixture(scope="module")
def dad_rubric():
    return judge.load_rubric(judge.DEFAULT_RUBRIC_PATH)


@pytest.fixture(scope="module")
def sdf_rubric():
    return judge.load_rubric(judge_sdf.DEFAULT_RUBRIC_PATH)


def _scalar_dims(rubric, na_able):
    return [d for d, spec in rubric["dimensions"].items()
            if spec["type"] == "scalar" and bool(spec.get("na_when")) == na_able]


def _full_dad_verdict(rubric, score=8):
    """A well-formed verdict: every non-NA scalar present, gates satisfied."""
    agg = rubric["aggregation"]
    posture = next(iter(agg["behavior_gate"]))
    return {
        "dimension_scores": {d: score for d in _scalar_dims(rubric, na_able=False)},
        "posture_class": posture,
        "autonomy_behavior": agg["behavior_gate"][posture],
        "value_stability": {"outcome_held": True, "rationale_held": "held"},
        "self_contained": True,
    }


def _full_sdf_verdict(rubric, score=8):
    agg = rubric["aggregation"]
    return {
        "dimension_scores": {d: score for d in _scalar_dims(rubric, na_able=False)},
        "depicted_ai_alignment": agg["depicted_ai_gate"][0],
        "no_scaffolding_leak": True,
    }


class TestDadAggregate:
    def test_full_verdict_passes(self, dad_rubric):
        out = judge.aggregate(_full_dad_verdict(dad_rubric), dad_rubric)
        assert out["gate_failures"] == []
        assert out["passing"] is True

    def test_sparse_verdict_fails_gate(self, dad_rubric):
        """The adversarial-review scenario: only the critical + exemplar-floor dims
        present. Must fail, and must name every omitted non-NA scalar."""
        agg = dad_rubric["aggregation"]
        verdict = _full_dad_verdict(dad_rubric, score=9)
        kept = set(agg["critical_floors"]) | set(agg["exemplar"]["dimension_floors"])
        verdict["dimension_scores"] = {
            d: v for d, v in verdict["dimension_scores"].items() if d in kept
        }
        out = judge.aggregate(verdict, dad_rubric)
        assert out["passing"] is False
        assert out["exemplar"] is False
        omitted = [d for d in _scalar_dims(dad_rubric, na_able=False) if d not in kept]
        assert omitted, "scenario needs at least one omitted non-NA scalar to test"
        for dim in omitted:
            assert any(dim in f for f in out["gate_failures"]), f"{dim} not flagged"

    def test_na_able_scalars_may_sit_out(self, dad_rubric):
        """Omitting only NA-able dimensions is a well-formed verdict, not sparse."""
        out = judge.aggregate(_full_dad_verdict(dad_rubric), dad_rubric)
        na_able = _scalar_dims(dad_rubric, na_able=True)
        assert na_able, "rubric should have at least one NA-able scalar"
        assert not any(d in f for d in na_able for f in out["gate_failures"])

    def test_non_numeric_score_counts_as_missing(self, dad_rubric):
        verdict = _full_dad_verdict(dad_rubric)
        dim = _scalar_dims(dad_rubric, na_able=False)[-1]
        verdict["dimension_scores"][dim] = "NA"  # judge marked a non-NA dim as NA
        out = judge.aggregate(verdict, dad_rubric)
        assert out["passing"] is False
        assert any(dim in f for f in out["gate_failures"])

    def test_omitted_value_stability_fails_gate(self, dad_rubric):
        """Non-scalar guard: value_stability must be present even for single-turn
        records (schema: empty turn_moves) — omission is a malformed verdict."""
        verdict = _full_dad_verdict(dad_rubric)
        del verdict["value_stability"]
        out = judge.aggregate(verdict, dad_rubric)
        assert out["passing"] is False
        assert any("value_stability missing" in f for f in out["gate_failures"])

    def test_exemplar_needs_every_scalar_at_min(self, dad_rubric):
        """All-9s clears exemplar; one non-floor scalar below min_applicable blocks it."""
        agg = dad_rubric["aggregation"]
        out = judge.aggregate(_full_dad_verdict(dad_rubric, score=9), dad_rubric)
        assert out["exemplar"] is True
        weak = _full_dad_verdict(dad_rubric, score=9)
        non_floor = [d for d in _scalar_dims(dad_rubric, na_able=False)
                     if d not in agg["exemplar"]["dimension_floors"]]
        weak["dimension_scores"][non_floor[0]] = agg["exemplar"]["min_applicable_scalar"] - 1
        out = judge.aggregate(weak, dad_rubric)
        assert out["exemplar"] is False


class TestSdfAggregate:
    def test_full_verdict_passes(self, sdf_rubric):
        out = judge_sdf.aggregate(_full_sdf_verdict(sdf_rubric), sdf_rubric)
        assert out["gate_failures"] == []
        assert out["passing"] is True

    def test_sparse_verdict_fails_gate(self, sdf_rubric):
        """SDF twin of the adversarial scenario: criticals only, rest omitted."""
        agg = sdf_rubric["aggregation"]
        verdict = _full_sdf_verdict(sdf_rubric, score=9)
        verdict["dimension_scores"] = {
            d: v for d, v in verdict["dimension_scores"].items()
            if d in agg["critical_floors"]
        }
        out = judge_sdf.aggregate(verdict, sdf_rubric)
        assert out["passing"] is False
        assert out["exemplar"] is False
        omitted = [d for d in _scalar_dims(sdf_rubric, na_able=False)
                   if d not in agg["critical_floors"]]
        assert omitted, "scenario needs at least one omitted non-NA scalar to test"
        for dim in omitted:
            assert any(dim in f for f in out["gate_failures"]), f"{dim} not flagged"

    def test_na_able_scalars_may_sit_out(self, sdf_rubric):
        out = judge_sdf.aggregate(_full_sdf_verdict(sdf_rubric), sdf_rubric)
        na_able = _scalar_dims(sdf_rubric, na_able=True)
        assert na_able, "rubric should have at least one NA-able scalar"
        assert not any(d in f for d in na_able for f in out["gate_failures"])

    def test_omitted_depicted_ai_alignment_fails_gate(self, sdf_rubric):
        """Omission must not be coerced to a passing 'NA' — 'NA' is only legitimate
        when the judge states it explicitly (no AI in the document)."""
        verdict = _full_sdf_verdict(sdf_rubric)
        del verdict["depicted_ai_alignment"]
        out = judge_sdf.aggregate(verdict, sdf_rubric)
        assert out["passing"] is False
        assert any("depicted_ai_alignment missing" in f for f in out["gate_failures"])

    def test_explicit_na_depicted_ai_alignment_passes(self, sdf_rubric):
        verdict = _full_sdf_verdict(sdf_rubric)
        verdict["depicted_ai_alignment"] = "NA"
        out = judge_sdf.aggregate(verdict, sdf_rubric)
        assert out["gate_failures"] == []
        assert out["passing"] is True
