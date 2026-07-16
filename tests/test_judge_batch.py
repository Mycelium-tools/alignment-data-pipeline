"""Pure helpers of the batch-judge page that protect paid work: the skip logic
(needs_judging — whether a record is re-paid), partial-panel merging
(merge_results — whether other models' verdicts survive a re-judge), the
one-row-per-record invariant (upsert_row), and the cost estimate. All
plain-dict and offline; the streamlit UI around them is not tested."""

import pytest

from viewer.ui_pages import judge_batch


def _row(models: list[str]) -> dict:
    return {"record_id": "r1",
            "panel": {"results": [{"model": m, "verdict": {"ok": True}}
                                  for m in models]}}


# ---------------------------------------------------------------- needs_judging

def test_unjudged_record_needs_judging():
    assert judge_batch.needs_judging(None, ["m1"], rejudge=False)


def test_fully_judged_record_is_skipped():
    assert not judge_batch.needs_judging(_row(["m1", "m2"]), ["m1"], rejudge=False)


def test_model_missing_from_panel_forces_judging():
    assert judge_batch.needs_judging(_row(["m1"]), ["m1", "m2"], rejudge=False)


def test_rejudge_overrides_skip():
    assert judge_batch.needs_judging(_row(["m1"]), ["m1"], rejudge=True)


def test_errored_result_still_counts_as_judged_without_rejudge():
    # An errored model is still present in the row, so the skip logic keeps it —
    # re-running errors goes through the re-judge checkbox (with the
    # prev_verdict=error filter), never a silent re-pay.
    row = {"record_id": "r1",
           "panel": {"results": [{"model": "m1", "verdict": None, "error": "boom"}]}}
    assert not judge_batch.needs_judging(row, ["m1"], rejudge=False)
    assert judge_batch.needs_judging(row, ["m1"], rejudge=True)


# ---------------------------------------------------------------- merge_results

def test_merge_replaces_selected_models_and_keeps_the_rest():
    old = [{"model": "m1", "verdict": "old"}, {"model": "m2", "verdict": "keep"}]
    new = [{"model": "m1", "verdict": "new"}]
    merged = judge_batch.merge_results(old, new, ["m1"])
    assert sorted(merged, key=lambda r: r["model"]) == [
        {"model": "m1", "verdict": "new"}, {"model": "m2", "verdict": "keep"}]


def test_merge_adds_a_model_the_old_panel_never_ran():
    old = [{"model": "m1", "verdict": "keep"}]
    new = [{"model": "m3", "verdict": "new"}]
    assert judge_batch.merge_results(old, new, ["m3"]) == [
        {"model": "m1", "verdict": "keep"}, {"model": "m3", "verdict": "new"}]


# ---------------------------------------------------------------- upsert_row

def test_upsert_replaces_existing_row_in_place():
    rows = [{"record_id": "a", "v": 1}, {"record_id": "b", "v": 1}]
    out = judge_batch.upsert_row(rows, {"record_id": "a", "v": 2})
    assert out == [{"record_id": "a", "v": 2}, {"record_id": "b", "v": 1}]


def test_upsert_appends_a_new_record():
    out = judge_batch.upsert_row([{"record_id": "a"}], {"record_id": "b"})
    assert [r["record_id"] for r in out] == ["a", "b"]


def test_upsert_never_duplicates_a_record_id():
    rows: list[dict] = []
    rows = judge_batch.upsert_row(rows, {"record_id": "a", "v": 1})
    rows = judge_batch.upsert_row(rows, {"record_id": "a", "v": 2})
    assert rows == [{"record_id": "a", "v": 2}]


# ---------------------------------------------------------------- estimate_cost

def test_estimate_cost_sums_per_model_in_and_out_rates():
    pricing = {"m1": (1.00, 2.00), "m2": (10.00, 20.00)}
    cost = judge_batch.estimate_cost(2, ["m1", "m2"], pricing,
                                     in_tokens=1_000_000, out_tokens=500_000)
    # per record: m1 = 1·1 + 0.5·2 = 2; m2 = 1·10 + 0.5·20 = 20; ×2 records
    assert cost == pytest.approx(2 * 2.0 + 2 * 20.0)


def test_estimate_cost_unpriced_model_falls_back_to_sonnet_rates():
    cost = judge_batch.estimate_cost(1, ["mystery"], {},
                                     in_tokens=1_000_000, out_tokens=1_000_000)
    assert cost == pytest.approx(3.00 + 15.00)
