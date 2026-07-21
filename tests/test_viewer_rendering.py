"""Viewer prompt reconstruction: the system/user split is honored.

rendering.py is streamlit-free, so _format_split is testable directly. It must
mirror shared.utils.load_split_prompt: cut on the ===USER=== marker, or treat a
marker-less template as user-only (so pre-split run snapshots reconstruct as
they actually ran)."""

from viewer import rendering


def _mk(text):
    tpl = rendering.Template("t.txt", text, "snapshot")
    r = rendering.RenderedPrompt(stage="x", is_llm_call=True)
    return tpl, r


def test_format_split_cuts_on_marker_and_formats_each_half():
    tpl, r = _mk("SYS {a}\n===USER===\nUSR {b}")
    system, user = rendering._format_split(tpl, {"a": "A", "b": "B"}, r)
    assert system == "SYS A"
    assert user == "USR B"


def test_format_split_no_marker_is_user_only():
    tpl, r = _mk("just the user prompt {a}")
    system, user = rendering._format_split(tpl, {"a": "A"}, r)
    assert system is None
    assert user == "just the user prompt A"


def test_format_split_missing_template_returns_none():
    tpl = rendering.Template("t.txt", None, "missing")
    r = rendering.RenderedPrompt(stage="x", is_llm_call=True)
    assert rendering._format_split(tpl, {}, r) == (None, None)
    assert r.warnings  # unavailable-template warning recorded


class TestInlineWordDiff:
    def test_additions_highlighted_and_equal_text_plain(self):
        html = rendering.inline_word_diff_html(
            "Keep the shed clean.", "Keep the shed clean and reduce insect harm.")
        # the unchanged prefix stays plain (outside any span)
        assert html.startswith("Keep the shed ")
        # the added words are wrapped in a highlight span; the prefix is not
        assert "background:rgba" in html
        highlighted = html.split("background:rgba", 1)[1]
        assert "reduce insect harm." in highlighted
        assert "Keep the" not in highlighted

    def test_removed_words_struck_through(self):
        html = rendering.inline_word_diff_html("an obviously wrong claim", "an claim")
        assert "line-through" in html
        struck = html.split("line-through", 1)[1]
        assert "obviously wrong" in struck

    def test_text_is_escaped_and_newlines_become_breaks(self):
        html = rendering.inline_word_diff_html("a <b> start", "a <b> start\n\nnew para")
        assert "&lt;b&gt;" in html and "<b>" not in html.replace("<br>", "")
        assert "<br><br>" in html


class TestAuditSectionTable:
    def test_verdicts_get_color_badges(self):
        sec = {"title": "T", "rows": [
            {"label": "a", "value": "1", "verdict": "GOOD", "note": ""},
            {"label": "b", "value": "2", "verdict": "BAD", "note": "look here"},
            {"label": "c", "value": "3", "verdict": None, "note": ""},
        ]}
        rows = rendering.audit_section_table(sec)
        assert rows[0]["verdict"] == "🟢 GOOD"
        assert rows[1]["verdict"] == "🔴 BAD"
        assert rows[1]["note"] == "look here"
        assert rows[2]["verdict"] == ""  # informational row keeps the column blank

    def test_columns_omitted_when_section_has_no_verdicts_or_notes(self):
        sec = {"rows": [{"label": "a", "value": "1", "verdict": None, "note": ""}]}
        assert rendering.audit_section_table(sec) == [{"check": "a", "value": "1"}]

    def test_empty_section_is_empty(self):
        assert rendering.audit_section_table({}) == []

    def test_arm_comparison_section_splits_into_pipeline_plain_columns(self):
        # a genuine pipeline-vs-plain section: value strings split into columns
        sec = {"rows": [
            {"label": "distinct shapes", "value": "pipeline 12/40 / plain 16/40",
             "verdict": None, "note": ""},
            {"label": "Self-BLEU", "value": "pipeline 0.71 · plain 0.55",
             "verdict": None, "note": ""},  # the lexical section's '·' separator
            {"label": "top shape share (pipeline)", "value": "28%",
             "verdict": "GOOD", "note": "(10+ paras)"},  # pipeline-only single row
        ]}
        rows = rendering.audit_section_table(sec)
        assert rows[0] == {"check": "distinct shapes", "pipeline": "12/40",
                           "plain": "16/40", "verdict": "", "note": ""}
        assert rows[1]["pipeline"] == "0.71" and rows[1]["plain"] == "0.55"
        # the single-value pipeline-only row lands in the pipeline column
        assert rows[2]["pipeline"] == "28%" and rows[2]["plain"] == ""
        assert rows[2]["verdict"] == "🟢 GOOD"

    def test_single_arm_section_keeps_one_value_column(self):
        # response-openings-style: no plain arm → no split, keep 'value'
        sec = {"rows": [
            {"label": "responses scanned", "value": "40", "verdict": None, "note": ""},
            {"label": "families", "value": "other 34, heres-the-x 1", "verdict": None, "note": ""},
        ]}
        rows = rendering.audit_section_table(sec)
        assert "pipeline" not in rows[0] and rows[0]["value"] == "40"

    def test_plain_only_single_row_lands_in_plain_column(self):
        sec = {"rows": [
            {"label": "check-back additions", "value": "pipeline 61 / plain 57",
             "verdict": None, "note": ""},
            {"label": "plain-baseline median chars", "value": "812",
             "verdict": None, "note": ""},
        ]}
        rows = rendering.audit_section_table(sec)
        assert rows[1]["plain"] == "812" and rows[1]["pipeline"] == ""


