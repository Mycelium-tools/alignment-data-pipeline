"""The Field registry is the pluggability core: adding, replacing, or removing an
extraction field must be a single registry call, and everything downstream (the
extraction prompt, validation) reads the current registry — nothing is hardcoded."""

import pytest

from evals.holistic import fields as F


# ---------------------------------------------------------------- Field.validate

def test_single_field_accepts_a_value_in_its_vocabulary():
    fld = F.Field(name="taxa", kind="single", values=("farmed", "wild"))
    ok, coerced = fld.validate("wild")
    assert ok is True
    assert coerced == "wild"


def test_single_field_rejects_a_value_outside_its_vocabulary():
    fld = F.Field(name="taxa", kind="single", values=("farmed", "wild"))
    ok, _ = fld.validate("dragon")
    assert ok is False


def test_multi_field_keeps_only_in_vocabulary_values_and_flags_unknowns():
    fld = F.Field(name="goals", kind="multi", values=("a", "b", "c"))
    ok, coerced = fld.validate(["a", "zzz", "c"])
    assert ok is False          # an unknown element makes the whole value invalid
    assert coerced == ["a", "c"]  # but the coerced value drops the unknown


def test_multi_field_dedups_repeated_values():
    fld = F.Field(name="tags", kind="multi", values=("a", "b"))
    ok, coerced = fld.validate(["a", "a", "b"])
    assert ok is True
    assert coerced == ["a", "b"]        # a multi field is a set of categories, not a bag


def test_bool_field_validates_booleans():
    fld = F.Field(name="flag", kind="bool")
    assert fld.validate(True) == (True, True)
    assert fld.validate("nope")[0] is False
    # quoted-string bools (some providers emit these) coerce to real bools
    assert fld.validate("false") == (True, False)
    assert fld.validate("True") == (True, True)


def test_free_field_accepts_any_string():
    fld = F.Field(name="lang", kind="free")
    ok, coerced = fld.validate("en")
    assert ok is True and coerced == "en"


# ---------------------------------------------------------------- registry

def test_add_then_get_and_all_preserve_insertion_order():
    reg = F.FieldRegistry()
    reg.add(F.Field(name="one", kind="free"))
    reg.add(F.Field(name="two", kind="free"))
    assert reg.names() == ["one", "two"]
    assert reg.get("two").name == "two"


def test_adding_a_duplicate_name_raises_unless_replace():
    reg = F.FieldRegistry()
    reg.add(F.Field(name="dup", kind="free"))
    with pytest.raises(ValueError):
        reg.add(F.Field(name="dup", kind="single", values=("x",)))


def test_replace_swaps_the_field_in_place():
    reg = F.FieldRegistry()
    reg.add(F.Field(name="dir", kind="single", values=("up", "down")))
    reg.replace(F.Field(name="dir", kind="single", values=("up", "down", "mixed")))
    assert reg.get("dir").values == ("up", "down", "mixed")


def test_remove_drops_the_field():
    reg = F.FieldRegistry()
    reg.add(F.Field(name="gone", kind="free"))
    reg.remove("gone")
    assert "gone" not in reg


def test_default_registry_is_non_empty_and_independent_per_call():
    a = F.default_fields()
    b = F.default_fields()
    assert len(a) > 0
    a.remove(a.names()[0])
    assert len(b) == len(a) + 1   # mutating one default registry never touches another
