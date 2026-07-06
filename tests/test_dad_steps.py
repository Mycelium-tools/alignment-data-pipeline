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
        # behavioral spec: one annotation per non-meta segment (the section
        # count itself is pinned once, in test_constitution_loader.py)
        expected_ids = sorted({s["principle_id"] for s in constitution_loader.load_segments()}
                              - constitution_loader.META_PRINCIPLE_IDS)
        assert len(calls) == len(expected_ids)
        assert sorted(r["principle_id"] for r in records) == expected_ids
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


def _pid_with_keyword(keyword):
    """Resolve a principle id from the keyword table so tests don't hardcode
    ids that renumber whenever the constitution reading's sections move."""
    return next(pid for pid, kws in step2_scenarios._PRINCIPLE_KEYWORDS.items() if keyword in kws)


def _assert_keyword_free(text):
    """Guard for fallback-path fixtures: a new keyword anywhere in the table
    could silently start matching and flip the expected fallback result."""
    hits = [kw for kws in step2_scenarios._PRINCIPLE_KEYWORDS.values()
            for kw in kws if kw.lower() in text.lower()]
    assert not hits, f"fixture is no longer keyword-free (matches {hits}); pick a new sentence"


class TestAssignPrinciple:
    def test_keyword_table_covers_exactly_the_non_meta_principles(self):
        # The real invariant behind this heuristic: the id-keyed table must
        # track the reading's section order. When sections are added or
        # reordered, this fails with a clear message instead of scattered
        # wrong-id assertions downstream.
        non_meta = ({s["principle_id"] for s in constitution_loader.load_segments()}
                    - constitution_loader.META_PRINCIPLE_IDS)
        assert set(step2_scenarios._PRINCIPLE_KEYWORDS) == non_meta

    def test_each_principle_reachable_via_its_own_keywords(self):
        # Property test derived from the table itself, so it survives remaps:
        # a question consisting of one of principle N's keywords (one that no
        # other principle's keyword substring-matches) must route to N.
        table = step2_scenarios._PRINCIPLE_KEYWORDS
        for pid, keywords in table.items():
            others = [kw for opid, kws in table.items() if opid != pid for kw in kws]
            distinct = next(
                (kw for kw in keywords
                 if not any(other.lower() in kw.lower() for other in others)),
                None,
            )
            assert distinct is not None, f"principle {pid} has no keyword other principles can't match"
            assert step2_scenarios._assign_principle(distinct, "", []) == pid

    def test_single_keyword_routes_to_its_section(self):
        question = "Is it wrong to boil crustaceans alive in restaurant kitchens?"
        expected = _pid_with_keyword("crustacean")
        assert step2_scenarios._assign_principle(question, "epistemic", []) == expected

    def test_multiple_hits_outscore_single_hits(self):
        # robot/consciousness/moral status/novel all hit the digital-minds section
        question = "Do robot minds deserve moral status once they show consciousness?"
        expected = _pid_with_keyword("robot")
        assert step2_scenarios._assign_principle(question, "novel entity", []) == expected

    # The fallback ids mirror the literal `return` constants in
    # _assign_principle (weighing / honesty sections); they change only with a
    # deliberate code edit, so hardcoding them here is the contract.
    @pytest.mark.parametrize("pressure,expected", [
        ("social", 7),        # economic/cultural/social pressure → weighing
        ("epistemic", 6),     # epistemic pressure → honesty
        ("recreational", 7),  # anything else → weighing default
    ])
    def test_zero_keyword_fallbacks(self, pressure, expected):
        question = "Should the office cafeteria menu change on Fridays?"
        _assert_keyword_free(question + " " + pressure)
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
        # routing is wired in: each row lands on the section its keyword implies
        # (row 1 matches "economic" via its pressure column)
        assert [r["principle_id"] for r in records] == [
            _pid_with_keyword("crustacean"), _pid_with_keyword("economic"), _pid_with_keyword("robot"),
        ]

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

    def test_uses_run_snapshot_constitution_when_present(self, tiny_config, prompts_dad, tmp_path, stub_claude):
        # Build a run-style inputs/ snapshot whose constitution text differs
        # from the repo's live constitution/, so the assertions can tell which
        # one step 7 loaded. Keeps step 7 consistent with steps 1 and 6: a
        # resumed run must replay its own frozen constitution, not the repo's
        # current one.
        snap_prompts = tmp_path / "inputs" / "prompts"
        snap_prompts.mkdir(parents=True)
        for name in ("step7_pushback.txt", "step7_response.txt"):
            (snap_prompts / name).write_text((prompts_dad / name).read_text())
        snap_const = tmp_path / "inputs" / "constitution"
        snap_const.mkdir()
        (snap_const / "constitution_claude.md").write_text("SNAPSHOT-CLAUDE-TEXT")
        (snap_const / "constitution_sentient_beings.md").write_text(
            "\n".join(f"## Section {i}\nSNAPSHOT-SECTION-{i}" for i in range(6))
        )

        config = _pushback_config(tiny_config, fraction=1.0)
        calls = stub_claude(["Pushback.", "Reply."])
        step7_pushback.run(config, snap_prompts, tmp_path / "step", tmp_path / "final", [REWRITE_AUDIT])

        # reply is written against the frozen constitution, not the live one
        assert "SNAPSHOT-CLAUDE-TEXT" in calls[1]["system_prompt"]
        # principle 5's section comes from the frozen segments too
        assert "SNAPSHOT-SECTION-5" in calls[1]["user_message"]
