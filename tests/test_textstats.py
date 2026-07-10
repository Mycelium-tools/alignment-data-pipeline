"""Unit tests for shared/textstats.py (fully offline)."""

from shared import textstats


class TestTrimUnfinished:
    def test_trims_midsentence_tail_back_to_last_boundary(self):
        body = "The committee reviewed the aquaculture welfare standards in detail."
        cut = body + " But the follow-up paragraph was cut mid wo"
        assert textstats.trim_unfinished(cut) == body

    def test_leaves_complete_text_alone(self):
        assert textstats.trim_unfinished("Ends cleanly.") == "Ends cleanly."
        assert textstats.trim_unfinished('He said "done."') == 'He said "done."'

    def test_conservative_when_boundary_in_first_half(self):
        # A short text whose only boundary is early: trimming would discard
        # more than half, so it is left alone.
        t = "Short. But this untrimmed tail runs on and on and on"
        assert textstats.trim_unfinished(t) == t

    def test_empty_and_whitespace(self):
        assert textstats.trim_unfinished("") == ""
        assert textstats.trim_unfinished("   ") == ""

    def test_ends_mid_sentence_flag(self):
        assert textstats.ends_mid_sentence("cut off mid")
        assert not textstats.ends_mid_sentence("finished.")
        assert not textstats.ends_mid_sentence("")

    def test_trailing_separator_is_not_mid_sentence(self):
        doc = "Monitoring will continue through the year.\n\n---"
        assert not textstats.ends_mid_sentence(doc)
        assert textstats.has_trailing_separator(doc)
        assert textstats.strip_trailing_separators(doc).endswith("year.")

    def test_separator_only_inside_text_untouched(self):
        doc = "Part one.\n---\nPart two continues here."
        assert textstats.strip_trailing_separators(doc) == doc
        assert not textstats.has_trailing_separator(doc)


class TestNormalizeForMatch:
    def test_collapses_whitespace_and_case(self):
        assert textstats.normalize_for_match("A  Farm\n Choice") == "a farm choice"

    def test_verbatim_quote_containment_survives_reflow(self):
        doc = "We chose the supplier because their handling  standards\nreduce stress on the birds."
        quote = "their handling standards reduce stress on the birds"
        assert textstats.normalize_for_match(quote) in textstats.normalize_for_match(doc)


class TestNearDupFilter:
    def test_drops_near_identical_keeps_first(self):
        a = "The quick brown fox jumps over the lazy dog near the barn today"
        texts = [a, a + "!", "Completely different subject about feed conversion ratios in trout farming"]
        keep, dropped = textstats.near_dup_filter(texts, 0.9)
        assert keep == [0, 2]
        assert dropped[0]["index"] == 1 and dropped[0]["kept_index"] == 0
        assert dropped[0]["similarity"] >= 0.9

    def test_no_threshold_hits_keeps_everything(self):
        texts = ["alpha beta gamma delta epsilon", "one two three four five six", "red green blue yellow purple"]
        keep, dropped = textstats.near_dup_filter(texts, 0.9)
        assert keep == [0, 1, 2] and dropped == []

    def test_empty_input(self):
        assert textstats.near_dup_filter([], 0.9) == ([], [])

    def test_deterministic_across_calls(self):
        texts = ["a b c d e f g h", "a b c d e f g h", "i j k l m n o p"]
        assert textstats.near_dup_filter(texts, 0.9) == textstats.near_dup_filter(texts, 0.9)

    def test_nearest_neighbor_sims_shape_and_selfmask(self):
        sims = textstats.nearest_neighbor_sims(["a b c d e", "a b c d e", "x y z w v"])
        assert len(sims) == 3
        assert sims[0] > 0.99  # its twin, not itself
        assert sims[2] < 0.5


class TestIncrementalNearDup:
    def test_matches_near_dup_filter_on_concatenated_stream(self):
        # streamed in two batches must drop exactly what the one-shot filter
        # drops on the concatenation (same keep-first semantics)
        a = "The quick brown fox jumps over the lazy dog near the barn today"
        batch1 = [a, "Completely different subject about trout feed conversion ratios"]
        batch2 = [a + "!", "Another wholly unrelated topic on solar panel installation angles"]
        flat_keep, _ = textstats.near_dup_filter(batch1 + batch2, 0.9)

        idx = textstats.IncrementalNearDup(0.9)
        k1, _ = idx.filter(batch1)
        k2, d2 = idx.filter(batch2)
        # batch1 both kept; batch2[0] is a's twin -> dropped, batch2[1] kept
        assert k1 == [0, 1]
        assert k2 == [1]
        assert d2[0]["index"] == 0 and d2[0]["similarity"] >= 0.9
        # equivalent to the one-shot filter: it keeps concat indices 0,1,3
        assert flat_keep == [0, 1, 3]

    def test_seed_texts_are_avoided_not_refiltered(self):
        seed = "The quick brown fox jumps over the lazy dog near the barn today"
        idx = textstats.IncrementalNearDup(0.9, seed_texts=[seed])
        keep, dropped = idx.filter([seed + "!", "unrelated content about greenhouse ventilation"])
        assert keep == [1]  # the seed's near-twin is dropped, the novel one kept
        assert dropped[0]["index"] == 0

    def test_buffer_grows_past_initial_capacity(self):
        # exercise the _add doubling path deterministically without 1000+ items
        idx = textstats.IncrementalNearDup(0.99)
        idx._kept = idx._kept[:2]  # shrink to force a grow after 2 keeps
        keep, _ = idx.filter([f"unique sentence number {i} about topic {i}" for i in range(5)])
        assert keep == [0, 1, 2, 3, 4]
        assert idx._count == 5
