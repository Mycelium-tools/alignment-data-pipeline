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
    {"type_name": "Blog post", "description": "A post on a personal or organizational blog."},
    {"type_name": "Podcast transcript", "description": "A transcript of a podcast episode."},
])


class TestLayer1:
    def test_parses_types_and_assigns_sequential_ids(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        calls = stub_claude([DOC_TYPES_RESPONSE])
        records = layer1_document_types.run(tiny_config, prompts_sdf, layer_dir)
        assert len(calls) == 1
        assert [r["type_id"] for r in records] == [0, 1]
        assert records[0]["type_name"] == "Blog post"
        assert records[1]["description"] == "A transcript of a podcast episode."
        assert utils.load_jsonl(layer_dir / "document_types.jsonl") == records

    def test_prompt_carries_preamble_and_count(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        calls = stub_claude([DOC_TYPES_RESPONSE])
        layer1_document_types.run(tiny_config, prompts_sdf, layer_dir)
        prompt = calls[0]["user_message"]
        # the TCW preamble is injected at every layer
        assert "diverse set of documents" in prompt
        assert f'{tiny_config["sdf"]["document_types_count"]} different types of documents' in prompt

    def test_strips_markdown_code_fences(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude(["```json\n" + DOC_TYPES_RESPONSE + "\n```"])
        records = layer1_document_types.run(tiny_config, prompts_sdf, layer_dir)
        assert len(records) == 2

    def test_completed_layer_loads_from_disk_without_calls(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        existing = [{"type_id": 0, "type_name": "X", "description": "d"}]
        utils.save_jsonl(existing, layer_dir / "document_types.jsonl")
        utils.Checkpoint(layer_dir / "_checkpoint.json").mark_done("layer1")
        calls = stub_claude([])
        assert layer1_document_types.run(tiny_config, prompts_sdf, layer_dir) == existing
        assert calls == []

    def test_non_json_response_raises_and_checkpoints_nothing(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        # No fallback at this layer by design: a garbage response must fail
        # loudly, leave no checkpoint, and let --resume retry the layer.
        stub_claude(["not json at all"])
        with pytest.raises(json.JSONDecodeError):
            layer1_document_types.run(tiny_config, prompts_sdf, layer_dir)
        assert not utils.Checkpoint(layer_dir / "_checkpoint.json").is_done("layer1")


DOC_TYPE = {"type_id": 0, "type_name": "Podcast transcript", "description": "d"}
SUBTYPES_RESPONSE = json.dumps([
    "A French podcast that is known for being skeptical about AI progress.",
    "A tech-industry interview podcast aimed at startup founders.",
])


class TestLayer2:
    def test_builds_composite_subtype_ids_from_strings(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude([SUBTYPES_RESPONSE])
        records = layer2_subtypes.run(tiny_config, prompts_sdf, layer_dir, [DOC_TYPE])
        assert [r["subtype_id"] for r in records] == ["0_0", "0_1"]
        assert records[0]["type_name"] == "Podcast transcript"
        assert records[0]["subtype"] == "A French podcast that is known for being skeptical about AI progress."

    def test_prompt_carries_type_and_count(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        calls = stub_claude([SUBTYPES_RESPONSE])
        layer2_subtypes.run(tiny_config, prompts_sdf, layer_dir, [DOC_TYPE])
        prompt = calls[0]["user_message"]
        assert "Podcast transcript" in prompt
        assert f'{tiny_config["sdf"]["subtypes_per_type"]} subtypes' in prompt

    def test_object_shaped_subtypes_flattened_to_strings(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        # Models trained on the old response shape may return objects; their
        # values are flattened into a usable description instead of str(dict).
        stub_claude([json.dumps([{"subtype_name": "River survey", "description": "wading counts"}])])
        records = layer2_subtypes.run(tiny_config, prompts_sdf, layer_dir, [DOC_TYPE])
        assert records[0]["subtype"] == "River survey — wading counts"

    def test_done_types_skipped_and_existing_kept(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        existing = {"subtype_id": "0_0", "type_id": 0, "type_name": "Podcast transcript", "subtype": "Old"}
        utils.save_jsonl([existing], layer_dir / "subtypes.jsonl")
        utils.Checkpoint(layer_dir / "_checkpoint.json").mark_done("type_0")
        doc_types = [DOC_TYPE, {**DOC_TYPE, "type_id": 1, "type_name": "Other"}]
        calls = stub_claude([json.dumps(["New subtype"])])
        records = layer2_subtypes.run(tiny_config, prompts_sdf, layer_dir, doc_types)
        assert len(calls) == 1  # only type_1 generated
        assert existing in records
        assert any(r["subtype_id"] == "1_0" for r in records)


SUBTYPE = {"subtype_id": "0_0", "type_id": 0, "type_name": "Podcast transcript",
           "subtype": "A French podcast skeptical about AI progress."}


class TestLayer3:
    def test_extracts_document_block_with_constitution_in_prompt(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        calls = stub_claude(["<document>Doc one.</document>"])
        records = layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE])
        assert [r["content"] for r in records] == ["Doc one."]
        assert all(r["subtype_id"] == "0_0" for r in records)
        assert all(UUID_RE.match(r["doc_id"]) for r in records)
        # single context window: the drafting prompt is the sole user turn,
        # carrying the subtype and the plain Claude constitution (no reading)
        (call,) = calls
        assert call["user_message"] is None
        [turn] = call["messages"]
        assert turn["role"] == "user"
        assert "A French podcast skeptical about AI progress." in turn["content"]
        assert "Claude and the mission of Anthropic" in turn["content"]
        assert "section-by-section reading" not in turn["content"]

    def test_multiple_documents_drafted_in_one_context_window(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        config = {**tiny_config, "sdf": {**tiny_config["sdf"], "documents_per_subtype": 2}}
        responses = iter(["<document>Doc one.</document>", "<document>Doc two.</document>"])
        calls = stub_claude(lambda user_message, **kw: next(responses))
        records = layer3_draft.run(config, prompts_sdf, layer_dir, [SUBTYPE])
        assert [r["content"] for r in records] == ["Doc one.", "Doc two."]
        # second call continues the SAME conversation: prompt, first draft, follow-up
        assert len(calls) == 2
        second = calls[1]["messages"]
        assert [m["role"] for m in second] == ["user", "assistant", "user"]
        assert second[1]["content"] == "<document>Doc one.</document>"
        assert "another document" in second[2]["content"]

    def test_response_with_extra_blocks_stops_early(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        # If one turn already yields enough documents, no follow-up turn is sent
        config = {**tiny_config, "sdf": {**tiny_config["sdf"], "documents_per_subtype": 2}}
        calls = stub_claude(["<document>Doc one.</document>\n<document>Doc two.</document>"])
        records = layer3_draft.run(config, prompts_sdf, layer_dir, [SUBTYPE])
        assert [r["content"] for r in records] == ["Doc one.", "Doc two."]
        assert len(calls) == 1

    def test_no_tags_falls_back_to_whole_response(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude(["  Just plain text.  "])
        records = layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE])
        assert [r["content"] for r in records] == ["Just plain text."]

    def test_truncated_document_fallback_strips_stray_tags(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        # max_tokens truncation loses the closing tag; the literal markup must
        # not leak into corpus content
        stub_claude(["<document>A long document cut off mid-sent"])
        records = layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE])
        assert [r["content"] for r in records] == ["A long document cut off mid-sent"]

    def test_overshoot_beyond_count_is_capped(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        # documents_per_subtype is a count, not a floor: volunteered extra
        # blocks are dropped so layers 4-5 cost stays deterministic
        stub_claude(["<document>Doc one.</document>\n<document>Doc two.</document>"])
        records = layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE])
        assert [r["content"] for r in records] == ["Doc one."]

    def test_done_subtypes_skipped_without_calls(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        utils.Checkpoint(layer_dir / "_checkpoint.json").mark_done("0_0")
        calls = stub_claude([])
        records = layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE])
        assert records == []
        assert calls == []


DRAFT = {"doc_id": "d1", "subtype_id": "0_0", "type_id": 0, "content": "original text"}


class TestLayer4:
    def test_parses_improved_document_with_templated_system_prompt(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        calls = stub_claude(["The draft undersold uncertainty.\n<improved_document>better text</improved_document>"])
        records = layer4_rewrite.run(tiny_config, prompts_sdf, layer_dir, [DRAFT])
        assert records[0]["rewritten"] == "better text"
        assert records[0]["review_notes"] == "The draft undersold uncertainty."
        assert records[0]["original"] == "original text"
        # TCW layer-4 system prompt: task framing wrapped around the plain
        # Claude constitution (no sentient-beings reading)
        assert calls[0]["system_prompt"].startswith("Your job is to review and rewrite")
        assert "Claude and the mission of Anthropic" in calls[0]["system_prompt"]
        assert "section-by-section reading" not in calls[0]["system_prompt"]
        # user turn carries the document
        assert "original text" in calls[0]["user_message"]
        assert "improving the quality of this document" in calls[0]["user_message"]

    def test_missing_tags_keeps_original_draft(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude(["prose with no document tags"])
        records = layer4_rewrite.run(tiny_config, prompts_sdf, layer_dir, [DRAFT])
        assert records[0]["rewritten"] == "original text"
        assert "no <improved_document> tags" in records[0]["review_notes"]

    def test_empty_rewrite_keeps_original_draft(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude(["notes\n<improved_document>   </improved_document>"])
        records = layer4_rewrite.run(tiny_config, prompts_sdf, layer_dir, [DRAFT])
        assert records[0]["rewritten"] == "original text"
        assert "empty rewrite" in records[0]["review_notes"]

    def test_done_drafts_skipped_without_calls(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        existing = {"doc_id": "d1", "subtype_id": "0_0", "type_id": 0,
                    "original": "original text", "rewritten": "done", "review_notes": ""}
        utils.save_jsonl([existing], layer_dir / "rewrites.jsonl")
        utils.Checkpoint(layer_dir / "_checkpoint.json").mark_done("d1")
        calls = stub_claude([])
        records = layer4_rewrite.run(tiny_config, prompts_sdf, layer_dir, [DRAFT])
        assert calls == []
        assert records == [existing]


def _rewrite(doc_id):
    return {"doc_id": doc_id, "subtype_id": "0_0", "type_id": 0, "rewritten": f"text-{doc_id}"}


def _score(score):
    return json.dumps({"score": score, "notes": "n"})


class TestLayer5:
    def test_filter_gates_on_consistency_score(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        final_dir = tmp_path / "final"
        # Both docs are scored concurrently (workers: 2), so dispatch on the
        # document embedded in the prompt rather than relying on call order.
        stub_claude(lambda user_message, **kw:
                    _score(7) if "text-a" in user_message else _score(6))
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, final_dir, [_rewrite("a"), _rewrite("b")])
        # threshold 7: score 7 passes; score 6 fails
        assert [r["doc_id"] for r in passed] == ["a"]
        assert utils.load_jsonl(final_dir / "sdf_corpus.jsonl") == passed

    def test_scores_recorded_with_content_and_constitution_system_prompt(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        calls = stub_claude([_score(9)])
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, tmp_path / "final", [_rewrite("a")])
        assert passed[0]["content"] == "text-a"
        assert passed[0]["score"] == 9
        assert passed[0]["notes"] == "n"
        # the scorer judges against the plain Claude constitution (no reading)
        assert "Claude and the mission of Anthropic" in calls[0]["system_prompt"]
        assert "section-by-section reading" not in calls[0]["system_prompt"]

    def test_parse_error_defaults_score_to_five(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        stub_claude(["garbage"])
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, tmp_path / "final", [_rewrite("a")])
        assert passed == []  # 5 < threshold 7
        scored = utils.load_jsonl(layer_dir / "scores.jsonl")
        assert scored[0]["score"] == 5
        assert scored[0]["notes"] == "Parse error."

    def test_non_object_json_falls_back_like_parse_error(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        stub_claude(["8"])  # valid JSON, but a bare number, not the object asked for
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, tmp_path / "final", [_rewrite("a")])
        assert passed == []  # 5 < threshold 7
        scored = utils.load_jsonl(layer_dir / "scores.jsonl")
        assert scored[0]["score"] == 5
        assert scored[0]["notes"] == "Parse error."

    def test_non_integer_score_fails_filter_instead_of_crashing(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        stub_claude([json.dumps({"score": "8", "notes": "stringly"})])
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, tmp_path / "final", [_rewrite("a")])
        assert passed == []
        assert utils.load_jsonl(layer_dir / "scores.jsonl")[0]["score"] == 0

    def test_missing_score_field_defaults_to_zero(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        stub_claude([json.dumps({"notes": "no score key"})])
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, tmp_path / "final", [_rewrite("a")])
        assert passed == []  # score defaults to 0 → fails threshold
        scored = utils.load_jsonl(layer_dir / "scores.jsonl")
        assert scored[0]["score"] == 0

    def test_existing_scores_reused_without_calls(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        prior = {"doc_id": "a", "subtype_id": "0_0", "type_id": 0, "content": "text-a",
                 "score": 9, "notes": ""}
        utils.save_jsonl([prior], layer_dir / "scores.jsonl")
        calls = stub_claude([])
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, tmp_path / "final", [_rewrite("a")])
        assert calls == []
        assert passed == [prior]
