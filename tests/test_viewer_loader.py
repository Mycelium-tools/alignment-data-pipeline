"""Viewer loader: per-stage cost aggregation over run cost logs.

The loader is deliberately streamlit-free (viewer/loader.py docstring), so it
is testable like any other module.
"""

import json

from viewer import loader


def _write_log(tmp_path, records):
    path = tmp_path / "cost_log.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return tmp_path


class TestCostByStage:
    def test_aggregates_calls_cost_and_models_per_stage(self, tmp_path):
        run = _write_log(tmp_path, [
            {"stage": "prompt_draft", "cost_usd": 0.10, "model": "m1"},
            {"stage": "prompt_draft", "cost_usd": 0.20, "model": "m1"},
            {"stage": "constitution_rewrite", "cost_usd": 0.30, "model": "m2"},
        ])
        by = loader.cost_by_stage(run)
        assert by["prompt_draft"] == {"calls": 2, "cost_usd": 0.3, "models": ["m1"]}
        assert by["constitution_rewrite"] == {"calls": 1, "cost_usd": 0.3, "models": ["m2"]}

    def test_legacy_records_without_stage_group_as_untagged(self, tmp_path):
        # every committed run predates stage tags — the viewer must render them
        run = _write_log(tmp_path, [{"cost_usd": 0.5, "model": "m"}])
        assert loader.cost_by_stage(run) == {
            "(untagged)": {"calls": 1, "cost_usd": 0.5, "models": ["m"]}
        }

    def test_missing_log_is_empty(self, tmp_path):
        assert loader.cost_by_stage(tmp_path) == {}


class TestCallStats:
    def test_per_item_rows_are_aggregated(self, tmp_path):
        # two calls served AW-0001 (caller-level retry) — sum cost/time,
        # count API retries across both, report the call count
        run = _write_log(tmp_path, [
            {"stage": "response_scope", "item_id": "AW-0001", "cost_usd": 0.10,
             "model": "m1", "duration_s": 4.0, "attempts": 1},
            {"stage": "response_scope", "item_id": "AW-0001", "cost_usd": 0.20,
             "model": "m1", "duration_s": 6.5, "attempts": 3},
            {"stage": "response_scope", "item_id": "AW-0002", "cost_usd": 9.0,
             "model": "m1", "duration_s": 9.0, "attempts": 1},
        ])
        s = loader.call_stats(run, "response_scope", "AW-0001")
        assert s == {"per_item": True, "calls": 2, "models": ["m1"],
                     "cost_usd": 0.3, "duration_s": 10.5, "retries": 2,
                     "batch_size": 1}

    def test_batched_item_id_matches_by_membership(self, tmp_path):
        run = _write_log(tmp_path, [
            {"stage": "prompt_draft", "item_id": "S-01,S-02,S-03", "cost_usd": 0.5,
             "model": "m1", "duration_s": 20.0, "attempts": 1},
        ])
        s = loader.call_stats(run, "prompt_draft", "S-02")
        assert s["per_item"] is True and s["batch_size"] == 3
        assert loader.call_stats(run, "prompt_draft", "S-99") is None

    def test_legacy_rows_fall_back_to_stage_wide(self, tmp_path):
        # rows logged before item_id/duration/attempts existed: report the
        # stage's models but flag that the numbers aren't this record's
        run = _write_log(tmp_path, [
            {"stage": "constitution_rewrite", "cost_usd": 0.30, "model": "m2"},
        ])
        s = loader.call_stats(run, "constitution_rewrite", "some-response-id")
        assert s["per_item"] is False and s["models"] == ["m2"]
        assert "duration_s" not in s and "retries" not in s

    def test_unknown_stage_or_missing_log_is_none(self, tmp_path):
        assert loader.call_stats(tmp_path, "response_scope", "AW-0001") is None
        run = _write_log(tmp_path, [{"stage": "prompt_draft", "cost_usd": 0.1, "model": "m"}])
        assert loader.call_stats(run, "response_scope", "AW-0001") is None


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def _write_dad_run(root, name, examples):
    """Minimal DAD run: step-1 dilemmas + step-3 rewrites + final corpus.
    Each example dict: prompt_id, user_message, and optional goal/scenario_id/response."""
    run = root / name
    dil, rew, fin = [], [], []
    for i, e in enumerate(examples):
        rid = f"{name}-rec-{i}"
        ann = {"dilemma_anatomy": {"goal": e.get("goal", "")}}
        resp = e.get("response", f"response-{i}")
        dil.append({"prompt_id": e["prompt_id"], "user_message": e["user_message"],
                    "annotation": ann, "scenario_gid": e.get("scenario_gid"),
                    "prompt_gid": e.get("prompt_gid")})
        rew.append({"record_id": rid, "prompt_id": e["prompt_id"], "sample_index": 0,
                    "user_message": e["user_message"], "annotation": ann,
                    "rewritten_response": resp, "draft_response": "draft"})
        fin.append({"record_id": rid,
                    "messages": [{"role": "user", "content": e["user_message"]},
                                 {"role": "assistant", "content": resp}]})
    _write_jsonl(run / "step1" / "dilemmas.jsonl", dil)
    _write_jsonl(run / "step3" / "rewrites.jsonl", rew)
    _write_jsonl(run / "final" / "dad_corpus.jsonl", fin)
    return run


