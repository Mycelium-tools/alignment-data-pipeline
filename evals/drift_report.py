"""Judge-vs-generation tagging drift for a complete spec-driven DAD run.

Compares the generation-time annotation (dealt at steps 1-2, carried to step 3)
with the diversity judge's independent tagging of the final record, per axis.
Everything is computed by the shared holistic pipeline: annotation alignment
(welfare split + step-1 axes) happens at input loading, and the ``drift``
analyzer scores every comparable axis — scalars by exact match, multi-valued
axes by set overlap. Tagging reuses the run's existing provenance bundle for
`evals/dad_axes.yaml`, so a corpus already tagged (e.g. from the viewer's
Run-diversity page) costs zero extra API calls. This script just renders the
report.

    python evals/drift_report.py --input outputs/dad/runs/<run>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.holistic import analyzers as analyzers_mod
from evals.holistic import fields as fields_mod
from evals.holistic import pipeline
from shared import api

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AXES = ROOT / "evals" / "dad_axes.yaml"


def _pct(x) -> str:
    return f"{round(x * 100)}%"


def _row_cells(axis: str, m: dict) -> list[str]:
    conf = "; ".join(f"{d['intended']} → {d['realized']} ×{d['count']}"
                     for d in m.get("disagreements", [])[:3]) or "—"
    jac = f"{m['mean_jaccard']:.2f}" if "mean_jaccard" in m else "—"
    return [axis, str(m.get("n", 0)), _pct(m.get("agreement", 0)), jac,
            m.get("verdict", ""), conf]


_HEADER = ["axis", "n", "agreement", "jaccard", "verdict",
           "top confusions (intended → realized)"]


def render_report(drift: dict, run_id: str) -> tuple[str, str]:
    """(markdown, html) for the intended-vs-realized drift table, worst first.
    ``agreement`` is exact match (exact-set for multi axes; those also get a mean
    Jaccard column)."""
    rows = sorted(drift.items(), key=lambda kv: kv[1].get("agreement", 1.0))
    agreements = [m.get("agreement") for _, m in rows if m.get("agreement") is not None]
    mean_ag = sum(agreements) / len(agreements) if agreements else None

    md = [f"# Judge-vs-generation tagging drift — {run_id}", ""]
    if mean_ag is not None:
        worst = rows[0][0]
        md.append(f"**Mean agreement across {len(rows)} axes: {_pct(mean_ag)}** "
                  f"(lowest: `{worst}` at {_pct(rows[0][1]['agreement'])}).")
    else:
        md.append("_No comparable axes (no annotations joined)._")
    md += ["", "| " + " | ".join(_HEADER) + " |",
           "|" + "---|" * len(_HEADER)]
    for axis, m in rows:
        md.append("| " + " | ".join(_row_cells(axis, m)) + " |")
    md_text = "\n".join(md) + "\n"

    headline = (f"Mean agreement across {len(rows)} axes: {_pct(mean_ag)}"
                if mean_ag is not None else "No comparable axes.")
    trs = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in _row_cells(axis, m)) + "</tr>"
        for axis, m in rows)
    html = (
        f"<!doctype html><meta charset=utf-8>"
        f"<title>Drift — {run_id}</title>"
        f"<style>body{{font:14px system-ui;margin:2rem;}}"
        f"table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:4px 8px}}</style>"
        f"<h1>Judge-vs-generation tagging drift — {run_id}</h1>"
        f"<p><b>{headline}</b></p>"
        f"<table><tr>{''.join(f'<th>{h}</th>' for h in _HEADER)}</tr>{trs}</table>")
    return md_text, html


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description="Judge-vs-generation tagging drift report.")
    ap.add_argument("--input", required=True, help="run dir (complete spec-driven run)")
    ap.add_argument("--model", default=None, help="override the extraction judge model")
    ap.add_argument("--judge-version", default=None,
                    help="pick one judge-verdict version when a run has several "
                         "(verdicts are unused by drift, but the loader needs one).")
    args = ap.parse_args(argv)

    api.init()
    run_dir = Path(args.input)
    fields = fields_mod.load_fields(DEFAULT_AXES)
    analyzers = analyzers_mod.select(analyzers_mod.default_analyzers(), ["drift"])
    report = pipeline.run(run_dir, fields=fields, analyzers=analyzers,
                          model=args.model, judge_version=args.judge_version,
                          axes_text=DEFAULT_AXES.read_text())

    drift = report["stats"]["analyses"].get("drift", {})
    md, html = render_report(drift, report.get("run_id") or run_dir.name)
    (run_dir / "drift_report.md").write_text(md)
    (run_dir / "drift_report.html").write_text(html)
    print(f"drift report written to {run_dir}/drift_report.md")
    return report


if __name__ == "__main__":
    main()
