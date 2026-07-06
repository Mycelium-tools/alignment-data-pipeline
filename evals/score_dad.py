#!/usr/bin/env python3
"""Score DAD corpus records with the judge panel (evals/judge.py + rubric_dad_v1.yaml).

Judges every record with each model on the panel, computes gates/consensus in code,
joins pipeline annotations post-hoc for the judge-vs-annotation comparison, and writes:

  <input dir>/judge/<rubric_version>/verdicts.jsonl   one line per record (all models)
  <input dir>/judge/<rubric_version>/summary.json     per-model + consensus report

Usage:
  python evals/score_dad.py --input outputs/dad/latest/final/dad_corpus.jsonl \
      --judges claude-haiku-4-5 claude-sonnet-4-6 [--limit 5]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils
from evals import judge


def _corr(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation (length-vs-score verbosity telemetry)."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = (sum((x - mx) ** 2 for x in xs)) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys)) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), 3)


def summarize(rows: list[dict], models: list[str], rubric: dict) -> dict:
    """Per-model means/pass-rates + consensus + verbosity telemetry."""
    scalar_dims = [d for d, s in rubric["dimensions"].items() if s["type"] == "scalar"]
    report: dict = {"rubric_version": rubric["version"], "records": len(rows), "models": {}}

    for model in models:
        dim_vals: dict[str, list[int]] = {d: [] for d in scalar_dims}
        passes, errors, means, lengths = 0, 0, [], []
        verdict_dist: dict[str, int] = {}
        for row in rows:
            res = next((r for r in row["panel"]["results"] if r["model"] == model), None)
            if not res or not res.get("verdict"):
                errors += 1
                continue
            v, agg = res["verdict"], res["aggregate"]
            for d in scalar_dims:
                val = (v.get("dimension_scores") or {}).get(d)
                if isinstance(val, (int, float)):
                    dim_vals[d].append(int(val))
            if agg["passing"]:
                passes += 1
            if agg["mean"] is not None:
                means.append(agg["mean"])
                lengths.append(row["panel"]["response_words"])
            b = v.get("autonomy_behavior")
            verdict_dist[b] = verdict_dist.get(b, 0) + 1
        graded = len(rows) - errors
        report["models"][model] = {
            "graded": graded,
            "judge_errors": errors,
            "pass_rate": round(passes / graded, 3) if graded else None,
            "mean_of_means": round(sum(means) / len(means), 3) if means else None,
            "dimension_means": {
                d: round(sum(vals) / len(vals), 2) for d, vals in dim_vals.items() if vals
            },
            "autonomy_verdicts": verdict_dist,
            "score_length_correlation": _corr(lengths, means),
        }

    graded_rows = [r for r in rows if not r["panel"].get("judge_error")]
    report["consensus"] = {
        "pass_rate": round(
            sum(1 for r in graded_rows if r["panel"]["consensus_aggregate"]["passing"]) / len(graded_rows), 3
        ) if graded_rows else None,
        "unstable_rate": round(
            sum(1 for r in graded_rows if r["panel"]["judge_unstable"]) / len(graded_rows), 3
        ) if graded_rows else None,
        "error_rate": round((len(rows) - len(graded_rows)) / len(rows), 3) if rows else None,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Judge a DAD corpus with a model panel.")
    parser.add_argument("--input", required=True, help="Path to dad_corpus.jsonl")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--rubric", default=str(judge.DEFAULT_RUBRIC_PATH))
    parser.add_argument("--judges", nargs="+", default=["gemini-2.5-flash"],
                        help="Judge model ids (panel); gemini-* and claude-* both work")
    parser.add_argument("--limit", type=int, default=None, help="Max records to judge")
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args()

    api.init(args.config)
    rubric = judge.load_rubric(args.rubric)
    principles = judge.load_principles()
    records = utils.load_jsonl(args.input)
    if args.limit:
        records = records[: args.limit]

    annotations = judge.find_annotations(args.input)
    out_dir = Path(args.input).parent / "judge" / rubric["version"]
    out_dir.mkdir(parents=True, exist_ok=True)
    verdicts_path = out_dir / "verdicts.jsonl"

    done = {r["record_id"] for r in utils.load_jsonl(verdicts_path)}
    rows = [r for r in utils.load_jsonl(verdicts_path)]

    print(f"Judging {len(records)} records with panel {args.judges} "
          f"(rubric {rubric['version']}; {len(annotations)} annotations joinable)")

    for i, rec in enumerate(records):
        rid = rec["record_id"]
        if rid in done:
            continue
        print(f"  [{i + 1}/{len(records)}] {rid[:12]}...")
        panel = judge.panel_judge(rec["messages"], args.judges, rubric, principles,
                                  temperature=args.temperature)
        row = {"record_id": rid, "rubric_version": rubric["version"], "panel": panel}
        upstream = annotations.get(rid)
        if upstream:
            first = next((r["verdict"] for r in panel["results"] if r.get("verdict")), None)
            if first:
                row["annotation_comparison"] = judge.compare_annotation(first, upstream)
        utils.append_jsonl(row, verdicts_path)
        rows.append(row)

    report = summarize(rows, args.judges, rubric)
    with open(out_dir / "summary.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n=== DAD Judge Summary ({report['records']} records, rubric {rubric['version']}) ===")
    for model, m in report["models"].items():
        print(f"\n  {model}: pass {m['pass_rate']}, mean {m['mean_of_means']}, "
              f"errors {m['judge_errors']}, score-length corr {m['score_length_correlation']}")
        for d, v in m["dimension_means"].items():
            print(f"    {d:<28} {v:.2f}")
        print(f"    verdicts: {m['autonomy_verdicts']}")
    c = report["consensus"]
    print(f"\n  consensus: pass {c['pass_rate']}, unstable {c['unstable_rate']}, error {c['error_rate']}")
    print(f"  written to: {out_dir}/")


if __name__ == "__main__":
    main()
