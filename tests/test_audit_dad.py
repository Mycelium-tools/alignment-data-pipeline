"""Tests for evals/audit_dad.py — the offline prompt-corpus audit.

Fully offline (the audit makes no API calls). Each check is driven over a small
synthetic set of step-1 records and asserted on the returned ``report`` dict, in
the style of tests/test_openings_dad.py. Frontier-frame and cultural-setting
values are taken from the real axis definitions so the checks stay pinned to the
strings the pipeline actually deals.
"""

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


def test_library_selection_calm_without_step2(tmp_path):
    run = _write_run(tmp_path, [{"prompt_id": "AW-0001", "user_message": "hi"}])
    report = {}
    audit_dad.audit_library_selection(run, report)
    assert report["library_selection"] == {"n": 0}
    report2 = {}
    audit_dad.audit_library_selection(None, report2)  # bare-file input
    assert "library_selection" not in report2


def test_jargon_scan_counts_and_compares_to_baseline(tmp_path):
    run = _write_run(tmp_path, [{"prompt_id": "AW-0001", "user_message": "hi"}])
    (run / "final").mkdir()
    (run / "baseline").mkdir()
    # pipeline responses carry insider vocab; the plain baseline carries less
    corpus = [
        {"record_id": "r1", "messages": [{"role": "user", "content": "u"},
         {"role": "assistant", "content": "The counterfactual moral weight here is high; valenced experience matters."}]},
        {"record_id": "r2", "messages": [{"role": "user", "content": "u"},
         {"role": "assistant", "content": "Consider the counterfactual and the objective function."}]},
    ]
    for c in corpus:
        utils.append_jsonl(c, run / "final" / "dad_corpus.jsonl")
    utils.append_jsonl({"prompt_id": "AW-0001", "baseline_response": "A plain kind answer with no jargon."},
                       run / "baseline" / "baseline_responses.jsonl")
    utils.append_jsonl({"prompt_id": "AW-0002", "baseline_response": "Weigh the counterfactual once."},
                       run / "baseline" / "baseline_responses.jsonl")

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
    run = _write_run(tmp_path, [{"prompt_id": "AW-0001", "user_message": "hi"}])
    (run / "final").mkdir()
    utils.append_jsonl({"record_id": "r1", "messages": [{"role": "user", "content": "u"},
        {"role": "assistant", "content": "Only marginally worse, a neglected corner, the sentient dog suffered."}]},
        run / "final" / "dad_corpus.jsonl")
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
