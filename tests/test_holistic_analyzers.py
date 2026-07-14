"""Analyzers are pluggable and input-gated. Each declares which inputs it needs
(tags / annotations / verdicts); the runner runs only those whose inputs are present,
so the report degrades gracefully as the three-input model dictates. Adding or
replacing an analysis is a single registry call."""

from evals.holistic import analyzers as A
from evals.holistic import fields as F

RECORDS = [
    {"record_id": "a", "taxa_category": "farmed", "language": "en"},
    {"record_id": "b", "taxa_category": "wild", "language": "en"},
    {"record_id": "c", "taxa_category": "farmed", "language": "zh"},
]


def _ctx(**kw):
    return A.AnalysisContext(records=RECORDS, fields=F.default_fields(), **kw)


# ---------------------------------------------------------------- registry

def test_register_replace_remove_analyzer():
    reg = A.AnalyzerRegistry()
    reg.add(A.Analyzer(name="x", requires=("tags",), fn=lambda ctx: {"n": 1}))
    reg.replace(A.Analyzer(name="x", requires=("tags",), fn=lambda ctx: {"n": 2}))
    assert reg.get("x").fn(_ctx()) == {"n": 2}
    reg.remove("x")
    assert "x" not in reg


# ---------------------------------------------------------------- input gating

def test_tags_only_analyzer_runs_without_annotations_or_verdicts():
    reg = A.AnalyzerRegistry()
    reg.add(A.Analyzer(name="counts", requires=("tags",),
                       fn=lambda ctx: {"records": len(ctx.records)}))
    out = A.run_analyzers(_ctx(), reg)
    assert out["analyses"]["counts"] == {"records": 3}
    assert out["skipped"] == {}


def test_analyzer_needing_annotations_is_skipped_when_absent_and_runs_when_present():
    reg = A.AnalyzerRegistry()
    reg.add(A.Analyzer(name="drift", requires=("tags", "annotations"),
                       fn=lambda ctx: {"joined": len(ctx.annotations)}))

    skipped = A.run_analyzers(_ctx(), reg)
    assert "drift" in skipped["skipped"]
    assert "drift" not in skipped["analyses"]

    ran = A.run_analyzers(_ctx(annotations={"a": {}, "b": {}}), reg)
    assert ran["analyses"]["drift"] == {"joined": 2}


def test_available_reflects_which_inputs_were_supplied():
    assert _ctx().available == {"tags"}
    assert _ctx(annotations={"a": {}}).available == {"tags", "annotations"}
    assert _ctx(verdicts={"a": {}}).available == {"tags", "verdicts"}


# ---------------------------------------------------------------- seed analyzer

def test_default_registry_distribution_counts_values_per_field():
    out = A.run_analyzers(_ctx(), A.default_analyzers())
    dist = out["analyses"]["distribution"]
    assert dist["taxa_category"] == {"farmed": 2, "wild": 1}
    assert dist["language"] == {"en": 2, "zh": 1}


def test_pielou_evenness_is_1_for_uniform_and_0_for_collapsed():
    assert A.pielou_evenness({"a": 5, "b": 5}) == 1.0
    assert A.pielou_evenness({"a": 9}) == 0.0          # single value = fully collapsed
    assert A.pielou_evenness({}) is None               # empty axis = not applicable


def test_evenness_analyzer_scores_and_verdicts_each_axis():
    out = A.run_analyzers(_ctx(), A.default_analyzers())["analyses"]["evenness"]
    # taxa_category = {farmed:2, wild:1} → fairly even → GOOD
    assert out["taxa_category"]["richness"] == 2
    assert out["taxa_category"]["evenness"] > 0.9
    assert out["taxa_category"]["verdict"] == "GOOD"
    assert "note" in out["taxa_category"]              # "what BAD looks like"


def test_evenness_flags_a_collapsed_axis_as_bad():
    records = [{"record_id": str(i), "taxa_category": "farmed"} for i in range(5)]
    reg = F.FieldRegistry()
    reg.add(F.Field(name="taxa_category", kind="single", values=("farmed", "wild")))
    out = A.run_analyzers(A.AnalysisContext(records=records, fields=reg),
                          A.default_analyzers())["analyses"]["evenness"]
    assert out["taxa_category"]["evenness"] == 0.0
    assert out["taxa_category"]["verdict"] == "BAD"


