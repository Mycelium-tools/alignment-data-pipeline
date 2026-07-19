"""Tests for evals/audit_dad.py — the offline prompt-corpus audit.

Fully offline (the audit makes no API calls). Each check is driven over a small
synthetic set of step-1 records and asserted on the returned ``report`` dict, in
the style of tests/test_openings_dad.py. Frontier-frame and cultural-setting
values are taken from the real axis definitions so the checks stay pinned to the
strings the pipeline actually deals.
"""

import pytest

from dad_pipeline.step1_dilemmas import _FRONTIER_FRAMES
from evals import audit_dad
from shared import utils

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
    assert rl["pipeline_median"] == 500 and rl["plain_median"] == 200
    assert rl["median_ratio"] == 2.5
    rows = {r["label"]: r for r in report["sections"][0]["rows"]}
    assert rows["median length ratio (pipeline/plain)"]["verdict"] == \
        audit_dad._verdict(2.5, 1.5, 2.5)
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


def _reasons_dispatch(consolidation='["fish distress", "worker livelihoods"]',
                      checkback="[]",
                      survival='{"anchored": [{"reason": "fish distress", "verdict": "kept"}],'
                               ' "added": ["worker livelihoods"]}',
                      extraction=None):
    """Dispatcher for the four call kinds audit_reasons makes, keyed on each
    prompt's opening prose (extraction is the fall-through)."""
    def dispatch(user_message, **kwargs):
        if user_message.startswith("Below is a JSON list"):
            return consolidation
        if user_message.startswith("Below is one assistant response"):
            return checkback
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
    assert all(c["stage"] == "eval_audit_dad" for c in calls)
    # 2 extractions + 2 check-backs + 2 consolidations + 1 survival judge
    assert len(calls) == 7


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
    stub_claude(_reasons_dispatch(extraction=extraction, survival=survival))
    report = {}
    audit_dad.audit_reasons(run, {"workers": 1}, report)

    mpr = report["moral_patient_reasons"]
    surv = mpr["per_case"]["AW-0001"]["survival"]
    assert [a["verdict"] for a in surv["anchored"]] == ["kept", "weakened", "dropped"]
    assert surv["added"] == ["scale of fish farming"]
    assert mpr["survival"] == {"judged": 1, "failures": 0, "added_total": 1,
                               "dropped_share": round(1 / 3, 3),
                               "kept": 1, "weakened": 1, "dropped": 1}
    rows = {r["label"]: r for s in report["sections"] for r in s["rows"]}
    assert rows["plain-reason survival (in pipeline)"]["verdict"] == \
        audit_dad._verdict(1 / 3, 0.10, 0.30)


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
    from dad_pipeline.step1_dilemmas import _LENGTH_BANDS
    msg = "Short. Two."
    run = _write_run(tmp_path, [
        {"prompt_id": "AW-0001", "length_class": "2-3-sentences", "user_message": msg},
    ])
    report = {}
    audit_dad.audit_lengths(run, report)
    sec = report["sections"][0]
    by_label = {r["label"]: r for r in sec["rows"]}
    assert by_label["prompt lengths"]["value"].startswith("1 prompts")
    assert by_label["2-3-sentences"]["value"] == f"n=1, chars {len(msg)}-{len(msg)}, median {len(msg)}"
    lo, hi = _LENGTH_BANDS["2-3-sentences"]
    expected = "GOOD" if lo <= len(msg) <= hi else "BAD"
    assert by_label["records outside their band"]["verdict"] == expected
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


# --- stock phrases & structural variation ----------------------------------

def test_stock_phrases_watchlist_counts_both_arms(tmp_path):
    run = _write_run_with_responses(tmp_path, [
        ("AW-0001", "You’re the one who signs it.\n\nMore text here.",  # curly quote
         "Here's the thing about the barn."),
        ("AW-0002", "You're the one deciding.\n\nOther text.", "Plain reply."),
    ])
    report = {}
    audit_dad.audit_stock_phrases(run, report)
    watch = report["stock_phrases"]["watch"]
    assert watch["you're the one"] == {"origin": "pipeline-origin", "pipeline": 2, "plain": 0}
    assert watch["here's the thing"] == {"origin": "plain-origin", "pipeline": 0, "plain": 1}
    rows = {r["label"]: r for r in report["sections"][0]["rows"]}
    # worst pipeline-origin phrase at 2/2 -> derived verdict
    assert rows["worst pipeline-origin phrase"]["verdict"] == audit_dad._verdict(1.0, 0.20, 0.40)
    assert "you're the one" in rows["worst pipeline-origin phrase"]["value"]


def test_stock_phrases_discovery_finds_new_engram(tmp_path):
    novel = "the quiet part out loud"
    run = _write_run_with_responses(tmp_path, [
        ("AW-0001", f"Saying {novel} matters.\n\nYes.", "A plain answer."),
        ("AW-0002", f"That is {novel} again.\n\nNo.", "Another plain answer."),
    ])
    report = {}
    audit_dad.audit_stock_phrases(run, report)
    new_p = [x["phrase"] for x in report["stock_phrases"]["new_pipeline"]]
    assert any(novel in g or g in novel for g in new_p)
    # and it is reported as a detail line, not silently stored
    assert any("new" in d and "quiet part" in d for d in report["sections"][0]["detail"])


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


def test_stock_and_structure_skip_cleanly_for_bare_input():
    report = {}
    audit_dad.audit_stock_phrases(None, report)
    audit_dad.audit_structure(None, report)
    assert "stock_phrases" not in report and "structure" not in report
    assert [s["title"] for s in report["sections"]] == [
        "Stock phrases (responses)", "Structural variation (responses)"]


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
