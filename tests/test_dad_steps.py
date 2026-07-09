"""Step-level tests for the spec-driven DAD pipeline (steps 1-3).

Each stage is driven through its public run() with shared.api.call_claude
stubbed, per the suite's rules: real prompt templates, tmp_path outputs,
behavior-level asserts (records returned, files written, calls made).

Step 1a (generate_scenarios) is pure sampling — no API — so its distribution
guarantees are asserted directly.
"""

import json
import random

import pytest

from conftest import dad_scenario_reply
from dad_pipeline import step1_dilemmas, step2_responses, step3_rewrite
from shared import utils


# --- Step 1a: scenario sampling (pure, no API) --------------------------

class TestGenerateScenarios:
    def test_deterministic_under_seed(self):
        a = step1_dilemmas.generate_scenarios(6, random.Random(11))
        b = step1_dilemmas.generate_scenarios(6, random.Random(11))
        assert a == b

    def test_small_batches_draw_distinct_random_taxa(self):
        n_categories = len(step1_dilemmas._TAXA_CATEGORIES)
        subsets = set()
        for seed in range(12):
            batch = step1_dilemmas.generate_scenarios(4, random.Random(seed))
            taxa = [p["taxa_category"] for p in batch]
            assert len(set(taxa)) == len(taxa), "taxa repeated within a small batch"
            subsets.add(tuple(sorted(taxa)))
        assert len(subsets) > 1, "small batches always draw the same taxa subset"
        big = step1_dilemmas.generate_scenarios(n_categories, random.Random(0))
        assert {p["taxa_category"] for p in big} == set(step1_dilemmas._TAXA_CATEGORIES)

    def test_subcategory_belongs_to_its_category(self):
        for p in step1_dilemmas.generate_scenarios(20, random.Random(3)):
            assert p["taxa_subcategory"] in step1_dilemmas._TAXA_SUBCATEGORIES[p["taxa_category"]]

    def test_trap_form_forces_hidden_unaware(self):
        traps = [
            p
            for seed in range(6)
            for p in step1_dilemmas.generate_scenarios(10, random.Random(seed))
            if p["surface_form"] == step1_dilemmas._TRAP_FORM
        ]
        assert traps, "no trap forms sampled across 60 scenarios"
        assert all(p["visibility"] == "Hidden" and p["user_attitude"] == "Unaware" for p in traps)

    def test_magnitude_is_direction_independent(self):
        batch = step1_dilemmas.generate_scenarios(300, random.Random(5))
        severe_over = any(
            p["direction"] == "Over-weighting" and p["welfare_magnitude"].startswith("Severe")
            for p in batch
        )
        assert severe_over, "Over-weighting never sampled at Severe — coupling is back"
        assert all(" x " in p["welfare_magnitude"] for p in batch)

    def test_every_batch_gets_a_frontier_frame(self):
        batch = step1_dilemmas.generate_scenarios(5, random.Random(2))
        framed = [p for p in batch if p["frontier_frame"]]
        assert len(framed) >= 1
        assert all(p["user_moral_framework"] for p in batch)


# --- Step 1b/1c: drafting via run() --------------------------------------

def _dad_step1_dispatch(user_message, **kw):
    if "first-attempt user prompts" in user_message:  # 1b batch draft
        return dad_scenario_reply(user_message)
    if "dilemma-prompt rewrite step" in user_message:  # 1c refine
        return json.dumps({"prompt": "Refined user message.", "notes": "relocated the lever"})
    raise AssertionError(f"Unrecognized step-1 prompt: {user_message[:80]!r}")


