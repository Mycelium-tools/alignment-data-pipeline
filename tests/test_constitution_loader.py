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


def test_welfare_principles_block_is_formatted_csv_only():
    block = constitution_loader.load_welfare_principles_block()
    assert block == constitution_loader.format_principles(constitution_loader.load_principles())
    # the lens is the bare block — neither constitution document rides along
    assert constitution_loader.load_constitution_claude() not in block
    assert constitution_loader.load_constitution_welfare_reading() not in block


def test_welfare_principles_block_honors_base_dir_and_csv_fallback(tmp_path):
    # snapshot dir with its own CSV: read from there
    snap = tmp_path / "constitution"
    snap.mkdir()
    (snap / constitution_loader.PRINCIPLES_FILENAME).write_text(
        "number,principle,constitution_summary,raw_text_from_constitution\n"
        "1,SNAP-PRINCIPLE,SNAP-SUMMARY,SNAP-QUOTE\n"
    )
    block = constitution_loader.load_welfare_principles_block(snap)
    assert "SNAP-PRINCIPLE" in block and 'Constitution: "SNAP-QUOTE"' in block

    # snapshot predating the CSV: falls back to the repo's live copy
    (snap / constitution_loader.PRINCIPLES_FILENAME).unlink()
    block = constitution_loader.load_welfare_principles_block(snap)
    assert block == constitution_loader.format_principles(constitution_loader.load_principles())