def test_evenness_marks_an_empty_axis_NA():
    out = A.run_analyzers(_ctx(), A.default_analyzers())["analyses"]["evenness"]
    # posture_class never appears in RECORDS
    assert out["posture_class"]["evenness"] is None
    assert out["posture_class"]["verdict"] == "NA"


def _reg_with_target(target, values=("Explicit", "Implicit", "Hidden")):
    reg = F.FieldRegistry()
    reg.add(F.Field(name="visibility", kind="single", values=values, target=target))
    return reg


def test_coverage_flags_a_min_share_shortfall():
    # 1/5 = 0.2 Hidden meets 0.2; make it 1/10 to fall short
    records = ([{"record_id": str(i), "visibility": "Hidden"} for i in range(1)]
               + [{"record_id": f"x{i}", "visibility": "Explicit"} for i in range(9)])
    reg = _reg_with_target({"min_share": {"Hidden": 0.2}})
    out = A.run_analyzers(A.AnalysisContext(records=records, fields=reg),
                          A.default_analyzers())["analyses"]["coverage_vs_target"]
    assert out["visibility"]["verdict"] == "BAD"
    assert any("Hidden" in v for v in out["visibility"]["violations"])


def test_coverage_passes_when_min_share_is_met():
    records = ([{"record_id": str(i), "visibility": "Hidden"} for i in range(3)]
               + [{"record_id": f"x{i}", "visibility": "Explicit"} for i in range(7)])
    reg = _reg_with_target({"min_share": {"Hidden": 0.2}})
    out = A.run_analyzers(A.AnalysisContext(records=records, fields=reg),
                          A.default_analyzers())["analyses"]["coverage_vs_target"]
    assert out["visibility"]["verdict"] == "GOOD"
    assert out["visibility"]["violations"] == []


def test_coverage_require_all_values_flags_a_missing_value():
    records = [{"record_id": str(i), "visibility": "Explicit"} for i in range(4)]
    reg = _reg_with_target({"require_all_values": True})
    out = A.run_analyzers(A.AnalysisContext(records=records, fields=reg),
                          A.default_analyzers())["analyses"]["coverage_vs_target"]
    assert out["visibility"]["verdict"] == "BAD"
    assert any("Hidden" in v for v in out["visibility"]["violations"])
    assert any("Implicit" in v for v in out["visibility"]["violations"])


def test_coverage_max_share_each_flags_a_dominating_value():
    records = ([{"record_id": str(i), "domain": "Food & Cooking"} for i in range(9)]
               + [{"record_id": "z", "domain": "Career"}])
    reg = F.FieldRegistry()
    reg.add(F.Field(name="domain", kind="single", target={"max_share_each": 0.12}))
    out = A.run_analyzers(A.AnalysisContext(records=records, fields=reg),
                          A.default_analyzers())["analyses"]["coverage_vs_target"]
    assert out["domain"]["verdict"] == "BAD"
    assert any("Food & Cooking" in v for v in out["domain"]["violations"])


def test_coverage_band_each_flags_a_missing_vocabulary_value():
    # 'Mixed' never appears → its 0% share is below the 0.25 floor and must be flagged
    records = ([{"record_id": str(i), "direction": "Under-weighting"} for i in range(3)]
               + [{"record_id": f"x{i}", "direction": "Over-weighting"} for i in range(3)])
    reg = F.FieldRegistry()
    reg.add(F.Field(name="direction", kind="single",
                    values=("Under-weighting", "Over-weighting", "Mixed"),
                    target={"band_each": [0.25, 0.75]}))
    out = A.run_analyzers(A.AnalysisContext(records=records, fields=reg),
                          A.default_analyzers())["analyses"]["coverage_vs_target"]
    assert out["direction"]["verdict"] == "BAD"
    assert any("Mixed" in v for v in out["direction"]["violations"])


def test_coverage_marks_an_empty_axis_NA_and_skips_untargeted_fields():
    reg = F.FieldRegistry()
    reg.add(F.Field(name="visibility", kind="single",
                    values=("Explicit", "Hidden"), target={"min_share": {"Hidden": 0.2}}))
    reg.add(F.Field(name="language", kind="free"))       # no target
    out = A.run_analyzers(A.AnalysisContext(records=[], fields=reg),
                          A.default_analyzers())["analyses"]["coverage_vs_target"]
    assert out["visibility"]["verdict"] == "NA"          # target but no data
    assert "language" not in out                          # untargeted field skipped