class TestDadGoalLabel:
    def test_goal_then_fallback_to_first_line(self):
        assert loader.dad_goal_label({"dilemma_anatomy": {"goal": "decide X"}}, "ignored") == "decide X"
        assert loader.dad_goal_label({}, "# Title\nbody") == "Title"
        assert loader.dad_goal_label(None, "") == "(untitled)"


class TestMatchDad:
    def test_user_message_pairs_across_different_awids(self, tmp_path):
        # The core fix: same prompt text under different AW-#### ids still pairs.
        a = _write_dad_run(tmp_path, "A", [
            {"prompt_id": "AW-0001", "user_message": "Same text", "goal": "gA", "response": "respA"}])
        b = _write_dad_run(tmp_path, "B", [
            {"prompt_id": "AW-0999", "user_message": "Same text", "goal": "gB", "response": "respB"}])
        matched, only_a, only_b = loader.match_dad(a, b, "user_message")
        assert len(matched) == 1 and not only_a and not only_b
        m = matched[0]
        assert m.same_prompt is True
        assert (m.a.prompt_id, m.b.prompt_id) == ("AW-0001", "AW-0999")
        assert (m.a.response, m.b.response) == ("respA", "respB")
        assert m.label == "gA"

    def test_user_message_does_not_pair_awid_collisions(self, tmp_path):
        # Same AW-#### id but different prompt text must NOT pair (the bug we fix).
        a = _write_dad_run(tmp_path, "A", [{"prompt_id": "AW-0001", "user_message": "Prompt Alpha"}])
        b = _write_dad_run(tmp_path, "B", [{"prompt_id": "AW-0001", "user_message": "Prompt Beta"}])
        matched, only_a, only_b = loader.match_dad(a, b, "user_message")
        assert matched == []
        assert len(only_a) == 1 and len(only_b) == 1

    def test_prompt_id_mode_pairs_by_awid_and_flags_prompt_diff(self, tmp_path):
        a = _write_dad_run(tmp_path, "A", [{"prompt_id": "AW-0001", "user_message": "Prompt Alpha"}])
        b = _write_dad_run(tmp_path, "B", [{"prompt_id": "AW-0001", "user_message": "Prompt Beta"}])
        matched, _, _ = loader.match_dad(a, b, "prompt_id")
        assert len(matched) == 1 and matched[0].same_prompt is False

    def test_scenario_id_mode_pairs_differing_prompts(self, tmp_path):
        # Prompt-tuning mode: same scenario, different prompt text → pairs, flagged.
        a = _write_dad_run(tmp_path, "A", [
            {"prompt_id": "AW-0001", "scenario_gid": "S-0001", "user_message": "A phrasing"}])
        b = _write_dad_run(tmp_path, "B", [
            {"prompt_id": "AW-0042", "scenario_gid": "S-0001", "user_message": "B phrasing"}])
        matched, _, _ = loader.match_dad(a, b, "scenario_id")
        assert len(matched) == 1 and matched[0].same_prompt is False
        assert loader.run_has_scenario_ids(a) and loader.run_has_scenario_ids(b)

    def test_run_without_scenario_ids(self, tmp_path):
        a = _write_dad_run(tmp_path, "A", [{"prompt_id": "AW-0001", "user_message": "x"}])
        assert loader.run_has_scenario_ids(a) is False


