"""The batch-judge page's selection seam (spec §12.2): one facet row per final
record — combined-index facets plus the computed prev_verdict status — feeding the
shared evals/selection.py grammar. Pure; the streamlit UI around it is not tested."""

from evals import selection
from viewer.ui_pages import judge_batch

FINALS = [{"record_id": "a"}, {"record_id": "b"}, {"record_id": "c"}]
INDEX = {
    "a": {"record_id": "a", "injection_used": "plain", "taxa_category": "farmed"},
    "b": {"record_id": "b", "injection_used": "deference", "taxa_category": "wild"},
    # c: never tagged, never annotated
}
SAVED = {"a": {"panel": {"consensus_aggregate": {"passing": False}}}}


def test_selection_rows_merge_facets_and_prev_verdict_in_finals_order():
    rows = judge_batch.selection_rows(FINALS, INDEX, SAVED)
    assert rows == [
        {"record_id": "a", "injection_used": "plain", "taxa_category": "farmed",
         "prev_verdict": "failed"},
        {"record_id": "b", "injection_used": "deference", "taxa_category": "wild",
         "prev_verdict": "not-yet-judged"},
        {"record_id": "c", "prev_verdict": "not-yet-judged"},
    ]


def test_selection_rows_compose_with_filter_records():
    rows = judge_batch.selection_rows(FINALS, INDEX, SAVED)
    out = selection.filter_records(rows, {"prev_verdict": {"not-yet-judged"},
                                          "taxa_category": {"wild"}})
    assert [r["record_id"] for r in out] == ["b"]


def test_selection_rows_do_not_mutate_the_index():
    judge_batch.selection_rows(FINALS, INDEX, SAVED)
    assert "prev_verdict" not in INDEX["a"]