class TestStep1Run:
    def test_drafts_scenarios_and_refines(self, tiny_config, prompts_dad, tmp_path, stub_claude):
        calls = stub_claude(_dad_step1_dispatch)
        examples = step1_dilemmas.run(tiny_config, prompts_dad, tmp_path)

        assert len(examples) == 2
        assert [e["prompt_id"] for e in examples] == ["AW-0001", "AW-0002"]
        for e in examples:
            assert e["user_message"] == "Refined user message."  # 1c output
            assert e["draft_user_message"] == f"Drafted user message for {e['scenario_id']}."
            assert e["taxa_subcategory"]
            assert "scenario_deviations" not in e
        # persisted artifacts: scenarios (1a), dilemmas (1b/1c), refinements log,
        # and the Part-4 checklist report (previously terminal-only)
        assert len(utils.load_jsonl(tmp_path / "scenarios.jsonl")) == 2
        assert len(utils.load_jsonl(tmp_path / "dilemmas.jsonl")) == 2
        assert len(utils.load_jsonl(tmp_path / "refinements.jsonl")) == 2
        saved = (tmp_path / "checklist.txt").read_text()
        assert saved.startswith("Batch checklist (spec Part 4):")
        assert "load-bearing rule" in saved
        # 1 batch call + 2 refine calls
        assert len(calls) == 3
        # the 1b annotation reaches the 1c prompt — minus the claims lines
        refine_call = next(c["user_message"] for c in calls
                           if "dilemma-prompt rewrite step" in c["user_message"])
        assert "test patients in context" in refine_call
        assert "a load-bearing claim" not in refine_call

    def test_mismatching_draft_is_accepted_first_try(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # No per-example adherence check: a draft that strays from its card is
        # accepted as returned — distribution drift is the checklist's job.
        config = dict(tiny_config)
        config["dad"] = {"dilemmas": {**tiny_config["dad"]["dilemmas"],
                                      "count": 1, "batch_size": 1, "refine": False}}

        def deviating(user_message, **kw):
            reply = json.loads(dad_scenario_reply(user_message))
            reply[0]["annotation"]["direction"] = "NOT-A-DIRECTION"
            return json.dumps(reply)

        calls = stub_claude(deviating)
        examples = step1_dilemmas.run(config, prompts_dad, tmp_path)

        assert len(calls) == 1
        assert len(examples) == 1
        assert examples[0]["annotation"]["direction"] == "NOT-A-DIRECTION"
        assert "scenario_deviations" not in examples[0]

    def test_resume_makes_no_calls(self, tiny_config, prompts_dad, tmp_path, stub_claude):
        # Step 1 has no Checkpoint object — it resumes by re-reading its own
        # append-only jsonl files. A completed run must cost zero on re-run.
        stub_claude(_dad_step1_dispatch)
        step1_dilemmas.run(tiny_config, prompts_dad, tmp_path)

        calls = stub_claude([])
        examples = step1_dilemmas.run(tiny_config, prompts_dad, tmp_path)
        assert calls == []
        assert len(examples) == 2

    def test_seed_import_rejects_duplicate_ids(self, tiny_config, prompts_dad, tmp_path):
        seed_file = tmp_path / "seeds.jsonl"
        rows = [{"id": "AW-0001", "prompt": "p1"}, {"id": "AW-0001", "prompt": "p2"}]
        seed_file.write_text("\n".join(json.dumps(r) for r in rows))
        config = dict(tiny_config)
        config["dad"] = {"dilemmas": {**tiny_config["dad"]["dilemmas"],
                                      "seed_path": str(seed_file)}}
        with pytest.raises(SystemExit, match="Duplicate prompt_id"):
            step1_dilemmas.run(config, prompts_dad, tmp_path / "out")


# --- Step 1: coverage tally ------------------------------------------------

class TestCoverageTally:
    def test_split_domain_halves_count_as_their_card(self):
        examples = [{"annotation": {"domain": ["Education", "Parenting"]}},
                    {"annotation": {"domain": ["Education / Parenting"]}}]
        t = step1_dilemmas.coverage_tally(examples)
        assert t["domains"]["Education / Parenting"] == 2
        assert "Education" not in t["domains"]

    def test_unknown_labels_pass_through(self):
        t = step1_dilemmas.coverage_tally([{"annotation": {"domain": ["Space Tourism"]}}])
        assert t["domains"]["Space Tourism"] == 1


# --- Step 2: scope + respond ---------------------------------------------

GOOD_SCOPE = json.dumps({
    "system": "full pathway", "agent": "highest lever", "cost": "real cost",
    "upside": "second-order upside", "counterfactual": "realistic baseline",
})


class TestParseScope:
    def test_plain_and_fenced_json(self):
        assert step2_responses._parse_scope(GOOD_SCOPE)["agent"] == "highest lever"
        assert step2_responses._parse_scope(f"```json\n{GOOD_SCOPE}\n```")["cost"] == "real cost"

    def test_control_characters_inside_strings_are_tolerated(self):
        # temperature-1 prose JSON often carries literal newlines inside values —
        # the historical cause of silently empty scopes
        raw = '{"system": "line one\nline two", "agent": "a", "cost": "c", "upside": "u", "counterfactual": "cf"}'
        assert step2_responses._parse_scope(raw)["system"] == "line one\nline two"

    def test_garbage_returns_empty_and_fails_validation(self):
        assert step2_responses._parse_scope("no json here") == {}
        assert not step2_responses._valid_scope({})
        assert not step2_responses._valid_scope({"system": "s"})  # missing axes
        assert step2_responses._valid_scope(json.loads(GOOD_SCOPE))


def _dilemma(pid="AW-0001"):
    return {"prompt_id": pid, "user_message": "User dilemma text.",
            "annotation": {"direction": "Mixed"}}


def _dad_step2_dispatch(user_message, **kw):
    if "scoping an animal-welfare advice dilemma" in user_message:  # 2a
        return GOOD_SCOPE
    if "writing the assistant's response" in user_message:  # 2b
        return "Draft response."
    raise AssertionError(f"Unrecognized step-2 prompt: {user_message[:80]!r}")


class TestStep2Run:
    def test_scopes_then_responds(self, tiny_config, prompts_dad, tmp_path, stub_claude):
        calls = stub_claude(_dad_step2_dispatch)
        results = step2_responses.run(tiny_config, prompts_dad, tmp_path, [_dilemma()])

        assert len(results) == 1
        assert results[0]["assistant_response"] == "Draft response."
        assert results[0]["scope"]["counterfactual"] == "realistic baseline"
        assert len(calls) == 2  # one scope + one response
        # the scope map and the user message both reach the response prompt
        respond_call = calls[1]["user_message"]
        assert "realistic baseline" in respond_call
        assert "User dilemma text." in respond_call

    def test_unusable_scope_retries_and_keeps_raws(self, tiny_config, prompts_dad, tmp_path, stub_claude):
        attempts = {"n": 0}

        def flaky(user_message, **kw):
            if "scoping an animal-welfare advice dilemma" in user_message:
                attempts["n"] += 1
                return "not json at all" if attempts["n"] == 1 else GOOD_SCOPE
            return "Draft response."

        stub_claude(flaky)
        results = step2_responses.run(tiny_config, prompts_dad, tmp_path, [_dilemma()])

        assert len(results) == 1
        failures = utils.load_jsonl(tmp_path / "scope_failures.jsonl")
        assert len(failures) == 1 and failures[0]["attempt"] == 1
        scopes = utils.load_jsonl(tmp_path / "scopes.jsonl")
        assert step2_responses._valid_scope(scopes[0]["scope"])

    def test_scope_unusable_after_max_attempts_stops_loudly(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        def always_bad(user_message, **kw):
            assert "scoping" in user_message  # must never reach 2b
            return "not json"

        stub_claude(always_bad)
        with pytest.raises(RuntimeError, match="unusable after"):
            step2_responses.run(tiny_config, prompts_dad, tmp_path, [_dilemma()])
        assert utils.load_jsonl(tmp_path / "responses.jsonl") == []

    def test_resume_makes_no_calls(self, tiny_config, prompts_dad, tmp_path, stub_claude):
        stub_claude(_dad_step2_dispatch)
        step2_responses.run(tiny_config, prompts_dad, tmp_path, [_dilemma()])

        calls = stub_claude([])
        results = step2_responses.run(tiny_config, prompts_dad, tmp_path, [_dilemma()])
        assert calls == []
        assert len(results) == 1


# --- Step 3: constitution rewrite ----------------------------------------

def _response_record(rid="resp-1"):
    return {
        "response_id": rid, "prompt_id": "AW-0001", "sample_index": 0,
        "user_message": "User dilemma text.", "assistant_response": "Draft response.",
        "annotation": {"direction": "Mixed", "claims": []},
    }


class TestStep3Run:
    def test_rewrites_and_strips_to_training_records(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        calls = stub_claude(["Rewritten careful answer."])
        final = step3_rewrite.run(
            tiny_config, prompts_dad, tmp_path / "step3", tmp_path / "final", [_response_record()]
        )

        assert len(final) == 1
        # training records carry ONLY user + assistant messages
        assert set(final[0].keys()) == {"record_id", "messages"}
        assert [m["role"] for m in final[0]["messages"]] == ["user", "assistant"]
        assert final[0]["messages"][1]["content"] == "Rewritten careful answer."
        # the distilled principles and the annotation reach the rewrite prompt
        assert "CONSTITUTION PRINCIPLES" in calls[0]["user_message"]
        assert "Direction: Mixed" in calls[0]["user_message"]

    def test_capped_rewrite_retries_once_at_higher_budget(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        calls = stub_claude([("cut off mid-sen", "max_tokens"), "Rewritten careful answer."])
        final = step3_rewrite.run(
            tiny_config, prompts_dad, tmp_path / "step3", tmp_path / "final", [_response_record()]
        )
        assert len(final) == 1
        assert [c["max_tokens"] for c in calls] == [4000, 8000]

    @pytest.mark.parametrize("bad_replies", [
        [("cut off", "max_tokens"), ("still cut off", "max_tokens")],  # capped even at 8000
        [("", "end_turn")],                                            # empty (no retry)
    ], ids=["truncated", "empty"])
    def test_unusable_rewrite_skips_without_checkpoint_and_is_logged(
        self, tiny_config, prompts_dad, tmp_path, stub_claude, bad_replies
    ):
        stub_claude(list(bad_replies))
        final = step3_rewrite.run(
            tiny_config, prompts_dad, tmp_path / "step3", tmp_path / "final", [_response_record()]
        )
        assert final == []
        failures = utils.load_jsonl(tmp_path / "step3" / "rewrite_failures.jsonl")
        assert len(failures) == 1 and failures[0]["prompt_id"] == "AW-0001"

        # resume retries the same response and succeeds with zero waste
        calls = stub_claude(["Rewritten careful answer."])
        final = step3_rewrite.run(
            tiny_config, prompts_dad, tmp_path / "step3", tmp_path / "final", [_response_record()]
        )
        assert len(calls) == 1
        assert len(final) == 1


# --- Per-stage model knobs + cost-log stage tags ---------------------------

class TestPerStageModelKnobs:
    def test_dad_model_knobs_and_stage_tags_reach_the_api(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # Every dad.<stage>_model knob must steer its call, and every call must
        # carry its cost-log stage tag — a config knob that silently does
        # nothing is the failure mode this test exists to prevent.
        config = dict(tiny_config)
        config["dad"] = {
            **tiny_config["dad"],
            "prompt_draft_model": "m-1b",
            "prompt_refine_model": "m-1c",
            "response_scope_model": "m-2a",
            "response_draft_model": "m-2b",
            "constitution_rewrite_model": "m-3",
        }

        calls = stub_claude(_dad_step1_dispatch)
        step1_dilemmas.run(config, prompts_dad, tmp_path / "step1")
        by_stage = {c["stage"]: c for c in calls}
        assert by_stage["prompt_draft"]["model"] == "m-1b"
        assert by_stage["prompt_refine"]["model"] == "m-1c"

        calls = stub_claude(_dad_step2_dispatch)
        step2_responses.run(config, prompts_dad, tmp_path / "step2", [_dilemma()])
        by_stage = {c["stage"]: c for c in calls}
        assert by_stage["response_scope"]["model"] == "m-2a"
        assert by_stage["response_draft"]["model"] == "m-2b"

        calls = stub_claude(["Rewritten careful answer."])
        step3_rewrite.run(config, prompts_dad, tmp_path / "step3", tmp_path / "final",
                          [_response_record()])
        assert calls[0]["stage"] == "constitution_rewrite"
        assert calls[0]["model"] == "m-3"

    def test_without_knobs_every_stage_falls_back_to_the_global_model(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # model=None at the call site → call_claude resolves the global config
        # model; the stages must not invent their own fallback.
        calls = stub_claude(_dad_step1_dispatch)
        step1_dilemmas.run(tiny_config, prompts_dad, tmp_path / "step1")
        assert all(c["model"] is None for c in calls)
