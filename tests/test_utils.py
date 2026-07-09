"""Tests for shared/utils.py: JSONL I/O, prompts, RNG, run dirs, checkpoints,
and the parallel_map helper the SDF layers fan out on."""

import json
import random
import re
import time

import pytest

from shared import utils


class TestParallelMap:
    @pytest.mark.parametrize("workers", [1, 4])
    def test_maps_all_items(self, workers):
        assert list(utils.parallel_map(lambda x: x * 2, [1, 2, 3], workers)) == [2, 4, 6]

    def test_results_come_back_in_input_order(self):
        # First item finishes last; order must still follow the input, because
        # callers zip() results with items to write files and mark checkpoints.
        def slow_first(x):
            if x == 0:
                time.sleep(0.02)
            return x

        assert list(utils.parallel_map(slow_first, [0, 1, 2, 3], workers=4)) == [0, 1, 2, 3]

    def test_worker_exception_propagates(self):
        def boom(x):
            if x == 2:
                raise ValueError("worker failed")
            return x

        with pytest.raises(ValueError, match="worker failed"):
            list(utils.parallel_map(boom, [1, 2, 3], workers=2))


class TestJsonl:
    def test_save_load_roundtrip_preserves_records(self, tmp_path):
        records = [{"id": 1, "text": "héllo wörld — 🐙"}, {"id": 2, "nested": {"a": [1, 2]}}]
        path = tmp_path / "out" / "data.jsonl"
        utils.save_jsonl(records, path)
        assert utils.load_jsonl(path) == records

    def test_save_jsonl_does_not_escape_unicode(self, tmp_path):
        path = tmp_path / "data.jsonl"
        utils.save_jsonl([{"text": "🐟"}], path)
        assert "🐟" in path.read_text()

    def test_append_jsonl_extends_existing_file(self, tmp_path):
        path = tmp_path / "data.jsonl"
        utils.save_jsonl([{"id": 1}], path)
        utils.append_jsonl({"id": 2}, path)
        assert utils.load_jsonl(path) == [{"id": 1}, {"id": 2}]

    def test_load_jsonl_missing_file_returns_empty_list(self, tmp_path):
        assert utils.load_jsonl(tmp_path / "nope.jsonl") == []

    def test_load_jsonl_skips_blank_lines(self, tmp_path):
        path = tmp_path / "data.jsonl"
        path.write_text('{"id": 1}\n\n{"id": 2}\n\n')
        assert utils.load_jsonl(path) == [{"id": 1}, {"id": 2}]


class TestLoadPrompt:
    def test_renders_placeholders(self, tmp_path):
        tpl = tmp_path / "t.txt"
        tpl.write_text("Hello {name}, count={count}")
        assert utils.load_prompt(tpl, name="world", count=3) == "Hello world, count=3"

    def test_without_kwargs_returns_verbatim(self, tmp_path):
        tpl = tmp_path / "t.txt"
        tpl.write_text("Literal {braces} untouched")
        assert utils.load_prompt(tpl) == "Literal {braces} untouched"

    def test_missing_placeholder_raises(self, tmp_path):
        tpl = tmp_path / "t.txt"
        tpl.write_text("Hello {name}")
        with pytest.raises(KeyError):
            utils.load_prompt(tpl, other="x")


class TestSplitPrompt:
    def test_prefix_plus_rendered_rest_matches_load_prompt(self, tmp_path):
        tpl = tmp_path / "t.txt"
        tpl.write_text("HEAD {stable} MID {per_call} TAIL")
        prefix, rest = utils.split_prompt(tpl, "per_call", stable="lib")
        assert prefix == "HEAD lib MID "
        assert rest == "{per_call} TAIL"
        assert prefix + rest.format(per_call="x") == utils.load_prompt(
            tpl, stable="lib", per_call="x"
        )

    def test_splits_at_first_occurrence_only(self, tmp_path):
        tpl = tmp_path / "t.txt"
        tpl.write_text("A {m} B {m}")
        prefix, rest = utils.split_prompt(tpl, "m")
        assert (prefix, rest) == ("A ", "{m} B {m}")

    def test_missing_marker_raises(self, tmp_path):
        tpl = tmp_path / "t.txt"
        tpl.write_text("no placeholder here")
        with pytest.raises(ValueError, match="no .marker."):
            utils.split_prompt(tpl, "marker")


