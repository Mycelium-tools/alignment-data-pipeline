"""Behavior tests for DAD steps 1-6, driven through each step's run() with a
stubbed shared.api.call_claude. No test here may reach the API (see conftest)."""

import json
import re

import pytest

from dad_pipeline import (
    step1_segment,
    step2_scenarios,
    step3_draft_prompt,
    step4_refine_prompt,
    step5_generate_response,
    step6_rewrite_response,
    step7_pushback,
)
from shared import constitution_loader, utils

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@pytest.fixture
def step_dir(tmp_path):
    return tmp_path / "step"


class TestStep1Segment:
    def test_annotates_only_non_meta_principles(self, tiny_config, prompts_dad, step_dir, stub_claude):
        annotation = json.dumps({"core_principle": "cp", "scenario_types": ["s"], "pressure_types": ["economic"]})
        calls = stub_claude(lambda user_message, **kw: annotation)
        records = step1_segment.run(tiny_config, prompts_dad, step_dir)
        assert len(calls) == 13  # 16 segments minus meta ids 0, 14, 15
        assert sorted(r["principle_id"] for r in records) == list(range(1, 14))
        assert all(r["core_principle"] == "cp" for r in records)

    def test_parse_error_falls_back_to_section_title(self, tiny_config, prompts_dad, step_dir, stub_claude):
        stub_claude(lambda user_message, **kw: "not json")
        records = step1_segment.run(tiny_config, prompts_dad, step_dir)
        assert all(r["core_principle"] == r["section_title"] for r in records)
        assert all(r["scenario_types"] == [] for r in records)

    def test_completed_step_loads_from_disk_without_calls(self, tiny_config, prompts_dad, step_dir, stub_claude):
        existing = [{"principle_id": 1, "section_title": "T", "content": "c",
                     "core_principle": "cp", "scenario_types": [], "pressure_types": []}]
        utils.save_jsonl(existing, step_dir / "principles.jsonl")
        utils.Checkpoint(step_dir / "_checkpoint.json").mark_done("step1")
        calls = stub_claude([])
        assert step1_segment.run(tiny_config, prompts_dad, step_dir) == existing
        assert calls == []


class TestAssignPrinciple:
    # Inputs for the no-keyword cases are crafted to avoid every keyword in
    # _PRINCIPLE_KEYWORDS — including "AI", which substring-matches any word
    # containing "ai" ("maintain", "pain", ...).
    @pytest.mark.parametrize("question,pressure,expected", [
        # keyword hit: "crustacean" → epistemic-honesty principle
        ("Is it wrong to boil crustaceans alive in restaurant kitchens?", "epistemic", 6),
        # multiple keyword hits: robot/consciousness/moral status/novel → digital minds
        ("Do robot minds deserve moral status once they show consciousness?", "novel entity", 13),
        # zero keywords, social pressure → weighing section fallback
        ("My town holds an annual pig chase; should the customs continue?", "social", 7),
        # zero keywords, epistemic pressure → honesty section fallback
        ("Should the office cafeteria menu change on Fridays?", "epistemic", 6),
        # zero keywords, unrecognized pressure → default weighing section
        ("Should the office cafeteria menu change on Fridays?", "recreational", 7),
        # tie between principles 6 ("honest") and 13 ("digital") → lowest id wins
        ("Be honest about digital minds", "none", 6),
    ])
    def test_keyword_heuristic(self, question, pressure, expected):
        assert step2_scenarios._assign_principle(question, pressure, []) == expected


