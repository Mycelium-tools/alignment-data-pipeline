"""Tests for evals/audit_dad.py — the offline prompt-corpus audit.

Fully offline (the audit makes no API calls). Each check is driven over a small
synthetic set of step-1 records and asserted on the returned ``report`` dict, in
the style of tests/test_openings_dad.py. Frontier-frame and cultural-setting
values are taken from the real axis definitions so the checks stay pinned to the
strings the pipeline actually deals.
"""

import json

import pytest

from dad_pipeline import compose_scenarios
from evals import audit_dad
from shared import utils

# Frontier frames now live in prompts/dad/variables.txt (the 2026-07 matrix
# refactor); derive them the way the composer does, excluding the none value.
_AXIS_VALUES, _ = compose_scenarios.load_axes()
_FRONTIER_FRAMES = tuple(
    v for v in _AXIS_VALUES["frontier_frame"]
    if v != compose_scenarios.resolve_value(
        _AXIS_VALUES["frontier_frame"],
        compose_scenarios.NONE_PREFIXES["frontier_frame"]))

# A real "space / off-world" frontier frame and its expected in-text traces.
_SPACE_FRAME = next(f for f in _FRONTIER_FRAMES if "space or off-world" in f)


# --- skeletons ------------------------------------------------------------

def test_skeletons_flag_produce_by_deadline_set():
    records = [
        {"prompt_id": "AW-0001", "user_message": "I've got a feature due friday and I can't decide."},
        {"prompt_id": "AW-0002", "user_message": "I've been asked to write up the culling protocol."},
        {"prompt_id": "AW-0003",
         "user_message": "There are two paths in front of me: one is to keep the contract or sell."},
        {"prompt_id": "AW-0004", "user_message": "My cat scratched the couch and I wonder about declawing."},
    ]
    report = {}
    audit_dad.audit_skeletons(records, report)
    s = report["skeletons"]
    assert s["n"] == 4
    # AW-0001 (deadline) + AW-0002 (asked-to-produce) = 2 of 4
    assert s["produce_by_deadline"] == 2
    assert s["produce_by_deadline_share"] == 0.5
    assert s["families"]["other"] == 1
    assert "two-paths-choice" in s["families"]


def test_skeletons_clean_set_is_mostly_other():
    records = [
        {"prompt_id": "AW-0001", "user_message": "My neighbour's dog barks and I don't know how to raise it."},
        {"prompt_id": "AW-0002", "user_message": "We keep bees and I'm curious whether the hive is crowded."},
    ]
    report = {}
    audit_dad.audit_skeletons(records, report)
    assert report["skeletons"]["produce_by_deadline"] == 0
    assert report["skeletons"]["families"] == {"other": 2}


# --- openers & closers ----------------------------------------------------

def test_openers_and_closers_detect_repeats():
    records = [
        {"prompt_id": "AW-0001", "user_message": "I have been running this shelter for years. Am I overthinking this?"},
        {"prompt_id": "AW-0002", "user_message": "I have been asked to weigh in on the cull. Am I overthinking this?"},
        {"prompt_id": "AW-0003", "user_message": "My neighbour keeps chickens in a small coop."},
    ]
    report = {}
    audit_dad.audit_openers_closers(records, report)
    oc = report["openers_closers"]
    assert oc["n"] == 3
    assert oc["distinct_openers"] == 2          # "i have been" shared by two
    assert oc["repeated_openers"] == {"i have been": 2}
    assert oc["repeated_closers"] == {"am i overthinking": 2}


# --- lexical diversity (shared phrases + style Vendi) --------------------

def test_lexical_diversity_surfaces_over_represented_phrase():
    # a phrase planted in 3 of 4 prompts should be the top shared n-gram, with
    # no hardcoded tic list — the scan finds it from document frequency alone
    shared = "can you help me think this through"
    records = [
        {"prompt_id": "AW-0001", "user_message": f"I run a small dairy. {shared}?"},
        {"prompt_id": "AW-0002", "user_message": f"My lab keeps mice in bare cages. {shared}?"},
        {"prompt_id": "AW-0003", "user_message": f"We cull deer every autumn. {shared}?"},
        {"prompt_id": "AW-0004", "user_message": "Totally unrelated wording about octopus farming economics."},
    ]
    report = {}
    audit_dad.audit_lexical_diversity(records, report)
    ld = report["lexical_diversity"]
    assert ld["n"] == 4
    top4 = dict(ld["top_shared"]["4"])
    assert top4.get("can you help me") == 3          # found the planted phrase, shared by 3/4
    assert ld["max_prevalence"] == 0.75              # 3/4
    assert 1.0 <= ld["style_vendi_ratio"] * ld["n"] <= ld["n"]  # a valid Vendi in [1, n]


def test_lexical_diversity_handles_tiny_corpus():
    report = {}
    audit_dad.audit_lexical_diversity([{"user_message": "only one"}], report)
    assert report["lexical_diversity"] == {"n": 1}


# --- unrealized dealt details --------------------------------------------

def test_unrealized_frontier_flags_prompt_with_no_lexical_trace():
    records = [
        # realized: "station" is a space-frame keyword
        {"prompt_id": "AW-0001", "frontier_frame": _SPACE_FRAME,
         "user_message": "We're deciding whether to keep the fur unit going on the station."},
        # unrealized: nothing in the text signals the off-world setting
        {"prompt_id": "AW-0002", "frontier_frame": _SPACE_FRAME,
         "user_message": "My daughter wants to raise crickets in the garage and I'm unsure it's humane."},
    ]
    report = {}
    audit_dad.audit_unrealized_details(records, report)
    u = report["unrealized_frontier"]
    assert u["n_dealt"] == 2 and u["n_checked"] == 2
    assert u["unrealized_ids"] == ["AW-0002"]
    assert u["unrealized_share"] == 0.5


def test_unrealized_frontier_counts_unmapped_frames_separately():
    records = [
        {"prompt_id": "AW-0001", "frontier_frame": "some brand-new frame with no keyword map",
         "user_message": "A plain message about a farm decision."},
    ]
    report = {}
    audit_dad.audit_unrealized_details(records, report)
    u = report["unrealized_frontier"]
    assert u["n_dealt"] == 1 and u["n_checked"] == 0
    assert u["unmapped"] == 1 and u["unrealized_ids"] == []


def test_unrealized_frontier_calm_when_none_dealt():
    report = {}
    audit_dad.audit_unrealized_details(
        [{"prompt_id": "AW-0001", "user_message": "no frame here"}], report)
    assert report["unrealized_frontier"] == {"n_dealt": 0}


# --- locale / taxa plausibility ------------------------------------------

