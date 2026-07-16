"""Cross-record phrase repetition (evals/holistic/phrases.py): document frequency,
not raw counts — one response using an idiom five times is style; five responses
sharing it is a template. Fully offline; no API, no fixtures needed."""

from evals.holistic import phrases

GRAM = "the quick brown fox jumps"   # exactly five words


# ---------------------------------------------------------------- lexicon layer

def test_lexicon_hits_count_documents_not_occurrences():
    texts = ["It's worth noting this. And it's worth noting that.",  # twice in ONE record
             "A completely different response."]
    rep = phrases.phrase_report(texts)
    assert rep["lexicon_hits"]["it's worth noting"] == 1


def test_lexicon_matching_is_case_insensitive():
    rep = phrases.phrase_report(["IT'S IMPORTANT TO NOTE that hens feel."])
    assert rep["lexicon_hits"]["it's important to note"] == 1


def test_lexicon_matches_typographic_apostrophes():
    # LLM output often uses curly quotes; "it’s" must still hit the ASCII lexicon.
    rep = phrases.phrase_report(["It’s worth noting hens feel pain."])
    assert rep["lexicon_hits"]["it's worth noting"] == 1


def test_clean_texts_produce_no_lexicon_hits():
    rep = phrases.phrase_report(["Hens need space.", "Fish feel pain."])
    assert rep["lexicon_hits"] == {}


# ---------------------------------------------------------------- discovery layer

def test_recurring_ngram_shared_across_records_is_discovered():
    texts = [f"{GRAM} over the first fence",
             f"{GRAM} over another fence",
             "entirely unrelated words in this one"]
    rep = phrases.phrase_report(texts)
    assert {"phrase": GRAM, "records": 2} in rep["recurring_ngrams"]


def test_ngram_repeated_within_one_record_stays_below_the_floor():
    # Document frequency: the same 5-gram twice in a single record counts once,
    # so it never reaches the 2-record discovery floor.
    rep = phrases.phrase_report([f"{GRAM} and then {GRAM} again"])
    assert rep["recurring_ngrams"] == []


def test_discovery_sees_non_ascii_words():
    shared = "les poules méritent une vie décente"
    rep = phrases.phrase_report([f"{shared} un", f"{shared} deux"])
    assert any("méritent" in row["phrase"] for row in rep["recurring_ngrams"])


def test_discovery_floor_is_a_ceiling_at_scale():
    # 50 records → floor = ceil(2.5) = 3: a phrase in only 2 of 50 (4%) is style,
    # not a template, and must not be reported.
    texts = [f"{GRAM} in record one", f"{GRAM} in record two"] + \
            [f"filler text number {i} unlike all other records" for i in range(48)]
    rep = phrases.phrase_report(texts)
    assert all(GRAM not in row["phrase"] for row in rep["recurring_ngrams"])


def test_ngram_in_only_one_record_is_not_reported():
    rep = phrases.phrase_report([f"{GRAM} once", "different text entirely here now"])
    assert all(row["phrase"] != GRAM for row in rep["recurring_ngrams"])


# ---------------------------------------------------------------- verdicts

def test_empty_corpus_is_na():
    rep = phrases.phrase_report([])
    assert rep == {"n": 0, "lexicon_hits": {}, "recurring_ngrams": [], "verdict": "NA"}


def test_distinct_texts_are_good():
    rep = phrases.phrase_report(["Hens need room to roam.",
                                 "Fish farms crowd their tanks badly.",
                                 "Insect welfare is hard to measure."])
    assert rep["verdict"] == "GOOD"


def test_lexicon_hits_within_tolerance_are_ok():
    # A known tic in 2 of 3 records: no longer GOOD, but within the OK ceiling.
    rep = phrases.phrase_report(["It's worth noting hens suffer here.",
                                 "Also, it's worth noting fish do too.",
                                 "A clean response about insect farms."])
    assert rep["verdict"] == "OK"


def test_corpus_wide_shared_ngram_is_bad():
    rep = phrases.phrase_report([f"{GRAM} over fence one",
                                 f"{GRAM} over fence two",
                                 f"{GRAM} over fence three"])
    assert rep["verdict"] == "BAD"


# ---------------------------------------------------------------- record helper

def test_assistant_text_joins_only_assistant_turns():
    record = {"messages": [{"role": "user", "content": "user words"},
                           {"role": "assistant", "content": "first reply"},
                           {"role": "user", "content": "more user words"},
                           {"role": "assistant", "content": "second reply"}]}
    text = phrases.assistant_text(record)
    assert "first reply" in text and "second reply" in text
    assert "user words" not in text