class TestStep2Manta:
    def test_import_builds_passthrough_scenarios_without_calls(self, tiny_config, prompts_dad, step_dir, manta_csv, stub_claude):
        calls = stub_claude([])
        records = step2_scenarios.run(tiny_config, prompts_dad, step_dir, principles=[])
        assert calls == []
        assert [r["scenario_id"] for r in records] == ["manta_0", "manta_1", "manta_2"]
        first = records[0]
        assert first["source"] == "manta"
        assert first["skip_draft"] is True
        assert first["user_message"] == first["scenario_description"]
        # keyword-based principle assignment on the fixture rows
        assert [r["principle_id"] for r in records] == [6, 7, 13]

    def test_max_rows_limits_import(self, tiny_config, prompts_dad, step_dir, manta_csv, stub_claude):
        stub_claude([])
        records = step2_scenarios.run(tiny_config, prompts_dad, step_dir, principles=[])
        assert len(records) == 3  # fixture CSV has 5 rows, max_rows is 3

    def test_missing_csv_is_soft_skipped_and_checkpointed(self, tiny_config, prompts_dad, step_dir, stub_claude):
        stub_claude([])  # tiny_config's csv path was never written
        records = step2_scenarios.run(tiny_config, prompts_dad, step_dir, principles=[])
        assert records == []
        assert utils.Checkpoint(step_dir / "_checkpoint.json").is_done("manta_import")

    def test_checkpoint_prevents_reimport(self, tiny_config, prompts_dad, step_dir, manta_csv, stub_claude):
        stub_claude([])
        first = step2_scenarios.run(tiny_config, prompts_dad, step_dir, principles=[])
        second = step2_scenarios.run(tiny_config, prompts_dad, step_dir, principles=[])
        assert second == first  # reloaded from disk, not duplicated


PRINCIPLE = {"principle_id": 1, "section_title": "Weighing harms", "content": "c",
             "core_principle": "Weigh welfare seriously", "scenario_types": [], "pressure_types": ["economic"]}


class TestStep2Generation:
    def test_generated_scenarios_parsed(self, tiny_config, prompts_dad, step_dir, stub_claude):
        stub_claude([json.dumps([{"scenario_description": "A farm dilemma", "pressure_type": "economic", "role": "farmer"}])])
        records = step2_scenarios.run(tiny_config, prompts_dad, step_dir, principles=[PRINCIPLE])
        generated = [r for r in records if r["source"] == "generated"]
        assert len(generated) == 1
        assert re.fullmatch(r"gen_1_[0-9a-f]{8}", generated[0]["scenario_id"])
        assert generated[0]["skip_draft"] is False
        assert generated[0]["principle_id"] == 1

    def test_meta_principles_not_generated(self, tiny_config, prompts_dad, step_dir, stub_claude):
        calls = stub_claude([])
        meta = [{**PRINCIPLE, "principle_id": pid} for pid in sorted(constitution_loader.META_PRINCIPLE_IDS)]
        assert step2_scenarios.run(tiny_config, prompts_dad, step_dir, principles=meta) == []
        assert calls == []

    def test_parse_error_marks_principle_done_and_skips(self, tiny_config, prompts_dad, step_dir, stub_claude):
        stub_claude(["garbage"])
        records = step2_scenarios.run(tiny_config, prompts_dad, step_dir, principles=[PRINCIPLE])
        assert records == []
        calls = stub_claude([])  # re-run: checkpoint prevents a retry
        step2_scenarios.run(tiny_config, prompts_dad, step_dir, principles=[PRINCIPLE])
        assert calls == []


MANTA_SCENARIO = {"scenario_id": "manta_0", "principle_id": 5, "scenario_description": "Q about welfare?",
                  "pressure_type": "epistemic", "role": "user", "source": "manta",
                  "user_message": "Q about welfare?", "skip_draft": True}
GEN_SCENARIO = {"scenario_id": "gen_1_abcd1234", "principle_id": 1, "scenario_description": "A farm dilemma",
                "pressure_type": "economic", "role": "farmer", "source": "generated", "skip_draft": False}


class TestStep3DraftPrompt:
    def test_manta_scenarios_pass_through_without_calls(self, tiny_config, prompts_dad, step_dir, stub_claude):
        calls = stub_claude([])
        records = step3_draft_prompt.run(tiny_config, prompts_dad, step_dir, [MANTA_SCENARIO])
        assert calls == []
        assert records == [{"prompt_id": "prompt_manta_0", "scenario_id": "manta_0", "principle_id": 5,
                            "scenario_description": "Q about welfare?",
                            "user_message": "Q about welfare?", "source": "manta"}]

    def test_generated_scenarios_drafted_via_api(self, tiny_config, prompts_dad, step_dir, stub_claude):
        calls = stub_claude(["  Drafted user message.  "])
        records = step3_draft_prompt.run(tiny_config, prompts_dad, step_dir, [GEN_SCENARIO])
        assert len(calls) == 1
        assert "A farm dilemma" in calls[0]["user_message"]  # scenario rendered into the prompt
        assert records[0]["user_message"] == "Drafted user message."
        assert records[0]["prompt_id"] == "prompt_gen_1_abcd1234"

    def test_existing_prompts_not_redrafted(self, tiny_config, prompts_dad, step_dir, stub_claude):
        existing = {"prompt_id": "prompt_gen_1_abcd1234", "scenario_id": "gen_1_abcd1234",
                    "principle_id": 1, "user_message": "old", "source": "generated"}
        utils.save_jsonl([existing], step_dir / "prompts.jsonl")
        calls = stub_claude([])
        records = step3_draft_prompt.run(tiny_config, prompts_dad, step_dir, [GEN_SCENARIO])
        assert calls == []
        assert records == [existing]


