"""Tests for evals/openings_dad.py — the opening-shape audit.

The bucketing cases are real openers from the July 2026 smoke runs, so the
family regexes are pinned to the tics they were built to catch. Fully offline;
the embeddings path runs against the stub_embeddings seam.
"""

import json

import pytest

from evals import openings_dad
from shared import utils


# --- first-sentence extraction -------------------------------------------

def test_first_sentence_strips_markdown_and_stops_at_boundary():
    assert openings_dad.first_sentence(
        "**What's actually settled, and what isn't.** \"These are working dogs\"..."
    ) == "What's actually settled, and what isn't."
    # a leading markdown heading marker never reaches the bucketing regexes
    assert not openings_dad.first_sentence("## Heading\nMore text follows here.").startswith("#")


def test_first_sentence_plain():
    assert openings_dad.first_sentence("Keep the constraint. But before...") == "Keep the constraint."
    # no sentence boundary at all: falls back to a bounded prefix
    assert openings_dad.first_sentence("x" * 500).startswith("x")


# --- family bucketing: real openers from the July runs --------------------

@pytest.mark.parametrize("sentence,family", [
    ("You've basically answered your own question by asking it this precisely,"
     " but let's pull the threads.", "already-answered"),
    ("You already know the answer to your own question, which is why it feels sick.", "already-answered"),
    ("You've basically already diagnosed the problem correctly, which is the hard part.", "already-answered"),
    ("Here's how I'd take this apart.", "heres-the-x"),
    ("Here's the honest read: the fact-checker is right.", "heres-the-x"),
    ("Let's separate two questions you've folded together.", "lets-separate"),
    ("Two separate things are tangled together here.", "lets-separate"),
    ("This is a genuinely good opportunity for her.", "validation"),
    ("Good instinct to separate what's actually driving this.", "validation"),
    ("Your sister is right, and it's worth being precise about why.", "x-is-right"),
    ("You're not wrong, but I'd narrow the target.", "x-is-right"),
    ("You're framing this as a binary.", "reframe"),
    ("The actual decision here isn't \"which blurb is nicer\".", "reframe"),
    ("\"Wild-caught, and I'll tell you why.\"", "quoted-user"),
    ("No, I wouldn't sign it as written.", "direct-address-of-ask"),
    ("The strongest argument for running the unit again is the one nobody has made yet.", "other"),
])
def test_family_bucketing(sentence, family):
    assert openings_dad.family_of(sentence) == family


# --- report over a fake run dir -------------------------------------------

def _fake_run(tmp_path, drafts, finals=None):
    run = tmp_path / "run"
    (run / "step2").mkdir(parents=True)
    for r in drafts:
        utils.append_jsonl(r, run / "step2" / "responses.jsonl")
    if finals:
        (run / "step3").mkdir()
        (run / "final").mkdir()
        for i, (pid, text) in enumerate(finals):
            rid = f"rec-{i}"
            utils.append_jsonl({"record_id": rid, "prompt_id": pid, "sample_index": 0,
                                "rewritten_response": text}, run / "step3" / "rewrites.jsonl")
            utils.append_jsonl({"record_id": rid, "messages": [
                {"role": "user", "content": "u"}, {"role": "assistant", "content": text}]},
                run / "final" / "dad_corpus.jsonl")
    return run


def test_prompt_length_report_assigned_vs_realized(tmp_path, capsys):
    from dad_pipeline.step1_dilemmas import _LENGTH_BANDS

    run = tmp_path / "run"
    (run / "step1").mkdir(parents=True)
    lo, _hi = _LENGTH_BANDS["ramble"]
    records = [
        {"prompt_id": "AW-0001", "length_class": "2-3-sentences",
         "user_message": "Short and blunt. Two sentences."},
        {"prompt_id": "AW-0002", "length_class": "ramble",
         "user_message": "x" * (lo + 100)},                       # in band
        {"prompt_id": "AW-0003", "length_class": "ramble",
         "user_message": "way under the ramble band"},            # out of band
        {"prompt_id": "AW-0004", "user_message": "legacy record, no class"},
    ]
    for r in records:
        utils.append_jsonl(r, run / "step1" / "dilemmas.jsonl")

    stats = openings_dad.prompt_length_report(run)
    assert stats["n"] == 4
    assert sorted(stats["by_class"]) == ["2-3-sentences", "ramble"]
    assert stats["out_of_band"] == [("ramble", len("way under the ramble band"))]
    assert "outside band" in capsys.readouterr().out