def test_locale_taxa_flags_cold_climate_practice_in_warm_setting():
    records = [
        {"prompt_id": "AW-0001", "taxa_subcategory": "fur animals (mink, foxes)",
         "cultural_setting": "the Caribbean", "user_message": "..."},
        {"prompt_id": "AW-0002", "taxa_subcategory": "fur animals (mink, foxes)",
         "cultural_setting": "Nordic countries", "user_message": "..."},   # plausible
        {"prompt_id": "AW-0003", "taxa_subcategory": "pigs",
         "cultural_setting": "the Caribbean", "user_message": "..."},       # unrelated
    ]
    report = {}
    audit_dad.audit_locale_taxa(records, report)
    lt = report["locale_taxa"]
    assert lt["n_flagged"] == 1
    assert lt["flags"][0]["id"] == "AW-0001"
    assert lt["flags"][0]["cultural_setting"] == "the Caribbean"


# --- input resolution & length delegation --------------------------------

def _write_run(tmp_path, records):
    run = tmp_path / "run"
    (run / "step1").mkdir(parents=True)
    for r in records:
        utils.append_jsonl(r, run / "step1" / "dilemmas.jsonl")
    return run


def test_resolve_input_run_dir_vs_bare_file(tmp_path):
    records = [{"prompt_id": "AW-0001", "user_message": "hi"}]
    run = _write_run(tmp_path, records)

    recs, report_dir, run_dir = audit_dad.resolve_input(str(run))
    assert len(recs) == 1 and report_dir == run / "audit" and run_dir == run

    bare = run / "step1" / "dilemmas.jsonl"
    recs2, report_dir2, run_dir2 = audit_dad.resolve_input(str(bare))
    assert len(recs2) == 1 and report_dir2 == bare.parent / "audit" and run_dir2 is None


def _write_gid_run(tmp_path):
    """Run dir whose step1 dilemmas carry prompt/scenario gids and step3
    rewrites carry response/example gids — the two sources _gid_map merges."""
    run = _write_run(tmp_path, [
        {"prompt_id": "AW-0001", "user_message": "u1",
         "prompt_gid": "P-0150", "scenario_gid": "S-0140"},
        {"prompt_id": "AW-0002", "user_message": "u2",
         "prompt_gid": "P-0151", "scenario_gid": "S-0141"},
    ])
    (run / "step3").mkdir()
    for pid, rgid, egid in [("AW-0001", "R-0203", "E-0174"),
                            ("AW-0002", "R-0204", "E-0175")]:
        utils.append_jsonl(
            {"prompt_id": pid, "record_id": pid, "response_gid": rgid, "example_gid": egid},
            run / "step3" / "rewrites.jsonl")
    return run


def test_gid_map_bridges_prompt_id_to_stable_gids(tmp_path):
    run = _write_gid_run(tmp_path)
    m = audit_dad._gid_map(run)
    assert m["AW-0001"] == {"prompt": "P-0150", "scenario": "S-0140",
                            "response": "R-0203", "example": "E-0174"}
    report = {}
    audit_dad.resolve_gids(run, report)
    assert report["gid_map"] == m
    # display prefers the requested kind, defaulting to the response gid
    assert audit_dad._disp_id(report, "AW-0002") == "R-0204"
    assert audit_dad._disp_id(report, "AW-0002", "example") == "E-0175"
    assert audit_dad._disp_id(report, "AW-0002", "prompt") == "P-0151"


def test_gid_map_empty_and_disp_id_falls_back_for_pre_gid_runs(tmp_path):
    assert audit_dad._gid_map(None) == {}
    # a run with dilemmas but no gids anywhere: _disp_id returns the prompt_id
    run = _write_run(tmp_path, [{"prompt_id": "AW-0009", "user_message": "u"}])
    report = {}
    audit_dad.resolve_gids(run, report)
    assert report["gid_map"] == {"AW-0009": {}}
    assert audit_dad._disp_id(report, "AW-0009") == "AW-0009"


def test_response_lengths_tag_gids_inline(tmp_path):
    run = _write_run_with_responses(tmp_path, [("AW-0001", "x" * 300, "y" * 100)])
    # give the rewrite record its stable gids (the base helper omits them)
    (run / "step3" / "rewrites.jsonl").write_text(
        json.dumps({"record_id": "rec-0", "prompt_id": "AW-0001", "response_id": "AW-0001_s0",
                    "response_gid": "R-0201", "example_gid": "E-0172",
                    "rewritten_response": "x" * 300}) + "\n", encoding="utf-8")
    report = {}
    audit_dad.resolve_gids(run, report)
    audit_dad.audit_response_lengths(run, report)
    entry = report["response_lengths"]["per_case"]["AW-0001"]
    assert entry["response_gid"] == "R-0201" and entry["example_gid"] == "E-0172"
    # keyed by prompt_id still (the downstream join key), gids ride inline
    assert entry["pipeline"] == 300 and entry["plain"] == 100


def test_carry_forward_retags_paid_per_case_with_current_gids(tmp_path):
    run = _write_gid_run(tmp_path)
    report = {}
    audit_dad.resolve_gids(run, report)
    # a prior report whose paid per-case data predates gid tagging
    old = {"moral_patient_reasons": {"per_case": {"AW-0001": {"pipeline": {"reasons": []}}}},
           "moves": {"per_case": {"AW-0002": {"stance": {}}}},
           "sections": []}
    assert audit_dad.carry_forward_reasons(old, report) is True
    assert report["moral_patient_reasons"]["per_case"]["AW-0001"]["response_gid"] == "R-0203"
    assert report["moves"]["per_case"]["AW-0002"]["example_gid"] == "E-0175"


def test_library_selection_reports_sizes_and_fallbacks(tmp_path):
    from dad_pipeline import reasoning_library
    total = len(reasoning_library.all_ids(reasoning_library.load("prompts/dad")))

    run = _write_run(tmp_path, [{"prompt_id": "AW-0001", "user_message": "hi"}])
    (run / "step2").mkdir()
    scopes = [
        {"prompt_id": "AW-0001", "entry_ids": ["C1", "M1", "T3"], "selection_source": "select"},
        {"prompt_id": "AW-0002", "entry_ids": list(map(str, range(total))),  # fail-open
         "selection_source": "full_library"},
        {"prompt_id": "AW-0003"},  # pre-selection record: no entry_ids, skipped
    ]
    for s in scopes:
        utils.append_jsonl(s, run / "step2" / "scopes.jsonl")

    report = {}
    audit_dad.audit_library_selection(run, report)
    ls = report["library_selection"]
    assert ls["n"] == 2 and ls["library_size"] == total
    assert ls["sizes"] == [3, total]
    assert ls["fallbacks"] == 1
    assert ls["per_case"] == {"AW-0001": 3, "AW-0002": total}


