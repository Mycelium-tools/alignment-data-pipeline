"""Tests for the mechanical checks in evals/audit_sdf.py (fully offline).

Only the pure-ish audit functions are tested (records in, report dict out);
the LLM pattern pass goes through shared.api.call_claude and is guarded by
the same conftest safety net as everything else.
"""

import json

from evals import audit_sdf


def _recs(*contents):
    return [{"doc_id": f"d{i}", "content": c, "language": "en"} for i, c in enumerate(contents)]


class TestMarkdownMetric:
    def test_counts_each_markdown_class(self):
        report = {}
        audit_sdf.audit_markdown(_recs(
            "# Heading\nplain prose follows here.",
            "Prose with **bold emphasis** inside.",
            "- a markdown bullet\n- another",
            "| a | b |\n| c | d |",
            "Entirely plain prose, no markup at all.",
        ), report)
        md = report["markdown"]
        assert md["# headings"] == 0.2
        assert md["**bold**"] == 0.2
        assert md["markdown bullets"] == 0.2
        assert md["tables"] == 0.2
        assert md["any_frac"] == 0.8

    def test_clean_corpus_scores_zero(self):
        report = {}
        audit_sdf.audit_markdown(_recs(
            "Plain running prose. Nothing fancy here at all.",
            "1. A plain-text enumeration is not markdown.\n2. Second item.",
        ), report)
        assert report["markdown"]["any_frac"] == 0.0

    def test_mid_text_dashes_are_not_bullets(self):
        report = {}
        audit_sdf.audit_markdown(_recs("A clause — set off with dashes — is fine.\nSo is a hy-phen."), report)
        assert report["markdown"]["markdown bullets"] == 0.0


class TestParseJsonBlock:
    def test_plain_and_fenced(self):
        assert audit_sdf._parse_json_block('[1, 2]') == [1, 2]
        assert audit_sdf._parse_json_block('```json\n{"a": 1}\n```') == {"a": 1}

    def test_recovers_first_block_from_trailing_prose(self):
        # the "Extra data" failure seen live: valid JSON followed by more text
        raw = '[{"pattern": "x"}]\n\nAdditionally, I noticed...'
        assert audit_sdf._parse_json_block(raw) == [{"pattern": "x"}]

    def test_recovers_json_after_leading_prose(self):
        raw = 'Here are the patterns:\n[{"pattern": "y"}]'
        assert audit_sdf._parse_json_block(raw) == [{"pattern": "y"}]


class TestTruncationAudit:
    def test_separates_mid_sentence_from_trailing_separator(self):
        report = {}
        audit_sdf.audit_length_truncation(_recs(
            "Complete sentence.",
            "Cut off mid wo",
            "Ends fine but with a rule.\n\n---",
        ), report)
        assert report["length"]["truncated"] == 1
        assert report["length"]["trailing_separator"] == 1
