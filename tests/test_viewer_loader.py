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