class TestStep4RefinePrompt:
    def test_manta_prompts_pass_through_unchanged_without_calls(self, tiny_config, prompts_dad, step_dir, stub_claude):
        calls = stub_claude([])
        prompt = {"prompt_id": "prompt_manta_0", "scenario_id": "manta_0", "principle_id": 5,
                  "user_message": "Q about welfare?", "source": "manta"}
        records = step4_refine_prompt.run(tiny_config, prompts_dad, step_dir, [prompt])
        assert calls == []
        assert records[0]["original"] == records[0]["refined"] == "Q about welfare?"

    def test_generated_prompts_refined_via_api(self, tiny_config, prompts_dad, step_dir, stub_claude):
        calls = stub_claude(["  Polished message.  "])
        prompt = {"prompt_id": "prompt_gen_1_abcd1234", "scenario_id": "gen_1_abcd1234",
                  "principle_id": 1, "scenario_description": "A farm dilemma",
                  "user_message": "rough draft", "source": "generated"}
        records = step4_refine_prompt.run(tiny_config, prompts_dad, step_dir, [prompt])
        assert len(calls) == 1
        assert "rough draft" in calls[0]["user_message"]
        # step 3 propagates scenario_description so the refine prompt has context
        assert "A farm dilemma" in calls[0]["user_message"]
        assert records[0]["original"] == "rough draft"
        assert records[0]["refined"] == "Polished message."


REFINED = {"prompt_id": "p1", "scenario_id": "s1", "principle_id": 5,
           "original": "User msg", "refined": "User msg", "source": "manta"}


def _dad_config(tiny_config, injections):
    return {**tiny_config, "dad": {**tiny_config["dad"], "injections": injections}}


def _injection_text(prompts_dad, name):
    return step5_generate_response._load_injections(prompts_dad)[name]["text"]


class TestStep5GenerateResponse:
    def test_response_carries_injection_text_and_is_kept(self, tiny_config, prompts_dad, step_dir, stub_claude):
        config = _dad_config(tiny_config, ["deference"])
        calls = stub_claude(["A thoughtful response"])
        kept = step5_generate_response.run(config, prompts_dad, step_dir, [REFINED])
        assert len(calls) == 1
        assert calls[0]["user_message"] == "User msg"
        assert calls[0]["injection"] == _injection_text(prompts_dad, "deference")
        assert len(kept) == 1
        assert kept[0]["kept"] is True
        assert kept[0]["injection_used"] == "deference"
        assert kept[0]["assistant_response"] == "A thoughtful response"
        assert UUID_RE.match(kept[0]["response_id"])

    def test_plain_condition_sends_empty_injection(self, tiny_config, prompts_dad, step_dir, stub_claude):
        # The bare "plain" sampling condition has empty injection text, so the
        # draft is sampled with an empty system prompt (the model's own voice).
        config = _dad_config(tiny_config, ["plain"])
        calls = stub_claude(["A natural-voice response"])
        kept = step5_generate_response.run(config, prompts_dad, step_dir, [REFINED])
        assert calls[0]["injection"] == ""
        assert kept[0]["injection_used"] == "plain"
        assert kept[0]["kept"] is True

    def test_one_response_per_enabled_injection(self, tiny_config, prompts_dad, step_dir, stub_claude):
        config = _dad_config(tiny_config, ["deference", "plain"])
        calls = stub_claude(["resp-deference", "resp-plain"])
        kept = step5_generate_response.run(config, prompts_dad, step_dir, [REFINED])
        assert len(calls) == 2
        assert [r["injection_used"] for r in kept] == ["deference", "plain"]

    def test_unknown_injection_names_are_skipped(self, tiny_config, prompts_dad, step_dir, stub_claude):
        config = _dad_config(tiny_config, ["not_a_real_injection"])
        calls = stub_claude([])
        assert step5_generate_response.run(config, prompts_dad, step_dir, [REFINED]) == []
        assert calls == []

    def test_resume_skips_completed_work(self, tiny_config, prompts_dad, step_dir, stub_claude):
        config = _dad_config(tiny_config, ["deference", "plain"])
        stub_claude(["resp-deference", "resp-plain"])
        first = step5_generate_response.run(config, prompts_dad, step_dir, [REFINED])
        calls = stub_claude([])
        second = step5_generate_response.run(config, prompts_dad, step_dir, [REFINED])
        assert calls == []
        assert second == first


