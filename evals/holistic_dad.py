#!/usr/bin/env python3
"""Holistic DAD diversity judge — CLI entry point.

Tag a run's records with their categorical axes, then run the registered analyzers
and write a report. This is intentionally a thin wrapper over ``evals.holistic``:
the *what* (which fields, which analyses) lives in the pluggable registries
(``evals/holistic/fields.py``, ``evals/holistic/analyzers.py``); this file only wires
resolve → tag → analyze → report and does the I/O.

    python evals/holistic_dad.py --input outputs/dad/latest          # tag + analyze
    python evals/holistic_dad.py --input outputs/dad/latest --analyze-only
    python evals/holistic_dad.py --input path/to/dad_corpus.jsonl    # bare corpus

The report is written to <run>/audit/holistic_dad_report.json (next to
evals/diversity.py's semantic report), plus a short console summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dataclasses import replace

from evals import selection
from evals.holistic import analyzers as analyzers_mod
from evals.holistic import fields as fields_mod
from evals.holistic import pipeline
from shared import api

REPORT_NAME = "holistic_dad_report.json"
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AXES = ROOT / "evals" / "dad_axes.yaml"
DEFAULT_EXTRACT_PROMPT = ROOT / "prompts" / "tools" / "dad_category_extract.txt"
DEFAULT_SYNTH_PROMPT = ROOT / "prompts" / "tools" / "dad_holistic_synthesis.txt"


def _read_if_exists(path: str | Path) -> str | None:
    p = Path(path)
    return p.read_text() if p.exists() else None


def _load_fields(path: str | Path):
    """Fields from the YAML schema file. A missing path fails loudly — silently falling
    back to the seed schema would produce a plausible-looking but wrong report."""
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"axes file not found: {p}")
    return fields_mod.load_fields(p)


def report_path_for(inputs: pipeline.Inputs) -> Path:
    """Where to write the report: the run's audit/ dir, or beside a bare corpus file
    (next to its tag index)."""
    if inputs.run_dir is not None:
        return inputs.run_dir / "audit" / REPORT_NAME
    return inputs.index_path.with_name(
        inputs.index_path.name.replace("category_records.jsonl", REPORT_NAME))


def write_report(path: Path, report: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return path


def summary_lines(report: dict) -> list[str]:
    """Render the report as GOOD/BAD-framed console lines (CAML-style verdicts).
    Pure — returns the lines so it can be tested without capturing stdout."""
    lines = [f"Holistic DAD report — run {report.get('run_id')} · "
             f"{report['records']} records · inputs: {', '.join(report['inputs_present'])}"]
    analyses = report["stats"]["analyses"]
    dist = analyses.get("distribution", {})
    scored = [(a, m) for a, m in analyses.get("evenness", {}).items()
              if m.get("evenness") is not None]
    if scored:
        lines.append("per-axis balance (Pielou evenness 0–1; "
                     "GOOD = spread across values, BAD = one value dominates):")
        for axis, m in scored:
            top = ", ".join(f"{k}={v}" for k, v in list(dist.get(axis, {}).items())[:5])
            lines.append(f"  {axis:22s} evenness {m['evenness']:.2f} [{m['verdict']}]  ({top})")
    coverage = analyses.get("coverage_vs_target", {})
    missed = [(axis, m) for axis, m in coverage.items() if m.get("verdict") == "BAD"]
    if missed:
        lines.append("coverage vs target (BAD = a designed quota missed):")
        for axis, m in missed:
            lines.append(f"  {axis:22s} [BAD]  " + "; ".join(m["violations"][:4]))
    corr = analyses.get("correlation", {})
    bad_corr = [(pair, m) for pair, m in corr.items() if m.get("verdict") == "BAD"]
    if bad_corr:
        lines.append("correlations (BAD = one axis predicts the other — e.g. sycophancy):")
        for pair, m in bad_corr:
            lines.append(f"  {pair:30s} Cramér's V {m['cramers_v']:.2f} [BAD]")
    combos = analyses.get("combination_coverage", {})
    bad_combos = [(pair, m) for pair, m in combos.items() if m.get("verdict") == "BAD"]
    if bad_combos:
        lines.append("combination coverage (BAD = designed axis-pair cells never appear):")
        for pair, m in bad_combos:
            lines.append(f"  {pair:30s} {m['filled']}/{m['cells']} cells "
                         f"({m['coverage']:.2f}) [BAD]  missing: "
                         + ", ".join(m["missing"][:6]))
    drift = analyses.get("drift", {})
    bad_drift = [(axis, m) for axis, m in drift.items() if m.get("verdict") == "BAD"]
    if bad_drift:
        lines.append("intent→realization drift (BAD = extraction disagrees with the "
                     "generator's intent — route to a human):")
        for axis, m in bad_drift:
            confusions = "; ".join(f"{d['intended']}→{d['realized']} ×{d['count']}"
                                   for d in m["disagreements"][:3])
            lines.append(f"  {axis:22s} agreement {m['agreement']:.2f} [BAD]  ({confusions})")
    skipped = report["stats"].get("skipped", {})
    if skipped:
        lines.append("skipped analyzers: " + ", ".join(skipped))
    syn = report.get("synthesis") or {}
    if syn.get("top_issues"):
        lines.append("top issues:")
        for it in syn["top_issues"][:5]:
            lines.append(f"  [{it.get('severity', '?')}] {it.get('axis', '?')}: "
                         f"{it.get('detail', '')}")
    return lines


def print_summary(report: dict) -> None:
    print("\n" + "\n".join(summary_lines(report)))


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description="Holistic categorical diversity report for a DAD run.")
    ap.add_argument("--input", required=True, help="a DAD run dir or a bare corpus .jsonl")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--model", default=None, help="extraction-judge model override")
    ap.add_argument("--axes", default=str(DEFAULT_AXES),
                    help="YAML schema of extraction fields (edit to change the JSON)")
    ap.add_argument("--extract-prompt", default=str(DEFAULT_EXTRACT_PROMPT),
                    help="editable extraction prompt template ({{FIELDS}}/{{KEYS}})")
    ap.add_argument("--synthesis-prompt", default=str(DEFAULT_SYNTH_PROMPT),
                    help="editable holistic-synthesis prompt template ({{STATS}})")
    ap.add_argument("--judge-version", default=None,
                    help="judge verdict subdirectory under final/judge to join, if present")
    ap.add_argument("--analyze-only", action="store_true",
                    help="analyze an existing tag index; do not call the API")
    ap.add_argument("--extract-only", action="store_true",
                    help="tag only (build/refresh the index that powers selection); "
                         "skip analysis and synthesis")
    ap.add_argument("--no-resume", action="store_true",
                    help="re-tag every selected record instead of skipping "
                         "already-tagged ones")
    ap.add_argument("--no-synthesize", action="store_true",
                    help="skip the LLM synthesis pass (stats only)")
    ap.add_argument("--where", action="append", metavar="AXIS=V1[,V2...]",
                    help="facet filter over the tag index choosing which records get "
                         "tagged (repeatable; repeated flags for one axis union)")
    ap.add_argument("--ids", default=None,
                    help="comma-separated record_ids to tag (composes with --where)")
    ap.add_argument("--limit", type=selection.nonneg_int, default=None,
                    help="tag only the first N selected records")
    ap.add_argument("--sample", type=selection.nonneg_int, default=None,
                    help="tag a seeded random N of the selected records")
    ap.add_argument("--seed", type=int, default=0, help="seed for --sample")
    args = ap.parse_args(argv)

    if args.extract_only and args.analyze_only:
        raise SystemExit("--extract-only and --analyze-only are mutually exclusive")
    try:
        where = selection.parse_where(args.where)
    except ValueError as err:
        raise SystemExit(str(err))
    ids = selection.parse_ids(args.ids)
    selecting = bool(where) or ids is not None \
        or args.sample is not None or args.limit is not None
    if selecting and args.analyze_only:
        raise SystemExit("--where/--ids/--sample/--limit choose which records get "
                         "TAGGED; they have no effect with --analyze-only "
                         "(analysis always reads the whole index)")

    api.init(args.config)
    fields = _load_fields(args.axes)          # raises SystemExit if the path is missing
    analysis_cfg = fields_mod.load_analysis_config(args.axes)
    analyzers = analyzers_mod.select(analyzers_mod.default_analyzers(),
                                     analysis_cfg.get("analyzers"))
    extract_template = _read_if_exists(args.extract_prompt)
    synthesis_template = None if args.no_synthesize else _read_if_exists(args.synthesis_prompt)

    inputs = pipeline.resolve_inputs(args.input, judge_version=args.judge_version)
    if selecting:
        index = {r["record_id"]: r
                 for r in pipeline.load_category_records(inputs) if "record_id" in r}
        if where and not index:
            raise SystemExit(
                f"--where needs the tag index at {inputs.index_path} — build it "
                "first with --extract-only (no selection flags)")
        # The subset rows themselves (positional), never a record_id round-trip:
        # duplicate ids in a corrupt corpus must not re-expand past --sample/--limit.
        subset = selection.apply_cli_selection(
            inputs.corpus, index=index if where else None, where=where,
            ids=ids, sample=args.sample, seed=args.seed, limit=args.limit)
        inputs = replace(inputs, corpus=subset)

    if args.extract_only:
        written = pipeline.tag(inputs, fields,
                               model=args.model, resume=not args.no_resume,
                               extract_template=extract_template)
        print(f"tagged {len(written)} record(s) → {inputs.index_path}")
        return {"tagged": len(written), "index_path": str(inputs.index_path)}

    report = pipeline.run(inputs, fields=fields, analyzers=analyzers, model=args.model,
                          do_tag=not args.analyze_only, resume=not args.no_resume,
                          extract_template=extract_template,
                          synthesis_template=synthesis_template,
                          judge_version=args.judge_version,
                          config=analysis_cfg.get("params"))

    path = write_report(report_path_for(inputs), report)
    print(f"wrote {path}")
    print_summary(report)
    return report


if __name__ == "__main__":
    main()
