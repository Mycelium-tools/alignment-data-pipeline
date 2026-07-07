#!/usr/bin/env python3
"""Score SDF corpus documents with the judge panel (evals/judge_sdf.py + rubric_sdf_v3.yaml).

Mirrors evals/score_dad.py for the SDF corpus: judges every document with each model
on the panel, computes gates/consensus in code, joins the generation cell from the
run's layer2/subtypes.jsonl (cell_adherence is NA when no cell is found), and writes:

  <input dir>/judge/<rubric_version>/verdicts.jsonl   one line per document (all models)
  <input dir>/judge/<rubric_version>/summary.json     per-model + consensus report

Usage:
  python evals/score_sdf.py --input outputs/sdf/latest/final/sdf_corpus.jsonl \
      --judges gemini-2.5-flash [--limit 5]
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import api, utils
from evals import judge, judge_sdf


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


def load_cells(corpus_path: str | Path) -> dict[str, dict]:
    """subtype_id -> generation cell, from the run's layer2/subtypes.jsonl (the same
    join the viewer does). Empty when the corpus is judged outside a run dir — the
    judge then gets cell=None and cell_adherence is NA, by design."""
    run_dir = Path(corpus_path).resolve().parent.parent
    subtypes_path = run_dir / "layer2" / "subtypes.jsonl"
    if not subtypes_path.exists():
        return {}
    return {
        row["subtype_id"]: {f: row.get(f) for f in judge_sdf.CELL_FIELDS}
        for row in utils.load_jsonl(subtypes_path)
        if row.get("subtype_id")
    }


def summarize(rows: list[dict], models: list[str], rubric: dict) -> dict:
    """Per-model means/pass-rates + consensus + verbosity telemetry."""
    scalar_dims = [d for d, s in rubric["dimensions"].items() if s["type"] == "scalar"]
    report: dict = {"rubric_version": rubric["version"], "documents": len(rows), "models": {}}

    for model in models:
        dim_vals: dict[str, list[int]] = {d: [] for d in scalar_dims}
        passes, exemplars, errors, means, lengths = 0, 0, 0, [], []
        dai_dist: dict[str, int] = {}
        cell_mismatches = 0
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
            if agg["exemplar"]:
                exemplars += 1
            if agg["cell_mismatch"]:
                cell_mismatches += 1
            if agg["mean"] is not None:
                means.append(agg["mean"])
                lengths.append(row["panel"]["document_words"])
            dai = v.get("depicted_ai_alignment")
            dai_dist[str(dai)] = dai_dist.get(str(dai), 0) + 1
        graded = len(rows) - errors
        report["models"][model] = {
            "graded": graded,
            "judge_errors": errors,
            "pass_rate": round(passes / graded, 3) if graded else None,
            "exemplar_rate": round(exemplars / graded, 3) if graded else None,
            "mean_of_means": round(sum(means) / len(means), 3) if means else None,
            "dimension_means": {
                d: round(sum(vals) / len(vals), 2) for d, vals in dim_vals.items() if vals
            },
            "depicted_ai_verdicts": dai_dist,
            "cell_mismatches": cell_mismatches,
            "score_length_correlation": _corr(lengths, means),
        }

    graded_rows = [r for r in rows if not r["panel"].get("judge_error")]
    report["consensus"] = {
        "unstable_rate": round(
            sum(1 for r in graded_rows if r["panel"].get("judge_unstable")) / len(graded_rows), 3
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
    # even after evals/rubric_sdf_v3.yaml changes.
    (out_dir / "rubric.yaml").write_text(Path(args.rubric).read_text())
    manifest_path = out_dir / "judge_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest[prompt_md5] = {
        "rubric_version": rubric["version"],
        "judges": args.judges,
        "temperature": args.temperature,
        "prompt_file": prompt_file,
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Judge an SDF corpus with a model panel.")
    parser.add_argument("--input", required=True, help="Path to sdf_corpus.jsonl")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--rubric", default=str(judge_sdf.DEFAULT_RUBRIC_PATH))
    parser.add_argument("--judges", nargs="+", default=["gemini-3.1-pro-preview"],
                        help="Judge model ids (panel); gemini-* and claude-* both work")
    parser.add_argument("--limit", type=int, default=None, help="Max documents to judge")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--retry-errors", action="store_true",
                        help="Drop saved rows that have no successful verdict and re-judge them")
    args = parser.parse_args()

    api.init(args.config)
    rubric = judge_sdf.load_rubric(args.rubric)
    principles = judge.load_principles()
    docs = utils.load_jsonl(args.input)
    if args.limit:
        docs = docs[: args.limit]
    cells = load_cells(args.input)

    out_dir = Path(args.input).parent / "judge" / rubric["version"]
    out_dir.mkdir(parents=True, exist_ok=True)
    verdicts_path = out_dir / "verdicts.jsonl"

    system_prompt = judge_sdf.build_system_prompt(rubric, principles)
    prompt_md5 = hashlib.md5(system_prompt.encode()).hexdigest()
    _record_prompt_manifest(out_dir, prompt_md5, system_prompt, rubric, args)

    rows = utils.load_jsonl(verdicts_path)
    if args.retry_errors:
        keep = [r for r in rows if any(res.get("verdict") for res in r["panel"]["results"])]
        if len(keep) < len(rows):
            print(f"Retrying {len(rows) - len(keep)} errored documents (rows dropped, re-judging).")
            utils.save_jsonl(keep, verdicts_path)
            rows = keep
    done = {r["doc_id"] for r in rows}
    stale = sum(1 for r in rows if r.get("prompt_md5") != prompt_md5)
    if stale:
        print(f"WARNING: {stale} existing rows were judged with a different or unrecorded "
              f"judge prompt (current {prompt_md5[:8]}). They are kept, not re-judged — "
              "bump the rubric version (or delete verdicts.jsonl) for a clean re-run.")

    print(f"Judging {len(docs)} documents with panel {args.judges} "
          f"(rubric {rubric['version']}; {len(cells)} cells joinable)")

    for i, doc in enumerate(docs):
        did = doc["doc_id"]
        if did in done:
            continue
        print(f"  [{i + 1}/{len(docs)}] {did[:16]}...")
        cell = cells.get(doc.get("subtype_id"))
        panel = judge_sdf.panel_judge(doc["content"], cell, args.judges, rubric,
                                      principles, temperature=args.temperature)
        row = {"doc_id": did, "subtype_id": doc.get("subtype_id"),
               "rubric_version": rubric["version"], "prompt_md5": prompt_md5,
               "panel": panel}
        utils.append_jsonl(row, verdicts_path)
        rows.append(row)

    report = summarize(rows, args.judges, rubric)
    with open(out_dir / "summary.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n=== SDF Judge Summary ({report['documents']} documents, rubric {rubric['version']}) ===")
    for model, m in report["models"].items():
        print(f"\n  {model}: pass {m['pass_rate']}, exemplar {m['exemplar_rate']}, "
              f"mean {m['mean_of_means']}, errors {m['judge_errors']}, "
              f"score-length corr {m['score_length_correlation']}")
        for d, v in m["dimension_means"].items():
            print(f"    {d:<28} {v:.2f}")
        print(f"    depicted_ai: {m['depicted_ai_verdicts']}; cell mismatches: {m['cell_mismatches']}")
    c = report["consensus"]
    print(f"\n  consensus: unstable {c['unstable_rate']}, error {c['error_rate']}")
    print(f"  written to: {out_dir}/")


if __name__ == "__main__":
    main()