class TestSampleLanguage:
    def test_certain_distribution_always_returns_that_language(self):
        assert all(utils.sample_language({"en": 1.0}) == "en" for _ in range(20))

    def test_repeatable_under_global_seed(self):
        dist = {"en": 0.5, "de": 0.5}
        random.seed(123)
        first = [utils.sample_language(dist) for _ in range(20)]
        random.seed(123)
        second = [utils.sample_language(dist) for _ in range(20)]
        assert first == second

    def test_injected_rng_gives_reproducible_sequence(self):
        dist = {"en": 0.5, "de": 0.5}
        seq1 = [utils.sample_language(dist, rng=random.Random(42)) for _ in range(5)]
        seq2 = [utils.sample_language(dist, rng=random.Random(42)) for _ in range(5)]
        assert seq1 == seq2


class TestRunDirs:
    def test_new_run_id_sanitizes_label(self):
        rid = utils.new_run_id("my run!/v2 ")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}_my-run--v2", rid)

    def test_create_run_dir_writes_manifest(self, tmp_path):
        runs_root = tmp_path / "runs"
        config = {"model": "test-model", "foo": "bar"}
        run_dir = utils.create_run_dir(runs_root, label="dev", config=config)
        manifest = json.loads((run_dir / "run_manifest.json").read_text())
        assert manifest["run_id"] == run_dir.name
        assert manifest["label"] == "dev"
        assert manifest["model"] == "test-model"
        assert manifest["config"] == config
        assert manifest["git_commit"] is None or isinstance(manifest["git_commit"], str)

    def test_create_run_dir_points_latest_symlink_at_run(self, tmp_path):
        runs_root = tmp_path / "runs"
        run_dir = utils.create_run_dir(runs_root, label="dev", config={})
        link = tmp_path / "latest"
        assert link.is_symlink()
        assert link.resolve() == run_dir.resolve()

    def test_create_run_dir_collision_appends_suffix(self, tmp_path, monkeypatch):
        # Pin the minted id so both calls collide regardless of wall clock
        monkeypatch.setattr(utils, "new_run_id", lambda label: "2026-01-01_00-00_dev")
        runs_root = tmp_path / "runs"
        first = utils.create_run_dir(runs_root, label="dev", config={})
        second = utils.create_run_dir(runs_root, label="dev", config={})
        assert first.name == "2026-01-01_00-00_dev"
        assert second.name == "2026-01-01_00-00_dev-2"
        assert (tmp_path / "latest").resolve() == second.resolve()

    def test_create_run_dir_manifest_records_git_state(self, tmp_path):
        run_dir = utils.create_run_dir(tmp_path / "runs", label="dev", config={})
        manifest = json.loads((run_dir / "run_manifest.json").read_text())
        assert manifest["manifest_version"] == 2
        assert manifest["inputs_snapshot"] is False
        assert isinstance(manifest["git_dirty"], bool)
        assert isinstance(manifest["git_dirty_files"], list)

    def test_create_run_dir_snapshots_input_dirs(self, tmp_path):
        src = tmp_path / "src_prompts"
        src.mkdir()
        (src / "t.txt").write_text("template")
        run_dir = utils.create_run_dir(
            tmp_path / "runs", label="dev", config={}, snapshot_dirs={"prompts": src}
        )
        assert (run_dir / "inputs" / "prompts" / "t.txt").read_text() == "template"
        manifest = json.loads((run_dir / "run_manifest.json").read_text())
        assert manifest["inputs_snapshot"] is True

    def test_resolve_run_dir_by_id(self, tmp_path):
        (tmp_path / "run_a").mkdir()
        assert utils.resolve_run_dir(tmp_path, "run_a") == tmp_path / "run_a"

    def test_resolve_run_dir_unknown_id_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            utils.resolve_run_dir(tmp_path, "missing")

    def test_resolve_run_dir_picks_latest_by_name(self, tmp_path):
        for name in ["2026-01-01_10-00_dev", "2026-01-02_09-00_dev", "2026-01-01_23-59_dev"]:
            (tmp_path / name).mkdir()
        (tmp_path / "stray.txt").write_text("not a dir")
        assert utils.resolve_run_dir(tmp_path).name == "2026-01-02_09-00_dev"

    def test_resolve_run_dir_empty_root_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            utils.resolve_run_dir(tmp_path / "does-not-exist")


