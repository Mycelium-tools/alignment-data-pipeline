"""axes_io: comment-preserving round-trip editing of evals/dad_axes.yaml.

The editor must never destroy the file's documentation: the header block, the
MOCKUP quota comments, and the analysis-block commentary all survive a load →
dump cycle. Byte-identity is guaranteed at the fixed point (the first dump may
re-wrap long flow lists once — ruamel re-emits multi-line flow sequences)."""

from pathlib import Path

from evals.holistic import axes_io

REAL_AXES = Path(__file__).resolve().parents[1] / "evals" / "dad_axes.yaml"

SMALL = """\
# header comment — must survive
fields:
  - name: direction
    kind: single
    derived_from: response
    prompt_hint: Which way it corrected.
    values: [Under-weighting, Over-weighting, Mixed]
    target: {band_each: [0.25, 0.40]}   # MOCKUP: thirds
analysis:
  analyzers: [distribution]   # trailing analysis comment
"""


def test_small_file_roundtrips_byte_identical():
    doc = axes_io.load_text(SMALL)
    assert axes_io.dump_text(doc) == SMALL


def test_real_axes_file_dump_is_idempotent_and_keeps_comments():
    once = axes_io.dump_text(axes_io.load_doc(REAL_AXES))
    twice = axes_io.dump_text(axes_io.load_text(once))
    assert once == twice                              # fixed point
    assert once.startswith("# DAD extraction schema")  # header block kept
    assert "# MOCKUP: every taxa category present" in once
    assert "# MOCKUP quota — tune later" in once
    assert "important_pairs" in once                  # analysis block kept
    assert "  - name: language" in once               # block-item style kept
    assert "    kind: free" in once


def test_save_doc_writes_the_dump(tmp_path):
    p = tmp_path / "axes.yaml"
    doc = axes_io.load_text(SMALL)
    axes_io.save_doc(doc, p)
    assert p.read_text() == axes_io.dump_text(doc)


def test_axes_path_points_at_the_canonical_file():
    assert axes_io.AXES_PATH == REAL_AXES


def test_registry_from_doc_builds_real_fields():
    reg = axes_io.registry_from_doc(axes_io.load_doc(REAL_AXES))
    assert "direction" in reg.names()
    assert reg.get("direction").values == ("Under-weighting", "Over-weighting", "Mixed")


def test_validate_doc_ok_on_the_real_file():
    assert axes_io.validate_doc(axes_io.load_doc(REAL_AXES)) == []


def test_validate_doc_rejects_non_mapping_or_missing_fields():
    for bad in (None, axes_io.load_text("- x"), axes_io.load_text("hello"), {},
                {"fields": []}):
        errs = axes_io.validate_doc(bad)
        assert errs and "mapping" in errs[0] and "fields" in errs[0]


def test_structurally_editable_gates_the_editor_shape():
    for bad in (None, [], {}, {"fields": [{"kind": "single"}]},
                {"fields": [{"name": ["a"]}]}):
        assert not axes_io.structurally_editable(bad)
    assert axes_io.structurally_editable(axes_io.load_doc(REAL_AXES))


def test_validate_doc_rejects_non_mapping_analysis():
    doc = axes_io.load_text(SMALL)
    doc["analysis"] = ["oops"]
    errs = axes_io.validate_doc(doc)
    assert errs and "analysis" in errs[0] and "mapping" in errs[0]


def test_validate_doc_catches_unhashable_field_name():
    doc = axes_io.load_text(SMALL)
    doc["fields"][0]["name"] = ["not", "a", "string"]
    errs = axes_io.validate_doc(doc)
    assert errs   # TypeError from the registry build, not a crash


def test_validate_doc_rejects_yaml_the_pipeline_loader_cannot_read():
    class Weird:
        pass

    doc = axes_io.load_text(SMALL)
    # An object ruamel's round-trip dumper cannot faithfully represent as plain
    # YAML PyYAML's safe_load can parse back — must not raise, must error out.
    doc["fields"][0]["prompt_hint"] = Weird()
    errs = axes_io.validate_doc(doc)
    assert errs and "readable by the pipeline's loader" in errs[0]


