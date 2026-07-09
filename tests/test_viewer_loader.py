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