class TestSplitArmValue:
    def test_slash_separator(self):
        assert rendering._split_arm_value("pipeline 12/40 / plain 16/40") == ("12/40", "16/40")

    def test_middot_separator(self):
        assert rendering._split_arm_value("pipeline 0.71 · plain 0.55") == ("0.71", "0.55")

    def test_pipeline_only_when_no_baseline(self):
        assert rendering._split_arm_value("pipeline 40") == ("40", "")

    def test_non_arm_value_returns_none(self):
        assert rendering._split_arm_value("28%") is None
        assert rendering._split_arm_value("") is None


class TestAuditShapeChartRows:
    def test_long_form_rows_per_shape_and_arm(self):
        structure = {"pipeline": {"shapes": {"3-5 paras": 30, "1-2 paras": 10}},
                     "plain": {"shapes": {"3-5 paras": 25}}}
        rows = rendering.audit_shape_chart_rows(structure)
        assert {"shape": "3-5 paras", "arm": "pipeline", "count": 30} in rows
        assert {"shape": "3-5 paras", "arm": "plain Claude", "count": 25} in rows
        assert len(rows) == 3

    def test_empty_structure_is_empty(self):
        assert rendering.audit_shape_chart_rows({}) == []


class TestAuditStockPhraseRows:
    def test_watch_and_discovered_sorted_by_pipeline_count(self):
        sp = {"n_pipeline": 40, "n_plain": 40,
              "watch": {"i want to be": {"origin": "pipeline-origin", "pipeline": 8, "plain": 3},
                        "here's the thing": {"origin": "plain-origin", "pipeline": 0, "plain": 5},
                        "never appears": {"origin": "pipeline-origin", "pipeline": 0, "plain": 0}},
              "new_pipeline": [{"phrase": "the quiet part", "count": 4}],
              "new_plain": []}
        rows = rendering.audit_stock_phrase_rows(sp)
        # phrases that never appear in either arm are dropped
        assert all(r["phrase"] != "never appears" for r in rows)
        # sorted by pipeline count desc: 'i want to be' (8) first
        assert rows[0]["phrase"] == "i want to be"
        # discovered phrases carry a distinguishing origin
        disc = next(r for r in rows if r["phrase"] == "the quiet part")
        assert disc["origin"] == "discovered (pipeline)" and disc["pipeline"] == 4

    def test_empty_is_empty(self):
        assert rendering.audit_stock_phrase_rows({}) == []


class TestAuditChartRows:
    def test_length_rows_wide_form_keeps_missing_plain_as_none(self):
        per_case = {"AW-0002": {"pipeline": 500, "plain": 200},
                    "AW-0001": {"pipeline": 300, "plain": None}}
        rows = rendering.audit_length_chart_rows(per_case)
        # sorted by record; one row per record, one column per arm (colors are
        # pinned by column order — AUDIT_ARM_COLUMNS/AUDIT_ARM_COLORS)
        assert rows == [
            {"record": "AW-0001", "plain Claude": None, "pipeline": 300},
            {"record": "AW-0002", "plain Claude": 200, "pipeline": 500},
        ]

    def test_reason_rows_count_unique_reasons_per_arm(self):
        per_case = {"AW-0001": {
            "plain": {"reasons": ["a"], "chars": 100},
            "pipeline": {"reasons": ["a", "b", "c"], "chars": 400},
        }}
        rows = rendering.audit_reason_chart_rows(per_case)
        assert rows == [{"record": "AW-0001", "plain Claude": 1, "pipeline": 3}]

    def test_arm_columns_and_colors_stay_paired(self):
        assert len(rendering.AUDIT_ARM_COLUMNS) == len(rendering.AUDIT_ARM_COLORS)
        assert rendering.AUDIT_ARM_COLUMNS[0] == "plain Claude"


class TestAuditSurvivalGroups:
    def test_reasons_bucketed_by_verdict_plus_added(self):
        case = {
            "plain": {"reasons": ["a", "b", "c"]},
            "pipeline": {"reasons": ["x", "y"]},
            "survival": {"anchored": [
                {"reason": "a", "verdict": "kept"},
                {"reason": "b", "verdict": "weakened"},
                {"reason": "c", "verdict": "dropped"},
            ], "added": ["y"]},
        }
        groups = rendering.audit_survival_groups(case)
        assert [(t.split(" (")[0], rs) for t, rs in groups] == [
            ("✓ Kept by the pipeline", ["a"]),
            ("〜 Weakened", ["b"]),
            ("✗ Dropped", ["c"]),
            ("➕ Added by the pipeline", ["y"]),
        ]
        # counts live in the titles
        assert groups[0][0].endswith("(1)") and groups[3][0].endswith("(1)")

    def test_no_survival_data_returns_none_for_fallback(self):
        assert rendering.audit_survival_groups({"plain": {"reasons": ["a"]}}) is None


