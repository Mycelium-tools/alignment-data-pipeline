"""Behavior tests for SDF layers 1-5, driven through each layer's run() with a
stubbed shared.api.call_claude. No test here may reach the API (see conftest)."""

import json
import re

import pytest

from sdf_pipeline import (
    layer1_document_types,
    layer2_subtypes,
    layer3_draft,
    layer4_rewrite,
    layer5_score,
)
from shared import utils

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@pytest.fixture
def layer_dir(tmp_path):
    return tmp_path / "layer"


DOC_TYPES_RESPONSE = json.dumps([
    {"type_name": "AI diary", "description": "First-person AI notes", "role": "ai-character", "tone": "reflective"},
    {"type_name": "Field report", "description": "Wildlife survey"},
])


class TestLayer1:
    def test_parses_types_and_assigns_sequential_ids(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        calls = stub_claude([DOC_TYPES_RESPONSE])
        records = layer1_document_types.run(tiny_config, prompts_sdf, layer_dir)
        assert len(calls) == 1
        assert [r["type_id"] for r in records] == [0, 1]
        assert records[0]["role"] == "ai-character"
        assert records[0]["tone"] == "reflective"
        assert utils.load_jsonl(layer_dir / "document_types.jsonl") == records

    def test_missing_role_and_tone_get_defaults(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude([DOC_TYPES_RESPONSE])
        records = layer1_document_types.run(tiny_config, prompts_sdf, layer_dir)
        assert records[1]["role"] == "welfare-topic"
        assert records[1]["tone"] == "neutral"

    def test_strips_markdown_code_fences(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude(["```json\n" + DOC_TYPES_RESPONSE + "\n```"])
        records = layer1_document_types.run(tiny_config, prompts_sdf, layer_dir)
        assert len(records) == 2

    def test_completed_layer_loads_from_disk_without_calls(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        existing = [{"type_id": 0, "type_name": "X", "description": "d", "role": "welfare-topic", "tone": "neutral"}]
        utils.save_jsonl(existing, layer_dir / "document_types.jsonl")
        utils.Checkpoint(layer_dir / "_checkpoint.json").mark_done("layer1")
        calls = stub_claude([])
        assert layer1_document_types.run(tiny_config, prompts_sdf, layer_dir) == existing
        assert calls == []


DOC_TYPE = {"type_id": 0, "type_name": "Field report", "description": "d", "role": "welfare-topic", "tone": "neutral"}
SUBTYPES_RESPONSE = json.dumps([
    {"subtype_name": "River survey", "description": "sd", "language": "en"},
    {"subtype_name": "Coastal survey", "description": "sd2", "language": "xx"},
])


class TestLayer2:
    def test_builds_composite_subtype_ids(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude([SUBTYPES_RESPONSE])
        records = layer2_subtypes.run(tiny_config, prompts_sdf, layer_dir, [DOC_TYPE])
        assert [r["subtype_id"] for r in records] == ["0_0", "0_1"]
        assert records[0]["type_name"] == "Field report"

    def test_unknown_language_replaced_from_distribution(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude([SUBTYPES_RESPONSE])
        records = layer2_subtypes.run(tiny_config, prompts_sdf, layer_dir, [DOC_TYPE])
        # "xx" is not in language_distribution {en: 1.0} → re-sampled to "en"
        assert records[1]["language"] == "en"

    def test_done_types_skipped_and_existing_kept(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        existing = {"subtype_id": "0_0", "type_id": 0, "type_name": "Field report", "role": "welfare-topic",
                    "subtype_name": "Old", "description": "d", "tone": "neutral", "language": "en"}
        utils.save_jsonl([existing], layer_dir / "subtypes.jsonl")
        utils.Checkpoint(layer_dir / "_checkpoint.json").mark_done("type_0")
        doc_types = [DOC_TYPE, {**DOC_TYPE, "type_id": 1, "type_name": "Other"}]
        calls = stub_claude([json.dumps([{"subtype_name": "New", "description": "d"}])])
        records = layer2_subtypes.run(tiny_config, prompts_sdf, layer_dir, doc_types)
        assert len(calls) == 1  # only type_1 generated
        assert existing in records
        assert any(r["subtype_id"] == "1_0" for r in records)


SUBTYPE = {"subtype_id": "0_0", "type_id": 0, "type_name": "Field report",
           "subtype_name": "River survey", "description": "d", "tone": "neutral", "language": "en"}


class TestLayer3:
    def test_extracts_document_blocks(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude(["<document>Doc one.</document>\nnoise\n<document>Doc two.</document>"])
        records = layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE])
        assert [r["content"] for r in records] == ["Doc one.", "Doc two."]
        assert all(r["subtype_id"] == "0_0" and r["language"] == "en" for r in records)
        assert all(UUID_RE.match(r["doc_id"]) for r in records)

    def test_no_tags_falls_back_to_whole_response(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude(["  Just plain text.  "])
        records = layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE])
        assert [r["content"] for r in records] == ["Just plain text."]

    def test_done_subtypes_skipped_without_calls(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        utils.Checkpoint(layer_dir / "_checkpoint.json").mark_done("0_0")
        calls = stub_claude([])
        records = layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE])
        assert records == []
        assert calls == []


DRAFT = {"doc_id": "d1", "subtype_id": "0_0", "type_id": 0, "language": "en", "content": "original text"}


class TestLayer4:
    def test_parses_rewrite_json_with_constitution_as_system_prompt(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        calls = stub_claude([json.dumps({"review_notes": "tightened", "rewritten": "better text"})])
        records = layer4_rewrite.run(tiny_config, prompts_sdf, layer_dir, [DRAFT])
        assert records[0]["rewritten"] == "better text"
        assert records[0]["review_notes"] == "tightened"
        assert records[0]["original"] == "original text"
        assert "joins two complementary frameworks" in calls[0]["system_prompt"]

    def test_fenced_json_parsed(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude(["```json\n" + json.dumps({"rewritten": "better"}) + "\n```"])
        records = layer4_rewrite.run(tiny_config, prompts_sdf, layer_dir, [DRAFT])
        assert records[0]["rewritten"] == "better"

    def test_broken_json_falls_back_to_raw_response(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude(["not json at all"])
        records = layer4_rewrite.run(tiny_config, prompts_sdf, layer_dir, [DRAFT])
        assert records[0]["rewritten"] == "not json at all"
        assert records[0]["review_notes"] == "Parse error — used raw output."

    def test_missing_rewritten_key_keeps_original_draft(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude([json.dumps({"review_notes": "no change"})])
        records = layer4_rewrite.run(tiny_config, prompts_sdf, layer_dir, [DRAFT])
        assert records[0]["rewritten"] == "original text"


def _rewrite(doc_id):
    return {"doc_id": doc_id, "subtype_id": "0_0", "type_id": 0, "language": "en", "rewritten": f"text-{doc_id}"}


def _score(alignment, realism, diversity=5):
    return json.dumps({"alignment": alignment, "realism": realism, "diversity": diversity, "notes": "n"})


class TestLayer5:
    def test_filter_gates_on_alignment_and_realism_only(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        final_dir = tmp_path / "final"
        stub_claude([_score(7, 7, diversity=1), _score(9, 6, diversity=10)])
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, final_dir, [_rewrite("a"), _rewrite("b")])
        # threshold 7: (7,7) passes despite diversity 1; (9,6) fails on realism
        assert [r["doc_id"] for r in passed] == ["a"]
        assert utils.load_jsonl(final_dir / "sdf_corpus.jsonl") == passed

    def test_scores_recorded_with_content(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        stub_claude([_score(9, 9)])
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, tmp_path / "final", [_rewrite("a")])
        assert passed[0]["content"] == "text-a"
        assert passed[0]["scores"]["alignment"] == 9
        assert passed[0]["scores"]["notes"] == "n"

    def test_parse_error_defaults_scores_to_five(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        stub_claude(["garbage"])
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, tmp_path / "final", [_rewrite("a")])
        assert passed == []  # 5 < threshold 7
        scored = utils.load_jsonl(layer_dir / "scores.jsonl")
        assert scored[0]["scores"]["alignment"] == 5
        assert scored[0]["scores"]["realism"] == 5

    def test_missing_score_fields_default_to_zero(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        stub_claude([json.dumps({"alignment": 9})])
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, tmp_path / "final", [_rewrite("a")])
        assert passed == []  # realism defaults to 0 → fails threshold
        scored = utils.load_jsonl(layer_dir / "scores.jsonl")
        assert scored[0]["scores"]["realism"] == 0

    def test_existing_scores_reused_without_calls(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        prior = {"doc_id": "a", "subtype_id": "0_0", "type_id": 0, "language": "en", "content": "text-a",
                 "scores": {"alignment": 9, "realism": 9, "diversity": 9, "notes": ""}}
        utils.save_jsonl([prior], layer_dir / "scores.jsonl")
        calls = stub_claude([])
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, tmp_path / "final", [_rewrite("a")])
        assert calls == []
        assert passed == [prior]
