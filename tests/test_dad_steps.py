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

from conftest import dad_scenario_reply
from dad_pipeline import baseline, reasoning_library, step1_dilemmas, step2_responses, step3_rewrite
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

    def test_length_classes_dealt_to_exact_shares(self):
        # At n=40 every share is integral, so counts are exact by construction —
        # derived from the sampler's own table, never hardcoded.
        batch = step1_dilemmas.generate_scenarios(40, random.Random(1))
        counts = {}
        for p in batch:
            counts[p["length_class"]] = counts.get(p["length_class"], 0) + 1
        expected = {label: round(share * 40)
                    for label, share, _, _ in step1_dilemmas._LENGTH_CLASSES}
        assert counts == expected
        # no positional truncation bias: the tail share must be reachable at
        # small n (the pre-fix _share_deck could never deal it at n=5)
        tail = step1_dilemmas._LENGTH_CLASSES[-1][0]
        assert any(p["length_class"] == tail
                   for seed in range(12)
                   for p in step1_dilemmas.generate_scenarios(5, random.Random(seed)))

    def test_cultural_setting_on_a_minority_slice_without_repeats(self):
        batch = step1_dilemmas.generate_scenarios(40, random.Random(1))
        dealt = [p["cultural_setting"] for p in batch if p["cultural_setting"]]
        assert len(dealt) == round(step1_dilemmas._CULTURAL_SETTING_FRACTION * 40)
        assert set(dealt) <= set(step1_dilemmas._CULTURAL_SETTINGS)
        assert len(set(dealt)) == len(dealt), "a setting repeated before the deck cycled"
        assert any(p["cultural_setting"] is None for p in batch)

    def test_format_scenario_renders_length_always_and_culture_conditionally(self):
        p = step1_dilemmas.generate_scenarios(1, random.Random(3))[0]
        p["cultural_setting"] = "Jain tradition"
        card = step1_dilemmas.format_scenario(p)
        assert f"- Length: {step1_dilemmas._LENGTH_TEXT[p['length_class']]}" in card
        assert "- Cultural setting: Jain tradition" in card
        p["cultural_setting"] = None
        assert "Cultural setting" not in step1_dilemmas.format_scenario(p)

    def test_length_ok_bands_are_lenient_and_fail_open_for_legacy(self):
        assert not step1_dilemmas._length_ok("way too short", "ramble")
        assert not step1_dilemmas._length_ok("x" * 5000, "2-3-sentences")
        assert step1_dilemmas._length_ok("A blunt ask about the corridor?", "2-3-sentences")
        assert step1_dilemmas._length_ok("x" * 1200, "ramble")
        # scenarios from runs that predate the axis carry no class: no gate
        assert step1_dilemmas._length_ok("anything", None)
        assert step1_dilemmas._length_ok("anything", "unknown-class")


# --- Step 1b/1c: drafting via run() --------------------------------------

def _sysuser(user_message, kw):
    """Every DAD template splits into system + user, so the role marker lives
    in system_prompt while the payload (scenarios, scope, library, draft)
    stays in the user message. Dispatchers match against both halves."""
    return (kw.get("system_prompt") or "") + "\n" + user_message


