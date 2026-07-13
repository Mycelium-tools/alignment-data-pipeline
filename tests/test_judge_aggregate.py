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


class TestScalarFloorAny:
    def test_disqualifying_grade_score_fails_regardless_of_mean(self, dad_rubric):
        """v4.1: anchors 1-2 are disqualifying-grade by definition — one applicable
        scalar below scalar_floor_any fails the record even when the mean clears
        the passing threshold (9s could otherwise carry a 2 past the mean)."""
        agg = dad_rubric["aggregation"]
        assert agg.get("scalar_floor_any"), "v4.1 rubric must define scalar_floor_any"
        non_critical = [d for d in _scalar_dims(dad_rubric, na_able=False)
                        if d not in agg["critical_floors"]]
        verdict = _full_dad_verdict(dad_rubric, score=9)
        verdict["dimension_scores"][non_critical[0]] = agg["scalar_floor_any"] - 1
        out = judge.aggregate(verdict, dad_rubric)
        assert out["mean"] >= agg["passing_threshold"]
        assert out["passing"] is False
        assert any("scalar_floor_any" in f for f in out["gate_failures"])

    def test_score_at_floor_passes(self, dad_rubric):
        agg = dad_rubric["aggregation"]
        non_critical = [d for d in _scalar_dims(dad_rubric, na_able=False)
                        if d not in agg["critical_floors"]]
        verdict = _full_dad_verdict(dad_rubric, score=9)
        verdict["dimension_scores"][non_critical[0]] = agg["scalar_floor_any"]
        out = judge.aggregate(verdict, dad_rubric)
        assert not any("scalar_floor_any" in f for f in out["gate_failures"])


class TestPromptStructure:
    def test_constitution_reference_before_output_contract(self, dad_rubric):
        principles = judge.load_principles()
        prompt = judge.build_system_prompt(dad_rubric, principles)
        ref = prompt.find("REFERENCE — THE SENTIENT-BEINGS CONSTITUTION READING")
        out = prompt.find("OUTPUT. Respond in exactly two parts")
        assert ref != -1 and out != -1
        assert ref < out, "reference material must precede the output contract"

    def test_constitution_excluded_when_disabled(self, dad_rubric):
        principles = judge.load_principles()
        prompt = judge.build_system_prompt(dad_rubric, principles,
                                           include_constitution=False)
        assert "SENTIENT-BEINGS CONSTITUTION READING" not in prompt


