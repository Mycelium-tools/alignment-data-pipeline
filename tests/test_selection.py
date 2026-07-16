"""Shared, pure selection grammar: filter a run's records by any categorical facet,
then pick a subset (all / first-N / range / random-N / hand-pick). Reused by the
holistic CLI, the quality-judge CLI, and the viewer batch page — so it must be pure
and deterministic."""

from evals import selection

ROWS = [
    {"record_id": "a", "taxa_category": "farmed", "direction": "Under-weighting",
     "domain": ["Food & Cooking"]},
    {"record_id": "b", "taxa_category": "wild", "direction": "Over-weighting",
     "domain": ["Wildlife Management", "Public Policy / Law"]},
    {"record_id": "c", "taxa_category": "farmed", "direction": "Over-weighting",
     "domain": ["Food & Cooking"]},
    {"record_id": "d", "taxa_category": "edge-of-sentience", "direction": "Mixed",
     "domain": ["Research"]},
]


# ---------------------------------------------------------------- filtering

def test_filter_by_a_single_facet():
    ids = [r["record_id"] for r in selection.filter_records(ROWS, {"taxa_category": {"farmed"}})]
    assert ids == ["a", "c"]


def test_filter_ANDs_multiple_facets():
    out = selection.filter_records(
        ROWS, {"taxa_category": {"farmed"}, "direction": {"Over-weighting"}})
    assert [r["record_id"] for r in out] == ["c"]


def test_filter_matches_any_element_of_a_list_valued_field():
    out = selection.filter_records(ROWS, {"domain": {"Public Policy / Law"}})
    assert [r["record_id"] for r in out] == ["b"]


def test_empty_filter_returns_everything_in_order():
    assert [r["record_id"] for r in selection.filter_records(ROWS, {})] == ["a", "b", "c", "d"]


def test_filter_accepts_a_bare_string_facet_value_not_just_a_collection():
    # A scalar string must not be treated as a set of characters.
    out = selection.filter_records(ROWS, {"taxa_category": "wild"})
    assert [r["record_id"] for r in out] == ["b"]


# ---------------------------------------------------------------- picking

def test_pick_first_n():
    assert selection.pick_subset(["a", "b", "c", "d"], "First N", n=2) == ["a", "b"]


def test_pick_range_is_1_based_inclusive():
    assert selection.pick_subset(["a", "b", "c", "d"], "Range", start=2, end=3) == ["b", "c"]


def test_pick_random_n_is_seed_deterministic_and_order_preserving():
    ids = ["a", "b", "c", "d"]
    first = selection.pick_subset(ids, "Random N", n=2, seed=7)
    again = selection.pick_subset(ids, "Random N", n=2, seed=7)
    assert first == again
    assert first == [i for i in ids if i in set(first)]   # original order preserved


def test_pick_handpick_keeps_only_named_ids_in_order():
    assert selection.pick_subset(["a", "b", "c", "d"], "Hand-pick",
                                 handpicked=["c", "a"]) == ["a", "c"]


def test_pick_all_is_the_default():
    assert selection.pick_subset(["a", "b"], "All") == ["a", "b"]


def test_random_n_never_returns_more_than_n_even_with_duplicate_ids():
    ids = ["a", "a", "b", "c"]                 # defensive: dup ids must not leak
    out = selection.pick_subset(ids, "Random N", n=2, seed=1)
    assert len(out) == 2
    assert len(set(out)) == 2


# ---------------------------------------------------------------- composition

def test_select_composes_filter_then_pick_and_returns_ids():
    ids = selection.select(ROWS, where={"direction": {"Over-weighting"}},
                           mode="First N", n=1)
    assert ids == ["b"]


# ---------------------------------------------------------------- CLI grammar

def test_parse_where_splits_axis_and_comma_values():
    where = selection.parse_where(["taxa_category=edge-of-sentience,wild",
                                   "direction=Over-weighting"])
    assert where == {"taxa_category": {"edge-of-sentience", "wild"},
                     "direction": {"Over-weighting"}}


def test_parse_where_merges_repeated_flags_for_the_same_axis():
    where = selection.parse_where(["taxa_category=farmed", "taxa_category=wild"])
    assert where == {"taxa_category": {"farmed", "wild"}}


def test_parse_where_rejects_malformed_entries():
    import pytest
    with pytest.raises(ValueError, match="--where"):
        selection.parse_where(["taxa_category"])            # no '='
    with pytest.raises(ValueError, match="--where"):
        selection.parse_where(["=farmed"])                  # empty axis
    with pytest.raises(ValueError, match="--where"):
        selection.parse_where(["taxa_category="])           # empty values
    assert selection.parse_where([]) == {}
    assert selection.parse_where(None) == {}


def test_parse_ids_splits_and_strips():
    assert selection.parse_ids("a, b,c") == ["a", "b", "c"]
    assert selection.parse_ids(None) is None
    assert selection.parse_ids("") is None


def test_apply_cli_selection_filters_records_by_the_index_facets():
    # corpus records carry no facets — the where matches the separate tag index
    records = [{"record_id": r["record_id"], "messages": []} for r in ROWS]
    out = selection.apply_cli_selection(
        records, index={r["record_id"]: r for r in ROWS},
        where={"direction": {"Over-weighting"}})
    assert [r["record_id"] for r in out] == ["b", "c"]


def test_apply_cli_selection_where_without_index_matches_the_records_themselves():
    out = selection.apply_cli_selection(ROWS, where={"taxa_category": {"farmed"}})
    assert [r["record_id"] for r in out] == ["a", "c"]


def test_apply_cli_selection_ids_then_limit_then_sample_compose():
    records = [{"record_id": i} for i in "abcdef"]
    picked = selection.apply_cli_selection(records, ids=["a", "c", "e", "f"], limit=2)
    assert [r["record_id"] for r in picked] == ["a", "c"]
    sampled = selection.apply_cli_selection(records, sample=2, seed=3)
    again = selection.apply_cli_selection(records, sample=2, seed=3)
    assert sampled == again and len(sampled) == 2
    # sampled records keep original corpus order
    order = [r["record_id"] for r in records]
    assert [r["record_id"] for r in sampled] == sorted(
        [r["record_id"] for r in sampled], key=order.index)


def test_apply_cli_selection_sample_returns_exactly_n_rows_with_duplicate_ids():
    # Sampling is positional: duplicate record_ids (a corrupt corpus) must not
    # re-expand one chosen id into several rows and blow past N.
    records = [{"record_id": "a"}, {"record_id": "a"}, {"record_id": "b"}]
    out = selection.apply_cli_selection(records, sample=1, seed=1)
    assert len(out) == 1


def test_nonneg_int_rejects_negative_flag_values():
    import argparse
    import pytest
    assert selection.nonneg_int("3") == 3
    assert selection.nonneg_int("0") == 0
    with pytest.raises(argparse.ArgumentTypeError, match="non-negative"):
        selection.nonneg_int("-40")


def test_apply_cli_selection_where_with_index_drops_unindexed_records():
    # a record with no tag row cannot match a facet filter — excluded, not crashed
    records = [{"record_id": "a"}, {"record_id": "zz-untagged"}]
    out = selection.apply_cli_selection(
        records, index={r["record_id"]: r for r in ROWS},
        where={"taxa_category": {"farmed"}})
    assert [r["record_id"] for r in out] == ["a"]
