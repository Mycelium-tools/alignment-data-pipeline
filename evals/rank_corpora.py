"""Corpus-level rank agreement: v5 judge ranking vs the owner's human ranking.

The reference table (CORPORA) is the owner's hand-ranking of ten DAD corpora,
transcribed in docs/v5-handoff/handoff-judge-v5-corpus-run.md — the signal the
v5 rubrics are meant to reproduce better than v4.3 did. Tied owner ranks are
averaged (E and J tie at 1 -> 1.5 each), matching the handoff's gap arithmetic.

Usage (after judging every corpus with evals/score_dad.py --rubric <v5 file>):

    python evals/rank_corpora.py --versions dad-v5a dad-v5b

Per rubric version it reads each corpus's judge verdicts, takes the per-record
consensus mean, averages per corpus, ranks the corpora, and tabulates judge
rank + gap (owner_rank - judge_rank; negative = judge harsher than the owner)
beside the frozen v4.3 baseline. Offline — reads verdicts already on disk.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
RUNS_ROOT = REPO_ROOT / "outputs" / "dad" / "runs"

# Owner ranking + v4.3 baseline, frozen 2026-07-09 (handoff-judge-v5-corpus-run.md).
CORPORA = [
    {"label": "E", "run_dir": "2026-07-06_18-16_naturalness-smoke", "owner_rank": 1.5,
     "v43_rank": 6, "v43_mean": 7.450},
    {"label": "J", "run_dir": "2026-07-05_14-16_spec-smoke4", "owner_rank": 1.5,
     "v43_rank": 1, "v43_mean": 8.533},
    {"label": "D", "run_dir": "2026-07-05_17-14_spec-smoke5", "owner_rank": 3,
     "v43_rank": 7, "v43_mean": 7.400},
    {"label": "F", "run_dir": "2026-07-04_18-02_spec-smoke", "owner_rank": 4,
     "v43_rank": 9, "v43_mean": 5.960},
    {"label": "G", "run_dir": "2026-07-06_16-02_scopefix-smoke", "owner_rank": 5,
     "v43_rank": 3, "v43_mean": 8.025},
    {"label": "A", "run_dir": "2026-07-05_13-03_spec-smoke3", "owner_rank": 6,
     "v43_rank": 2, "v43_mean": 8.144},
    {"label": "B", "run_dir": "2026-07-05_17-30_spec-smoke6", "owner_rank": 7,
     "v43_rank": 4, "v43_mean": 7.922},
    {"label": "C", "run_dir": "2026-07-01_14-56_const-split-test", "owner_rank": 8,
     "v43_rank": 10, "v43_mean": 5.104},
    {"label": "I", "run_dir": "2026-07-06_16-57_quality-iter-smoke", "owner_rank": 9,
     "v43_rank": 5, "v43_mean": 7.475},
    {"label": "H", "run_dir": "2026-07-06_09-09_postfix-smoke", "owner_rank": 10,
     "v43_rank": 8, "v43_mean": 7.003},
]


def corpus_mean(verdicts_path: Path) -> tuple[float | None, int, int]:
    """(mean of per-record consensus means, graded count, judge-error count)."""
    means, errors = [], 0
    with open(verdicts_path) as f:
        for line in f:
            panel = json.loads(line).get("panel") or {}
            agg = panel.get("consensus_aggregate") or {}
            if panel.get("judge_error") or agg.get("mean") is None:
                errors += 1
            else:
                means.append(agg["mean"])
    mean = round(statistics.mean(means), 3) if means else None
    return mean, len(means), errors


def rank_desc(values: list[float]) -> list[float]:
    """Rank positions (1 = highest value), ties averaged."""
    order = sorted(range(len(values)), key=lambda i: -values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float:
    """Spearman rho = Pearson correlation of the (tie-averaged) rank vectors."""
    ra = rank_desc([-x for x in a])  # rank by ascending value either way — signs cancel
    rb = rank_desc([-x for x in b])
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    var_a = sum((x - ma) ** 2 for x in ra)
    var_b = sum((y - mb) ** 2 for y in rb)
    return cov / (var_a * var_b) ** 0.5


def build_table(corpora: list[dict], version: str, runs_root: Path) -> list[dict]:
    rows = []
    for c in corpora:
        path = runs_root / c["run_dir"] / "final" / "judge" / version / "verdicts.jsonl"
        mean, graded, errors = corpus_mean(path) if path.exists() else (None, 0, 0)
        rows.append({**c, "mean": mean, "graded": graded, "errors": errors})
    scored = [r for r in rows if r["mean"] is not None]
    ranks = rank_desc([r["mean"] for r in scored])
    for r, jr in zip(scored, ranks):
        r["judge_rank"] = jr
        r["gap"] = round(r["owner_rank"] - jr, 1)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--versions", nargs="+", default=["dad-v5a", "dad-v5b"])
    args = parser.parse_args()

    owner = [c["owner_rank"] for c in CORPORA]
    v43_rho = spearman(owner, [float(c["v43_rank"]) for c in CORPORA])
    print(f"v4.3 baseline: Spearman rho vs owner = {v43_rho:.3f}, "
          f"mean |gap| = {statistics.mean(abs(c['owner_rank'] - c['v43_rank']) for c in CORPORA):.2f}")

    for version in args.versions:
        rows = build_table(CORPORA, version, RUNS_ROOT)
        scored = [r for r in rows if r["mean"] is not None]
        missing = [r["label"] for r in rows if r["mean"] is None]
        print(f"\n=== {version} ===")
        if missing:
            print(f"missing verdicts for: {', '.join(missing)} — run evals/score_dad.py first")
        if len(scored) < 2:
            continue
        print("| Corpus | Owner rank | judge mean | judge rank | Gap | v4.3 gap |")
        print("|---|---|---|---|---|---|")
        for r in sorted(scored, key=lambda r: r["owner_rank"]):
            v43_gap = round(r["owner_rank"] - r["v43_rank"], 1)
            print(f"| {r['label']} ({r['run_dir'].split('_')[-1]}) | {r['owner_rank']} "
                  f"| {r['mean']} ({r['graded']} rec, {r['errors']} err) "
                  f"| {r['judge_rank']} | {r['gap']:+} | {v43_gap:+} |")
        rho = spearman([r["owner_rank"] for r in scored], [r["judge_rank"] for r in scored])
        print(f"Spearman rho vs owner = {rho:.3f} (v4.3 baseline {v43_rho:.3f}), "
              f"mean |gap| = {statistics.mean(abs(r['gap']) for r in scored):.2f}")


if __name__ == "__main__":
    sys.exit(main())
