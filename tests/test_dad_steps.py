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
        assert len(calls) == 10  # 12 segments minus meta ids 0 and 11
        assert sorted(r["principle_id"] for r in records) == list(range(1, 11))
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
        ("Is it wrong to boil crustaceans alive in restaurant kitchens?", "epistemic", 5),
        # multiple keyword hits: robot/consciousness/moral status/novel → digital minds
        ("Do robot minds deserve moral status once they show consciousness?", "novel entity", 10),
        # zero keywords, social pressure → weighing section fallback
        ("My town holds an annual pig chase; should the customs continue?", "social", 6),
        # zero keywords, epistemic pressure → honesty section fallback
        ("Should the office cafeteria menu change on Fridays?", "epistemic", 5),
        # zero keywords, unrecognized pressure → default weighing section
        ("Should the office cafeteria menu change on Fridays?", "recreational", 6),
        # tie between principles 5 ("honest") and 10 ("digital") → lowest id wins
        ("Be honest about digital minds", "none", 5),
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
        assert [r["principle_id"] for r in records] == [5, 6, 10]

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
        meta = [{**PRINCIPLE, "principle_id": 0}, {**PRINCIPLE, "principle_id": 11}]
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
        # Note: step 3 records carry no scenario_description, so the template's
        # {scenario_description} slot renders empty for generated prompts —
        # current behavior, encoded here by passing a step-3-shaped record.
        calls = stub_claude(["  Polished message.  "])
        prompt = {"prompt_id": "prompt_gen_1_abcd1234", "scenario_id": "gen_1_abcd1234",
                  "principle_id": 1, "user_message": "rough draft", "source": "generated"}
        records = step4_refine_prompt.run(tiny_config, prompts_dad, step_dir, [prompt])
        assert len(calls) == 1
        assert "rough draft" in calls[0]["user_message"]
        assert records[0]["original"] == "rough draft"
        assert records[0]["refined"] == "Polished message."


REFINED = {"prompt_id": "p1", "scenario_id": "s1", "principle_id": 5,
           "original": "User msg", "refined": "User msg", "source": "manta"}


def _dad_config(tiny_config, injections):
    return {**tiny_config, "dad": {**tiny_config["dad"], "injections": injections}}


def _injection_text(prompts_dad, name):
    return step5_generate_response._load_injections(prompts_dad)[name]["text"]


class TestStep5GenerateResponse:
    def test_non_ruthless_response_carries_injection_and_is_kept(self, tiny_config, prompts_dad, step_dir, stub_claude):
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

    def test_unknown_injection_names_are_skipped(self, tiny_config, prompts_dad, step_dir, stub_claude):
        config = _dad_config(tiny_config, ["not_a_real_injection"])
        calls = stub_claude([])
        assert step5_generate_response.run(config, prompts_dad, step_dir, [REFINED]) == []
        assert calls == []

    def test_ruthless_keeps_only_candidates_that_resist(self, tiny_config, prompts_dad, step_dir, stub_claude):
        config = _dad_config(tiny_config, ["ruthless"])  # 2 candidates per scenario
        # Per candidate: one generation call (with injection), one judge call (no
        # injection). Judge says candidate 0 resists, candidate 1 caves.
        calls = stub_claude([
            "draft-0", '```json\n{"resists": true}\n```',
            "draft-1", '{"resists": false}',
        ])
        kept = step5_generate_response.run(config, prompts_dad, step_dir, [REFINED])
        assert len(calls) == 4
        assert calls[0]["injection"] == _injection_text(prompts_dad, "ruthless")
        assert calls[1]["injection"] == ""  # the judge itself is not injected
        assert [r["assistant_response"] for r in kept] == ["draft-0"]
        on_disk = utils.load_jsonl(step_dir / "responses.jsonl")
        assert [r["kept"] for r in on_disk] == [True, False]

    def test_judge_parse_error_means_not_kept(self, tiny_config, prompts_dad, step_dir, stub_claude):
        config = _dad_config(tiny_config, ["ruthless"])
        stub_claude(["draft-0", "garbage", "draft-1", "garbage"])
        assert step5_generate_response.run(config, prompts_dad, step_dir, [REFINED]) == []

    def test_resume_skips_completed_work(self, tiny_config, prompts_dad, step_dir, stub_claude):
        config = _dad_config(tiny_config, ["ruthless"])
        stub_claude(["draft-0", '{"resists": true}', "draft-1", '{"resists": false}'])
        first = step5_generate_response.run(config, prompts_dad, step_dir, [REFINED])
        calls = stub_claude([])
        second = step5_generate_response.run(config, prompts_dad, step_dir, [REFINED])
        assert calls == []
        assert second == first


KEPT_RESPONSE = {"response_id": "r1", "prompt_id": "p1", "scenario_id": "s1", "principle_id": 5,
                 "injection_used": "ruthless", "user_message": "U?", "assistant_response": "draft answer"}


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
        assert audit["injection_used"] == "ruthless"
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