def test_validate_doc_reports_bad_kind_with_locator():
    doc = axes_io.load_text(SMALL)
    doc["fields"][0]["kind"] = "banana"
    errs = axes_io.validate_doc(doc)
    assert len(errs) == 1
    assert "fields[0]" in errs[0] and "banana" in errs[0]


def test_validate_doc_reports_quota_naming_a_missing_value():
    doc = axes_io.load_text(SMALL)
    doc["fields"][0]["target"] = {"min_share": {"Nope": 0.2}}
    errs = axes_io.validate_doc(doc)
    assert errs and "Nope" in errs[0]


def test_set_attr_edits_in_place_and_keeps_neighbor_comments():
    doc = axes_io.load_text(SMALL)
    axes_io.set_attr(doc, "direction", "prompt_hint", "New hint.")
    out = axes_io.dump_text(doc)
    assert "New hint." in out
    assert out.startswith("# header comment — must survive")
    assert "# MOCKUP: thirds" in out          # sibling inline comment kept


def test_set_attr_drops_keys_back_to_default():
    doc = axes_io.load_text(SMALL)
    axes_io.set_attr(doc, "direction", "required", False)
    assert axes_io.field_entry(doc, "direction")["required"] is False
    axes_io.set_attr(doc, "direction", "required", True)   # back to default
    assert "required" not in axes_io.field_entry(doc, "direction")


def test_set_values_prunes_quota_keys_for_removed_values():
    doc = axes_io.load_text(SMALL)
    axes_io.set_target(doc, "direction", {"min_share": {"Mixed": 0.2}})
    pruned = axes_io.set_values(doc, "direction", ["Under-weighting", "Over-weighting"])
    assert pruned == ["Mixed"]
    assert axes_io.field_entry(doc, "direction").get("target") in (None, {},)
    assert axes_io.validate_doc(doc) == []


def test_set_target_none_removes_the_key():
    doc = axes_io.load_text(SMALL)
    axes_io.set_target(doc, "direction", None)
    assert "target" not in axes_io.field_entry(doc, "direction")


def test_structural_edits_preserve_comments():
    doc = axes_io.load_text(SMALL)
    axes_io.add_field(doc, "stakes")
    axes_io.move_field(doc, "stakes", -1)
    axes_io.delete_field(doc, "stakes")
    out = axes_io.dump_text(doc)
    assert axes_io.field_names(doc) == ["direction"]
    assert out.startswith("# header comment — must survive")
    assert "# MOCKUP: thirds" in out


def test_add_delete_move_field():
    doc = axes_io.load_text(SMALL)
    axes_io.add_field(doc, "stakes")
    assert axes_io.field_names(doc) == ["direction", "stakes"]
    axes_io.move_field(doc, "stakes", -1)
    assert axes_io.field_names(doc) == ["stakes", "direction"]
    axes_io.move_field(doc, "stakes", -1)                    # clamped at top
    assert axes_io.field_names(doc) == ["stakes", "direction"]
    axes_io.delete_field(doc, "stakes")
    assert axes_io.field_names(doc) == ["direction"]
    assert axes_io.validate_doc(doc) == []


def test_add_field_rejects_duplicates():
    import pytest
    doc = axes_io.load_text(SMALL)
    with pytest.raises(ValueError):
        axes_io.add_field(doc, "direction")


def _pair():
    return axes_io.load_text(SMALL), axes_io.load_text(SMALL)


def test_classify_none_for_untouched_draft():
    old, new = _pair()
    assert axes_io.classify_change(old, new) == "none"


def test_classify_identity_for_hint_values_and_reorder():
    old, new = _pair()
    axes_io.set_attr(new, "direction", "prompt_hint", "Different.")
    assert axes_io.classify_change(old, new) == "identity"

    old, new = _pair()
    axes_io.add_field(old, "extra"), axes_io.add_field(new, "extra")
    axes_io.move_field(new, "extra", -1)                     # reorder only
    assert axes_io.classify_change(old, new) == "identity"


