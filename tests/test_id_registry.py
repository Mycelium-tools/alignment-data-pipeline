"""Stable content-keyed id registry: assignment, reuse, persistence."""

from dad_pipeline.id_registry import IdRegistry, prompt_fingerprint, scenario_fingerprint


def test_assigns_incrementing_ids_and_reuses_same_content(tmp_path):
    reg = IdRegistry(tmp_path / "id_registry.json")
    assert reg.assign("scenario", "fp-A") == 1
    assert reg.assign("scenario", "fp-B") == 2
    assert reg.assign("scenario", "fp-A") == 1   # seen content keeps its id
    assert reg.assign("scenario", "fp-C") == 3   # new content counts up


def test_kinds_are_independent(tmp_path):
    reg = IdRegistry(tmp_path / "id_registry.json")
    assert reg.assign("scenario", "x") == 1
    assert reg.assign("prompt", "x") == 1        # separate id space per kind


def test_persists_and_keeps_counting_across_instances(tmp_path):
    path = tmp_path / "id_registry.json"
    reg = IdRegistry(path)
    reg.assign("scenario", "fp-A")
    reg.assign("scenario", "fp-B")
    reg.save()
    # a fresh instance (a later "run") loads the file and does not reset
    reg2 = IdRegistry(path)
    assert reg2.assign("scenario", "fp-A") == 1  # stable across runs
    assert reg2.assign("scenario", "fp-C") == 3  # keeps counting up


def test_fingerprints_ignore_ids_and_normalize_whitespace():
    s1 = {"scenario_id": "S-001", "scenario_gid": "S-0007", "domain": ["x"], "conflict": "c"}
    s2 = {"scenario_id": "S-999", "domain": ["x"], "conflict": "c"}
    assert scenario_fingerprint(s1) == scenario_fingerprint(s2)  # own ids don't affect identity
    assert prompt_fingerprint("hello   world\n") == prompt_fingerprint("hello world")


def test_corrupt_registry_starts_fresh(tmp_path):
    path = tmp_path / "id_registry.json"
    path.write_text("not json{{")
    reg = IdRegistry(path)
    assert reg.assign("scenario", "fp") == 1