def test_library_selection_detail_uses_prompt_gids_when_available(tmp_path):
    run = _write_run(tmp_path, [
        {"prompt_id": "AW-0001", "prompt_gid": "P-0042", "user_message": "hi"}])
    (run / "step2").mkdir()
    for s in ({"prompt_id": "AW-0001", "entry_ids": ["C1"], "selection_source": "select"},
              {"prompt_id": "AW-0002", "entry_ids": ["C1", "M1"], "selection_source": "select"}):
        utils.append_jsonl(s, run / "step2" / "scopes.jsonl")

    report = {}
    audit_dad.audit_library_selection(run, report)
    # labeled by the stable prompt gid where one exists, per-run id otherwise
    assert report["sections"][0]["detail"] == ["P-0042 1, AW-0002 2"]
    # per_case stays keyed by prompt_id — it is the join key downstream
    assert report["library_selection"]["per_case"] == {"AW-0001": 1, "AW-0002": 2}


def test_library_selection_calm_without_step2(tmp_path):
    run = _write_run(tmp_path, [{"prompt_id": "AW-0001", "user_message": "hi"}])
    report = {}
    audit_dad.audit_library_selection(run, report)
    assert report["library_selection"] == {"n": 0}
    report2 = {}
    audit_dad.audit_library_selection(None, report2)  # bare-file input
    assert "library_selection" not in report2


def test_jargon_scan_counts_and_compares_to_baseline(tmp_path):
    # pipeline responses carry insider vocab; the plain baseline carries less.
    # Built through the step3 join — jargon scans the same prompt-keyed
    # population as every other response section.
    run = _write_run_with_responses(tmp_path, [
        ("AW-0001", "The counterfactual moral weight here is high; valenced experience matters.",
         "A plain kind answer with no jargon."),
        ("AW-0002", "Consider the counterfactual and the objective function.",
         "Weigh the counterfactual once."),
    ])
    report = {}
    audit_dad.audit_jargon(run, report)
    j = report["jargon"]
    assert j["n"] == 2
    assert j["pipeline_terms"]["counterfactual"] == 2   # once per response
    assert j["pipeline_terms"]["moral weight"] == 1
    assert j["pipeline_terms"]["valenced"] == 1
    assert j["pipeline_terms"]["objective function"] == 1
    assert j["total"] == 5
    # plain baseline had one "counterfactual"; pipeline adds the rest
    assert j["plain_terms"]["counterfactual"] == 1
    assert j["pipeline_excess_vs_plain"] == 4


def test_jargon_scan_avoids_plain_word_false_positives(tmp_path):
    run = _write_run_with_responses(tmp_path, [
        ("AW-0001", "Only marginally worse, a neglected corner, the sentient dog suffered.",
         None),
    ])
    report = {}
    audit_dad.audit_jargon(run, report)
    # "marginally", "neglected", "sentient", "suffered" are plain usage — not flagged
    assert report["jargon"]["total"] == 0


def test_jargon_scan_calm_without_final_corpus(tmp_path):
    run = _write_run(tmp_path, [{"prompt_id": "AW-0001", "user_message": "hi"}])
    report = {}
    audit_dad.audit_jargon(run, report)
    assert report["jargon"] == {"n": 0}
    report2 = {}
    audit_dad.audit_jargon(None, report2)
    assert "jargon" not in report2


def test_audit_lengths_delegates_for_run_dir_and_skips_for_bare(tmp_path):
    run = _write_run(tmp_path, [
        {"prompt_id": "AW-0001", "length_class": "2-3-sentences", "user_message": "Short. Two."},
    ])
    report = {}
    audit_dad.audit_lengths(run, report)
    assert report["prompt_lengths"]["n"] == 1

    report2 = {}
    audit_dad.audit_lengths(None, report2)
    assert "prompt_lengths" not in report2


# --- response lengths & moral-patient reasons (vs plain baseline) ----------

def _write_run_with_responses(tmp_path, pairs):
    """Run dir with final corpus + step3 rewrites (the record_id→prompt_id
    join) + baseline arm. pairs: [(prompt_id, pipeline_text, plain_text|None)]."""
    run = _write_run(tmp_path, [{"prompt_id": p, "user_message": f"dilemma {p}"}
                                for p, _, _ in pairs])
    (run / "final").mkdir()
    (run / "step3").mkdir()
    (run / "baseline").mkdir()
    for i, (pid, pipe_text, plain_text) in enumerate(pairs):
        rid = f"rec-{i}"
        utils.append_jsonl({"record_id": rid, "messages": [
            {"role": "user", "content": "u"}, {"role": "assistant", "content": pipe_text}]},
            run / "final" / "dad_corpus.jsonl")
        utils.append_jsonl({"record_id": rid, "prompt_id": pid, "response_id": f"{pid}_s0",
                            "rewritten_response": pipe_text},
                           run / "step3" / "rewrites.jsonl")
        if plain_text is not None:
            utils.append_jsonl({"prompt_id": pid, "baseline_response": plain_text},
                               run / "baseline" / "baseline_responses.jsonl")
    return run


def test_response_lengths_compare_to_baseline(tmp_path):
    run = _write_run_with_responses(tmp_path, [
        ("AW-0001", "x" * 300, "y" * 100),
        ("AW-0002", "x" * 500, "y" * 200),
    ])
    report = {}
    audit_dad.audit_response_lengths(run, report)
    rl = report["response_lengths"]
    assert rl["per_case"]["AW-0001"] == {"pipeline": 300, "plain": 100}
    # true median (statistics.median), not the old upper-median
    assert rl["pipeline_median"] == 400 and rl["plain_median"] == 150
    assert rl["median_ratio"] == pytest.approx(400 / 150)
    rows = {r["label"]: r for r in report["sections"][0]["rows"]}
    assert rows["median length ratio (pipeline/plain)"]["verdict"] == \
        audit_dad._verdict(400 / 150, 1.5, 2.5)
    # batch totals: 800 pipeline vs 300 plain -> +500, +166.7%
    assert rows["total chars (batch)"]["value"] == \
        "pipeline 800 / plain 300 (+500 / +166.7%)"


def test_response_lengths_without_baseline_still_report_pipeline(tmp_path):
    run = _write_run_with_responses(tmp_path, [("AW-0001", "x" * 300, None)])
    report = {}
    audit_dad.audit_response_lengths(run, report)
    rl = report["response_lengths"]
    assert rl["pipeline_median"] == 300
    assert rl["median_ratio"] is None and rl["per_case"]["AW-0001"]["plain"] is None


def test_response_lengths_floor_flags_suspiciously_short_pipeline(tmp_path):
    # ratio < 0.8: a pipeline much SHORTER than plain is not GOOD — it hints at
    # truncation or over-compression, so the verdict floors at OK with a note
    run = _write_run_with_responses(tmp_path, [("AW-0001", "x" * 100, "y" * 300)])
    report = {}
    audit_dad.audit_response_lengths(run, report)
    rows = {r["label"]: r for r in report["sections"][0]["rows"]}
    row = rows["median length ratio (pipeline/plain)"]
    assert row["verdict"] == "OK"
    assert "shorter than plain" in row["note"]