class TestWarnIfBackendChanged:
    def test_warns_when_live_backend_differs_from_manifest(self, tmp_path, capsys):
        run_dir = utils.create_run_dir(tmp_path / "runs", label="dev", config={"backend": "claude_code"})
        utils.warn_if_backend_changed(run_dir, {"backend": "api"})
        assert "different backend" in capsys.readouterr().err

    def test_silent_when_backend_matches(self, tmp_path, capsys):
        run_dir = utils.create_run_dir(tmp_path / "runs", label="dev", config={"backend": "claude_code"})
        utils.warn_if_backend_changed(run_dir, {"backend": "claude_code"})
        assert capsys.readouterr().err == ""

    def test_manifest_without_backend_key_treated_as_api(self, tmp_path, capsys):
        # A run created before the backend key existed defaults to api.
        run_dir = utils.create_run_dir(tmp_path / "runs", label="dev", config={})
        utils.warn_if_backend_changed(run_dir, {"backend": "api"})
        assert capsys.readouterr().err == ""
        utils.warn_if_backend_changed(run_dir, {"backend": "claude_code"})
        assert "different backend" in capsys.readouterr().err

    def test_missing_manifest_is_silent(self, tmp_path, capsys):
        utils.warn_if_backend_changed(tmp_path / "no-such-run", {"backend": "api"})
        assert capsys.readouterr().err == ""


class TestResolveConstitutionDir:
    def test_returns_sibling_constitution_for_snapshot_prompts(self, tmp_path):
        prompts = tmp_path / "inputs" / "prompts"
        constitution = tmp_path / "inputs" / "constitution"
        prompts.mkdir(parents=True)
        constitution.mkdir()
        assert utils.resolve_constitution_dir(prompts) == constitution

    def test_returns_none_for_live_prompts_dir(self, tmp_path):
        live = tmp_path / "prompts" / "dad"
        live.mkdir(parents=True)
        assert utils.resolve_constitution_dir(live) is None

    def test_returns_none_when_snapshot_has_no_constitution(self, tmp_path):
        prompts = tmp_path / "inputs" / "prompts"
        prompts.mkdir(parents=True)
        assert utils.resolve_constitution_dir(prompts) is None


class TestCheckpoint:
    def test_starts_empty_without_file(self, tmp_path):
        cp = utils.Checkpoint(tmp_path / "_checkpoint.json")
        assert not cp.is_done("x")
        assert cp.done_count == 0

    def test_mark_done_persists_across_instances(self, tmp_path):
        path = tmp_path / "_checkpoint.json"
        utils.Checkpoint(path).mark_done("layer1")
        assert utils.Checkpoint(path).is_done("layer1")

    def test_ids_are_stringified(self, tmp_path):
        cp = utils.Checkpoint(tmp_path / "_checkpoint.json")
        cp.mark_done(3)
        assert cp.is_done(3)
        assert cp.is_done("3")

    def test_done_count_ignores_duplicate_marks(self, tmp_path):
        cp = utils.Checkpoint(tmp_path / "_checkpoint.json")
        cp.mark_done("a")
        cp.mark_done("b")
        cp.mark_done("a")
        assert cp.done_count == 2

    def test_creates_parent_dirs_on_first_mark(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "_checkpoint.json"
        utils.Checkpoint(path).mark_done("x")
        assert path.exists()
