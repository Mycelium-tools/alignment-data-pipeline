#!/usr/bin/env python3
"""Score DAD corpus records with the judge panel (evals/judge.py + rubric_dad_v4.yaml).

Judges every record with each model on the panel, computes gates/consensus in code,
joins pipeline annotations post-hoc for the judge-vs-annotation comparison, and writes:

  <input dir>/judge/<rubric_version>/verdicts.jsonl   one line per record (all models)
  <input dir>/judge/<rubric_version>/summary.json     per-model + consensus report

Usage:
  python evals/score_dad.py --input outputs/dad/latest/final/dad_corpus.jsonl \
      --judges claude-haiku-4-5 claude-sonnet-4-6 [--limit 5]

Judge only a curated subset (facets need the holistic tag index — build it with
``python evals/holistic_dad.py --input <run> --extract-only``):
  python evals/score_dad.py --input .../dad_corpus.jsonl \
      --where taxa_category=edge-of-sentience --where direction=Over-weighting --sample 40

Selection narrows which records get JUDGED this invocation; verdicts.jsonl
accumulates across invocations (resume), and summary.json always covers every
saved row, not just the latest subset.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils
from evals import judge, selection
from evals.holistic import bundle


def select_records(records: list[dict], corpus_path: str | Path, *,
                   where: dict | None = None, ids: list[str] | None = None,
                   sample: int | None = None, seed: int = 0,
                   limit: int | None = None) -> list[dict]:
    """CLI selection for the judge: which corpus records to score. Facet filters
    (``--where``) match against the holistic tag index built by holistic_dad — the latest
    provenance bundle under ``<run>/holistic/`` (falling back to the legacy flat ``audit/category_records.jsonl``)
    for a run-dir corpus, or the sibling ``<stem>.holistic/`` bundle (falling back to ``<stem>.category_records.jsonl``)
    for a bare corpus file; records without a tag row cannot match and drop out. Fails loudly when ``--where`` is given
    but no usable index exists — silently judging zero records would be worse."""
    index = None
    if where:
        p = Path(corpus_path).resolve()
        candidates = [
            bundle.reading_index_path(
                p.parent.parent / "holistic",
                p.parent.parent / "audit" / "category_records.jsonl"),
            bundle.reading_index_path(
                p.with_name(p.stem + ".holistic"),
                p.with_name(p.stem + ".category_records.jsonl")),
        ]
        for index_path in candidates:
            index = {r["record_id"]: r for r in utils.load_jsonl(index_path)
                     if "record_id" in r}
            if index:
                break
        if not index:
            raise SystemExit(
                "--where needs the holistic tag index ("
                + " or ".join(str(c) for c in candidates) + ") — build it first: "
                "python evals/holistic_dad.py --input <run-or-corpus> --extract-only")
    return selection.apply_cli_selection(records, index=index, where=where, ids=ids,
                                         sample=sample, seed=seed, limit=limit)


def drop_retryable_errors(rows: list[dict], selected_ids: set[str]) -> list[dict]:
    """``--retry-errors``: drop saved rows that have no successful verdict, but only
    for records in this run's selection — the judging loop only revisits selected
    records, so dropping an unselected errored row would delete it forever."""
    return [r for r in rows
            if any(res.get("verdict") for res in r["panel"]["results"])
            or r["record_id"] not in selected_ids]


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


def _record_prompt_manifest(out_dir: Path, prompt_md5: str, system_prompt: str,
                            rubric: dict, args: argparse.Namespace) -> None:
    """Save the exact judge system prompt that verdict rows reference by prompt_md5,
    so every saved verdict is traceable to the prompt that produced it."""
    prompt_file = f"prompt_{prompt_md5[:8]}.txt"
    (out_dir / prompt_file).write_text(system_prompt)
    # Snapshot the rubric too, so saved verdicts stay interpretable (gates, floors)
    # even after evals/rubric_dad_v4.yaml changes.
    (out_dir / "rubric.yaml").write_text(Path(args.rubric).read_text())
    manifest_path = out_dir / "judge_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest[prompt_md5] = {
        "rubric_version": rubric["version"],
        "judges": args.judges,
        "temperature": args.temperature,
        "prompt_file": prompt_file,
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Judge a DAD corpus with a model panel.")
    parser.add_argument("--input", required=True, help="Path to dad_corpus.jsonl")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--rubric", default=str(judge.DEFAULT_RUBRIC_PATH))
    parser.add_argument("--judges", nargs="+", default=["gemini-3.1-pro-preview"],
                        help="Judge model ids (panel); gemini-* and claude-* both work")
    parser.add_argument("--limit", type=selection.nonneg_int, default=None,
                        help="Max records to judge")
    parser.add_argument("--where", action="append", metavar="AXIS=V1[,V2...]",
                        help="facet filter over the holistic tag index "
                             "(<run>/audit/category_records.jsonl; repeatable)")
    parser.add_argument("--ids", default=None,
                        help="comma-separated record_ids to judge")
    parser.add_argument("--sample", type=selection.nonneg_int, default=None,
                        help="judge a seeded random N of the selected records")
    parser.add_argument("--seed", type=int, default=0, help="seed for --sample")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--retry-errors", action="store_true",
                        help="Drop saved rows that have no successful verdict and re-judge them")
    args = parser.parse_args()

    try:
        where = selection.parse_where(args.where)
    except ValueError as err:
        raise SystemExit(str(err))

    api.init(args.config)
    rubric = judge.load_rubric(args.rubric)
    principles = judge.load_principles()
    records = select_records(utils.load_jsonl(args.input), args.input,
                             where=where, ids=selection.parse_ids(args.ids),
                             sample=args.sample, seed=args.seed, limit=args.limit)

    annotations = judge.find_annotations(args.input)
    out_dir = Path(args.input).parent / "judge" / rubric["version"]
    out_dir.mkdir(parents=True, exist_ok=True)
    verdicts_path = out_dir / "verdicts.jsonl"

    system_prompt = judge.build_system_prompt(rubric, principles)
    prompt_md5 = hashlib.md5(system_prompt.encode()).hexdigest()
    _record_prompt_manifest(out_dir, prompt_md5, system_prompt, rubric, args)

    rows = utils.load_jsonl(verdicts_path)
    if args.retry_errors:
        keep = drop_retryable_errors(rows, {r["record_id"] for r in records})
        if len(keep) < len(rows):
            print(f"Retrying {len(rows) - len(keep)} errored records (rows dropped, re-judging).")
            utils.save_jsonl(keep, verdicts_path)
            rows = keep
    done = {r["record_id"] for r in rows}
    stale = sum(1 for r in rows if r.get("prompt_md5") != prompt_md5)
    if stale:
        print(f"WARNING: {stale} existing rows were judged with a different or unrecorded "
              f"judge prompt (current {prompt_md5[:8]}). They are kept, not re-judged — "
              "bump the rubric version (or delete verdicts.jsonl) for a clean re-run.")

    print(f"Judging {len(records)} records with panel {args.judges} "
          f"(rubric {rubric['version']}; {len(annotations)} annotations joinable)")

    for i, rec in enumerate(records):
        rid = rec["record_id"]
        if rid in done:
            continue
        print(f"  [{i + 1}/{len(records)}] {rid[:12]}...")
        panel = judge.panel_judge(rec["messages"], args.judges, rubric, principles,
                                  temperature=args.temperature)
        row = {"record_id": rid, "rubric_version": rubric["version"],
               "prompt_md5": prompt_md5, "panel": panel}
        upstream = annotations.get(rid)
        if upstream:
            first = next((r["verdict"] for r in panel["results"] if r.get("verdict")), None)
            if first:
                row["annotation_comparison"] = judge.compare_annotation(first, upstream)
        utils.append_jsonl(row, verdicts_path)
        rows.append(row)

    report = summarize(rows, args.judges, rubric)
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
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