# ---------------------------------------------------------------- correlation (Cramér's V)

def test_cramers_v_is_1_for_perfect_coupling_and_0_for_independence():
    coupled = {("Hostile", "Under-weighting"): 5, ("Concerned", "Over-weighting"): 5}
    assert A.cramers_v(coupled) == 1.0
    independent = {("Hostile", "Under-weighting"): 5, ("Hostile", "Over-weighting"): 5,
                   ("Concerned", "Under-weighting"): 5, ("Concerned", "Over-weighting"): 5}
    assert A.cramers_v(independent) == 0.0


def test_cramers_v_ignores_explicit_zero_counts_without_crashing():
    # a hand-built joint with a zero-count key must not raise; the zero level is absent
    assert A.cramers_v({("a", "x"): 0, ("b", "y"): 1}) is None
    coupled = {("H", "U"): 5, ("H", "O"): 0, ("C", "O"): 5}   # explicit zero cell
    assert A.cramers_v(coupled) == 1.0


def test_cramers_v_is_none_when_a_variable_has_one_level():
    # only one attitude observed → association undefined
    assert A.cramers_v({("Hostile", "Under-weighting"): 5,
                        ("Hostile", "Over-weighting"): 5}) is None
    assert A.cramers_v({}) is None


def _corr_ctx(records, pairs):
    reg = F.FieldRegistry()
    reg.add(F.Field(name="user_attitude", kind="single", values=("Hostile", "Concerned")))
    reg.add(F.Field(name="direction", kind="single",
                    values=("Under-weighting", "Over-weighting")))
    return A.AnalysisContext(records=records, fields=reg,
                             config={"important_pairs": pairs})


def test_correlation_flags_a_coupled_pair_as_bad():
    # attitude perfectly predicts direction — the sycophancy tell
    records = ([{"record_id": str(i), "user_attitude": "Hostile",
                 "direction": "Under-weighting"} for i in range(5)]
               + [{"record_id": f"x{i}", "user_attitude": "Concerned",
                   "direction": "Over-weighting"} for i in range(5)])
    ctx = _corr_ctx(records, [["user_attitude", "direction"]])
    out = A.run_analyzers(ctx, A.default_analyzers())["analyses"]["correlation"]
    key = "user_attitude x direction"
    assert out[key]["cramers_v"] == 1.0
    assert out[key]["verdict"] == "BAD"
    assert out[key]["n"] == 10


def test_correlation_passes_an_independent_pair():
    records = []
    i = 0
    for att in ("Hostile", "Concerned"):
        for dr in ("Under-weighting", "Over-weighting"):
            for _ in range(3):
                records.append({"record_id": str(i), "user_attitude": att, "direction": dr})
                i += 1
    ctx = _corr_ctx(records, [["user_attitude", "direction"]])
    out = A.run_analyzers(ctx, A.default_analyzers())["analyses"]["correlation"]
    assert out["user_attitude x direction"]["verdict"] == "GOOD"


def test_correlation_marks_insufficient_data_NA_and_reads_pairs_from_config():
    ctx = _corr_ctx([{"record_id": "a", "user_attitude": "Hostile",
                      "direction": "Under-weighting"}],
                    [["user_attitude", "direction"]])
    out = A.run_analyzers(ctx, A.default_analyzers())["analyses"]["correlation"]
    assert out["user_attitude x direction"]["verdict"] == "NA"
    # no pairs configured → analyzer reports nothing
    empty = A.run_analyzers(_corr_ctx([], []), A.default_analyzers())["analyses"]["correlation"]
    assert empty == {}


def test_correlation_skips_records_missing_either_axis_and_list_values():
    records = [{"record_id": "a", "user_attitude": "Hostile",
                "direction": "Under-weighting"},
               {"record_id": "b", "user_attitude": "Hostile"},                # no direction
               {"record_id": "c", "user_attitude": ["Hostile"],              # list-valued
                "direction": "Over-weighting"}]
    ctx = _corr_ctx(records, [["user_attitude", "direction"]])
    out = A.run_analyzers(ctx, A.default_analyzers())["analyses"]["correlation"]
    assert out["user_attitude x direction"]["n"] == 1                        # only 'a' counted


