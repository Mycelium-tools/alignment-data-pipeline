"""Tests for evals/rank_corpora.py — the corpus-level rank-agreement harness for
the v5 judge comparison (owner ranking vs judge ranking, per
docs/v5-handoff/handoff-judge-v5-corpus-run.md).

All offline: verdicts files are synthesized into tmp run dirs.
"""

import json

import pytest

from evals import rank_corpora as rc


def _verdict_row(record_id, mean):
    return {"record_id": record_id, "panel": {
        "judge_error": False, "consensus_aggregate": {"mean": mean}}}


def _error_row(record_id):
    return {"record_id": record_id, "panel": {"judge_error": True}}


def _write_verdicts(root, run_dir, version, rows):
    d = root / run_dir / "final" / "judge" / version
    d.mkdir(parents=True)
    with open(d / "verdicts.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


class TestCorpusMean:
    def test_mean_over_graded_records_skips_errors(self, tmp_path):
        _write_verdicts(tmp_path, "run-x", "dad-v5a",
                        [_verdict_row("r1", 6.0), _verdict_row("r2", 8.0), _error_row("r3")])
        mean, graded, errors = rc.corpus_mean(
            tmp_path / "run-x" / "final" / "judge" / "dad-v5a" / "verdicts.jsonl")
        assert mean == 7.0
        assert graded == 2
        assert errors == 1


class TestRankMath:
    def test_rank_desc_with_average_ties(self):
        # Higher mean = better = rank 1; ties share the average rank.
        assert rc.rank_desc([9.0, 7.0, 9.0]) == [1.5, 3.0, 1.5]

    def test_spearman_perfect_agreement(self):
        assert rc.spearman([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)

    def test_spearman_perfect_disagreement(self):
        assert rc.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)


class TestBuildTable:
    def test_gap_sign_matches_handoff_convention(self, tmp_path):
        # Gap = owner_rank - judge_rank: negative = judge ranked the corpus
        # WORSE (higher rank number) than the owner did.
        corpora = [
            {"label": "X", "run_dir": "run-x", "owner_rank": 1.0},
            {"label": "Y", "run_dir": "run-y", "owner_rank": 2.0},
        ]
        _write_verdicts(tmp_path, "run-x", "dad-v5a", [_verdict_row("r1", 5.0)])
        _write_verdicts(tmp_path, "run-y", "dad-v5a", [_verdict_row("r1", 9.0)])
        rows = rc.build_table(corpora, "dad-v5a", tmp_path)
        by_label = {r["label"]: r for r in rows}
        # Owner best (X) judged worst -> negative gap; owner-worst judged best -> positive.
        assert by_label["X"]["judge_rank"] == 2.0
        assert by_label["X"]["gap"] == -1.0
        assert by_label["Y"]["gap"] == 1.0

    def test_missing_verdicts_file_reports_none(self, tmp_path):
        corpora = [{"label": "X", "run_dir": "run-x", "owner_rank": 1.0}]
        rows = rc.build_table(corpora, "dad-v5a", tmp_path)
        assert rows[0]["mean"] is None


class TestReferenceTable:
    def test_reference_covers_the_ten_corpora_with_valid_run_dirs(self):
        # The frozen owner table from the handoff: ten corpora, tied ranks averaged.
        assert len(rc.CORPORA) == 10
        assert sorted(c["owner_rank"] for c in rc.CORPORA) == [
            1.5, 1.5, 3, 4, 5, 6, 7, 8, 9, 10]
        # run-dir existence is a local-checkout sanity check, not a CI invariant —
        # the corpora are run outputs and may not be present on every checkout
        missing = [c["label"] for c in rc.CORPORA
                   if not (rc.RUNS_ROOT / c["run_dir"] / "final" / "dad_corpus.jsonl").exists()]
        if missing:
            pytest.skip(f"reference corpora not on this checkout: {missing}")