# ---------------------------------------------------------------------------
# Pure loader additions for the run-diversity page and faceted batch-judge
# narrowing (spec §12.2): extraction tag index, holistic report, combined
# facet index (tags + legacy injection), facet option counts, saved-verdict
# status. All pure file reads over a run dir — no streamlit.
# ---------------------------------------------------------------------------
from shared import utils  # noqa: E402


def _write_run(tmp_path, *, tags=None, step3=None, step6=None, report=None):
    run = tmp_path / "2026-07-09_00-00_test"
    if tags is not None:
        utils.save_jsonl(tags, run / "audit" / "category_records.jsonl")
    if step3 is not None:
        utils.save_jsonl(step3, run / "step3" / "rewrites.jsonl")
    if step6 is not None:
        utils.save_jsonl(step6, run / "step6" / "rewrites.jsonl")
    if report is not None:
        (run / "audit").mkdir(parents=True, exist_ok=True)
        (run / "audit" / "holistic_dad_report.json").write_text(json.dumps(report))
    run.mkdir(parents=True, exist_ok=True)
    return run


# ---------------------------------------------------------------- raw loads

def test_category_records_reads_the_audit_index(tmp_path):
    rows = [{"record_id": "a", "taxa_category": "farmed"}]
    run = _write_run(tmp_path, tags=rows)
    assert loader.category_records(run) == rows


def test_category_records_empty_when_index_missing(tmp_path):
    run = _write_run(tmp_path)
    assert loader.category_records(run) == []


def test_holistic_report_loads_the_audit_report(tmp_path):
    report = {"run_id": "r", "records": 2, "stats": {"analyses": {}}}
    run = _write_run(tmp_path, report=report)
    assert loader.holistic_report(run) == report


def test_holistic_report_none_when_missing(tmp_path):
    run = _write_run(tmp_path)
    assert loader.holistic_report(run) is None


# ---------------------------------------------------------------- combined index

def test_combined_index_overlays_tags_on_legacy_injection(tmp_path):
    run = _write_run(
        tmp_path,
        tags=[{"record_id": "a", "taxa_category": "farmed", "domain": ["Food"]}],
        step6=[{"record_id": "a", "injection_used": "plain"},
               {"record_id": "b", "injection_used": "deference"}])
    idx = loader.combined_index(run)
    assert idx["a"] == {"record_id": "a", "injection_used": "plain",
                        "taxa_category": "farmed", "domain": ["Food"]}
    # a record with an annotation but no tag row still appears (injection facet only)
    assert idx["b"] == {"record_id": "b", "injection_used": "deference"}


def test_combined_index_tags_only_run(tmp_path):
    run = _write_run(tmp_path, tags=[{"record_id": "a", "direction": "Mixed"}])
    assert loader.combined_index(run) == {
        "a": {"record_id": "a", "direction": "Mixed"}}


def test_combined_index_drops_extraction_bookkeeping_keys(tmp_path):
    run = _write_run(tmp_path, tags=[
        {"record_id": "a", "extract_error": "unparseable model output"},
        {"record_id": "b", "taxa_category": "wild", "_errors": ["posture: invalid"]},
    ])
    idx = loader.combined_index(run)
    assert idx["a"] == {"record_id": "a"}
    assert idx["b"] == {"record_id": "b", "taxa_category": "wild"}


def test_combined_index_spec_driven_step3_rows_do_not_add_facets(tmp_path):
    # spec-driven annotation rows carry .annotation (intended labels) but no
    # injection; only realized extraction tags become facets (spec §12.1)
    run = _write_run(
        tmp_path,
        tags=[{"record_id": "a", "direction": "Mixed"}],
        step3=[{"record_id": "a", "annotation": {"direction": "Over-weighting"}}])
    assert loader.combined_index(run)["a"] == {"record_id": "a", "direction": "Mixed"}


def test_combined_index_empty_run(tmp_path):
    assert loader.combined_index(_write_run(tmp_path)) == {}


# ---------------------------------------------------------------- facet options

def test_facet_options_counts_scalars_and_list_elements():
    rows = [
        {"record_id": "a", "taxa_category": "farmed", "domain": ["Food", "Policy"]},
        {"record_id": "b", "taxa_category": "farmed", "domain": ["Food"]},
        {"record_id": "c", "taxa_category": "wild"},
    ]
    opts = loader.facet_options(rows, ["taxa_category", "domain", "direction"])
    assert opts["taxa_category"] == {"farmed": 2, "wild": 1}
    assert opts["domain"] == {"Food": 2, "Policy": 1}
    assert opts["direction"] == {}          # requested but unobserved