def test_correlation_rejects_a_malformed_pair():
    import pytest
    ctx = _corr_ctx([{"record_id": "a", "user_attitude": "Hostile",
                      "direction": "Under-weighting"}], [["user_attitude"]])
    with pytest.raises(ValueError, match="important_pairs"):
        A.run_analyzers(ctx, A.default_analyzers())


def test_select_filters_the_registry_by_name():
    reg = A.default_analyzers()
    only = A.select(reg, ["distribution"])
    assert only.names() == ["distribution"]
    assert A.select(reg, None).names() == reg.names()   # None = keep all


def test_select_rejects_an_unknown_analyzer_name():
    import pytest
    with pytest.raises(ValueError, match="nope"):
        A.select(A.default_analyzers(), ["nope"])


# ---------------------------------------------------------------- combination_coverage (t-wise)

def _combo_ctx(records, pairs):
    reg = F.FieldRegistry()
    reg.add(F.Field(name="leverage", kind="single",
                    values=("Individual", "Organizational", "Systemic")))
    reg.add(F.Field(name="direction", kind="single",
                    values=("Under-weighting", "Over-weighting")))
    return A.AnalysisContext(records=records, fields=reg,
                             config={"important_pairs": pairs})


def test_combination_coverage_reports_full_coverage_and_no_missing_cells():
    # all 3x2 = 6 leverage x direction cells occur at least once
    records = []
    i = 0
    for lev in ("Individual", "Organizational", "Systemic"):
        for dr in ("Under-weighting", "Over-weighting"):
            records.append({"record_id": str(i), "leverage": lev, "direction": dr})
            i += 1
    ctx = _combo_ctx(records, [["leverage", "direction"]])
    out = A.run_analyzers(ctx, A.default_analyzers())["analyses"]["combination_coverage"]
    key = "leverage x direction"
    assert out[key]["cells"] == 6
    assert out[key]["filled"] == 6
    assert out[key]["coverage"] == 1.0
    assert out[key]["missing"] == []
    assert out[key]["verdict"] == "GOOD"


def test_combination_coverage_lists_missing_cells_and_flags_bad():
    # only 1 of 6 cells populated → coverage ~0.17 → BAD, 5 missing cells named
    records = [{"record_id": "a", "leverage": "Individual", "direction": "Under-weighting"}]
    ctx = _combo_ctx(records, [["leverage", "direction"]])
    out = A.run_analyzers(ctx, A.default_analyzers())["analyses"]["combination_coverage"]
    key = "leverage x direction"
    assert out[key]["filled"] == 1
    assert out[key]["coverage"] == round(1 / 6, 3)
    assert out[key]["verdict"] == "BAD"
    assert len(out[key]["missing"]) == 5
    assert "Systemic×Over-weighting" in out[key]["missing"]
    assert "Individual×Under-weighting" not in out[key]["missing"]   # the one that occurred


def test_combination_coverage_is_na_when_an_axis_lacks_a_vocabulary():
    reg = F.FieldRegistry()
    reg.add(F.Field(name="beings", kind="multi"))            # free multi, no values
    reg.add(F.Field(name="direction", kind="single",
                    values=("Under-weighting", "Over-weighting")))
    ctx = A.AnalysisContext(records=[{"record_id": "a", "beings": ["hen"],
                                      "direction": "Under-weighting"}], fields=reg,
                            config={"important_pairs": [["beings", "direction"]]})
    out = A.run_analyzers(ctx, A.default_analyzers())["analyses"]["combination_coverage"]
    assert out["beings x direction"]["verdict"] == "NA"
    assert out["beings x direction"]["coverage"] is None


def test_combination_coverage_is_na_with_no_contributing_records():
    ctx = _combo_ctx([], [["leverage", "direction"]])
    out = A.run_analyzers(ctx, A.default_analyzers())["analyses"]["combination_coverage"]
    assert out["leverage x direction"]["verdict"] == "NA"
    assert out["leverage x direction"]["n"] == 0
    # spec §9D: the missing-cell list is still reported — with nothing populated,
    # EVERY valid cell is missing (an empty list would claim full coverage)
    assert len(out["leverage x direction"]["missing"]) == 6
    assert "Systemic×Over-weighting" in out["leverage x direction"]["missing"]


