"""Tests for sdf_pipeline/composition.py — deterministic axis assignments."""

from sdf_pipeline import composition
from shared import constitution_loader

N_PRINCIPLES = len(constitution_loader.load_principles())


def test_assignments_are_deterministic():
    a = composition.assign_axes(3, 2, 4, N_PRINCIPLES)
    b = composition.assign_axes(3, 2, 4, N_PRINCIPLES)
    assert a == b
    assert a != composition.assign_axes(3, 3, 4, N_PRINCIPLES)


def test_assignment_values_are_valid():
    for t in range(8):
        for i in range(4):
            ax = composition.assign_axes(t, i, 4, N_PRINCIPLES)
            assert ax["domain"] in composition.DOMAINS
            assert ax["outcome"] in composition.OUTCOMES
            assert ax["stance"] in composition.STANCES
            assert ax["explicitness"] in composition.EXPLICITNESS
            assert ax["principles"] and all(1 <= n <= N_PRINCIPLES for n in ax["principles"])
            assert len(set(ax["principles"])) == len(ax["principles"])


def test_grid_covers_all_domains_and_principles():
    # the default 8 types x 4 subtypes grid must exercise every domain and
    # every principle at least once — coverage is the whole point
    domains, principles = set(), set()
    for t in range(8):
        for i in range(4):
            ax = composition.assign_axes(t, i, 4, N_PRINCIPLES)
            domains.add(ax["domain"])
            principles.update(ax["principles"])
    assert domains == set(composition.DOMAINS)
    assert principles == set(range(1, N_PRINCIPLES + 1))


def test_render_assignment_tolerates_legacy_records():
    assert composition.render_assignment({"subtype_id": "0_0"}, {}) == ""


def test_render_assignment_names_the_principles():
    names = {n: f"principle-name-{n}" for n in range(1, N_PRINCIPLES + 1)}
    ax = composition.assign_axes(0, 0, 4, N_PRINCIPLES)
    text = composition.render_assignment(ax, names)
    assert "Assignment" in text and ax["domain"] in text
    for n in ax["principles"]:
        assert f"principle {n} (principle-name-{n})" in text
