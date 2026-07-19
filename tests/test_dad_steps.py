"""Step-level tests for the spec-driven DAD pipeline (steps 1-3).

Each stage is driven through its public run() with shared.api.call_claude
stubbed, per the suite's rules: real prompt templates, tmp_path outputs,
behavior-level asserts (records returned, files written, calls made).

Step 1a (generate_scenarios) is pure sampling — no API — so its distribution
guarantees are asserted directly.
"""

import json
import random
import threading

import pytest

from conftest import dad_scenario_plan_reply, dad_scenario_reply
from dad_pipeline import (baseline, compose_scenarios, reasoning_library,
                          step1_dilemmas, step2_responses, step3_rewrite)
from shared import utils


# --- Step 1b/1c: drafting via run() --------------------------------------

def _sysuser(user_message, kw):
    """Every DAD template splits into system + user, so the role marker lives
    in system_prompt while the payload (scenarios, scope, library, draft)
    stays in the user message. Dispatchers match against both halves."""
    return (kw.get("system_prompt") or "") + "\n" + user_message


def _dad_step1_dispatch(user_message, **kw):
    blob = _sysuser(user_message, kw)
    if "write a description of a specific scenario" in blob:  # 1a scenario plan
        return dad_scenario_plan_reply(user_message)
    if "generate a fictional user input" in blob:  # 1b single-scenario draft
        return dad_scenario_reply(user_message)
    if "editor of dilemma prompts" in blob:  # 1c refine
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
            # the stub pads drafts to their dealt length band, so match the stem
            assert e["draft_user_message"].startswith("Drafted user message")
            # 1b writes no annotation: the record's annotation is the dealt labels
            assert e["annotation"]["visibility"] and e["annotation"]["leverage"]
            assert not e["annotation"].get("claims")
            assert e["taxa_subcategory"]
            assert compose_scenarios.length_band(e["length_class"])  # stamped, has a band
            assert "scenario_deviations" not in e
            # stable content-keyed ids assigned alongside the per-run ids
            assert e["scenario_gid"].startswith("S-")
            assert e["prompt_gid"].startswith("P-")
        # persisted artifacts: deals + planned scenarios (1a), dilemmas (1b/1c),
        # refinements log, and the Part-4 checklist report
        assert len(utils.load_jsonl(tmp_path / "scenario_deals.jsonl")) == 2
        scenarios = utils.load_jsonl(tmp_path / "scenarios.jsonl")
        assert len(scenarios) == 2
        assert all(s["scenario_gid"].startswith("S-") for s in scenarios)
        assert all(s["scenario_description"] for s in scenarios)  # the plan ran
        assert (tmp_path / "id_registry.json").exists()  # registry persisted
        assert len(utils.load_jsonl(tmp_path / "dilemmas.jsonl")) == 2
        assert len(utils.load_jsonl(tmp_path / "refinements.jsonl")) == 2
        saved = (tmp_path / "checklist.txt").read_text()
        assert saved.startswith("Batch checklist (spec Part 4):")
        assert "load-bearing" in saved
        # 2 plan calls + 2 single-scenario draft calls + 2 refine calls
        assert len(calls) == 6
        # the plan's description reaches each 1b drafting prompt, one per call
        draft_calls = [c for c in calls
                       if "generate a fictional user input" in (c["system_prompt"] or "")]
        assert len(draft_calls) == 2
        assert all("<scenario_description>" in c["user_message"] for c in draft_calls)
        assert {c["item_id"] for c in draft_calls} == {"S-001", "S-002"}
        # the synthesized (dealt-labels) annotation reaches the 1c prompt
        refine_call = next(c["user_message"] for c in calls
                           if "editor of dilemma prompts" in c["system_prompt"])
        assert "Visibility:" in refine_call and "Leverage:" in refine_call

    def test_unusable_refine_is_retried_once_and_raw_kept(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        config = dict(tiny_config)
        config["dad"] = {"dilemmas": {**tiny_config["dad"]["dilemmas"],
                                      "count": 1}}
        refine_calls = {"n": 0}

        def flaky_refine(user_message, **kw):
            if "write a description of a specific scenario" in _sysuser(user_message, kw):
                return dad_scenario_plan_reply(user_message)
            if "editor of dilemma prompts" in _sysuser(user_message, kw):
                refine_calls["n"] += 1
                if refine_calls["n"] == 1:
                    return "not json at all"
                return json.dumps({"prompt": "Refined user message.", "notes": "n"})
            return dad_scenario_reply(user_message)

        calls = stub_claude(flaky_refine)
        examples = step1_dilemmas.run(config, prompts_dad, tmp_path)

        assert len(calls) == 4  # 1 plan + 1 draft + 2 refine attempts
        assert examples[0]["user_message"] == "Refined user message."
        assert "refine_failed" not in examples[0]
        failures = utils.load_jsonl(tmp_path / "refine_failures.jsonl")
        assert len(failures) == 1
        assert failures[0]["attempt"] == 1 and failures[0]["raw"] == "not json at all"

    def test_refine_unusable_after_retries_keeps_draft_and_stamps_record(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        config = dict(tiny_config)
        config["dad"] = {"dilemmas": {**tiny_config["dad"]["dilemmas"],
                                      "count": 1}}

        def bad_refine(user_message, **kw):
            if "write a description of a specific scenario" in _sysuser(user_message, kw):
                return dad_scenario_plan_reply(user_message)
            if "editor of dilemma prompts" in _sysuser(user_message, kw):
                return "still not json"
            return dad_scenario_reply(user_message)

        calls = stub_claude(bad_refine)
        examples = step1_dilemmas.run(config, prompts_dad, tmp_path)

        assert len(calls) == 4  # 1 plan + 1 draft + MAX_REFINE_ATTEMPTS refine attempts
        e = examples[0]
        assert e["refine_failed"] is True
        assert e["user_message"].startswith("Drafted user message")  # 1b draft shipped
        assert "draft_user_message" not in e  # only set when refine succeeded
        assert len(utils.load_jsonl(tmp_path / "refine_failures.jsonl")) == 2
        assert utils.load_jsonl(tmp_path / "refinements.jsonl") == []

    def test_length_violating_draft_is_retried_not_checkpointed(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # Pick a seed that deals a single scenario whose length class has a
        # nonzero lower band, so an egregiously short draft must be rejected
        # and re-drawn — and the reject is a retry, not a strike.
        seed = next(
            s for s in range(50)
            if compose_scenarios.length_band(
                compose_scenarios.deal_scenarios(1, random.Random(s))[0]["length_class"]
            )[0] > 0
        )
        scen = compose_scenarios.deal_scenarios(1, random.Random(seed))[0]
        config = dict(tiny_config)
        config["dad"] = {"dilemmas": {**tiny_config["dad"]["dilemmas"],
                                      "count": 1,
                                      "scenario_seed": seed, "refine": False}}
        batch_calls = {"n": 0}

        def short_then_valid(user_message, **kw):
            if "write a description of a specific scenario" in _sysuser(user_message, kw):
                return dad_scenario_plan_reply(user_message)
            batch_calls["n"] += 1
            if batch_calls["n"] == 1:
                return "<user_prompt>Too short.</user_prompt>"  # egregious band miss
            return dad_scenario_reply(user_message)

        calls = stub_claude(short_then_valid)
        examples = step1_dilemmas.run(config, prompts_dad, tmp_path)

        assert len(calls) == 3  # 1 plan; the rejected draft cost one call, then the retry
        assert len(examples) == 1
        assert examples[0]["length_class"] == scen["length_class"]
        assert compose_scenarios.length_ok(examples[0]["user_message"],
                                           scen["length_class"])
        # a length reject is not a parse failure: nothing lands in draft_failures
        assert utils.load_jsonl(tmp_path / "draft_failures.jsonl") == []

    def test_tagless_draft_raw_is_persisted_and_retried(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        config = dict(tiny_config)
        config["dad"] = {"dilemmas": {**tiny_config["dad"]["dilemmas"],
                                      "count": 1, "refine": False}}
        draft_calls = {"n": 0}

        def flaky_draft(user_message, **kw):
            if "write a description of a specific scenario" in _sysuser(user_message, kw):
                return dad_scenario_plan_reply(user_message)
            draft_calls["n"] += 1
            return "no tags here" if draft_calls["n"] == 1 else dad_scenario_reply(user_message)

        stub_claude(flaky_draft)
        examples = step1_dilemmas.run(config, prompts_dad, tmp_path)

        assert len(examples) == 1  # the second pass recovered
        failures = utils.load_jsonl(tmp_path / "draft_failures.jsonl")
        assert len(failures) == 1
        assert failures[0]["raw"] == "no tags here" and failures[0]["pass"] == 1

    def test_persistent_length_misses_hit_the_pass_cap_not_the_three_strike(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # A draft that keeps missing its length band is a plain re-roll — it
        # must never trip the 3-strike abort (that's for parse/truncation
        # failure); it runs to the 8-pass cap instead. Regression: the n=30
        # probe (2026-07-18) aborted after 3 length-miss passes.
        seed = next(
            s for s in range(50)
            if compose_scenarios.length_band(
                compose_scenarios.deal_scenarios(1, random.Random(s))[0]["length_class"]
            )[1] < 10 ** 6
        )
        config = dict(tiny_config)
        config["dad"] = {"dilemmas": {**tiny_config["dad"]["dilemmas"],
                                      "count": 1, "scenario_seed": seed,
                                      "refine": False}}
        draft_calls = {"n": 0}

        def always_too_long(user_message, **kw):
            if "write a description of a specific scenario" in _sysuser(user_message, kw):
                return dad_scenario_plan_reply(user_message)
            draft_calls["n"] += 1
            return f"<user_prompt>{'x' * 20000}</user_prompt>"  # over every ceiling

        stub_claude(always_too_long)
        with pytest.raises(SystemExit, match="8 drafting passes"):
            step1_dilemmas.run(config, prompts_dad, tmp_path)
        assert draft_calls["n"] == 8  # all eight passes ran; no early 3-strike
        # length misses are re-rolls, never failure records
        assert utils.load_jsonl(tmp_path / "draft_failures.jsonl") == []

    def test_checklist_uses_the_runs_variables_snapshot_not_the_repos(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # A run deals (and must be checked) against ITS OWN variables.txt.
        # Rename a conflict value in the run's snapshot: the deals and the
        # saved checklist must both speak the snapshot's vocabulary, even
        # though the repo's live file still says "converge".
        import shutil
        snap_prompts = tmp_path / "prompts"
        shutil.copytree(prompts_dad, snap_prompts)
        variables = (snap_prompts / "variables.txt").read_text(encoding="utf-8")
        assert "0.20 :: converge" in variables  # precondition on the repo file
        (snap_prompts / "variables.txt").write_text(
            variables.replace("0.20 :: converge", "0.20 :: align"), encoding="utf-8")

        stub_claude(_dad_step1_dispatch)
        step1_dilemmas.run(tiny_config, snap_prompts, tmp_path / "out")

        saved = (tmp_path / "out" / "checklist.txt").read_text()
        conflict_line = next(l for l in saved.splitlines() if "Conflict shares" in l)
        assert "'align'" in conflict_line
        assert "'converge'" not in conflict_line

    def test_preplan_legacy_scenarios_draft_from_their_card(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # A pre-plan run's scenarios carry no scenario_description. Resumed
        # through the current single-scenario template, the rendered legacy
        # card must fill the description slot — never an empty block — and no
        # plan calls may fire (the deal-less run skips planning entirely).
        legacy_scenario = {
            "scenario_id": "S-001", "scenario_gid": "S-0001",
            "domain": ["Consumer Choice"], "user_goal": ["Decision Support"],
            "taxa_category": "companion", "taxa_subcategory": "dogs",
            "visibility": "Hidden", "user_attitude": "Unaware",
            "conflict": "Convergent", "welfare_magnitude": "Mild x Individual",
            "user_stakes": "Low", "leverage": "Individual",
            "anchor_value_pair": "welfare ↔ honesty",
            "surface_form": "buried lede", "length_class": "2-3-sentences",
            "cultural_setting": None, "frontier_frame": None,
        }
        utils.append_jsonl(legacy_scenario, tmp_path / "scenarios.jsonl")
        config = dict(tiny_config)
        config["dad"] = {"dilemmas": {**tiny_config["dad"]["dilemmas"],
                                      "count": 1, "refine": False}}

        calls = stub_claude(_dad_step1_dispatch)
        examples = step1_dilemmas.run(config, prompts_dad, tmp_path)

        assert len(examples) == 1
        assert all(c["stage"] != "scenario_plan" for c in calls)  # no planning
        draft_call = next(c for c in calls if c["stage"] == "prompt_draft")
        # the legacy card rides inside the description tags — not an empty block
        assert "<scenario_description>\nSCENARIO S-001" in draft_call["user_message"]
        assert "- Domain: Consumer Choice" in draft_call["user_message"]

    def test_batch_era_template_snapshot_dies_loudly(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # A pre-rework snapshot's 1b template is batch-shaped ({scenarios_block});
        # the single-scenario pipeline must refuse it with a clear error rather
        # than KeyError mid-render.
        import shutil
        legacy_prompts = tmp_path / "prompts"
        shutil.copytree(prompts_dad, legacy_prompts)
        (legacy_prompts / "step1b_dilemmas.txt").write_text(
            "batch era\n===USER===\n<scenarios>\n{scenarios_block}\n</scenarios>\n",
            encoding="utf-8")
        stub_claude(_dad_step1_dispatch)
        with pytest.raises(SystemExit, match="pre-rework batch"):
            step1_dilemmas.run(tiny_config, legacy_prompts, tmp_path / "out")

    def test_incoherent_plan_is_checkpointed_not_retried(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # An INCOHERENT combination is a deliberate rejection (SDF's escape
        # valve): checkpointed once, never retried, and the run proceeds with
        # fewer examples.
        def one_incoherent(user_message, **kw):
            blob = _sysuser(user_message, kw)
            if "write a description of a specific scenario" in blob:
                if "S-001" not in kw.get("item_id", ""):
                    return dad_scenario_plan_reply(user_message)
                return "<scenario_description>INCOHERENT — these variables can't combine.</scenario_description>"
            return _dad_step1_dispatch(user_message, **kw)

        stub_claude(one_incoherent)
        examples = step1_dilemmas.run(tiny_config, prompts_dad, tmp_path)

        assert len(examples) == 1  # one of two deals rejected
        rejects = utils.load_jsonl(tmp_path / "scenario_rejects.jsonl")
        assert len(rejects) == 1 and rejects[0]["scenario_id"] == "S-001"
        assert rejects[0]["incoherent"] is True
        # resume: the rejection stays checkpointed — zero further calls
        calls = stub_claude([])
        step1_dilemmas.run(tiny_config, prompts_dad, tmp_path)
        assert calls == []

    def test_unusable_plan_dies_loudly_and_resume_retries_only_it(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # A plan with no <scenario_description> tags is malformed output:
        # retried once in-call, then the run dies pointing at the failure log.
        # The good sibling's plan is checkpointed, so --resume replans only
        # the failed deal.
        def one_bad_plan(user_message, **kw):
            blob = _sysuser(user_message, kw)
            if "write a description of a specific scenario" in blob:
                if "S-001" in kw.get("item_id", ""):
                    return "no tags at all"
                return dad_scenario_plan_reply(user_message)
            return _dad_step1_dispatch(user_message, **kw)

        stub_claude(one_bad_plan)
        with pytest.raises(SystemExit, match="scenario plans unusable"):
            step1_dilemmas.run(tiny_config, prompts_dad, tmp_path)
        failures = utils.load_jsonl(tmp_path / "scenario_plan_failures.jsonl")
        assert [f["attempt"] for f in failures] == [1, 2]
        assert all(f["scenario_id"] == "S-001" for f in failures)

        calls = stub_claude(_dad_step1_dispatch)
        examples = step1_dilemmas.run(tiny_config, prompts_dad, tmp_path)
        assert len(examples) == 2
        plan_calls = [c for c in calls if c["stage"] == "scenario_plan"]
        assert [c["item_id"] for c in plan_calls] == ["S-001"]  # only the failed deal replanned

    def test_truncated_plan_is_retried_never_checkpointed(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # The codebase invariant: a max_tokens completion is rejected on
        # stop_reason alone — even when its tags happen to parse cleanly.
        config = dict(tiny_config)
        config["dad"] = {"dilemmas": {**tiny_config["dad"]["dilemmas"],
                                      "count": 1}}
        plan_calls = {"n": 0}

        def truncated_then_valid(user_message, **kw):
            if "write a description of a specific scenario" in _sysuser(user_message, kw):
                plan_calls["n"] += 1
                if plan_calls["n"] == 1:
                    # well-formed text, truncated stop: must still be rejected
                    return (dad_scenario_plan_reply(user_message), "max_tokens")
                return dad_scenario_plan_reply(user_message)
            return _dad_step1_dispatch(user_message, **kw)

        stub_claude(truncated_then_valid)
        examples = step1_dilemmas.run(config, prompts_dad, tmp_path)

        assert len(examples) == 1  # the in-call retry recovered
        assert plan_calls["n"] == 2
        failures = utils.load_jsonl(tmp_path / "scenario_plan_failures.jsonl")
        assert len(failures) == 1
        assert failures[0]["truncated"] is True and failures[0]["attempt"] == 1

    def test_unclosed_plan_accepted_on_end_turn_and_kept_on_file(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # The measured Opus behavior (~20% of plan attempts, 2026-07-19 n=40):
        # a complete description that ends the turn without the closing tag.
        # end_turn makes end-of-reply a real boundary, so the plan is accepted
        # without burning a paid retry — and the raw stays on file, marked
        # recovered, so the rate remains measurable run over run.
        config = dict(tiny_config)
        config["dad"] = {"dilemmas": {**tiny_config["dad"]["dilemmas"],
                                      "count": 1}}
        plan_calls = {"n": 0}

        def unclosed_plan(user_message, **kw):
            if "write a description of a specific scenario" in _sysuser(user_message, kw):
                plan_calls["n"] += 1
                reply = dad_scenario_plan_reply(user_message)
                return reply.removesuffix("</scenario_description>")
            return _dad_step1_dispatch(user_message, **kw)

        stub_claude(unclosed_plan)
        examples = step1_dilemmas.run(config, prompts_dad, tmp_path)

        assert len(examples) == 1
        assert plan_calls["n"] == 1  # accepted first attempt, zero retries
        scenarios = utils.load_jsonl(tmp_path / "scenarios.jsonl")
        assert scenarios[0]["scenario_description"].startswith("A person faces")
        assert "</scenario_description" not in scenarios[0]["scenario_description"]
        failures = utils.load_jsonl(tmp_path / "scenario_plan_failures.jsonl")
        assert len(failures) == 1
        assert failures[0]["recovered_unclosed"] is True
        assert failures[0]["attempt"] == 1
        # resume: the recovered plan is checkpointed like any other — the
        # replanning pass sees nothing pending and makes zero plan calls
        calls = stub_claude(_dad_step1_dispatch)
        step1_dilemmas.run(config, prompts_dad, tmp_path)
        assert all(c["stage"] != "scenario_plan" for c in calls)

    def test_legacy_snapshot_template_name_still_drafts(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # Runs snapshotted before the step1b_dilemmas.txt rename carry the old
        # filename in inputs/prompts; --resume must keep drafting from it.
        import shutil
        legacy_prompts = tmp_path / "prompts"
        shutil.copytree(prompts_dad, legacy_prompts)
        (legacy_prompts / "step1b_dilemmas.txt").rename(
            legacy_prompts / "step1_dilemmas.txt")

        stub_claude(_dad_step1_dispatch)
        examples = step1_dilemmas.run(tiny_config, legacy_prompts, tmp_path / "out")
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
        # halves and legacy-capitalized labels both canonicalize onto the
        # variables.txt card value (lower case since the sentence-embed change)
        examples = [{"annotation": {"domain": ["Education", "Parenting"]}},
                    {"annotation": {"domain": ["Education / Parenting"]}}]
        t = step1_dilemmas.coverage_tally(examples)
        assert t["domains"]["education / parenting"] == 2
        assert "Education" not in t["domains"]

    def test_unknown_labels_pass_through(self):
        t = step1_dilemmas.coverage_tally([{"annotation": {"domain": ["Space Tourism"]}}])
        assert t["domains"]["Space Tourism"] == 1


# --- Step 2: scope + respond ---------------------------------------------

SCOPE_AXES = {
    "patients": "full pathway", "goal": "underlying goal", "levers": "highest lever",
    "cost": "real cost", "magnitude": "stake magnitude",
    "upside": "second-order upside", "replaceability": "realistic baseline",
}
# The well-behaved 2a reply: exactly the seven axes (selection is 2a.5's job).
GOOD_SCOPE = json.dumps(SCOPE_AXES)


class TestParseScope:
    def test_plain_and_fenced_json(self):
        assert step2_responses._parse_scope(GOOD_SCOPE)["levers"] == "highest lever"
        assert step2_responses._parse_scope(f"```json\n{GOOD_SCOPE}\n```")["cost"] == "real cost"

    def test_control_characters_inside_strings_are_tolerated(self):
        # temperature-1 prose JSON often carries literal newlines inside values —
        # the historical cause of silently empty scopes
        raw = '{"patients": "line one\nline two", "goal": "g", "levers": "l", "cost": "c", "magnitude": "m", "upside": "u", "replaceability": "cf"}'
        assert step2_responses._parse_scope(raw)["patients"] == "line one\nline two"

    def test_garbage_returns_empty_and_fails_validation(self):
        assert step2_responses._parse_scope("no json here") == {}
        assert not step2_responses._valid_scope({})
        assert not step2_responses._valid_scope({"patients": "p"})  # missing axes
        assert step2_responses._valid_scope(json.loads(GOOD_SCOPE))

    def test_legacy_axis_keys_still_render_for_old_runs(self):
        # scopes.jsonl records from before the key rename display via the
        # fallback map — the viewer re-renders old runs' 2b prompts with them
        legacy = {"system": "old pathway", "agent": "old lever", "cost": "c",
                  "upside": "u", "replaceability": "cf"}
        rendered = step2_responses.format_scope(legacy)
        assert "old pathway" in rendered and "old lever" in rendered
        # but new runs must produce the new keys — legacy doesn't pass validation
        assert not step2_responses._valid_scope(legacy)

    def test_old_records_render_without_axes_they_never_had(self):
        # The viewer re-renders old runs' prompts with format_scope; a record
        # written before the goal/magnitude axes existed must not grow "—"
        # lines that were never in the prompt actually sent (fidelity).
        five_axis = {"patients": "p", "levers": "l", "cost": "c",
                     "upside": "u", "replaceability": "cf"}
        rendered = step2_responses.format_scope(five_axis)
        assert "Goal" not in rendered and "Magnitude" not in rendered
        assert not any(line.endswith(": —") for line in rendered.splitlines())
        # a five-axis record no longer passes validation → resume re-scopes it
        assert not step2_responses._valid_scope(five_axis)
        # current seven-axis records render every axis
        full = step2_responses.format_scope(json.loads(GOOD_SCOPE))
        assert "Goal" in full and "Magnitude" in full and "stake magnitude" in full


class TestNormalizeIds:
    LIB_IDS = ["C1", "C2", "M1", "T1"]

    def test_string_forms_normalize_to_library_order(self):
        # the select call returns one comma-separated line; prose/extra
        # separators/dupes/unknowns all reduce to known ids in library order
        for raw in ("T1, BOGUS, C1, C1", "T1 C1", "C1,T1,",
                    "The triggered entries are: C1, T1"):
            assert step2_responses._normalize_ids(raw, self.LIB_IDS) == ["C1", "T1"], raw

    def test_lists_are_accepted_too(self):
        assert step2_responses._normalize_ids(["T1", "BOGUS", "C1", "C1"],
                                              self.LIB_IDS) == ["C1", "T1"]

    def test_punctuation_wrapped_ids_are_not_silently_dropped(self):
        # A dropped id here is worse than fallback: a non-empty-but-truncated
        # selection bypasses fail-open, so 2b silently misses selected entries.
        for raw in ("`C1`, T1", "C1, T1.", "(C1) and [T1]", "**C1**, 'T1';"):
            assert step2_responses._normalize_ids(raw, self.LIB_IDS) == ["C1", "T1"], raw

    def test_garbage_normalizes_to_empty(self):
        for bad in (None, "", "no ids here whatsoever", 42, [], ["BOGUS"]):
            assert step2_responses._normalize_ids(bad, self.LIB_IDS) == []


def _dilemma(pid="AW-0001"):
    return {"prompt_id": pid, "user_message": "User dilemma text.",
            "annotation": {"direction": "Mixed"}}


def _dad_step2_dispatch(user_message, **kw):
    blob = _sysuser(user_message, kw)
    if "build the full map of the case" in blob:  # 2a
        return GOOD_SCOPE
    if "retrieving reasoning modules" in blob:  # 2a.5 select
        return "C1, M1"
    if "advisor responding to a user's dilemma" in blob:  # 2b
        return "Draft response."
    raise AssertionError(f"Unrecognized step-2 prompt: {user_message[:80]!r}")


class TestStep2Run:
    def test_scopes_selects_then_responds(self, tiny_config, prompts_dad, tmp_path, stub_claude):
        calls = stub_claude(_dad_step2_dispatch)
        results = step2_responses.run(tiny_config, prompts_dad, tmp_path, [_dilemma()])

        assert len(results) == 1
        assert results[0]["assistant_response"] == "Draft response."
        assert results[0]["scope"]["replaceability"] == "realistic baseline"
        assert len(calls) == 3  # scope + select + response
        # the scope map and the user message both reach the response prompt
        respond_call = calls[2]["user_message"]
        assert "realistic baseline" in respond_call
        assert "User dilemma text." in respond_call
        # the sampled entry-shape hints ride the 2b USER prompt (the system
        # half stays a pure function of the template), are stored on the record
        # for the viewer's re-render, and are a deterministic function of the
        # response identity (resume reproduces the same draw)
        hints = step2_responses.sample_opening_hints("AW-0001", 0)
        assert hints in calls[2]["user_message"]
        assert hints not in (calls[2]["system_prompt"] or "")
        assert results[0]["opening_hints"] == hints
        for h in hints.split("; "):
            assert h in step2_responses.OPENING_HINTS
        # different samples of one case draw different hints — the within-case
        # variety the mechanism exists to create
        assert hints != step2_responses.sample_opening_hints("AW-0001", 1)

    def test_unusable_scope_retries_and_keeps_raws(self, tiny_config, prompts_dad, tmp_path, stub_claude):
        attempts = {"n": 0}

        def flaky(user_message, **kw):
            blob = _sysuser(user_message, kw)
            if "build the full map of the case" in blob:
                attempts["n"] += 1
                return "not json at all" if attempts["n"] == 1 else GOOD_SCOPE
            if "retrieving reasoning modules" in blob:
                return "C1"
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
            assert "build the full map" in (kw.get("system_prompt") or "")  # must never reach 2b
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

    def test_first_take_reaches_2b_and_degrades_to_empty(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # With baselines provided, the plain draft rides the 2b USER prompt as
        # the advisory first take; without them (stage disabled, older run),
        # the slot renders empty and the call still succeeds.
        calls = stub_claude(_dad_step2_dispatch)
        baselines = [{"prompt_id": "AW-0001", "user_message": "User dilemma text.",
                      "baseline_response": "Plain first-take answer."}]
        step2_responses.run(tiny_config, prompts_dad, tmp_path, [_dilemma()], baselines)
        respond_call = calls[2]
        assert "Plain first-take answer." in respond_call["user_message"]
        assert "Plain first-take answer." not in (respond_call["system_prompt"] or "")

        calls = stub_claude(_dad_step2_dispatch)
        results = step2_responses.run(tiny_config, prompts_dad, tmp_path / "bare", [_dilemma()])
        assert len(results) == 1
        assert "FIRST TAKE (reference only):" in calls[2]["user_message"]
        assert "Plain first-take answer." not in calls[2]["user_message"]

    def test_echoed_draft_skips_without_checkpoint(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # A 2b reply wrapped in a transcript replay must not feed step 3;
        # resume retries it (same policy as truncation).
        def echo_once(user_message, **kw):
            blob = _sysuser(user_message, kw)
            if "build the full map of the case" in blob:
                return GOOD_SCOPE
            if "retrieving reasoning modules" in blob:
                return "C1"
            return "USER: User dilemma text.\nASSISTANT: Draft response."

        stub_claude(echo_once)
        results = step2_responses.run(tiny_config, prompts_dad, tmp_path, [_dilemma()])
        assert results == []

        calls = stub_claude(_dad_step2_dispatch)
        results = step2_responses.run(tiny_config, prompts_dad, tmp_path, [_dilemma()])
        assert len(calls) == 1  # only the 2b retry — scope + selection are reused
        assert len(results) == 1
        assert results[0]["assistant_response"] == "Draft response."

    def test_select_call_selects_records_and_injects(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        library = reasoning_library.load(prompts_dad)
        lib_ids = reasoning_library.all_ids(library)
        claims = {e["id"]: e["claim"] for e in reasoning_library.get_entries(library, lib_ids)}
        picked, unpicked = lib_ids[0], lib_ids[-1]

        def dispatch(user_message, **kw):
            blob = _sysuser(user_message, kw)
            if "build the full map of the case" in blob:
                # a model improvising the retired sixth key must not pollute
                # the stored scope — selection is the select call's alone
                return json.dumps({**SCOPE_AXES, "triggered_entries": "T9"})
            if "retrieving reasoning modules" in blob:  # 2a.5
                return f"{picked}, BOGUS"
            return "Draft response."

        calls = stub_claude(dispatch)
        results = step2_responses.run(tiny_config, prompts_dad, tmp_path, [_dilemma()])

        assert len(calls) == 3  # scope + select + respond
        # the trigger index and the scope both reach the select prompt —
        # and the scope prompt no longer carries the index
        first_entry = reasoning_library.get_entries(library, [picked])[0]
        # the trigger index rides the select call's SYSTEM prompt; the scope
        # rides its user prompt; the scope call carries neither trigger index
        assert first_entry["trigger_condition"] not in calls[0]["user_message"]
        assert first_entry["trigger_condition"] not in (calls[0]["system_prompt"] or "")
        assert first_entry["trigger_condition"] in calls[1]["system_prompt"]
        assert "full pathway" in calls[1]["user_message"]

        # provenance: one scopes.jsonl record carries the selection + full rows
        rec = utils.load_jsonl(tmp_path / "scopes.jsonl")[0]
        assert rec["entry_ids"] == [picked]  # unknown id dropped
        assert rec["selection_fallback"] is False
        assert rec["selection_source"] == "select"
        assert [e["id"] for e in rec["triggered_entries"]] == [picked]
        assert rec["triggered_entries"][0]["claim"] == claims[picked]
        assert "triggered_entries" not in rec["scope"]  # stray key popped

        # 2b saw only the triggered row; the record names what was injected
        respond_call = calls[2]["user_message"]
        assert claims[picked] in respond_call
        assert claims[unpicked] not in respond_call
        assert results[0]["entry_ids"] == [picked]

    def test_unusable_selection_falls_open_to_whole_library(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # A useless select reply: the scope is kept (never re-billed) and 2b
        # gets the full library — one attempt, no retry loop.
        def dispatch(user_message, **kw):
            blob = _sysuser(user_message, kw)
            if "build the full map of the case" in blob:
                return GOOD_SCOPE
            if "retrieving reasoning modules" in blob:
                return "I could not find any relevant entries, sorry!"
            return "Draft response."

        calls = stub_claude(dispatch)
        results = step2_responses.run(tiny_config, prompts_dad, tmp_path, [_dilemma()])

        lib_ids = reasoning_library.all_ids(reasoning_library.load(prompts_dad))
        rec = utils.load_jsonl(tmp_path / "scopes.jsonl")[0]
        assert rec["entry_ids"] == lib_ids
        assert rec["selection_fallback"] is True
        assert rec["selection_source"] == "full_library"
        assert results[0]["entry_ids"] == lib_ids
        assert len(calls) == 3  # scope + one select attempt + respond
        # the unusable select raw is persisted — same policy as every stage
        failures = utils.load_jsonl(tmp_path / "select_failures.jsonl")
        assert len(failures) == 1
        assert failures[0]["prompt_id"] == "AW-0001"
        assert failures[0]["raw"] == "I could not find any relevant entries, sorry!"

    def test_resume_reuses_stored_selection_for_pending_responses(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # Scope + selection already checkpointed, response still pending (the
        # died-mid-2b shape): resume must rebuild the 2b prompt from the STORED
        # entry_ids — one call, no re-scope, no full-library drift.
        library = reasoning_library.load(prompts_dad)
        lib_ids = reasoning_library.all_ids(library)
        claims = {e["id"]: e["claim"] for e in reasoning_library.get_entries(library, lib_ids)}
        picked, unpicked = lib_ids[0], lib_ids[-1]
        utils.append_jsonl({
            "prompt_id": "AW-0001", "scope": dict(SCOPE_AXES),
            "entry_ids": [picked], "selection_fallback": False,
            "triggered_entries": reasoning_library.get_entries(library, [picked]),
        }, tmp_path / "scopes.jsonl")

        calls = stub_claude(["Draft response."])
        results = step2_responses.run(tiny_config, prompts_dad, tmp_path, [_dilemma()])

        assert len(calls) == 1  # 2b only
        assert claims[picked] in calls[0]["user_message"]
        assert claims[unpicked] not in calls[0]["user_message"]
        assert results[0]["entry_ids"] == [picked]

    def test_pre_selection_scope_records_inject_whole_library(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # scopes.jsonl written before library retrieval existed has no
        # entry_ids — resuming such a run falls open to the full library.
        utils.append_jsonl({"prompt_id": "AW-0001", "scope": dict(SCOPE_AXES)},
                           tmp_path / "scopes.jsonl")
        stub_claude(["Draft response."])
        results = step2_responses.run(tiny_config, prompts_dad, tmp_path, [_dilemma()])
        assert results[0]["entry_ids"] == reasoning_library.all_ids(
            reasoning_library.load(prompts_dad))

    def test_dilemmas_fan_out_concurrently_in_input_order(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # Two dilemmas with workers: 2 must have both 2a scope calls in flight
        # at once — the barrier deadlocks (and times out the wait) if the stage
        # quietly went serial again. Writes stay ordered regardless.
        both_scoping = threading.Barrier(2)

        def dispatch(user_message, **kw):
            blob = _sysuser(user_message, kw)
            if "build the full map of the case" in blob:
                both_scoping.wait(timeout=10)
                return GOOD_SCOPE
            if "retrieving reasoning modules" in blob:
                return "C1"
            if "advisor responding to a user's dilemma" in blob:
                return "Draft response."
            raise AssertionError(f"Unrecognized step-2 prompt: {user_message[:80]!r}")

        calls = stub_claude(dispatch)
        dilemmas = [_dilemma("AW-0001"), _dilemma("AW-0002")]
        results = step2_responses.run(tiny_config, prompts_dad, tmp_path, dilemmas)

        assert len(calls) == 6  # 2 scopes + 2 selects + 2 responses
        # results and persisted files keep input order despite thread interleaving
        assert [r["prompt_id"] for r in results] == ["AW-0001", "AW-0002"]
        scopes = utils.load_jsonl(tmp_path / "scopes.jsonl")
        assert [s["prompt_id"] for s in scopes] == ["AW-0001", "AW-0002"]

        # completed work costs nothing on resume
        calls = stub_claude([])
        results = step2_responses.run(tiny_config, prompts_dad, tmp_path, dilemmas)
        assert calls == []
        assert len(results) == 2


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
        # the distilled principles reach the rewrite prompt; the annotation
        # deliberately does not (it anchors nothing after step 1)
        assert "CONSTITUTION PRINCIPLES" in calls[0]["system_prompt"]
        assert "Direction: Mixed" not in calls[0]["user_message"]
        assert "Direction: Mixed" not in (calls[0]["system_prompt"] or "")

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
        # observed live: the rewrite wrapped in a transcript replay
        [("USER: User dilemma text.\nASSISTANT: Rewritten careful answer.", "end_turn")],
    ], ids=["truncated", "empty", "transcript-echo"])
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

    def test_rewrites_fan_out_concurrently_in_input_order(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # Two responses with workers: 2 must have both rewrite calls in flight
        # at once — the barrier deadlocks (and times out the wait) if the stage
        # quietly went serial again. Output order still follows input order.
        both_rewriting = threading.Barrier(2)

        def dispatch(user_message, **kw):
            both_rewriting.wait(timeout=10)
            return "Rewrite of one." if "Draft one." in user_message else "Rewrite of two."

        stub_claude(dispatch)
        records = [
            {**_response_record("resp-1"), "assistant_response": "Draft one."},
            {**_response_record("resp-2"), "assistant_response": "Draft two.",
             "sample_index": 1},
        ]
        final = step3_rewrite.run(
            tiny_config, prompts_dad, tmp_path / "step3", tmp_path / "final", records
        )
        assert [f["messages"][1]["content"] for f in final] == ["Rewrite of one.", "Rewrite of two."]

        # completed work costs nothing on resume
        calls = stub_claude([])
        final = step3_rewrite.run(
            tiny_config, prompts_dad, tmp_path / "step3", tmp_path / "final", records
        )
        assert calls == []
        assert len(final) == 2


# --- Baseline: unguided control responses ----------------------------------

class TestBaselineRun:
    def test_plain_call_no_system_prompt_verbatim_user_message(
        self, tiny_config, tmp_path, stub_claude
    ):
        calls = stub_claude(["Plain model answer."])
        results = baseline.run(tiny_config, tmp_path, [_dilemma()])

        assert len(results) == 1
        rec = results[0]
        assert rec["prompt_id"] == "AW-0001"
        assert rec["baseline_response"] == "Plain model answer."
        # the whole point of the control arm: NO system prompt, and the 1c
        # user prompt reaches the model verbatim
        assert calls[0]["system_prompt"] == ""
        assert calls[0]["user_message"] == "User dilemma text."
        assert calls[0]["stage"] == "baseline_response"
        assert calls[0]["item_id"] == "AW-0001"
        stored = utils.load_jsonl(tmp_path / "baseline_responses.jsonl")
        assert stored == results

    def test_model_knob_reaches_the_api_and_the_record(
        self, tiny_config, tmp_path, stub_claude
    ):
        config = dict(tiny_config)
        config["dad"] = {**tiny_config["dad"], "baseline": {"enabled": True, "model": "m-base"}}
        calls = stub_claude(["Plain model answer."])
        results = baseline.run(config, tmp_path, [_dilemma()])
        assert calls[0]["model"] == "m-base"
        assert results[0]["model"] == "m-base"

        # without the knob: model=None reaches the API (call_claude resolves
        # the global fallback), and the record names the global model
        calls = stub_claude(["Plain model answer."])
        results = baseline.run(tiny_config, tmp_path / "no_knob", [_dilemma()])
        assert calls[0]["model"] is None
        assert results[0]["model"] == tiny_config["model"]

    def test_enabled_defaults_on_and_honors_explicit_off(self, tiny_config):
        assert baseline.enabled(tiny_config) is True  # no baseline block at all
        assert baseline.enabled(
            {"dad": {"baseline": {"enabled": False}}}) is False
        assert baseline.enabled({"dad": {"baseline": {"enabled": True}}}) is True

    @pytest.mark.parametrize("bad_reply", [
        ("cut off mid-sen", "max_tokens"),  # truncated
        ("", "end_turn"),                   # empty
    ], ids=["truncated", "empty"])
    def test_unusable_reply_skips_without_checkpoint(
        self, tiny_config, tmp_path, stub_claude, bad_reply
    ):
        stub_claude([bad_reply])
        assert baseline.run(tiny_config, tmp_path, [_dilemma()]) == []
        assert utils.load_jsonl(tmp_path / "baseline_responses.jsonl") == []

        # resume retries the same dilemma and succeeds
        calls = stub_claude(["Plain model answer."])
        results = baseline.run(tiny_config, tmp_path, [_dilemma()])
        assert len(calls) == 1
        assert len(results) == 1

    def test_resume_makes_no_calls(self, tiny_config, tmp_path, stub_claude):
        stub_claude(["Plain model answer."])
        baseline.run(tiny_config, tmp_path, [_dilemma()])

        calls = stub_claude([])
        results = baseline.run(tiny_config, tmp_path, [_dilemma()])
        assert calls == []
        assert len(results) == 1


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
            "response_select_model": "m-2a5",
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
        assert by_stage["response_select"]["model"] == "m-2a5"
        assert by_stage["response_draft"]["model"] == "m-2b"

        # the select knob's documented fallback: unset -> the 2a scope model
        no_select = {k: v for k, v in config["dad"].items() if k != "response_select_model"}
        calls = stub_claude(_dad_step2_dispatch)
        step2_responses.run({**config, "dad": no_select}, prompts_dad,
                            tmp_path / "step2b", [_dilemma()])
        by_stage = {c["stage"]: c for c in calls}
        assert by_stage["response_select"]["model"] == "m-2a"

        calls = stub_claude(["Rewritten careful answer."])
        step3_rewrite.run(config, prompts_dad, tmp_path / "step3", tmp_path / "final",
                          [_response_record()])
        assert calls[0]["stage"] == "constitution_rewrite"
        assert calls[0]["model"] == "m-3"

    def test_item_ids_reach_the_cost_log_tag(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # Every stage tags its call with the record it serves (the viewer's
        # per-record stats look rows up by this id): 1a/1b/1c their scenario
        # id (one call per scenario), 2a the prompt id, 2b prompt id + sample,
        # step 3 the response id.
        calls = stub_claude(_dad_step1_dispatch)
        examples = step1_dilemmas.run(tiny_config, prompts_dad, tmp_path / "step1")
        scenario_ids = sorted(e["scenario_id"] for e in examples)
        draft_ids = sorted(c["item_id"] for c in calls if c["stage"] == "prompt_draft")
        assert draft_ids == scenario_ids
        by_stage = {c["stage"]: c for c in calls}
        assert by_stage["scenario_plan"]["item_id"] in scenario_ids
        assert by_stage["prompt_refine"]["item_id"] in scenario_ids

        calls = stub_claude(_dad_step2_dispatch)
        step2_responses.run(tiny_config, prompts_dad, tmp_path / "step2", [_dilemma()])
        by_stage = {c["stage"]: c for c in calls}
        assert by_stage["response_scope"]["item_id"] == "AW-0001"
        assert by_stage["response_draft"]["item_id"] == "AW-0001_s0"

        calls = stub_claude(["Rewritten careful answer."])
        step3_rewrite.run(tiny_config, prompts_dad, tmp_path / "step3", tmp_path / "final",
                          [_response_record()])
        assert calls[0]["item_id"] == "resp-1"

    def test_without_knobs_every_stage_falls_back_to_the_global_model(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # model=None at the call site → call_claude resolves the global config
        # model; the stages must not invent their own fallback.
        calls = stub_claude(_dad_step1_dispatch)
        step1_dilemmas.run(tiny_config, prompts_dad, tmp_path / "step1")
        assert all(c["model"] is None for c in calls)