class TestAuditBatchTotals:
    def test_totals_with_absolute_and_percent_deltas(self):
        report = {
            "response_lengths": {"per_case": {
                "AW-0001": {"pipeline": 400, "plain": 200},
                "AW-0002": {"pipeline": 600, "plain": 300},
                "AW-0003": {"pipeline": 999, "plain": None},  # unpaired: excluded
            }},
            "moral_patient_reasons": {"per_case": {
                "AW-0001": {"pipeline": {"reasons": ["a", "b", "c"]},
                            "plain": {"reasons": ["a", "b"]}},
            }},
        }
        rows = rendering.audit_batch_totals(report)
        assert rows == [
            {"metric": "total characters", "plain Claude": "500", "pipeline": "1,000",
             "Δ absolute": "+500", "Δ %": "+100.0%"},
            {"metric": "total unique reasons", "plain Claude": "2", "pipeline": "3",
             "Δ absolute": "+1", "Δ %": "+50.0%"},
        ]

    def test_empty_report_gives_no_rows(self):
        assert rendering.audit_batch_totals({}) == []


class TestAuditSurvivalChartRows:
    def test_rows_bucket_counts_and_carry_reason_texts(self):
        per_case = {"AW-0001": {
            "survival": {"anchored": [
                {"reason": "a", "verdict": "kept"},
                {"reason": "b", "verdict": "kept"},
                {"reason": "c", "verdict": "dropped"},
            ], "added": ["n1"]},
        }, "AW-0002": {}}  # no survival -> no rows
        rows = rendering.audit_survival_chart_rows(per_case)
        assert rows == [
            {"record": "AW-0001", "category": "✓ kept", "stack_order": 0,
             "count": 2, "reasons": "a • b"},
            {"record": "AW-0001", "category": "✗ dropped", "stack_order": 2,
             "count": 1, "reasons": "c"},
            {"record": "AW-0001", "category": "➕ added", "stack_order": 3,
             "count": 1, "reasons": "n1"},
        ]

    def test_no_survival_anywhere_gives_empty(self):
        assert rendering.audit_survival_chart_rows({"AW-0001": {"plain": {}}}) == []
        assert len(rendering.AUDIT_SURVIVAL_CATEGORIES) == len(rendering.AUDIT_SURVIVAL_COLORS)


class TestComposedGateRefineRendering:
    """Composed 1c gate + 1d refine runs: BOTH stages must be renderable —
    the gate must never short-circuit the refine view (the stage split's whole
    point is that both calls are real, paid, and reviewable)."""

    @staticmethod
    def _composed_run(tmp_path):
        import random
        import shutil

        from dad_pipeline import compose_scenarios as cs

        run = tmp_path / "run"
        (run / "inputs" / "prompts").mkdir(parents=True)
        for name in ("step1_gate.txt", "step1d_refine.txt"):
            shutil.copy(rendering.REPO_ROOT / "prompts" / "dad" / name
                        if hasattr(rendering, "REPO_ROOT")
                        else f"prompts/dad/{name}",
                        run / "inputs" / "prompts" / name)
        scenario = cs.deal_scenarios(1, random.Random(3))[0]
        scenario["scenario_description"] = "A designed situation."
        lineage = {
            "scenario": scenario,
            "gate": {"passed": True, "failures": [], "attempt": 1},
            "dilemma": {
                "scenario_id": scenario["scenario_id"],
                "user_message": "Refined final text.",
                "draft_user_message": "Judged draft text.",
                "annotation": {"visibility": "explicit", "leverage": "their personal choices"},
            },
        }
        manifest = {"manifest_version": 2, "git_commit": None}
        return run, manifest, lineage

    def test_gate_stage_renders_the_judged_draft(self, tmp_path):
        run, manifest, lineage = self._composed_run(tmp_path)
        r = rendering.render_prompt("dad", "step1_gate", run, manifest, lineage)
        assert r.is_llm_call
        # the gate judged the PRE-refine draft, not the shipped rewrite
        assert "Judged draft text." in (r.user or "")
        assert any("PASS" in w for w in r.warnings)

    def test_refine_stage_renders_even_when_the_gate_ran(self, tmp_path):
        # regression: the old single-stage view short-circuited to the gate
        # whenever gate.jsonl had a record, hiding the refine call entirely
        run, manifest, lineage = self._composed_run(tmp_path)
        r = rendering.render_prompt("dad", "step1_refine", run, manifest, lineage)
        assert r.is_llm_call
        assert "Judged draft text." in (r.user or "")     # the draft under review
        assert "<draft_prompt>" in (r.user or "")

    def test_gate_stage_marks_not_run_on_pre_gate_lineage(self, tmp_path):
        run, manifest, lineage = self._composed_run(tmp_path)
        lineage["gate"] = None
        r = rendering.render_prompt("dad", "step1_gate", run, manifest, lineage)
        assert not r.is_llm_call
        assert any("did not use the 1c gate" in w for w in r.warnings)