def test_classify_quota_only_for_target_edits():
    old, new = _pair()
    axes_io.set_target(new, "direction", {"require_all_values": True})
    assert axes_io.classify_change(old, new) == "quota_only"


def test_classify_analysis_only_for_analyzer_edits():
    old, new = _pair()
    new["analysis"]["analyzers"] = ["distribution", "evenness"]
    assert axes_io.classify_change(old, new) == "analysis_only"


def test_classify_mixed_edit_is_identity():
    old, new = _pair()
    axes_io.set_attr(new, "direction", "prompt_hint", "Different.")
    axes_io.set_target(new, "direction", {"require_all_values": True})
    assert axes_io.classify_change(old, new) == "identity"


PAIRED = SMALL.replace(
    "analyzers: [distribution]   # trailing analysis comment",
    "analyzers: [distribution]\n  params:\n    important_pairs:\n      - [direction, taxa_category]",
).replace(
    "fields:",
    "fields:\n  - name: taxa_category\n    kind: single\n    values: [farmed, wild]",
)


def _kinds(ws):
    return sorted(w["kind"] for w in ws)


def test_renaming_an_important_pairs_member_warns():
    old, new = axes_io.load_text(PAIRED), axes_io.load_text(PAIRED)
    axes_io.set_attr(new, "taxa_category", "name", "taxa")
    ws = axes_io.coupling_warnings(old, new)
    assert "important_pairs" in _kinds(ws)
    assert "reserved" in _kinds(ws)          # taxa_category is also reserved
    assert "generation_key" in _kinds(ws)    # and a generation annotation key


def test_deleting_an_important_pairs_member_warns():
    old, new = axes_io.load_text(PAIRED), axes_io.load_text(PAIRED)
    axes_io.delete_field(new, "taxa_category")
    assert "important_pairs" in _kinds(axes_io.coupling_warnings(old, new))


def test_deleting_a_generation_key_axis_warns():
    old, new = axes_io.load_text(PAIRED), axes_io.load_text(PAIRED)
    axes_io.delete_field(new, "taxa_category")
    assert "generation_key" in _kinds(axes_io.coupling_warnings(old, new))


def test_untouched_draft_has_no_warnings():
    old, new = axes_io.load_text(PAIRED), axes_io.load_text(PAIRED)
    assert axes_io.coupling_warnings(old, new) == []


def test_renames_are_detected_positionally():
    old, new = axes_io.load_text(PAIRED), axes_io.load_text(PAIRED)
    axes_io.set_attr(new, "taxa_category", "name", "taxa")
    assert axes_io.renames(old, new) == [("taxa_category", "taxa")]
    assert axes_io.renames(old, old) == []


def test_update_important_pairs_rewrites_renamed_member():
    doc = axes_io.load_text(PAIRED)
    axes_io.update_important_pairs(doc, "taxa_category", "taxa")
    assert axes_io.dump_text(doc).count("taxa_category") == 1   # only the field name


def test_coupling_warnings_tolerates_malformed_analysis_block():
    old, new = axes_io.load_text(PAIRED), axes_io.load_text(PAIRED)
    new["analysis"] = ["oops"]
    assert axes_io.coupling_warnings(old, new) == []


def test_stale_and_prune_important_pairs():
    doc = axes_io.load_text(PAIRED)
    assert axes_io.stale_important_pairs(doc) == []
    axes_io.delete_field(doc, "taxa_category")
    assert axes_io.stale_important_pairs(doc) == [["direction", "taxa_category"]]
    assert axes_io.prune_important_pairs(doc) == 1
    assert axes_io.stale_important_pairs(doc) == []


def test_save_text_writes_atomically_named_content(tmp_path):
    p = tmp_path / "prompt.txt"
    p.write_text("old")
    axes_io.save_text("new prompt body\n", p)
    assert p.read_text() == "new prompt body\n"
    assert not list(tmp_path.glob("*.tmp*"))          # no temp litter