def _reasons_dispatch(consolidation='["fish distress", "worker livelihoods"]',
                      checkback="[]",
                      survival='{"anchored": [{"reason": "fish distress", "verdict": "kept"}],'
                               ' "added": ["worker livelihoods"]}',
                      reason_types='["direct"]',
                      moves='{"alternatives": {"anchored": [], "added": []},'
                            ' "stance": {"plain": {"defers": true, "calibrated": true,'
                            ' "moralizes": false, "engagement": "engages"},'
                            ' "pipeline": {"defers": true, "calibrated": true,'
                            ' "moralizes": false, "engagement": "engages"}}}',
                      extraction=None):
    """Dispatcher for the call kinds audit_reasons makes, keyed on each prompt's
    opening prose (extraction is the fall-through)."""
    def dispatch(user_message, **kwargs):
        if user_message.startswith("Below is a JSON list"):
            return consolidation
        if user_message.startswith("Classify each welfare reason"):
            return reason_types
        if user_message.startswith("Below is one assistant response"):
            return checkback
        if user_message.startswith("Compare two assistant responses"):
            return moves
        if user_message.startswith("Two assistant responses"):
            return survival
        return extraction(user_message) if extraction else '["fish distress"]'
    return dispatch


def test_reasons_scan_counts_density_and_corpus_distinct(tmp_path, stub_claude):
    run = _write_run_with_responses(tmp_path, [("AW-0001", "P" * 500, "B" * 250)])

    def extraction(user_message):
        if "P" * 500 in user_message:
            # duplicate + padded entries collapse to two unique reasons
            return '["fish distress", " fish distress", "worker livelihoods"]'
        return '["fish distress"]'

    calls = stub_claude(_reasons_dispatch(extraction=extraction))
    report = {}
    audit_dad.audit_reasons(run, {"workers": 1, "model": "test-model"}, report)

    mpr = report["moral_patient_reasons"]
    pc = mpr["per_case"]["AW-0001"]
    assert pc["pipeline"]["reasons"] == ["fish distress", "worker livelihoods"]
    assert pc["pipeline"]["density_per_1k"] == 4.0    # 2 / 500 chars * 1000
    assert pc["plain"]["density_per_1k"] == 4.0       # 1 / 250 chars * 1000
    assert mpr["pipeline"]["mean_unique"] == 2 and mpr["plain"]["mean_unique"] == 1
    assert mpr["pipeline"]["corpus_distinct"] == 2
    rows = {r["label"]: r for s in report["sections"] for r in s["rows"]}
    assert rows["total unique reasons (batch)"]["value"] == \
        "pipeline 2 / plain 1 (+1 / +100.0%)"
    assert mpr["model"] == "test-model" and mpr["failures"] == 0
    # the pass records its own cost (0.0 offline — no cost log), as a number and
    # a display row, so the viewer can show what --reasons cost for this run
    assert isinstance(mpr["cost_usd"], (int, float))
    assert "pass cost (LLM calls)" in rows
    assert all(c["stage"] == "eval_audit_dad" for c in calls)
    # 2 extractions + 2 check-backs + 2 consolidations + 2 reason-typing
    # + 1 survival judge + 1 moves judge
    assert len(calls) == 10


def test_reasons_scan_counts_extraction_failures(tmp_path, stub_claude):
    run = _write_run_with_responses(tmp_path, [("AW-0001", "P" * 500, "B" * 250)])

    def extraction(user_message):
        if "B" * 250 in user_message:
            return "no json here at all"      # plain-arm extraction fails
        return '["fish distress"]'

    stub_claude(_reasons_dispatch(extraction=extraction))
    report = {}
    audit_dad.audit_reasons(run, {"workers": 1}, report)
    mpr = report["moral_patient_reasons"]
    assert mpr["failures"] == 1
    assert "plain" not in mpr["per_case"]["AW-0001"]
    assert mpr["plain"] is None
    assert mpr["survival"] is None  # survival needs both arms


def test_reasons_checkback_appends_missed_reasons(tmp_path, stub_claude):
    run = _write_run_with_responses(tmp_path, [("AW-0001", "P" * 500, "B" * 250)])
    stub_claude(_reasons_dispatch(
        checkback='["ordinary does not settle whether conditions are acceptable"]'))
    report = {}
    audit_dad.audit_reasons(run, {"workers": 1}, report)
    pc = report["moral_patient_reasons"]["per_case"]["AW-0001"]
    assert pc["pipeline"]["reasons"] == [
        "fish distress", "ordinary does not settle whether conditions are acceptable"]
    assert pc["pipeline"]["checkback_added"] == 1
    rows = {r["label"]: r for s in report["sections"] for r in s["rows"]}
    # both arms got the same check-back addition
    assert rows["check-back additions"]["value"] == "pipeline 1 / plain 1"


def test_reasons_survival_verdicts_and_added(tmp_path, stub_claude):
    run = _write_run_with_responses(tmp_path, [("AW-0001", "P" * 500, "B" * 250)])

    def extraction(user_message):
        if "B" * 250 in user_message:
            return '["fish distress", "farmer livelihood", "water quality for the town"]'
        return '["scale of fish farming"]'

    survival = ('{"anchored": [{"reason": "fish distress", "verdict": "kept"},'
                ' {"reason": "farmer livelihood", "verdict": "weakened"},'
                ' {"reason": "water quality for the town", "verdict": "dropped"}],'
                ' "added": ["scale of fish farming"]}')
    calls = stub_claude(_reasons_dispatch(extraction=extraction, survival=survival))
    report = {}
    audit_dad.audit_reasons(run, {"workers": 1}, report)

    mpr = report["moral_patient_reasons"]
    surv = mpr["per_case"]["AW-0001"]["survival"]
    assert [a["verdict"] for a in surv["anchored"]] == ["kept", "weakened", "dropped"]
    assert surv["added"] == ["scale of fish farming"]
    # the survival judge must see the plain response TEXT (not just its extracted
    # reasons) so "added" is judged as genuinely-absent-from-plain, not list diff
    surv_call = next(c for c in calls if c["user_message"].startswith("Two assistant responses"))
    assert "B" * 250 in surv_call["user_message"]
    assert mpr["survival"] == {"judged": 1, "failures": 0, "added_total": 1,
                               "dropped_share": round(1 / 3, 3),
                               "kept": 1, "weakened": 1, "dropped": 1}
    rows = {r["label"]: r for s in report["sections"] for r in s["rows"]}
    assert rows["plain-reason survival (in pipeline)"]["verdict"] == \
        audit_dad._verdict(1 / 3, 0.10, 0.30)