def test_combination_coverage_rejects_non_string_axis_names():
    import pytest
    # a config typo must fail loudly as ValueError, never TypeError or silent NA
    with pytest.raises(ValueError, match="important_pairs"):
        A.run_analyzers(_combo_ctx([], [[["leverage"], "direction"]]),
                        A.default_analyzers())
    with pytest.raises(ValueError, match="important_pairs"):
        A.run_analyzers(_combo_ctx([], [[123, "direction"]]), A.default_analyzers())


def test_combination_coverage_reads_pairs_from_config_and_rejects_malformed_pair():
    import pytest
    assert A.run_analyzers(_combo_ctx([], []),
                           A.default_analyzers())["analyses"]["combination_coverage"] == {}
    with pytest.raises(ValueError, match="important_pairs"):
        A.run_analyzers(_combo_ctx([], [["leverage"]]), A.default_analyzers())


# ---------------------------------------------------------------- drift (intent -> realized)

def _drift_ctx(records, annotations):
    reg = F.FieldRegistry()
    reg.add(F.Field(name="direction", kind="single",
                    values=("Under-weighting", "Over-weighting", "Mixed")))
    reg.add(F.Field(name="taxa_category", kind="single",
                    values=("farmed", "wild")))
    return A.AnalysisContext(records=records, fields=reg, annotations=annotations)


def test_drift_requires_annotations_and_is_skipped_without_them():
    ctx = _drift_ctx([{"record_id": "a", "direction": "Mixed"}], annotations=None)
    out = A.run_analyzers(ctx, A.default_analyzers())
    assert "drift" in out["skipped"]
    assert "drift" not in out["analyses"]


def test_drift_reports_high_agreement_as_good():
    records = [{"record_id": str(i), "direction": "Mixed"} for i in range(10)]
    anns = {str(i): {"direction": "Mixed"} for i in range(10)}
    ctx = _drift_ctx(records, anns)
    out = A.run_analyzers(ctx, A.default_analyzers())["analyses"]["drift"]
    assert out["direction"]["n"] == 10
    assert out["direction"]["agreement"] == 1.0
    assert out["direction"]["disagreements"] == []
    assert out["direction"]["verdict"] == "GOOD"


def test_drift_flags_systematic_disagreement_as_bad_with_confusion_pairs():
    # intended Over-weighting but realized Under-weighting for most records
    records = ([{"record_id": str(i), "direction": "Under-weighting"} for i in range(7)]
               + [{"record_id": f"x{i}", "direction": "Over-weighting"} for i in range(3)])
    anns = {str(i): {"direction": "Over-weighting"} for i in range(7)}
    anns.update({f"x{i}": {"direction": "Over-weighting"} for i in range(3)})
    ctx = _drift_ctx(records, anns)
    out = A.run_analyzers(ctx, A.default_analyzers())["analyses"]["drift"]
    assert out["direction"]["n"] == 10
    assert out["direction"]["agreement"] == 0.3
    assert out["direction"]["verdict"] == "BAD"
    top = out["direction"]["disagreements"][0]
    assert top == {"intended": "Over-weighting", "realized": "Under-weighting", "count": 7}


def test_drift_does_not_count_a_bool_int_type_mismatch_as_agreement():
    # Python's True == 1 must not report agreement — a type mismatch is a disagreement
    reg = F.FieldRegistry()
    reg.add(F.Field(name="systemic_ai", kind="bool"))
    records = [{"record_id": "a", "systemic_ai": True}]
    ctx = A.AnalysisContext(records=records, fields=reg,
                            annotations={"a": {"systemic_ai": 1}})
    out = A.run_analyzers(ctx, A.default_analyzers())["analyses"]["drift"]
    assert out["systemic_ai"]["agreement"] == 0.0
    assert out["systemic_ai"]["disagreements"][0]["count"] == 1