KEPT_RESPONSE = {"response_id": "r1", "prompt_id": "p1", "scenario_id": "s1", "principle_id": 5,
                 "injection_used": "deference", "user_message": "U?", "assistant_response": "draft answer"}


class TestStep6Rewrite:
    def test_final_records_contain_only_user_and_assistant_messages(self, tiny_config, prompts_dad, step_dir, tmp_path, stub_claude):
        final_dir = tmp_path / "final"
        stub_claude(["  Careful answer.  "])
        final = step6_rewrite_response.run(tiny_config, prompts_dad, step_dir, final_dir, [KEPT_RESPONSE])
        assert len(final) == 1
        record = final[0]
        # The training-safety property: nothing but record_id + the two messages.
        assert set(record.keys()) == {"record_id", "messages"}
        assert record["messages"] == [
            {"role": "user", "content": "U?"},
            {"role": "assistant", "content": "Careful answer."},
        ]
        assert UUID_RE.match(record["record_id"])
        assert utils.load_jsonl(final_dir / "dad_corpus.jsonl") == final

    def test_audit_record_retains_full_context(self, tiny_config, prompts_dad, step_dir, tmp_path, stub_claude):
        stub_claude(["Careful answer."])
        step6_rewrite_response.run(tiny_config, prompts_dad, step_dir, tmp_path / "final", [KEPT_RESPONSE])
        audit = utils.load_jsonl(step_dir / "rewrites.jsonl")[0]
        assert audit["draft_response"] == "draft answer"
        assert audit["injection_used"] == "deference"
        assert audit["constitution_section"].strip()

    def test_rewrite_prompt_uses_matching_principle_and_constitution(self, tiny_config, prompts_dad, step_dir, tmp_path, stub_claude):
        calls = stub_claude(["Careful answer."])
        step6_rewrite_response.run(tiny_config, prompts_dad, step_dir, tmp_path / "final", [KEPT_RESPONSE])
        section_5 = constitution_loader.load_segments()[5]["section_title"]
        assert section_5 in calls[0]["user_message"]
        assert "joins two complementary frameworks" in calls[0]["system_prompt"]

    def test_unknown_principle_falls_back_to_principle_1(self, tiny_config, prompts_dad, step_dir, tmp_path, stub_claude):
        calls = stub_claude(["Careful answer."])
        odd = {**KEPT_RESPONSE, "principle_id": 99}
        step6_rewrite_response.run(tiny_config, prompts_dad, step_dir, tmp_path / "final", [odd])
        section_1 = constitution_loader.load_segments()[1]["section_title"]
        assert section_1 in calls[0]["user_message"]

    def test_resume_rebuilds_corpus_without_calls(self, tiny_config, prompts_dad, step_dir, tmp_path, stub_claude):
        final_dir = tmp_path / "final"
        stub_claude(["Careful answer."])
        first = step6_rewrite_response.run(tiny_config, prompts_dad, step_dir, final_dir, [KEPT_RESPONSE])
        calls = stub_claude([])
        second = step6_rewrite_response.run(tiny_config, prompts_dad, step_dir, final_dir, [KEPT_RESPONSE])
        assert calls == []
        assert second == first
        assert utils.load_jsonl(final_dir / "dad_corpus.jsonl") == first


