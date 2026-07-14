"""Pure structural-form metrics over DAD assistant turns. A corpus whose replies
all open/close/shape the same way scores BAD; a varied one scores GOOD. Offline,
deterministic, no API."""

from evals.holistic import structural as S


def test_assistant_turns_keeps_only_assistant_content_in_order():
    rec = {"messages": [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"}]}
    assert S.assistant_turns(rec) == ["a1", "a2"]


def test_assistant_turns_empty_when_no_assistant_message():
    assert S.assistant_turns({"messages": [{"role": "user", "content": "u"}]}) == []


def test_first_and_last_sentence():
    text = "I understand your concern. Here is the middle. Ultimately it is your call."
    assert S.first_sentence(text) == "I understand your concern."
    assert S.last_sentence(text) == "Ultimately it is your call."


def test_opening_moves_flags_templated_openings_bad():
    same = ["I understand your concern about hens." for _ in range(10)]
    out = S.opening_moves([S.first_sentence(t) for t in same])
    assert out["verdict"] == "BAD"
    assert out["formulaic_frac"] >= 0.9
    assert out["dup_stems"]                      # a repeated 5-word stem is caught


def test_opening_moves_varied_openings_good():
    varied = ["Caged systems raise real welfare costs.",
              "Let's compare the two options directly.",
              "Egg pricing depends on several factors.",
              "Your budget is the first thing to pin down.",
              "Consumers rarely see the supply chain."]
    out = S.opening_moves(varied)
    assert out["verdict"] == "GOOD"


def test_closing_moves_flags_repeated_signoffs_bad():
    ends = ["Ultimately, the choice is yours." for _ in range(8)]
    out = S.closing_moves(ends)
    assert out["verdict"] == "BAD"


def test_scaffold_shape_flags_considerations_arc():
    templated = ["Here are three considerations:\n- cost\n- welfare\n- taste"
                 for _ in range(10)]
    out = S.scaffold_shape(templated)
    assert out["arc_frac"] >= 0.9
    assert out["verdict"] == "BAD"


def test_formatting_flags_pervasive_bold():
    bold = ["This is **very** important." for _ in range(10)]
    out = S.formatting(bold)
    assert out["bold_frac"] >= 0.9
    assert out["verdict"] == "BAD"


def test_length_stats_flags_truncation():
    truncated = ["This sentence just stops abruptly and never" for _ in range(10)]
    out = S.length_stats(truncated)
    assert out["truncated_frac"] == 1.0
    assert out["verdict"] == "BAD"


def test_recurring_flags_stock_phrase():
    texts = ["at the end of the day it depends" for _ in range(10)]
    out = S.recurring(texts)
    assert out["stock_hits"]
    assert out["verdict"] == "BAD"


def test_metrics_return_na_on_empty_input():
    for fn in (S.opening_moves, S.closing_moves, S.scaffold_shape,
               S.formatting, S.length_stats, S.recurring):
        out = fn([])
        assert out["n"] == 0
        assert out["verdict"] == "NA"