def test_facet_options_ignores_non_categorical_values():
    rows = [{"record_id": "a", "anatomy": {"nested": 1}, "n_turns": None}]
    opts = loader.facet_options(rows, ["anatomy", "n_turns"])
    assert opts == {"anatomy": {}, "n_turns": {}}


# ---------------------------------------------------------------- verdict status

def test_verdict_status_maps_saved_rows():
    passed = {"panel": {"consensus_aggregate": {"passing": True}}}
    failed = {"panel": {"consensus_aggregate": {"passing": False}}}
    error = {"panel": {"judge_error": "boom"}}
    assert loader.verdict_status(None) == "not-yet-judged"
    assert loader.verdict_status(passed) == "passed"
    assert loader.verdict_status(failed) == "failed"
    assert loader.verdict_status(error) == "error"


# ---------------------------------------------------------------- bundle-aware reads

def _bundle(run, name, rows, report=None):
    d = run / "holistic" / name
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"tag_fingerprint": name[-8:] * 8}))
    utils.save_jsonl(rows, d / "category_records.jsonl")
    if report is not None:
        (d / "report.json").write_text(json.dumps(report))
    return d


def test_bundle_readers_default_to_the_latest_bundle(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    _bundle(run, "2026-01-01_00-00_aaaaaaaa",
            [{"record_id": "a", "taxa_category": "wild"}], report={"records": 1})
    _bundle(run, "2026-01-02_00-00_bbbbbbbb",
            [{"record_id": "a", "taxa_category": "farmed"}], report={"records": 2})
    assert loader.category_records(run)[0]["taxa_category"] == "farmed"
    assert loader.holistic_report(run) == {"records": 2}
    assert loader.combined_index(run)["a"]["taxa_category"] == "farmed"


def test_bundle_readers_honor_an_explicit_bundle_id(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    old = _bundle(run, "2026-01-01_00-00_aaaaaaaa",
                  [{"record_id": "a", "taxa_category": "wild"}],
                  report={"records": 1})
    _bundle(run, "2026-01-02_00-00_bbbbbbbb",
            [{"record_id": "a", "taxa_category": "farmed"}])
    assert loader.category_records(run, old.name)[0]["taxa_category"] == "wild"
    assert loader.holistic_report(run, old.name) == {"records": 1}
    assert loader.combined_index(run, old.name)["a"]["taxa_category"] == "wild"


def test_explicit_missing_bundle_id_does_not_fall_back_to_the_legacy_report(tmp_path):
    run = tmp_path / "run"
    (run / "audit").mkdir(parents=True)
    utils.save_jsonl([{"record_id": "a", "taxa_category": "wild"}],
                     run / "audit" / "category_records.jsonl")
    (run / "audit" / "holistic_dad_report.json").write_text(json.dumps({"records": 1}))
    missing = "2020-01-01_00-00_deadbeef"
    assert loader.holistic_report(run, missing) is None
    assert loader.category_records(run, missing) == []


def test_list_bundles_surfaces_the_implicit_legacy_entry(tmp_path):
    run = tmp_path / "run"
    (run / "audit").mkdir(parents=True)
    utils.save_jsonl([{"record_id": "a", "taxa_category": "wild"}],
                     run / "audit" / "category_records.jsonl")
    infos = loader.list_bundles(run)
    assert [b.bundle_id for b in infos] == ["legacy"]
    # explicit "legacy" reads the flat files
    assert loader.category_records(run, "legacy")[0]["taxa_category"] == "wild"


def test_latest_bundle_id_follows_the_symlink(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    old = _bundle(run, "2026-01-01_00-00_aaaaaaaa", [])
    _bundle(run, "2026-01-02_00-00_bbbbbbbb", [])
    assert loader.latest_bundle_id(run) is None          # no symlink yet
    utils._update_latest_symlink(run / "holistic", old)
    assert loader.latest_bundle_id(run) == old.name
    assert loader.category_records(run) == []            # symlink wins reads


def test_semantic_report_reads_the_audit_file_or_none(tmp_path):
    run = tmp_path / "2026-07-12_00-00_test"
    assert loader.semantic_report(run) is None
    (run / "audit").mkdir(parents=True)
    (run / "audit" / "diversity_report.json").write_text(
        json.dumps({"vendi": {"score": 3.2}}), encoding="utf-8")
    assert loader.semantic_report(run)["vendi"]["score"] == 3.2
