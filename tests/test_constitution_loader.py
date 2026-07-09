"""Tests for shared/constitution_loader.py against the real constitution files."""

from shared import constitution_loader


def test_load_segments_assigns_sequential_principle_ids():
    segments = constitution_loader.load_segments()
    # CLAUDE.md contract: 16 sections mapped to principle_ids 0-15
    assert len(segments) == 16
    assert [s["principle_id"] for s in segments] == list(range(16))


def test_segments_have_nonempty_titles_and_content():
    for seg in constitution_loader.load_segments():
        assert seg["section_title"].strip()
        assert seg["content"].strip()


def test_meta_principle_ids_refer_to_real_segments():
    ids = {s["principle_id"] for s in constitution_loader.load_segments()}
    assert constitution_loader.META_PRINCIPLE_IDS <= ids


def test_segment_content_is_verbatim_from_source():
    seg = constitution_loader.load_segments()[1]
    assert seg["content"] in constitution_loader.load_constitution_welfare_reading()


def test_full_constitution_joins_preamble_and_both_documents():
    full = constitution_loader.load_full_constitution()
    claude = constitution_loader.load_constitution_claude()
    reading = constitution_loader.load_constitution_welfare_reading()
    assert "joins two complementary frameworks" in full
    assert claude in full
    assert reading in full
    assert full.index(claude) < full.index(reading)


def test_constitution_with_principles_joins_preamble_constitution_and_block():
    joined = constitution_loader.load_constitution_with_principles()
    claude = constitution_loader.load_constitution_claude()
    block = constitution_loader.format_principles(constitution_loader.load_principles())
    assert claude in joined
    assert block in joined
    assert joined.index(claude) < joined.index(block)
    # the sentient-beings reading must NOT ride along
    reading = constitution_loader.load_constitution_welfare_reading()
    assert reading not in joined


def test_constitution_with_principles_honors_base_dir_and_csv_fallback(tmp_path):
    # snapshot dir with its own constitution + CSV: both are read from there
    snap = tmp_path / "constitution"
    snap.mkdir()
    (snap / "constitution_claude.md").write_text("SNAP-CLAUDE")
    (snap / constitution_loader.PRINCIPLES_FILENAME).write_text(
        "number,principle,constitution_summary,raw_text_from_constitution\n"
        "1,SNAP-PRINCIPLE,SNAP-SUMMARY,SNAP-QUOTE\n"
    )
    joined = constitution_loader.load_constitution_with_principles(snap)
    assert "SNAP-CLAUDE" in joined
    assert "SNAP-PRINCIPLE" in joined

    # snapshot predating the CSV: principles fall back to the repo's live copy
    (snap / constitution_loader.PRINCIPLES_FILENAME).unlink()
    joined = constitution_loader.load_constitution_with_principles(snap)
    assert "SNAP-CLAUDE" in joined
    repo_block = constitution_loader.format_principles(constitution_loader.load_principles())
    assert repo_block in joined