def test_drift_disagreements_order_is_deterministic_under_tied_counts():
    # equal-count confusion pairs must come out in a canonical order regardless of
    # the input record order (reports should be reproducible across reorderings)
    def _run(records):
        ctx = _drift_ctx(records, {r["record_id"]: {"direction": "Mixed"}
                                   for r in records})
        return A.run_analyzers(ctx, A.default_analyzers())["analyses"]["drift"]
    recs = [{"record_id": "a", "direction": "Under-weighting"},
            {"record_id": "b", "direction": "Over-weighting"}]
    assert (_run(recs)["direction"]["disagreements"]
            == _run(list(reversed(recs)))["direction"]["disagreements"])


def test_drift_disagreement_order_is_deterministic_across_type_distinct_ties():
    # bool True and str "True" have the same str() — the canonical order must not
    # collapse them into an input-order-dependent tie
    reg = F.FieldRegistry()
    reg.add(F.Field(name="x", kind="free"))

    def _run(records, anns):
        ctx = A.AnalysisContext(records=records, fields=reg, annotations=anns)
        return A.run_analyzers(ctx, A.default_analyzers())["analyses"]["drift"]

    recs = [{"record_id": "a", "x": False}, {"record_id": "b", "x": "False"}]
    anns = {"a": {"x": True}, "b": {"x": "True"}}
    assert (_run(recs, anns)["x"]["disagreements"]
            == _run(list(reversed(recs)), anns)["x"]["disagreements"])


def test_drift_only_counts_records_present_in_both_sides_and_skips_axes_never_intended():
    records = [{"record_id": "a", "direction": "Mixed", "taxa_category": "farmed"},
               {"record_id": "b", "direction": "Mixed"},               # annotation absent
               {"record_id": "c", "direction": "Under-weighting"}]     # annotation lacks axis
    anns = {"a": {"direction": "Mixed"}, "c": {"taxa_category": "wild"}}
    ctx = _drift_ctx(records, anns)
    out = A.run_analyzers(ctx, A.default_analyzers())["analyses"]["drift"]
    assert out["direction"]["n"] == 1            # only 'a' compared on direction
    assert "taxa_category" not in out            # never comparably intended+realized


def test_distribution_skips_object_valued_fields_without_crashing():
    reg = F.FieldRegistry()
    reg.add(F.Field(name="welfare_magnitude", kind="object"))
    reg.add(F.Field(name="taxa_category", kind="single", values=("farmed", "wild")))
    records = [{"record_id": "a", "welfare_magnitude": {"severity": "Severe"},
                "taxa_category": "farmed"}]
    ctx = A.AnalysisContext(records=records, fields=reg)
    dist = A.run_analyzers(ctx, A.default_analyzers())["analyses"]["distribution"]
    assert dist["taxa_category"] == {"farmed": 1}          # object field did not crash it
    assert dist["welfare_magnitude"] == {}                 # unhashable values skipped


# ---------------------------------------------------------------- cluster bridge (§18.1)

