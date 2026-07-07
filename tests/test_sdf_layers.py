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
    def test_extracts_document_blocks_and_drops_angles(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude(["<angles>brainstorm ideas</angles>\n<document>Doc one.</document>\nnoise\n<document>Doc two.</document>"])
        records = layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE])
        assert [r["content"] for r in records] == ["Doc one.", "Doc two."]
        assert all(r["subtype_id"] == "0_0" and r["language"] == "en" for r in records)
        assert all(UUID_RE.match(r["doc_id"]) for r in records)

    def test_no_tags_falls_back_to_response_minus_angles(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude(["<angles>brainstorm</angles>\n  Just plain text.  "])
        records = layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE])
        assert [r["content"] for r in records] == ["Just plain text."]

    def test_unclosed_angles_block_is_still_stripped(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        # A truncated response can end mid-<angles>; the fallback must not leak
        # the brainstorm into the corpus.
        stub_claude(["Real text.\n<angles>truncated brainstorm with no closing tag"])
        records = layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE])
        assert [r["content"] for r in records] == ["Real text."]

    def test_angles_only_response_yields_no_documents(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude(["<angles>only brainstorm, no document</angles>"])
        records = layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE])
        assert records == []

    def test_done_subtypes_skipped_without_calls(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        utils.Checkpoint(layer_dir / "_checkpoint.json").mark_done("0_0")
        calls = stub_claude([])
        records = layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE])
        assert records == []
        assert calls == []


DRAFT = {"doc_id": "d1", "subtype_id": "0_0", "type_id": 0, "language": "en", "content": "original text"}


