"""Tests for evals/review_tics.py — the phrase-tic review queue.

Offline: aggregates <run>/audit/tic_candidates.jsonl across a synthetic runs
root and mutates a temp copy of tics.yaml. No API, no network.
"""
import json
from pathlib import Path

from evals import review_tics

STOCK = """\
watch:
  pipeline-origin:
    - {phrase: "you're the one", family: agency-ownership}
  plain-origin:
    - {phrase: "here's the thing"}
ignore: []
"""


def _stock(tmp_path) -> Path:
    p = tmp_path / "tics.yaml"
    p.write_text(STOCK, encoding="utf-8")
    return p


def _run_with_candidates(runs_root: Path, run_id: str, cands: list[dict]) -> None:
    d = runs_root / run_id / "audit"
    d.mkdir(parents=True)
    with (d / "tic_candidates.jsonl").open("w", encoding="utf-8") as f:
        for c in cands:
            f.write(json.dumps({"run_id": run_id, **c}) + "\n")


def _cand(phrase, arm="response", df=5, of=40, z=2.0, zipf=3.0, example="…e.g.…"):
    return {"phrase": phrase, "arm": arm, "df": df, "of": of, "z": z,
            "bg_zipf": zipf, "example": example}


def test_aggregate_counts_recurrence_across_runs(tmp_path):
    root = tmp_path / "runs"
    _run_with_candidates(root, "r1", [_cand("moral crumple zone", z=2.1)])
    _run_with_candidates(root, "r2", [_cand("moral crumple zone", z=2.6),
                                      _cand("one-off phrase", z=1.5)])
    stock = _stock(tmp_path)
    rows = review_tics.aggregate_candidates(root, stock)
    top = rows[0]
    assert top["phrase"] == "moral crumple zone"
    assert top["times_seen"] == 2          # recurred across both runs
    assert top["max_z"] == 2.6             # peak z kept
    # min_runs filter drops the singleton
    assert all(r["times_seen"] >= 2
               for r in review_tics.aggregate_candidates(root, stock, min_runs=2))


def test_aggregate_excludes_watched_and_ignored(tmp_path):
    root = tmp_path / "runs"
    _run_with_candidates(root, "r1", [
        _cand("you're the one"),        # already watched
        _cand("here's the thing", arm="prompt"),  # already watched (plain)
        _cand("fresh candidate")])
    stock = _stock(tmp_path)
    phrases = {r["phrase"] for r in review_tics.aggregate_candidates(root, stock)}
    assert phrases == {"fresh candidate"}


def test_promote_appends_to_watch_and_is_excluded_after(tmp_path):
    root = tmp_path / "runs"
    _run_with_candidates(root, "r1", [_cand("gut check")])
    stock = _stock(tmp_path)
    msg = review_tics.promote("gut check", "pipeline-origin", "performed-candor", stock)
    assert "Promoted" in msg
    watch, _ = review_tics.load_watch_ignore(stock)
    assert "gut check" in watch["pipeline-origin"]
    # no longer surfaced as a candidate
    assert not review_tics.aggregate_candidates(root, stock)
    # promoting again is a no-op
    assert "already" in review_tics.promote("gut check", "pipeline-origin", None, stock)


def test_ignore_appends_and_suppresses(tmp_path):
    root = tmp_path / "runs"
    _run_with_candidates(root, "r1", [_cand("and honestly", arm="prompt")])
    stock = _stock(tmp_path)
    msg = review_tics.ignore_phrase("and honestly", "common filler", stock)
    assert "Ignored" in msg
    _, ignore = review_tics.load_watch_ignore(stock)
    assert "and honestly" in ignore
    assert not review_tics.aggregate_candidates(root, stock)


def test_list_runs_via_main_without_error(tmp_path, capsys):
    root = tmp_path / "runs"
    _run_with_candidates(root, "r1", [_cand("moral crumple zone")])
    stock = _stock(tmp_path)
    review_tics.main(["list", "--runs-root", str(root), "--tics", str(stock)])
    out = capsys.readouterr().out
    assert "moral crumple zone" in out
