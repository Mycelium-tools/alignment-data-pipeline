"""Tests for evals/score_sdf.py's pure pieces (cell join + summary math).

The CLI loop mirrors score_dad.py and is exercised end-to-end by the judge tests;
here we pin the two functions with logic of their own: the layer2 cell join (wrong
join = every cell_adherence silently NA at $ per call) and the summary arithmetic.
"""

import json

import pytest

from evals import judge_sdf, score_sdf


@pytest.fixture
def run_dir(tmp_path):
    """A minimal run dir: final/sdf_corpus.jsonl + layer2/subtypes.jsonl."""
    (tmp_path / "layer2").mkdir()
    (tmp_path / "final").mkdir()
    subtype = {"subtype_id": "st-1", "type_id": 3, "type_name": "Blog post",
               "subtype_name": "Farm visit", "description": "d", "role": "welfare-topic",
               "tone": "literary", "register": "informal", "language": "en"}
    (tmp_path / "layer2" / "subtypes.jsonl").write_text(json.dumps(subtype) + "\n")
    corpus = tmp_path / "final" / "sdf_corpus.jsonl"
    corpus.write_text(json.dumps({"doc_id": "d-1", "subtype_id": "st-1", "content": "x"}) + "\n")
    return corpus


class TestLoadCells:
    def test_joins_cell_fields_by_subtype_id(self, run_dir):
        cells = score_sdf.load_cells(run_dir)
        assert set(cells) == {"st-1"}
        assert set(cells["st-1"]) == set(judge_sdf.CELL_FIELDS)
        assert cells["st-1"]["type_name"] == "Blog post"

    def test_missing_layer2_yields_empty(self, tmp_path):
        corpus = tmp_path / "final" / "sdf_corpus.jsonl"
        corpus.parent.mkdir()
        corpus.write_text("{}\n")
        assert score_sdf.load_cells(corpus) == {}


class TestSummarize:
    def test_counts_passes_exemplars_and_errors(self):
        rubric = judge_sdf.load_rubric(judge_sdf.DEFAULT_RUBRIC_PATH)
        ok = {"panel": {"document_words": 100, "results": [{
            "model": "m", "verdict": {"dimension_scores": {"realism": 8},
                                      "depicted_ai_alignment": "NA"},
            "aggregate": {"passing": True, "exemplar": True, "cell_mismatch": False,
                          "mean": 8.0},
        }]}}
        err = {"panel": {"judge_error": True, "document_words": 50,
                         "results": [{"model": "m", "verdict": None}]}}
        report = score_sdf.summarize([ok, ok, err], ["m"], rubric)
        m = report["models"]["m"]
        assert m["graded"] == 2 and m["judge_errors"] == 1
        assert m["pass_rate"] == 1.0 and m["exemplar_rate"] == 1.0
        assert m["depicted_ai_verdicts"] == {"NA": 2}
        assert report["consensus"]["error_rate"] == 0.333  # summarize rounds to 3dp


def test_retry_errors_keeps_errored_rows_outside_the_selection():
    # Twin of the score_dad guard: --retry-errors with --limit must not delete
    # errored verdicts for documents beyond the limit (they would never be
    # re-judged this run — the row would be gone forever).
    rows = [
        {"doc_id": "a", "panel": {"results": [{"model": "m", "verdict": None}]}},
        {"doc_id": "b", "panel": {"results": [{"model": "m", "verdict": None}]}},
        {"doc_id": "c", "panel": {"results": [{"model": "m", "verdict": {"ok": 1}}]}},
    ]
    kept = score_sdf.drop_retryable_errors(rows, selected_ids={"a"}, id_key="doc_id")
    assert [r["doc_id"] for r in kept] == ["b", "c"]