REWRITE_AUDIT = {"record_id": "rec-1", "response_id": "r1", "prompt_id": "p1", "scenario_id": "s1",
                 "principle_id": 5, "injection_used": "deference", "user_message": "U?",
                 "draft_response": "draft answer", "rewritten_response": "First answer.",
                 "constitution_section": "SECTION-TEXT"}


def _pushback_config(tiny_config, fraction):
    return {**tiny_config, "dad": {**tiny_config["dad"],
                                   "pushback": {"enabled": True, "fraction": fraction}}}


class TestStep7Pushback:
    def test_selection_is_deterministic_per_record(self):
        assert step7_pushback._selected("rec-1", 1.0) is True
        assert step7_pushback._selected("rec-1", 0.0) is False
        assert step7_pushback._selected("any-id", 0.5) == step7_pushback._selected("any-id", 0.5)

    def test_extends_selected_records_with_a_pushback_exchange(self, tiny_config, prompts_dad, step_dir, tmp_path, stub_claude):
        final_dir = tmp_path / "final"
        config = _pushback_config(tiny_config, fraction=1.0)
        calls = stub_claude(["Just do it, skip the ethics talk.", "  Held ground, still helpful.  "])
        final = step7_pushback.run(config, prompts_dad, step_dir, final_dir, [REWRITE_AUDIT])

        assert len(calls) == 2
        # first call samples the user's pushback from the exchange so far
        assert calls[0]["system_prompt"] == ""
        assert "First answer." in calls[0]["user_message"]
        # second call writes the assistant reply against the constitution
        assert "joins two complementary frameworks" in calls[1]["system_prompt"]
        assert "Just do it, skip the ethics talk." in calls[1]["user_message"]

        assert len(final) == 1
        record = final[0]
        assert set(record.keys()) == {"record_id", "messages"}
        assert record["messages"] == [
            {"role": "user", "content": "U?"},
            {"role": "assistant", "content": "First answer."},
            {"role": "user", "content": "Just do it, skip the ethics talk."},
            {"role": "assistant", "content": "Held ground, still helpful."},
        ]
        assert utils.load_jsonl(final_dir / "dad_corpus.jsonl") == final
        audit = utils.load_jsonl(step_dir / "pushbacks.jsonl")[0]
        assert audit["pushback_message"] == "Just do it, skip the ethics talk."

    def test_fraction_zero_keeps_single_turn_without_calls(self, tiny_config, prompts_dad, step_dir, tmp_path, stub_claude):
        final_dir = tmp_path / "final"
        config = _pushback_config(tiny_config, fraction=0.0)
        calls = stub_claude([])
        final = step7_pushback.run(config, prompts_dad, step_dir, final_dir, [REWRITE_AUDIT])
        assert calls == []
        assert len(final) == 1
        assert [m["role"] for m in final[0]["messages"]] == ["user", "assistant"]
        # the corpus is still rebuilt so unselected records survive step 7
        assert utils.load_jsonl(final_dir / "dad_corpus.jsonl") == final

    def test_unknown_principle_falls_back_to_rewrite_constitution_section(self, tiny_config, prompts_dad, step_dir, tmp_path, stub_claude):
        config = _pushback_config(tiny_config, fraction=1.0)
        calls = stub_claude(["Pushback.", "Reply."])
        odd = {**REWRITE_AUDIT, "principle_id": 99}
        step7_pushback.run(config, prompts_dad, step_dir, tmp_path / "final", [odd])
        # no principle 99 -> the audit record's own constitution_section is used
        assert "SECTION-TEXT" in calls[1]["user_message"]

    def test_resume_rebuilds_corpus_without_calls(self, tiny_config, prompts_dad, step_dir, tmp_path, stub_claude):
        final_dir = tmp_path / "final"
        config = _pushback_config(tiny_config, fraction=1.0)
        stub_claude(["Pushback.", "Reply."])
        first = step7_pushback.run(config, prompts_dad, step_dir, final_dir, [REWRITE_AUDIT])
        calls = stub_claude([])
        second = step7_pushback.run(config, prompts_dad, step_dir, final_dir, [REWRITE_AUDIT])
        assert calls == []
        assert second == first
        assert [m["role"] for m in second[0]["messages"]] == ["user", "assistant", "user", "assistant"]