def test_prompt_length_report_pre_dice_run_is_calm(tmp_path, capsys):
    run = tmp_path / "run"
    (run / "step1").mkdir(parents=True)
    utils.append_jsonl({"prompt_id": "AW-0001", "user_message": "old run"},
                       run / "step1" / "dilemmas.jsonl")
    stats = openings_dad.prompt_length_report(run)
    assert stats["n"] == 1 and not stats["by_class"]
    assert "pre-dice run" in capsys.readouterr().out


def test_card_echoes_detects_verbatim_wording_borrowing():
    card = "open with the factual crux the case turns on"
    assert openings_dad.card_echoes("The factual crux here is worth pinning down first.", card)
    assert not openings_dad.card_echoes("The evidence question comes before the ethics question.", card)
    # a run of pure function words shared with a card is not an echo
    assert not openings_dad.card_echoes(
        "Start with what is on the table.", "open with what is settled before what is contested")


def test_report_hint_echo_uses_stored_draws(tmp_path):
    card = "open with the factual crux the case turns on"
    drafts = [
        {"prompt_id": "AW-0001", "sample_index": 0, "opening_hints": card,
         "assistant_response": "The factual crux here decides everything. More."},
        {"prompt_id": "AW-0002", "sample_index": 0, "opening_hints": card,
         "assistant_response": "Start from the numbers in the report. More."},
    ]
    stats = openings_dad.report(_fake_run(tmp_path, drafts), "drafts")
    assert stats["hint_echo"] == {card: (1, 2)}


def test_report_counts_families_and_within_case_spread(tmp_path, capsys):
    drafts = [
        {"prompt_id": "AW-0001", "sample_index": 0,
         "assistant_response": "Here's the thing about the farm. More."},
        {"prompt_id": "AW-0001", "sample_index": 1,
         "assistant_response": "You've basically answered your own question. More."},
        {"prompt_id": "AW-0002", "sample_index": 0,
         "assistant_response": "Here's what I think is going on. More."},
    ]
    run = _fake_run(tmp_path, drafts)
    stats = openings_dad.report(run, "drafts")
    assert stats["n"] == 3
    assert stats["families"] == {"heres-the-x": 2, "already-answered": 1}
    assert stats["top_family"] == "heres-the-x"
    # AW-0001 has two samples with two distinct families
    assert stats["case_spread"] == {"AW-0001": "2/2 distinct"}
    assert "heres-the-x 2" in capsys.readouterr().out


def test_report_reads_finals_via_rewrite_audit(tmp_path):
    run = _fake_run(tmp_path, drafts=[], finals=[
        ("AW-0001", "Good instinct to check this before you file. More."),
        ("AW-0002", "The numbers in your message decide this one. More."),
    ])
    stats = openings_dad.report(run, "finals")
    assert stats["n"] == 2
    assert stats["families"] == {"validation": 1, "other": 1}


def test_report_empty_run_is_calm(tmp_path):
    run = tmp_path / "empty"
    run.mkdir()
    assert openings_dad.report(run, "drafts") == {"n": 0}
    assert openings_dad.report(run, "finals") == {"n": 0}


def test_embedding_report_uses_the_stubbed_seam(tmp_path, stub_embeddings, capsys):
    calls = stub_embeddings()
    drafts = [
        {"prompt_id": "AW-0001", "sample_index": 0, "assistant_response": "Same opener here. x"},
        {"prompt_id": "AW-0002", "sample_index": 0, "assistant_response": "Same opener here. y"},
    ]
    run = _fake_run(tmp_path, drafts)
    openings_dad.embedding_report(run, "drafts")
    # identical first sentences embed identically -> one pair above threshold
    assert len(calls) == 1
    assert calls[0]["texts"] == ["Same opener here.", "Same opener here."]
    assert "1 first-sentence pairs above" in capsys.readouterr().out