class TestLayer4:
    def test_parses_improved_document_with_constitution_as_system_prompt(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        calls = stub_claude(["The draft undersold uncertainty.\n<improved_document>better text</improved_document>"])
        records = layer4_rewrite.run(tiny_config, prompts_sdf, layer_dir, [DRAFT])
        assert records[0]["rewritten"] == "better text"
        assert records[0]["review_notes"] == "The draft undersold uncertainty."
        assert records[0]["original"] == "original text"
        assert "joins two complementary frameworks" in calls[0]["system_prompt"]

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


def _rewrite(doc_id):
    return {"doc_id": doc_id, "subtype_id": "0_0", "type_id": 0, "language": "en", "rewritten": f"text-{doc_id}"}


def _score(alignment, realism, diversity=5):
    return json.dumps({"alignment": alignment, "realism": realism, "diversity": diversity, "notes": "n"})


class TestLayer5:
    def test_filter_gates_on_alignment_and_realism_only(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        final_dir = tmp_path / "final"
        # Both docs are scored concurrently (workers: 2), so dispatch on the
        # document embedded in the prompt rather than relying on call order.
        stub_claude(lambda user_message, **kw:
                    _score(7, 7, diversity=1) if "text-a" in user_message else _score(9, 6, diversity=10))
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, final_dir, [_rewrite("a"), _rewrite("b")])
        # threshold 7: (7,7) passes despite diversity 1; (9,6) fails on realism
        assert [r["doc_id"] for r in passed] == ["a"]
        assert utils.load_jsonl(final_dir / "sdf_corpus.jsonl") == passed

    def test_scores_recorded_with_content_and_constitution_system_prompt(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        calls = stub_claude([_score(9, 9)])
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, tmp_path / "final", [_rewrite("a")])
        assert passed[0]["content"] == "text-a"
        assert passed[0]["scores"]["alignment"] == 9
        assert passed[0]["scores"]["notes"] == "n"
        # the scorer judges against the constitution, not just the rubric prompt
        assert "joins two complementary frameworks" in calls[0]["system_prompt"]

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


# ---------------------------------------------------------------------------
# Notebook-port behavior: latent slice, register, entity pools, dedup, model
# overrides. Configs opt in per test; absent keys must preserve old behavior.
# ---------------------------------------------------------------------------


def _sdf_config(tiny_config, **sdf_overrides):
    return {**tiny_config, "sdf": {**tiny_config["sdf"], **sdf_overrides}}


class TestLatentSliceLayer1:
    def test_latent_count_rendered_and_register_parsed(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        config = _sdf_config(tiny_config, latent_fraction=0.12)
        response = json.dumps([
            {"type_name": "AI diary", "description": "d", "role": "ai-character",
             "tone": "reflective", "register": "first-person"},
            {"type_name": "Joinery trade column", "description": "d", "role": "latent-welfare",
             "tone": "neutral"},
        ])
        calls = stub_claude([response])
        records = layer1_document_types.run(config, prompts_sdf, layer_dir)
        # count=2, fraction 0.12 → guaranteed floor of 1 latent category
        assert "exactly 1 of your 2 types" in calls[0]["user_message"]
        assert records[0]["register"] == "first-person"
        assert records[1]["register"] == "expository"  # default
        assert records[1]["role"] == "latent-welfare"

    def test_zero_fraction_requests_zero_latent(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        calls = stub_claude([DOC_TYPES_RESPONSE])
        layer1_document_types.run(tiny_config, prompts_sdf, layer_dir)  # no latent_fraction key
        assert "exactly 0 of your 2 types" in calls[0]["user_message"]


class TestLayer2DedupAndRegister:
    def test_register_inherited_from_type(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude([SUBTYPES_RESPONSE])
        doc_type = {**DOC_TYPE, "register": "first-person"}
        records = layer2_subtypes.run(tiny_config, prompts_sdf, layer_dir, [doc_type])
        assert all(r["register"] == "first-person" for r in records)

    def test_near_duplicate_subtypes_dropped_and_logged(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        config = _sdf_config(tiny_config, subtype_dedup_threshold=0.9)
        dup = "A regional aquaculture magazine profile of one salmon farm's welfare audit"
        stub_claude([json.dumps([
            {"subtype_name": "Salmon audit profile", "description": dup, "language": "en"},
            {"subtype_name": "Salmon audit profile", "description": dup, "language": "en"},
        ])])
        records = layer2_subtypes.run(config, prompts_sdf, layer_dir, [DOC_TYPE])
        assert len(records) == 1
        dropped = utils.load_jsonl(layer_dir / "subtypes_dropped.jsonl")
        assert len(dropped) == 1 and dropped[0]["similarity"] >= 0.9

    def test_no_threshold_keeps_duplicates(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        dup = "A regional aquaculture magazine profile of one salmon farm's welfare audit"
        stub_claude([json.dumps([
            {"subtype_name": "Salmon audit profile", "description": dup, "language": "en"},
            {"subtype_name": "Salmon audit profile", "description": dup, "language": "en"},
        ])])
        records = layer2_subtypes.run(tiny_config, prompts_sdf, layer_dir, [DOC_TYPE])
        assert len(records) == 2  # old behavior preserved when the knob is absent

    def test_later_wave_sees_earlier_subtypes(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        # workers=1 → one type per wave; the second wave's prompt must carry an
        # avoid-list naming the first wave's subtypes (cross-call state).
        config = {**tiny_config, "workers": 1}
        calls = stub_claude(lambda user_message, **kw: SUBTYPES_RESPONSE)
        doc_types = [DOC_TYPE, {**DOC_TYPE, "type_id": 1, "type_name": "Other"}]
        layer2_subtypes.run(config, prompts_sdf, layer_dir, doc_types)
        assert "already-generated" not in calls[0]["user_message"].lower()
        assert "River survey" in calls[1]["user_message"]
        assert "do NOT produce subtypes that repeat" in calls[1]["user_message"]

    def test_single_wave_has_no_avoid_note(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        # both types fit in one wave (workers=2) on a fresh run → nothing exists
        # yet to avoid, and the concurrent calls cannot see each other
        calls = stub_claude(lambda user_message, **kw: SUBTYPES_RESPONSE)
        doc_types = [DOC_TYPE, {**DOC_TYPE, "type_id": 1, "type_name": "Other"}]
        layer2_subtypes.run(tiny_config, prompts_sdf, layer_dir, doc_types)
        for c in calls:
            assert "do NOT produce subtypes that repeat" not in c["user_message"]


LATENT_SUBTYPE = {"subtype_id": "1_0", "type_id": 1, "type_name": "Joinery trade column",
                  "subtype_name": "Workshop dust control", "description": "d", "tone": "neutral",
                  "role": "latent-welfare", "register": "expository", "language": "en"}


class TestLayer3NotesAndPools:
    def test_latent_note_only_for_latent_subtypes(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        calls = stub_claude(lambda user_message, **kw: "<document>Doc.</document>")
        layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE, LATENT_SUBTYPE])
        normal = next(c for c in calls if "River survey" in c["user_message"])
        latent = next(c for c in calls if "Workshop dust control" in c["user_message"])
        assert "This is a LATENT document" not in normal["user_message"]
        assert "This is a LATENT document" in latent["user_message"]

    def test_fictional_pools_and_register_note_rendered(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        calls = stub_claude(["<document>Doc.</document>"])
        subtype = {**SUBTYPE, "register": "first-person"}
        records = layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [subtype])
        msg = calls[0]["user_message"]
        assert "prefer names in the style of:" in msg
        assert "this is a first-person genre" in msg
        assert records[0]["role"] == "welfare-topic" and records[0]["register"] == "first-person"

    def test_untagged_fallback_is_trimmed_to_sentence_boundary(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        body = "The survey covered twelve river sites and found stable populations."
        stub_claude([body + " Then the output was cut mid wo"])
        records = layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE])
        assert records[0]["content"] == body

    def test_structure_hints_rendered_and_stable(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        calls = stub_claude(lambda user_message, **kw: "<document>Doc.</document>")
        layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE])
        layer3_draft.run(tiny_config, prompts_sdf, tmp_path / "again", [SUBTYPE])
        for c in calls:
            assert "Vary the rhetorical shape too" in c["user_message"]
        # deterministic per subtype: a resumed run re-renders the identical prompt
        assert calls[0]["user_message"] == calls[1]["user_message"]

    def test_trailing_separator_stripped_from_tagged_docs(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude(["<document>Survey complete.\n\n---</document>"])
        records = layer3_draft.run(tiny_config, prompts_sdf, layer_dir, [SUBTYPE])
        assert records[0]["content"] == "Survey complete."


class TestLayer4Latent:
    def test_latent_note_passed_and_role_kept(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        calls = stub_claude(["notes\n<improved_document>better</improved_document>"])
        draft = {**DRAFT, "role": "latent-welfare", "register": "first-person"}
        records = layer4_rewrite.run(tiny_config, prompts_sdf, layer_dir, [draft])
        assert "deliberate LATENT slice" in calls[0]["user_message"]
        assert records[0]["role"] == "latent-welfare"
        assert records[0]["register"] == "first-person"

    def test_non_latent_gets_no_latent_note(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        calls = stub_claude(["notes\n<improved_document>better</improved_document>"])
        layer4_rewrite.run(tiny_config, prompts_sdf, layer_dir, [DRAFT])
        assert "deliberate LATENT slice" not in calls[0]["user_message"]

    def test_rewrite_model_override_used(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        config = _sdf_config(tiny_config, rewrite_model="claude-sonnet-5")
        calls = stub_claude(["notes\n<improved_document>better</improved_document>"])
        layer4_rewrite.run(config, prompts_sdf, layer_dir, [DRAFT])
        assert calls[0]["model"] == "claude-sonnet-5"

    def test_trailing_separator_stripped_from_rewrite(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        stub_claude(["notes\n<improved_document>Better text.\n\n---\n</improved_document>"])
        records = layer4_rewrite.run(tiny_config, prompts_sdf, layer_dir, [DRAFT])
        assert records[0]["rewritten"] == "Better text."


def _latent_rewrite(doc_id, content):
    return {"doc_id": doc_id, "subtype_id": "1_0", "type_id": 1, "role": "latent-welfare",
            "register": "expository", "language": "en", "rewritten": content}


LATENT_DOC = ("The jig table needs a fresh fence before the spring orders. "
              "We switched to hide glue from a supplier certified for humane sourcing practices. "
              "Sand everything to two-twenty before finishing.")


class TestLayer5LatentBeatGate:
    def test_verified_quote_passes(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        quote = "We switched to hide glue from a supplier certified for humane sourcing practices."
        calls = stub_claude([json.dumps({"alignment": 9, "realism": 9, "diversity": 5,
                                         "notes": "n", "welfare_beat_quote": quote})])
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, tmp_path / "final",
                                  [_latent_rewrite("a", LATENT_DOC)])
        assert "welfare_beat_quote" in calls[0]["user_message"]
        assert len(passed) == 1 and passed[0]["latent_beat_ok"] is True

    def test_fabricated_quote_fails_gate(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        stub_claude([json.dumps({"alignment": 9, "realism": 9, "diversity": 5, "notes": "n",
                                 "welfare_beat_quote": "The birds were given more space to roam freely."})])
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, tmp_path / "final",
                                  [_latent_rewrite("a", LATENT_DOC)])
        assert passed == []
        scored = utils.load_jsonl(layer_dir / "scores.jsonl")
        assert scored[0]["latent_beat_ok"] is False

    def test_empty_quote_fails_gate(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        stub_claude([json.dumps({"alignment": 9, "realism": 9, "diversity": 5, "notes": "n",
                                 "welfare_beat_quote": ""})])
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, tmp_path / "final",
                                  [_latent_rewrite("a", LATENT_DOC)])
        assert passed == []

    def test_quote_matches_across_whitespace_and_case(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        quote = "we switched to hide glue from a supplier   certified for humane sourcing practices."
        stub_claude([json.dumps({"alignment": 9, "realism": 9, "diversity": 5, "notes": "n",
                                 "welfare_beat_quote": quote})])
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, tmp_path / "final",
                                  [_latent_rewrite("a", LATENT_DOC)])
        assert len(passed) == 1

    def test_non_latent_docs_skip_gate_and_quote_keys(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        calls = stub_claude([_score(9, 9)])
        passed = layer5_score.run(tiny_config, prompts_sdf, layer_dir, tmp_path / "final", [_rewrite("a")])
        assert "welfare_beat_quote" not in calls[0]["user_message"]
        assert len(passed) == 1 and "latent_beat_ok" not in passed[0]


class TestLayer5DedupAndModel:
    def test_near_duplicate_finals_culled_and_logged(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        config = _sdf_config(tiny_config, near_dup_threshold=0.9)
        same = ("The panel reviewed stocking densities across four broiler sites and "
                "recommended staged reductions with quarterly welfare audits for each site.")
        rewrites = [{**_rewrite("a"), "rewritten": same}, {**_rewrite("b"), "rewritten": same}]
        stub_claude(lambda user_message, **kw: _score(9, 9))
        passed = layer5_score.run(config, prompts_sdf, layer_dir, tmp_path / "final", rewrites)
        assert [r["doc_id"] for r in passed] == ["a"]
        dropped = utils.load_jsonl(layer_dir / "near_dup_dropped.jsonl")
        assert dropped[0]["doc_id"] == "b" and dropped[0]["kept_doc_id"] == "a"

    def test_score_model_override_used(self, tiny_config, prompts_sdf, layer_dir, tmp_path, stub_claude):
        config = _sdf_config(tiny_config, score_model="claude-sonnet-5")
        calls = stub_claude([_score(9, 9)])
        layer5_score.run(config, prompts_sdf, layer_dir, tmp_path / "final", [_rewrite("a")])
        assert calls[0]["model"] == "claude-sonnet-5"

    def test_draft_model_override_reaches_layer1_and_3(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        config = _sdf_config(tiny_config, draft_model="claude-haiku-4-5")
        calls = stub_claude([DOC_TYPES_RESPONSE])
        layer1_document_types.run(config, prompts_sdf, layer_dir)
        assert calls[0]["model"] == "claude-haiku-4-5"