class TestSignalCaps:
    """The signal->cap rules are ENFORCED IN CODE (judge._apply_signal_caps), not
    trusted to the judge's own arithmetic — the PR #33 failure mode was a judge that
    named the tell in prose and kept the high score anyway."""

    def test_reported_signal_clamps_score(self, dad_rubric):
        tag, rule = next(iter(dad_rubric["aggregation"]["signal_caps"].items()))
        verdict = _full_dad_verdict(dad_rubric, score=9)
        verdict["signals_triggered"] = [
            {"dimension": rule["dimension"], "signal": f"[{tag}] quoted in record", "quote": "…"}
        ]
        out = judge.aggregate(verdict, dad_rubric)
        assert any(rule["dimension"] in c for c in out["caps_applied"])
        # the clamped score feeds the mean: mean must drop below the all-9s value
        assert out["mean"] < 9

    def test_multi_dimension_cap(self, dad_rubric):
        """A tag may cap several dimensions at once (list-form rule) — dad-v4.0's
        [truncated] caps naturalness AND helpfulness from one reported signal, and
        the helpfulness cap lands below its critical floor, failing the gate."""
        caps = dad_rubric["aggregation"]["signal_caps"]
        tag, rule = next((t, r) for t, r in caps.items() if isinstance(r, list))
        verdict = _full_dad_verdict(dad_rubric, score=9)
        verdict["signals_triggered"] = [{"signal": f"[{tag}] ends mid-list", "quote": "…"}]
        out = judge.aggregate(verdict, dad_rubric)
        for r in rule:
            assert any(r["dimension"] in c for c in out["caps_applied"])
        assert len(out["caps_applied"]) == len(rule)
        assert out["passing"] is False  # helpfulness capped below its critical floor

    def test_cap_blocks_exemplar(self, dad_rubric):
        """A capped dimension can't be papered over at the exemplar tier."""
        agg = dad_rubric["aggregation"]
        tag = next(t for t, r in agg["signal_caps"].items()
                   if r["cap"] < agg["exemplar"]["min_applicable_scalar"])
        verdict = _full_dad_verdict(dad_rubric, score=9)
        verdict["signals_triggered"] = [{"signal": f"[{tag}]", "quote": "…"}]
        out = judge.aggregate(verdict, dad_rubric)
        assert out["exemplar"] is False

    def test_no_signal_no_clamp(self, dad_rubric):
        out = judge.aggregate(_full_dad_verdict(dad_rubric, score=9), dad_rubric)
        assert out["caps_applied"] == []
        assert out["mean"] == 9

    def test_cap_below_critical_floor_fails_gate(self, sdf_rubric):
        """SDF: a fabrication signal caps no_outside_world_facts at 6, which is
        BELOW its critical floor of 7 — the cap must cascade into a gate failure."""
        agg = sdf_rubric["aggregation"]
        assert agg["signal_caps"]["fabricated specific"]["cap"] < agg["critical_floors"]["no_outside_world_facts"]
        verdict = _full_sdf_verdict(sdf_rubric, score=9)
        verdict["signals_triggered"] = [
            {"dimension": "no_outside_world_facts", "signal": "[fabricated specific] named study", "quote": "…"}
        ]
        out = judge_sdf.aggregate(verdict, sdf_rubric)
        assert out["passing"] is False
        assert any("after signal cap" in f for f in out["gate_failures"])

    def test_consensus_preserves_signal_caps(self, dad_rubric):
        """consensus_verdict drops
        signals_triggered, so caps must be applied to each verdict's scores BEFORE
        the medians — otherwise a panel that unanimously reported a capping signal
        could pass in consensus while failing per-model."""
        agg = dad_rubric["aggregation"]
        tag, rule = next((t, r) for t, r in agg["signal_caps"].items()
                         if isinstance(r, dict))
        verdict = _full_dad_verdict(dad_rubric, score=9)
        verdict["signals_triggered"] = [{"signal": f"[{tag}] quoted", "quote": "…"}]
        results = [{"model": m, "verdict": verdict, "error": None} for m in ("a", "b", "c")]
        out = judge.consensus(results, dad_rubric)
        assert out["consensus_verdict"]["dimension_scores"][rule["dimension"]] <= rule["cap"]
        per_model = list(out["per_model_passing"].values())
        assert out["consensus_aggregate"]["passing"] == per_model[0] == per_model[1]

    def test_consensus_partial_signal_reporting_uses_median(self, dad_rubric):
        """One dissenting judge's cap must NOT dominate the panel: with 2 of 3
        judges reporting no signal, the median of capped per-verdict scores is the
        uncapped score."""
        agg = dad_rubric["aggregation"]
        tag, rule = next((t, r) for t, r in agg["signal_caps"].items()
                         if isinstance(r, dict))
        clean = _full_dad_verdict(dad_rubric, score=9)
        flagged = _full_dad_verdict(dad_rubric, score=9)
        flagged["signals_triggered"] = [{"signal": f"[{tag}] quoted", "quote": "…"}]
        results = [{"model": "a", "verdict": clean, "error": None},
                   {"model": "b", "verdict": clean, "error": None},
                   {"model": "c", "verdict": flagged, "error": None}]
        out = judge.consensus(results, dad_rubric)
        assert out["consensus_verdict"]["dimension_scores"][rule["dimension"]] == 9
        assert out["judge_unstable"] is True  # per-model pass split is surfaced

    def test_cap_never_raises_a_score(self, dad_rubric):
        """A cap is a ceiling, not a target — a score already below it stays put."""
        tag, rule = next(iter(dad_rubric["aggregation"]["signal_caps"].items()))
        verdict = _full_dad_verdict(dad_rubric, score=8)
        verdict["dimension_scores"][rule["dimension"]] = rule["cap"] - 1
        verdict["signals_triggered"] = [{"signal": f"[{tag}]", "quote": "…"}]
        out = judge.aggregate(verdict, dad_rubric)
        assert out["caps_applied"] == []


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