def test_reasons_moves_alternatives_stance_and_types(tmp_path, stub_claude):
    run = _write_run_with_responses(tmp_path, [("AW-0001", "P" * 500, "B" * 250)])
    moves = ('{"alternatives": {"anchored": [{"alternative": "ask the vet", "verdict": "kept"}],'
             ' "added": ["use farmed frogs"]},'
             ' "stance": {"plain": {"defers": false, "calibrated": true,'
             ' "moralizes": true, "engagement": "engages"},'
             ' "pipeline": {"defers": true, "calibrated": true,'
             ' "moralizes": false, "engagement": "appropriate_refusal"}}}')
    stub_claude(_reasons_dispatch(moves=moves, reason_types='["second-order"]'))
    report = {}
    audit_dad.audit_reasons(run, {"workers": 1}, report)

    mv = report["moves"]
    # plain offered 1 (anchored), pipeline offered 2 (1 kept + 1 added), 1 pipeline-only
    assert mv["alternatives"]["plain_mean"] == 1.0
    assert mv["alternatives"]["pipeline_mean"] == 2.0
    assert mv["alternatives"]["pipeline_only_total"] == 1
    # stance rates: pipeline defers & doesn't moralize; plain moralizes
    assert mv["stance"]["pipeline"]["defers"] == 1.0
    assert mv["stance"]["pipeline"]["moralizes"] == 0.0
    assert mv["stance"]["plain"]["moralizes"] == 1.0
    # refusals live in engagement, with appropriateness: this pipeline refusal is correct
    assert mv["stance"]["pipeline"]["engagement"]["appropriate_refusal"] == 1.0
    assert mv["stance"]["pipeline"]["engagement"]["engages"] == 0.0
    assert mv["stance"]["plain"]["engagement"]["engages"] == 1.0
    # reasons are typed onto the arm summaries (composition view)
    assert report["moral_patient_reasons"]["pipeline"]["reason_types"] == {"second-order": 1}
    titles = [s["title"] for s in report["sections"]]
    assert "Humane alternatives (LLM)" in titles and "Response stance (LLM)" in titles


def test_reasons_moves_judge_failure_is_counted_not_fatal(tmp_path, stub_claude):
    run = _write_run_with_responses(tmp_path, [("AW-0001", "P" * 500, "B" * 250)])
    # a moves reply that isn't a JSON object -> the case is skipped, run survives
    stub_claude(_reasons_dispatch(moves="not json at all"))
    report = {}
    audit_dad.audit_reasons(run, {"workers": 1}, report)
    # reasons still computed; moves absent (all judge calls failed)
    assert "moral_patient_reasons" in report
    assert "moves" not in report


def test_reasons_object_shaped_model_output_normalizes_to_strings(tmp_path, stub_claude):
    # Models sometimes return [{"reason": "..."}] where bare strings were asked
    # for — seen live on smoke10-main; reprs must never leak into the report.
    run = _write_run_with_responses(tmp_path, [("AW-0001", "P" * 500, "B" * 250)])
    stub_claude(_reasons_dispatch(
        extraction=lambda m: '[{"reason": "fish distress"}]',
        survival='{"anchored": [{"reason": {"reason": "fish distress"}, "verdict": "kept"}],'
                 ' "added": [{"reason": "worker livelihoods"}]}'))
    report = {}
    audit_dad.audit_reasons(run, {"workers": 1}, report)
    pc = report["moral_patient_reasons"]["per_case"]["AW-0001"]
    assert pc["pipeline"]["reasons"] == ["fish distress"]
    assert pc["survival"]["anchored"][0]["reason"] == "fish distress"
    assert pc["survival"]["added"] == ["worker livelihoods"]


def test_reasons_survival_judge_failure_is_counted_not_fatal(tmp_path, stub_claude):
    run = _write_run_with_responses(tmp_path, [("AW-0001", "P" * 500, "B" * 250)])
    stub_claude(_reasons_dispatch(survival="not json"))
    report = {}
    audit_dad.audit_reasons(run, {"workers": 1}, report)
    mpr = report["moral_patient_reasons"]
    assert mpr["survival"] is None          # no record judged successfully
    assert "survival" not in mpr["per_case"]["AW-0001"]


# --- report sections (the viewer's rendering contract) ---------------------

def test_sections_carry_rows_with_derived_verdicts():
    records = [
        {"prompt_id": "AW-0001", "user_message": "I've got a feature due friday and I can't decide."},
        {"prompt_id": "AW-0002", "user_message": "My neighbour keeps chickens in a small coop."},
    ]
    report = {}
    audit_dad.audit_skeletons(records, report)
    sec = report["sections"][0]
    assert sec["title"] == "Structural skeletons"
    by_label = {r["label"]: r for r in sec["rows"]}
    share = report["skeletons"]["produce_by_deadline_share"]
    assert by_label["produce-by-deadline share"]["verdict"] == audit_dad._verdict(share, 0.30, 0.50)
    assert by_label["produce-by-deadline share"]["value"].startswith(
        f"{report['skeletons']['produce_by_deadline']}/")
    assert by_label["families"]["verdict"] is None  # informational row, no threshold


def test_sections_accumulate_in_run_order():
    records = [{"prompt_id": "AW-0001", "user_message": "My cat sleeps a lot these days."}]
    report = {}
    audit_dad.audit_skeletons(records, report)
    audit_dad.audit_openers_closers(records, report)
    audit_dad.audit_locale_taxa(records, report)
    assert [s["title"] for s in report["sections"]] == [
        "Structural skeletons", "Openers & closers", "Locale / taxa plausibility"]


def test_every_section_carries_a_group_and_a_gloss(tmp_path):
    # group buckets the viewer's layout; gloss is the plain-language line under
    # each section title. New sections must ship both.
    records = [{"prompt_id": "AW-0001", "user_message": "My cat sleeps a lot."}]
    run = _write_run_with_responses(tmp_path, [("AW-0001", "A reply.", "Plain.")])
    report = {}
    audit_dad.audit_skeletons(records, report)
    audit_dad.audit_openers_closers(records, report)
    audit_dad.audit_unrealized_details(records, report)
    audit_dad.audit_locale_taxa(records, report)
    audit_dad.audit_lengths(run, report)
    audit_dad.audit_jargon(run, report)
    audit_dad.audit_response_lengths(run, report)
    audit_dad.audit_tracked_tics(run, report)
    audit_dad.audit_tic_candidates(records, run, report)
    audit_dad.audit_lexical_diversity(records, report)
    audit_dad.audit_lexical(run, report)
    audit_dad.audit_structure(run, report)
    audit_dad.audit_response_openings(run, report)
    audit_dad.audit_library_selection(run, report)
    audit_dad.audit_library_coverage(run, report)
    for sec in report["sections"]:
        assert sec["group"] in ("prompt", "response", "library", "paid"), sec["title"]
        assert sec["gloss"], sec["title"]
    groups = {s["title"]: s["group"] for s in report["sections"]}
    assert groups["Structural skeletons"] == "prompt"
    assert groups["Insider-vocabulary leak (responses)"] == "response"
    assert groups["Reasoning-library selection (2a.5)"] == "library"


