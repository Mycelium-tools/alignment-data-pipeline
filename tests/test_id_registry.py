"""Stable content-keyed id registry: assignment, reuse, persistence."""

from dad_pipeline.id_registry import (IdRegistry, example_fingerprint, prompt_fingerprint,
                                      registry_path, response_fingerprint,
                                      scenario_fingerprint)


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


def test_gid_formats_with_kind_prefix_and_reuses(tmp_path):
    reg = IdRegistry(tmp_path / "id_registry.json")
    assert reg.gid("response", "fp-A") == "R-0001"
    assert reg.gid("plain", "fp-A") == "C-0001"    # separate id space per kind
    assert reg.gid("example", "fp-A") == "E-0001"
    assert reg.gid("response", "fp-A") == "R-0001"  # seen content keeps its id
    assert reg.gid("response", "fp-B") == "R-0002"
    assert reg.gid("scenario", "fp-A") == "S-0001"
    assert reg.gid("prompt", "fp-A") == "P-0001"


def test_response_and_example_fingerprints_normalize_whitespace():
    assert response_fingerprint("a  b\n") == response_fingerprint("a b")
    assert example_fingerprint("u ", "a\n") == example_fingerprint("u", "a")
    # the pair is ordered — a swapped user/assistant is a different example
    assert example_fingerprint("u", "a") != example_fingerprint("a", "u")


def test_registry_path_walks_up_to_the_runs_root(tmp_path):
    stage_dir = tmp_path / "outputs" / "dad" / "runs" / "2026-07-01_00-00_x" / "step2"
    assert registry_path(stage_dir) == tmp_path / "outputs" / "dad" / "id_registry.json"
    # non-standard layouts (bare tmp dirs in tests) keep the registry local
    assert registry_path(tmp_path / "bare") == tmp_path / "bare" / "id_registry.json"
