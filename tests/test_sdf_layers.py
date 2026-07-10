"""Behavior tests for SDF layers 3-5, driven through each layer's run() with a
stubbed shared.api.call_claude. No test here may reach the API (see conftest).

Layers 1-2 are the deterministic matrix sampler now — see tests/test_matrix.py.
"""

import json
import re

import pytest

from sdf_pipeline import (
    layer3_draft,
    layer4_rewrite,
    layer5_score,
)
from shared import constitution_loader, utils

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@pytest.fixture
def layer_dir(tmp_path):
    return tmp_path / "layer"


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
        # system prompt is the Claude constitution + distilled principles block,
        # derived from the loaders so CSV/constitution edits don't break this
        system = calls[0]["system_prompt"]
        assert constitution_loader.load_constitution_claude() in system
        principles_block = constitution_loader.format_principles(constitution_loader.load_principles())
        assert principles_block in system

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
        # the scorer judges against the constitution + principles, not just the rubric prompt
        system = calls[0]["system_prompt"]
        assert constitution_loader.load_constitution_claude() in system
        principles_block = constitution_loader.format_principles(constitution_loader.load_principles())
        assert principles_block in system

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

    def test_draft_model_override_reaches_layer3(self, tiny_config, prompts_sdf, layer_dir, stub_claude):
        config = _sdf_config(tiny_config, draft_model="claude-haiku-4-5")
        calls = stub_claude(["<document>Doc.</document>"])
        layer3_draft.run(config, prompts_sdf, layer_dir, [SUBTYPE])
        assert calls[0]["model"] == "claude-haiku-4-5"