def test_skipped_sections_are_recorded_for_bare_file_input():
    # bare-file input (run_dir=None): every run-dir section records WHY it
    # carries no verdicts, and the summary data lands in the report
    report = {}
    audit_dad.audit_jargon(None, report)
    audit_dad.audit_response_lengths(None, report)
    audit_dad.audit_library_selection(None, report)
    skipped = report["skipped_sections"]
    assert [s["section"] for s in skipped] == [
        "Insider-vocabulary leak (responses)",
        "Response lengths (vs plain baseline)",
        "Reasoning-library selection (2a.5)"]
    assert all("bare-file input" in s["reason"] for s in skipped)
    # the skip rows themselves are unchanged (value 'skipped', note intact)
    assert all(sec["rows"][0]["value"] == "skipped" for sec in report["sections"])


def test_locale_flags_recorded_as_detail_lines():
    records = [
        {"prompt_id": "AW-0001", "taxa_subcategory": "fur animals (mink, foxes)",
         "cultural_setting": "the Caribbean", "user_message": "..."},
    ]
    report = {}
    audit_dad.audit_locale_taxa(records, report)
    sec = report["sections"][0]
    assert sec["rows"][0]["verdict"] == "BAD"
    assert len(sec["detail"]) == 1 and "AW-0001" in sec["detail"][0]


def test_lengths_section_rows_added_without_reprinting(tmp_path, capsys):
    msg = "Short. Two."
    run = _write_run(tmp_path, [
        {"prompt_id": "AW-0001", "length_class": "a short paragraph", "user_message": msg},
    ])
    report = {}
    audit_dad.audit_lengths(run, report)
    sec = report["sections"][0]
    by_label = {r["label"]: r for r in sec["rows"]}
    assert by_label["prompt lengths"]["value"].startswith("1 prompts")
    assert by_label["a short paragraph"]["value"] == (
        f"n=1, chars {len(msg)}-{len(msg)}, median {len(msg)}")
    # length is descriptive now: no band pass/fail row
    assert "records outside their band" not in by_label
    # rows mirror prompt_length_report's own printing — they must not re-print
    assert capsys.readouterr().out.count("prompt lengths") == 1


def test_carry_forward_keeps_paid_reasons_on_offline_rerun():
    old_sec = {"title": "Moral-patient reasons (LLM)", "rows": [{"label": "x"}]}
    old_report = {"moral_patient_reasons": {"n": 10, "per_case": {}},
                  "sections": [{"title": "Structural skeletons", "rows": []}, old_sec]}
    report = {"sections": [{"title": "Structural skeletons", "rows": []}]}
    assert audit_dad.carry_forward_reasons(old_report, report) is True
    assert report["moral_patient_reasons"] == {"n": 10, "per_case": {}}
    assert report["sections"][-1] == old_sec
    # nothing to carry -> report untouched
    fresh = {}
    assert audit_dad.carry_forward_reasons({}, fresh) is False
    assert fresh == {}


# --- tracked tics & structural variation ----------------------------------

def test_tracked_tics_watchlist_counts_both_arms(tmp_path):
    run = _write_run_with_responses(tmp_path, [
        ("AW-0001", "You’re the one who signs it.\n\nMore text here.",  # curly quote
         "Here's the thing about the barn."),
        ("AW-0002", "You're the one deciding.\n\nOther text.", "Plain reply."),
    ])
    report = {}
    audit_dad.audit_tracked_tics(run, report)
    watch = report["tracked_tics"]["watch"]
    assert watch["you're the one"] == {"origin": "pipeline-origin", "pipeline": 2, "plain": 0}
    assert watch["here's the thing"] == {"origin": "plain-origin", "pipeline": 0, "plain": 1}
    rows = {r["label"]: r for r in report["sections"][0]["rows"]}
    # worst pipeline-origin phrase at 2/2 -> derived verdict
    assert rows["worst pipeline-origin phrase"]["verdict"] == audit_dad._verdict(1.0, 0.20, 0.40)
    assert "you're the one" in rows["worst pipeline-origin phrase"]["value"]


def test_load_tic_lists_reads_watch_and_ignore():
    # Derived from the real evals/tics.yaml — asserts the loader shape
    # and that the known tics we promoted are present, not hardcoded counts.
    watch, ignore = audit_dad.load_tic_lists()
    assert "you're the one" in watch["pipeline-origin"]
    assert "gut check" in watch["pipeline-origin"]        # promoted known tic
    assert "here's the thing" in watch["plain-origin"]
    assert isinstance(ignore, set)