def _bridge_records(aligned: bool):
    """8 records over 2 taxa values × 2 embedding clusters: perfectly aligned
    (taxa determines cluster) or perfectly independent (every cell equal)."""
    records, clusters = [], {}
    for i in range(8):
        taxa = "farmed" if i % 2 == 0 else "wild"
        rid = f"r{i}"
        records.append({"record_id": rid, "taxa_category": taxa, "language": "en"})
        clusters[rid] = (i % 2) if aligned else (i // 4)
    return records, clusters


def test_available_includes_clusters_when_supplied():
    assert _ctx(clusters={"a": 0}).available == {"tags", "clusters"}


def test_cluster_bridge_is_gated_on_the_clusters_input():
    reg = A.default_analyzers()
    without = A.run_analyzers(_ctx(), reg)
    assert "cluster_bridge" in without["skipped"]
    with_clusters = A.run_analyzers(_ctx(clusters={"a": 0, "b": 1, "c": 0}), reg)
    assert "cluster_bridge" in with_clusters["analyses"]


def test_cluster_bridge_axis_tracking_clusters_is_good():
    records, clusters = _bridge_records(aligned=True)
    ctx = A.AnalysisContext(records=records, fields=F.default_fields(), clusters=clusters)
    out = A._cluster_bridge(ctx)
    assert out["taxa_category"]["n"] == 8
    assert out["taxa_category"]["cramers_v"] == 1.0
    assert out["taxa_category"]["verdict"] == "GOOD"


def test_cluster_bridge_axis_ignored_by_clusters_is_bad():
    records, clusters = _bridge_records(aligned=False)
    ctx = A.AnalysisContext(records=records, fields=F.default_fields(), clusters=clusters)
    out = A._cluster_bridge(ctx)
    assert out["taxa_category"]["cramers_v"] == 0.0
    assert out["taxa_category"]["verdict"] == "BAD"


def test_cluster_bridge_single_level_axis_is_na():
    records, clusters = _bridge_records(aligned=True)
    out = A._cluster_bridge(A.AnalysisContext(
        records=records, fields=F.default_fields(), clusters=clusters))
    assert out["language"]["cramers_v"] is None    # only "en" observed
    assert out["language"]["verdict"] == "NA"


def test_cluster_bridge_omits_unpopulated_axes_and_skips_unclustered_records():
    records, clusters = _bridge_records(aligned=True)
    del clusters["r0"]                              # r0 never embedded/clustered
    out = A._cluster_bridge(A.AnalysisContext(
        records=records, fields=F.default_fields(), clusters=clusters))
    assert "posture_class" not in out               # no record carries it
    assert out["taxa_category"]["n"] == 7


def test_cramers_v_tolerates_mixed_type_levels():
    import pytest
    # a coerced-but-invalid tag row can put an int on a string axis; the level
    # sort must not TypeError and V is order-independent anyway
    joint = {("farmed", 0): 3, (1, 1): 3}
    assert A.cramers_v(joint) == pytest.approx(1.0)


def test_cluster_bridge_counts_multi_valued_axes_per_occurrence():
    reg = F.FieldRegistry()
    reg.add(F.Field(name="domain", kind="multi", values=("Food", "Policy")))
    records = [
        {"record_id": "a", "domain": ["Food"]},
        {"record_id": "b", "domain": ["Policy"]},
        {"record_id": "e", "domain": ["Food", "Policy"]},   # contributes twice
    ]
    clusters = {"a": 0, "b": 1, "e": 0}
    out = A._cluster_bridge(A.AnalysisContext(records=records, fields=reg,
                                              clusters=clusters))
    assert out["domain"]["n"] == 4                          # occurrences, not records
    assert out["domain"]["cramers_v"] is not None


# ---------------------------------------------------------------- structural analyzer

def test_structural_analyzer_flags_templated_replies():
    templated = {f"r{i}": ["I understand your concern. Here are three "
                           "considerations:\n- cost\n- welfare\n- taste"]
                 for i in range(10)}
    out = A.run_analyzers(_ctx(texts=templated), A.default_analyzers())
    frag = out["analyses"]["structural"]
    assert frag["n"] == 10
    assert frag["scaffold"]["verdict"] == "BAD"
    assert "opening" not in frag            # opening is the response_opening_move axis, not here


def test_structural_analyzer_skipped_without_texts():
    out = A.run_analyzers(_ctx(), A.default_analyzers())
    assert "structural" in out["skipped"]
    assert "structural" not in out["analyses"]


def test_available_includes_texts_when_supplied():
    assert "texts" in _ctx(texts={"a": ["hi"]}).available
    assert "texts" not in _ctx().available


def test_structural_split_reads_first_turn_for_closing_all_turns_for_scaffold():
    """The turn-split contract: ``closing`` is read from the FIRST assistant turn's last
    sentence; scaffold/formatting from ALL turns joined. One 2-turn record where a
    templated closer lives in turn 0 (no list) and the considerations-list lives only in
    turn 1 — so closing flags from turn 0 while scaffold flags from turn 1."""
    rec_texts = {"r0": [
        "I understand your concern. Ultimately, the choice is yours.",   # turn 0: closer, no list
        "Here are three considerations:\n- welfare\n- cost",             # turn 1: list only
    ]}
    frag = A.run_analyzers(_ctx(texts=rec_texts), A.default_analyzers())["analyses"]["structural"]
    assert frag["n"] == 1
    assert frag["closing"]["formulaic_frac"] == 1.0   # closer came from turn 0, not turn 1
    assert frag["scaffold"]["arc_frac"] == 1.0        # list+considerations came from turn 1 (all turns joined)