def _dad_step1_dispatch(user_message, **kw):
    blob = _sysuser(user_message, kw)
    if "first-attempt user prompts" in blob:  # 1b batch draft
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
            assert e["draft_user_message"].startswith(
                f"Drafted user message for {e['scenario_id']}.")
            assert e["taxa_subcategory"]
            assert e["length_class"] in step1_dilemmas._LENGTH_TEXT  # stamped
            assert "scenario_deviations" not in e
            # stable content-keyed ids assigned alongside the per-run ids
            assert e["scenario_gid"].startswith("S-")
            assert e["prompt_gid"].startswith("P-")
        # persisted artifacts: scenarios (1a), dilemmas (1b/1c), refinements log,
        # and the Part-4 checklist report (previously terminal-only)
        assert len(utils.load_jsonl(tmp_path / "scenarios.jsonl")) == 2
        assert all(s["scenario_gid"].startswith("S-")
                   for s in utils.load_jsonl(tmp_path / "scenarios.jsonl"))
        assert (tmp_path / "id_registry.json").exists()  # registry persisted
        assert len(utils.load_jsonl(tmp_path / "dilemmas.jsonl")) == 2
        assert len(utils.load_jsonl(tmp_path / "refinements.jsonl")) == 2
        saved = (tmp_path / "checklist.txt").read_text()
        assert saved.startswith("Batch checklist (spec Part 4):")
        assert "load-bearing rule" in saved
        # 1 batch call + 2 refine calls
        assert len(calls) == 3
        # the 1b annotation reaches the 1c prompt — minus the claims lines
        refine_call = next(c["user_message"] for c in calls
                           if "editor of dilemma prompts" in c["system_prompt"])
        assert "test patients in context" in refine_call
        assert "a load-bearing claim" not in refine_call

    def test_malformed_1b_annotation_is_normalized_before_the_1c_prompt(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # The model may ignore the "(list)" typing and return a bare string for
        # a list field, or a non-dict anatomy. The 1c annotation block must be
        # built from the NORMALIZED annotation, or ', '.join() silently
        # character-joins the string into garbage inside the paid refine call.
        config = dict(tiny_config)
        config["dad"] = {"dilemmas": {**tiny_config["dad"]["dilemmas"],
                                      "count": 1, "batch_size": 1}}

        def malformed(user_message, **kw):
            if "editor of dilemma prompts" in _sysuser(user_message, kw):  # 1c refine
                return json.dumps({"prompt": "Refined user message.", "notes": "n"})
            reply = json.loads(dad_scenario_reply(user_message))
            reply[0]["annotation"]["domain"] = "Education / Youth"  # bare string, not list
            reply[0]["annotation"]["dilemma_anatomy"] = "not a dict"
            return json.dumps(reply)

        calls = stub_claude(malformed)
        examples = step1_dilemmas.run(config, prompts_dad, tmp_path)

        assert len(examples) == 1
        refine_call = next(c["user_message"] for c in calls
                           if "editor of dilemma prompts" in c["system_prompt"])
        assert "Domain: Education / Youth" in refine_call
        assert "E, d, u" not in refine_call  # the character-join failure mode

    def test_unusable_refine_is_retried_once_and_raw_kept(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        config = dict(tiny_config)
        config["dad"] = {"dilemmas": {**tiny_config["dad"]["dilemmas"],
                                      "count": 1, "batch_size": 1}}
        refine_calls = {"n": 0}

        def flaky_refine(user_message, **kw):
            if "editor of dilemma prompts" in _sysuser(user_message, kw):
                refine_calls["n"] += 1
                if refine_calls["n"] == 1:
                    return "not json at all"
                return json.dumps({"prompt": "Refined user message.", "notes": "n"})
            return dad_scenario_reply(user_message)

        calls = stub_claude(flaky_refine)
        examples = step1_dilemmas.run(config, prompts_dad, tmp_path)

        assert len(calls) == 3  # 1 batch + 2 refine attempts
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
                                      "count": 1, "batch_size": 1}}

        def bad_refine(user_message, **kw):
            if "editor of dilemma prompts" in _sysuser(user_message, kw):
                return "still not json"
            return dad_scenario_reply(user_message)

        calls = stub_claude(bad_refine)
        examples = step1_dilemmas.run(config, prompts_dad, tmp_path)

        assert len(calls) == 3  # 1 batch + MAX_REFINE_ATTEMPTS refine attempts
        e = examples[0]
        assert e["refine_failed"] is True
        assert e["user_message"].startswith("Drafted user message")  # 1b draft shipped
        assert "draft_user_message" not in e  # only set when refine succeeded
        assert len(utils.load_jsonl(tmp_path / "refine_failures.jsonl")) == 2
        assert utils.load_jsonl(tmp_path / "refinements.jsonl") == []

    def test_length_violating_draft_is_retried_not_checkpointed(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        # seed 1 deals a single scenario whose length class has a nonzero lower
        # band (precondition asserted below), so an egregiously short draft must
        # be rejected and re-drawn — and the reject is a retry, not a strike.
        config = dict(tiny_config)
        config["dad"] = {"dilemmas": {**tiny_config["dad"]["dilemmas"],
                                      "count": 1, "batch_size": 1,
                                      "scenario_seed": 1, "refine": False}}
        scen = step1_dilemmas.generate_scenarios(1, random.Random(1))[0]
        lo, _hi = step1_dilemmas._LENGTH_BANDS[scen["length_class"]]
        assert lo > 0, "precondition: pick a seed whose class has a lower band"
        batch_calls = {"n": 0}

        def short_then_valid(user_message, **kw):
            batch_calls["n"] += 1
            reply = json.loads(dad_scenario_reply(user_message))
            if batch_calls["n"] == 1:
                reply[0]["prompt"] = "Too short."  # egregious band miss
            return json.dumps(reply)

        calls = stub_claude(short_then_valid)
        examples = step1_dilemmas.run(config, prompts_dad, tmp_path)

        assert len(calls) == 2  # rejected draft cost one call, then the retry
        assert len(examples) == 1
        assert examples[0]["length_class"] == scen["length_class"]
        assert step1_dilemmas._length_ok(examples[0]["user_message"],
                                         scen["length_class"])
        # a length reject is not a parse failure: nothing lands in draft_failures
        assert utils.load_jsonl(tmp_path / "draft_failures.jsonl") == []

    def test_unusable_batch_raw_is_persisted(
        self, tiny_config, prompts_dad, tmp_path, stub_claude
    ):
        config = dict(tiny_config)
        config["dad"] = {"dilemmas": {**tiny_config["dad"]["dilemmas"],
                                      "count": 1, "batch_size": 1, "refine": False}}
        batch_calls = {"n": 0}

        def flaky_batch(user_message, **kw):
            batch_calls["n"] += 1
            return "no json here" if batch_calls["n"] == 1 else dad_scenario_reply(user_message)

        stub_claude(flaky_batch)
        examples = step1_dilemmas.run(config, prompts_dad, tmp_path)

        assert len(examples) == 1  # retry recovered
        failures = utils.load_jsonl(tmp_path / "draft_failures.jsonl")
        assert len(failures) == 1
        assert failures[0]["raw"] == "no json here" and failures[0]["attempt"] == 1

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

SCOPE_AXES = {
    "patients": "full pathway", "goal": "underlying goal", "levers": "highest lever",
    "cost": "real cost", "magnitude": "stake magnitude",
    "upside": "second-order upside", "counterfactual": "realistic baseline",
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
        raw = '{"patients": "line one\nline two", "goal": "g", "levers": "l", "cost": "c", "magnitude": "m", "upside": "u", "counterfactual": "cf"}'
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
                  "upside": "u", "counterfactual": "cf"}
        rendered = step2_responses.format_scope(legacy)
        assert "old pathway" in rendered and "old lever" in rendered
        # but new runs must produce the new keys — legacy doesn't pass validation
        assert not step2_responses._valid_scope(legacy)

    def test_old_records_render_without_axes_they_never_had(self):
        # The viewer re-renders old runs' prompts with format_scope; a record
        # written before the goal/magnitude axes existed must not grow "—"
        # lines that were never in the prompt actually sent (fidelity).
        five_axis = {"patients": "p", "levers": "l", "cost": "c",
                     "upside": "u", "counterfactual": "cf"}
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
    if "doing retrieval for a response" in blob:  # 2a.5 select
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
        assert results[0]["scope"]["counterfactual"] == "realistic baseline"
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
            if "doing retrieval for a response" in blob:
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
            if "doing retrieval for a response" in blob:
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
            if "doing retrieval for a response" in blob:  # 2a.5
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
            if "doing retrieval for a response" in blob:
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
            if "doing retrieval for a response" in blob:
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
        # per-record stats look rows up by this id): 1b logs the batch's
        # scenario ids comma-joined, 1c its scenario id, 2a the prompt id,
        # 2b prompt id + sample, step 3 the response id.
        calls = stub_claude(_dad_step1_dispatch)
        examples = step1_dilemmas.run(tiny_config, prompts_dad, tmp_path / "step1")
        scenario_ids = sorted(e["scenario_id"] for e in examples)
        by_stage = {c["stage"]: c for c in calls}
        assert by_stage["prompt_draft"]["item_id"] == ",".join(scenario_ids)
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