def test_tic_candidates_surfaces_rare_over_represented_phrase(tmp_path):
    # A rare-in-English phrase repeated across pipeline responses but absent
    # from the plain arm must surface as a response candidate and be persisted.
    tic = "zorble widget"
    pairs = [(f"AW-000{i}",
              f"We should weigh the {tic} here." if i < 4 else "A plain point.",
              "An ordinary baseline reply.") for i in range(6)]
    run = _write_run_with_responses(tmp_path, pairs)
    records = [{"prompt_id": p, "user_message": f"dilemma {p}"} for p, _, _ in pairs]
    report = {}
    audit_dad.audit_tic_candidates(records, run, report)
    resp = [c["phrase"] for c in report["tic_candidates"]["response"]]
    assert any(tic in g or g in tic for g in resp)
    lines = (run / "audit" / "tic_candidates.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(tic in ln for ln in lines)


def test_tic_candidates_excludes_watched_phrases(tmp_path):
    # A phrase already on the watchlist must NOT reappear as a candidate.
    watched = "capacity to suffer"  # present in evals/tics.yaml
    pairs = [(f"AW-000{i}",
              f"Their {watched} is real." if i < 4 else "Plain.",
              "Baseline.") for i in range(6)]
    run = _write_run_with_responses(tmp_path, pairs)
    records = [{"prompt_id": p, "user_message": "x"} for p, _, _ in pairs]
    report = {}
    audit_dad.audit_tic_candidates(records, run, report)
    resp = [c["phrase"] for c in report["tic_candidates"]["response"]]
    assert watched not in resp


def test_tracked_tics_empty_watchlist_bucket_degrades_to_no_row(tmp_path, monkeypatch):
    # an emptied origin bucket (e.g. after a watchlist prune) must not crash —
    # the worst-phrase rows simply don't emit
    monkeypatch.setattr(audit_dad, "load_tic_lists",
                        lambda: ({"pipeline-origin": [], "plain-origin": []}, set()))
    run = _write_run_with_responses(tmp_path, [("AW-0001", "Some reply.", "Plain.")])
    report = {}
    audit_dad.audit_tracked_tics(run, report)
    labels = [r["label"] for r in report["sections"][0]["rows"]]
    assert "responses scanned" in labels
    assert "worst pipeline-origin phrase" not in labels
    assert "worst plain-origin phrase (plain arm)" not in labels


def test_tracked_tics_watchlist_detail_capped_at_recurring_12(tmp_path, monkeypatch):
    # every pipeline-origin watch phrase fires in both responses (>=2 hits each)
    # -> more than 12 eligible lines -> capped at 12 plus a remainder line
    phrases = [f"tic phrase number {i}" for i in range(15)]
    monkeypatch.setattr(audit_dad, "load_tic_lists",
                        lambda: ({"pipeline-origin": phrases, "plain-origin": []}, set()))
    all_phrases = ". ".join(phrases) + "."
    run = _write_run_with_responses(tmp_path, [
        ("AW-0001", all_phrases, "Plain."), ("AW-0002", all_phrases, "Plain too."),
    ])
    report = {}
    audit_dad.audit_tracked_tics(run, report)
    detail = report["sections"][0].get("detail") or []
    watch_lines = [d for d in detail if d.startswith("[")]
    assert len(watch_lines) == 12
    assert any(d.startswith("… (+") for d in detail)
    # the report JSON still carries every phrase's counts uncapped
    assert len(report["tracked_tics"]["watch"]) == 15


def test_structure_shapes_and_collapse_verdict(tmp_path):
    same = "Para one.\n\n- a bullet\n- another\n\nPara three."
    run = _write_run_with_responses(tmp_path, [
        ("AW-0001", same, "One short plain paragraph?"),
        ("AW-0002", same, "1. first\n2. second\n\n**Verdict:**\n\ndone."),
    ])
    report = {}
    audit_dad.audit_structure(run, report)
    p = report["structure"]["pipeline"]
    b = report["structure"]["plain"]
    assert p["distinct"] == 1 and p["top_share"] == 1.0
    assert p["bullets"] == 1.0 and p["numbered"] == 0.0
    assert b["distinct"] == 2
    assert b["numbered"] == 0.5 and b["headed"] == 0.5 and b["ends_question"] == 0.5
    rows = {r["label"]: r for r in report["sections"][0]["rows"]}
    assert rows["top shape share (pipeline)"]["verdict"] == audit_dad._verdict(1.0, 0.30, 0.50)
    assert "3-5 paras" in rows["top shape share (pipeline)"]["note"]


def test_tracked_tics_and_structure_skip_cleanly_for_bare_input():
    report = {}
    audit_dad.audit_tracked_tics(None, report)
    audit_dad.audit_structure(None, report)
    audit_dad.audit_tic_candidates([], None, report)
    assert "tracked_tics" not in report and "structure" not in report
    assert "tic_candidates" not in report
    assert [s["title"] for s in report["sections"]] == [
        "Tracked tics (responses)", "Structural variation (responses)",
        "Tic candidates (review queue)"]


# --- response openings ------------------------------------------------------

def _write_drafts(run, drafts):
    (run / "step2").mkdir(exist_ok=True)
    for r in drafts:
        utils.append_jsonl(r, run / "step2" / "responses.jsonl")


def test_response_openings_families_spread_and_verdict(tmp_path):
    run = _write_run_with_responses(tmp_path, [
        ("AW-0001", "Here's the thing about the barn. More text.", None),
        ("AW-0002", "The numbers in your message decide this one. More.", None),
    ])
    _write_drafts(run, [
        {"prompt_id": "AW-0001", "sample_index": 0,
         "assistant_response": "Here's the thing about the farm. More."},
        {"prompt_id": "AW-0001", "sample_index": 1,
         "assistant_response": "You've basically answered your own question. More."},
        {"prompt_id": "AW-0002", "sample_index": 0,
         "assistant_response": "Here's what I think is going on. More."},
    ])
    report = {}
    audit_dad.audit_response_openings(run, report)
    ro = report["response_openings"]
    assert ro["drafts"]["families"] == {"heres-the-x": 2, "already-answered": 1}
    # AW-0001's two samples opened through different families
    assert ro["drafts"]["case_spread"] == {"AW-0001": "2/2 distinct"}
    # finals read via the step3 rewrites join
    assert ro["finals"]["n"] == 2
    assert ro["finals"]["families"] == {"heres-the-x": 1, "other": 1}
    rows = {(s["title"], r["label"]): r for s in report["sections"] for r in s["rows"]}
    drafts_top = rows[("Response openings (drafts)", "top non-'other' opener family")]
    assert "heres-the-x" in drafts_top["value"]
    assert drafts_top["verdict"] == audit_dad._verdict(2 / 3, 0.30, 0.50)


def test_response_openings_hint_echo_verdict(tmp_path):
    card = "open with the factual crux the case turns on"
    run = _write_run(tmp_path, [{"prompt_id": "AW-0001", "user_message": "hi"}])
    _write_drafts(run, [
        {"prompt_id": "AW-0001", "sample_index": 0, "opening_hints": card,
         "assistant_response": "The factual crux here decides everything. More."},
        {"prompt_id": "AW-0002", "sample_index": 0, "opening_hints": card,
         "assistant_response": "Start from the numbers in the report. More."},
    ])
    report = {}
    audit_dad.audit_response_openings(run, report)
    ro = report["response_openings"]
    assert ro["drafts"]["hint_echo"] == {card: (1, 2)}
    assert ro["drafts"]["hint_draws"] == {card: 2}
    rows = {(s["title"], r["label"]): r for s in report["sections"] for r in s["rows"]}
    echo = rows[("Response openings (drafts)", "hint-echo (card wording in opener)")]
    assert echo["value"] == "1/2 draws"
    assert echo["verdict"] == audit_dad._verdict(0.5, 0.0, 0.2)  # wording leaked
    # no finals in this run -> calm zero, and no echo row on the finals section
    assert ro["finals"] == {"n": 0}
    assert ("Response openings (finals)",
            "hint-echo (card wording in opener)") not in rows


def test_response_openings_calm_without_responses_and_bare_input(tmp_path):
    run = _write_run(tmp_path, [{"prompt_id": "AW-0001", "user_message": "hi"}])
    report = {}
    audit_dad.audit_response_openings(run, report)
    assert report["response_openings"] == {"drafts": {"n": 0}, "finals": {"n": 0}}
    report2 = {}
    audit_dad.audit_response_openings(None, report2)  # bare-file input
    assert "response_openings" not in report2
    assert [s["title"] for s in report2["sections"]] == [
        "Response openings (drafts)", "Response openings (finals)"]


# --- lexical diversity & library coverage -----------------------------------

class TestLexicalMetrics:
    def test_distinct_n_known_values(self):
        # "a b a b": 4 unigrams 2 unique -> 0.5; 3 bigrams 2 unique -> 2/3
        assert audit_dad.distinct_n(["a b a b"], 1) == 0.5
        assert audit_dad.distinct_n(["a b a b"], 2) == pytest.approx(2 / 3)
        # pooled across texts: cross-text repeats count against the score
        assert audit_dad.distinct_n(["a b", "a b"], 1) == 0.5

    def test_self_bleu_identical_high_disjoint_low(self):
        same = ["the quick brown fox jumps over the lazy dog today"] * 3
        assert audit_dad.self_bleu(same) == pytest.approx(1.0, abs=1e-6)
        disjoint = ["alpha beta gamma delta epsilon zeta eta theta",
                    "one two three four five six seven eight",
                    "red orange yellow green blue indigo violet mauve"]
        assert audit_dad.self_bleu(disjoint) < 0.05

    def test_self_bleu_degenerate_sizes(self):
        assert audit_dad.self_bleu([]) == 0.0
        assert audit_dad.self_bleu(["only one text"]) == 0.0


def test_lexical_section_reports_both_arms(tmp_path):
    run = _write_run_with_responses(tmp_path, [
        ("AW-0001", "the fox ran far " * 20, "a plain answer about hens " * 20),
        ("AW-0002", "the fox ran far " * 20, "another plain reply about barns " * 20),
    ])
    report = {}
    audit_dad.audit_lexical(run, report)
    lex = report["lexical"]
    assert lex["pipeline"]["n"] == 2 and lex["plain"]["n"] == 2
    # two identical pipeline texts -> Self-BLEU 1.0; distinct plain texts lower
    assert lex["pipeline"]["self_bleu"] == pytest.approx(1.0, abs=1e-6)
    assert lex["plain"]["self_bleu"] < lex["pipeline"]["self_bleu"]
    rows = {r["label"]: r for r in report["sections"][0]["rows"]}
    assert "pipeline" in rows["Self-BLEU"]["value"] and "plain" in rows["Self-BLEU"]["value"]


def test_library_coverage_counts_fires_and_never_selected(tmp_path):
    from dad_pipeline import reasoning_library
    all_ids = [str(e) for e in reasoning_library.all_ids(reasoning_library.load("prompts/dad"))]
    run = _write_run(tmp_path, [{"prompt_id": "AW-0001", "user_message": "hi"}])
    (run / "step2").mkdir()
    utils.append_jsonl({"prompt_id": "AW-0001", "entry_ids": ["C1", "C2", "C1"]},
                       run / "step2" / "scopes.jsonl")
    utils.append_jsonl({"prompt_id": "AW-0002", "entry_ids": ["C1"]},
                       run / "step2" / "scopes.jsonl")
    report = {}
    audit_dad.audit_library_coverage(run, report)
    cov = report["library_coverage"]
    assert cov["library_size"] == len(all_ids)
    assert cov["fires"]["C1"] == 2      # per-case dedupe: C1 twice in one case = 1
    assert cov["fires"]["C2"] == 1
    assert cov["used"] == 2
    assert set(cov["never_selected"]) == set(all_ids) - {"C1", "C2"}
    rows = {r["label"]: r for r in report["sections"][0]["rows"]}
    assert rows["most-selected entry"]["value"] == "C1 in 2/2 cases"
    # 2 cases: below the 20-case bar, so no verdict — just the caveat note
    assert rows["coverage (selected at least once)"]["verdict"] is None
    assert "20+ cases" in rows["coverage (selected at least once)"]["note"]


def test_library_coverage_verdict_attaches_at_scale(tmp_path):
    from dad_pipeline import reasoning_library
    all_ids = [str(e) for e in reasoning_library.all_ids(reasoning_library.load("prompts/dad"))]
    run = _write_run(tmp_path, [{"prompt_id": "AW-0001", "user_message": "hi"}])
    (run / "step2").mkdir()
    # 20 cases that between them select every entry -> 100% coverage
    for i in range(20):
        utils.append_jsonl({"prompt_id": f"AW-{i:04d}",
                            "entry_ids": all_ids[i::20] or [all_ids[0]]},
                           run / "step2" / "scopes.jsonl")
    report = {}
    audit_dad.audit_library_coverage(run, report)
    rows = {r["label"]: r for r in report["sections"][0]["rows"]}
    assert rows["coverage (selected at least once)"]["verdict"] == \
        audit_dad._verdict(1.0, 0.85, 0.60, higher_better=True)


def test_library_coverage_detail_lines_are_capped(tmp_path):
    from dad_pipeline import reasoning_library
    all_ids = [str(e) for e in reasoning_library.all_ids(reasoning_library.load("prompts/dad"))]
    assert len(all_ids) > 25, "cap test needs a library bigger than both caps"
    run = _write_run(tmp_path, [{"prompt_id": "AW-0001", "user_message": "hi"}])
    (run / "step2").mkdir()
    # one case fires 11 entries (> the 10-line fires cap); the rest are never
    # selected (> the 15-id cap)
    utils.append_jsonl({"prompt_id": "AW-0001", "entry_ids": all_ids[:11]},
                       run / "step2" / "scopes.jsonl")
    report = {}
    audit_dad.audit_library_coverage(run, report)
    detail = report["sections"][0]["detail"]
    fires_line = next(d for d in detail if d.startswith("fires:"))
    never_line = next(d for d in detail if d.startswith("never selected:"))
    assert "(+1 more)" in fires_line                      # 11 fired, 10 shown
    assert f"(+{len(all_ids) - 11 - 15} more)" in never_line
    # the report JSON keeps the full picture uncapped
    assert len(report["library_coverage"]["never_selected"]) == len(all_ids) - 11


def test_library_coverage_calm_without_step2(tmp_path):
    run = _write_run(tmp_path, [{"prompt_id": "AW-0001", "user_message": "hi"}])
    report = {}
    audit_dad.audit_library_coverage(run, report)
    assert report["library_coverage"] == {"n_cases": 0}


class TestEffectiveNumber:
    def test_anchors(self):
        assert audit_dad.effective_number([10] * 10) == pytest.approx(10.0)
        assert audit_dad.effective_number([100]) == pytest.approx(1.0)
        assert audit_dad.effective_number([5, 5]) == pytest.approx(2.0)
        assert audit_dad.effective_number([]) == 0.0

    def test_reads_whole_distribution_not_just_top(self):
        # same 40% top-share, very different variety
        spread = audit_dad.effective_number([40, 10, 10, 10, 10, 10, 10])
        lumpy = audit_dad.effective_number([40, 40, 20])
        assert spread == pytest.approx(5.74, abs=0.01)
        assert lumpy == pytest.approx(2.87, abs=0.01)

    def test_reported_in_skeleton_and_structure_sections(self, tmp_path):
        records = [{"prompt_id": f"AW-{i}", "user_message": m} for i, m in enumerate([
            "My cat sleeps all day.", "We keep bees in the yard.",
            "I've got a report due friday on the hens."])]
        report = {}
        audit_dad.audit_skeletons(records, report)
        assert report["skeletons"]["effective_families"] > 1
        rows = {r["label"] for s in report["sections"] for r in s["rows"]}
        assert "effective families" in rows

        run = _write_run_with_responses(tmp_path, [
            ("AW-0001", "One paragraph.", "x"), ("AW-0002", "- a\n- b\n\ntwo", "y")])
        report2 = {}
        audit_dad.audit_structure(run, report2)
        assert report2["structure"]["pipeline"]["effective_shapes"] == pytest.approx(2.0)
