#!/usr/bin/env python3
"""Render saved DAD judge verdicts into one self-contained HTML document for analysis.

Reads the verdicts written by evals/score_dad.py
(<corpus dir>/judge/<rubric_version>/verdicts.jsonl), joins each record's
conversation from the corpus, and writes a single-file report that puts the chat
and the judge's review side by side — one section per record, filterable by
pass/fail and searchable in the browser. No API calls.

Usage:
  python evals/report_dad.py --input outputs/dad/latest/final/dad_corpus.jsonl
  python evals/report_dad.py --input <corpus> --rubric-version dad-v1.1
"""

import argparse
import difflib
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import utils
from evals import judge

CSS = """
:root { --pass:#1a7f37; --fail:#cf222e; --ink:#1f2328; --muted:#656d76;
        --line:#d0d7de; --bg:#ffffff; --panel:#f6f8fa; --accent:#0969da; }
* { box-sizing: border-box; }
body { font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       color: var(--ink); background: var(--bg); margin: 0; }
header.top { padding: 24px 32px; border-bottom: 1px solid var(--line); position: sticky;
       top: 0; background: var(--bg); z-index: 5; }
h1 { font-size: 20px; margin: 0 0 4px; }
.sub { color: var(--muted); font-size: 13px; }
.controls { margin-top: 14px; display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.controls input, .controls select { padding: 6px 10px; border: 1px solid var(--line);
       border-radius: 6px; font-size: 13px; }
.summary { padding: 16px 32px; background: var(--panel); border-bottom: 1px solid var(--line);
       overflow-x: auto; }
.summary table { border-collapse: collapse; font-size: 13px; }
.summary th, .summary td { padding: 5px 12px; text-align: left; border-bottom: 1px solid var(--line); }
.summary th { color: var(--muted); font-weight: 600; }
main { padding: 8px 32px 64px; }
.record { border: 1px solid var(--line); border-radius: 10px; margin: 18px 0; overflow: hidden; }
.record > summary { list-style: none; cursor: pointer; padding: 12px 18px; background: var(--panel);
       display: flex; gap: 12px; align-items: center; font-weight: 600; }
.record > summary::-webkit-details-marker { display: none; }
.badge { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; color: #fff; letter-spacing: .3px; }
.badge.pass { background: var(--pass); } .badge.fail { background: var(--fail); }
.rid { color: var(--muted); font-weight: 400; font-family: ui-monospace, monospace; font-size: 12px; }
.title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.body { display: grid; grid-template-columns: 1fr 1fr; gap: 0; }
@media (max-width: 900px) { .body { grid-template-columns: 1fr; } }
.col { padding: 18px; min-width: 0; }
.col.chat { border-right: 1px solid var(--line); }
@media (max-width: 900px) { .col.chat { border-right: none; border-bottom: 1px solid var(--line); } }
.col h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .5px; color: var(--muted);
       margin: 0 0 12px; }
.turn { margin-bottom: 14px; }
.role { font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--accent); }
.role.assistant { color: #8250df; }
.msg { white-space: pre-wrap; word-wrap: break-word; margin-top: 3px; }
.msg ins { background: #d3f9d8; text-decoration: none; border-radius: 2px; }
.msg del { background: #ffe3e3; color: #9a2530; border-radius: 2px; }
.record.variant { margin-left: 26px; }
.inj { font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 999px;
       background: #ddf4ff; color: #0969da; white-space: nowrap; }
.diff-note { font-size: 12px; color: var(--muted); margin-bottom: 10px; }
.model-block { margin-bottom: 22px; padding-bottom: 18px; border-bottom: 1px dashed var(--line); }
.model-block:last-child { border-bottom: none; margin-bottom: 0; }
.model-name { font-weight: 700; font-size: 14px; margin-bottom: 6px; }
.meta-line { font-size: 12px; color: var(--muted); margin: 4px 0; }
.meta-line code { background: var(--panel); padding: 1px 5px; border-radius: 4px; color: var(--ink); }
.scores { display: flex; flex-wrap: wrap; gap: 4px 6px; margin: 8px 0; }
.chip { font-size: 12px; padding: 2px 7px; border-radius: 5px; background: var(--panel); border: 1px solid var(--line); }
.chip b { color: var(--accent); }
.chip.low b { color: var(--fail); }
.signal { font-size: 13px; background: #fff8f0; border-left: 3px solid #d4a72c; padding: 6px 10px;
       margin: 6px 0; border-radius: 0 5px 5px 0; }
.signal .q { color: var(--muted); font-style: italic; }
.analysis { white-space: pre-wrap; word-wrap: break-word; font-size: 14px; background: var(--panel);
       padding: 12px 14px; border-radius: 6px; margin-top: 8px; }
.gate { color: var(--fail); font-size: 12px; margin-top: 6px; }
.err { color: var(--fail); font-size: 13px; }
details.sub-d > summary { cursor: pointer; font-size: 12px; color: var(--accent); margin-top: 8px; }
"""

JS = """
const q = document.getElementById('search');
const f = document.getElementById('filter');
function apply() {
  const term = (q.value || '').toLowerCase();
  const mode = f.value;
  document.querySelectorAll('.record').forEach(r => {
    const pass = r.dataset.pass === '1';
    const text = r.dataset.text;
    const okMode = mode === 'all' || (mode === 'pass' && pass) || (mode === 'fail' && !pass);
    const okTerm = !term || text.includes(term);
    r.style.display = (okMode && okTerm) ? '' : 'none';
  });
}
q.addEventListener('input', apply);
f.addEventListener('change', apply);
document.getElementById('expand').addEventListener('click', () =>
  document.querySelectorAll('.record').forEach(r => r.open = true));
document.getElementById('collapse').addEventListener('click', () =>
  document.querySelectorAll('.record').forEach(r => r.open = false));
"""


def _esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip().lstrip("#").strip().strip("*").strip()
        if line:
            return line[:100]
    return "(untitled)"


def _diff_html(base: str, new: str) -> str:
    """Word-level inline diff of `new` against `base`: additions in <ins>,
    removals in <del>, so near-identical variants show only what changed."""
    a = re.split(r"(\s+)", base)
    b = re.split(r"(\s+)", new)
    out = []
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(_esc("".join(b[b1:b2])))
            continue
        removed = "".join(a[a1:a2])
        added = "".join(b[b1:b2])
        if removed.strip():
            out.append(f"<del>{_esc(removed.strip())}</del> ")
        if added:
            out.append(f"<ins>{_esc(added)}</ins>")
    return "".join(out)


def _chat_html(messages: list[dict], base_messages: list[dict] | None = None) -> str:
    parts = []
    if base_messages:
        parts.append('<div class="diff-note">Differences vs the group’s first record: '
                     '<ins>added</ins> · <del>removed</del></div>')
    for i, m in enumerate(messages):
        role = m.get("role", "?")
        content = m.get("content", "")
        base = (base_messages[i] if base_messages and i < len(base_messages)
                and base_messages[i].get("role") == role else None)
        body = _diff_html(base["content"], content) if base and base["content"] != content \
            else _esc(content)
        parts.append(
            f'<div class="turn"><div class="role {_esc(role)}">{_esc(role)}</div>'
            f'<div class="msg">{body}</div></div>'
        )
    return "".join(parts)


def _scores_html(verdict: dict, floors: dict) -> str:
    chips = []
    for dim, val in (verdict.get("dimension_scores") or {}).items():
        low = isinstance(val, (int, float)) and dim in floors and val < floors[dim]
        cls = "chip low" if low else "chip"
        chips.append(f'<span class="{cls}">{_esc(dim)} <b>{_esc(val)}</b></span>')
    return f'<div class="scores">{"".join(chips)}</div>' if chips else ""


def _signals_html(verdict: dict) -> str:
    out = []
    for s in verdict.get("signals_triggered") or []:
        out.append(
            f'<div class="signal"><b>{_esc(s.get("dimension"))}</b> — {_esc(s.get("signal"))}'
            + (f'<br><span class="q">“{_esc(s.get("quote"))}”</span>' if s.get("quote") else "")
            + "</div>"
        )
    return "".join(out)


def _stability_html(verdict: dict) -> str:
    vs = verdict.get("value_stability") or {}
    if not vs:
        return ""
    moves = " → ".join(f't{m.get("turn")}:{m.get("move")}' for m in (vs.get("turn_moves") or []))
    bits = []
    if moves:
        bits.append(moves)
    for k in ("outcome_held", "rationale_held", "resistance_quality"):
        if vs.get(k) is not None:
            bits.append(f'{k}=<code>{_esc(vs.get(k))}</code>')
    return f'<div class="meta-line"><b>Stability:</b> {" · ".join(bits)}</div>' if bits else ""


def _model_review_html(res: dict, rubric: dict, floors: dict) -> str:
    model = _esc(res.get("model"))
    if not res.get("verdict"):
        return (f'<div class="model-block"><div class="model-name">{model}</div>'
                f'<div class="err">{_esc(res.get("error") or "no verdict")}</div></div>')
    v = res["verdict"]
    agg = res.get("aggregate") or judge.aggregate(v, rubric)  # older rows omit the aggregate
    passing = agg.get("passing")
    badge = ('<span class="badge pass">PASS</span>' if passing
             else '<span class="badge fail">FAIL</span>')
    head = (f'<div class="model-name">{model} {badge} '
            f'<span class="rid">mean {_esc(agg.get("mean"))}</span></div>')
    meta = (f'<div class="meta-line">Posture <code>{_esc(v.get("posture_class"))}</code> · '
            f'Behavior <code>{_esc(v.get("autonomy_behavior"))}</code> · '
            f'Self-contained <code>{_esc(v.get("self_contained"))}</code> · '
            f'Trajectory <code>{_esc(agg.get("trajectory"))}</code></div>')
    gate = ""
    if agg.get("gate_failures"):
        gate = '<div class="gate">Gate: ' + "; ".join(_esc(g) for g in agg["gate_failures"]) + "</div>"
    analysis = ""
    if v.get("analysis"):
        analysis = f'<div class="analysis">{_esc(v["analysis"])}</div>'
    notes = f'<div class="meta-line">Notes: {_esc(v["notes"])}</div>' if v.get("notes") else ""
    meta_json = ""
    if v.get("metadata"):
        meta_json = ('<details class="sub-d"><summary>Metadata emitted</summary>'
                     f'<div class="analysis">{_esc(json.dumps(v["metadata"], indent=2))}</div></details>')
    return (f'<div class="model-block">{head}{meta}{_stability_html(v)}'
            f'{_scores_html(v, floors)}{gate}{_signals_html(v)}{analysis}{notes}{meta_json}</div>')


def _annotation_html(row: dict) -> str:
    comp = row.get("annotation_comparison")
    if not comp:
        return ""
    return ('<details class="sub-d"><summary>Judge vs annotation (7b comparison)</summary>'
            f'<div class="analysis">{_esc(json.dumps(comp, indent=2))}</div></details>')


def _record_section(row: dict, messages: list[dict], rubric: dict, floors: dict,
                    base_messages: list[dict] | None, injection: str | None,
                    variant: bool, group_size: int) -> str:
    rid = row.get("record_id", "")
    panel = row.get("panel") or {}
    cons_pass = (panel.get("consensus_aggregate") or {}).get("passing")
    # consensus falls back to the single model's pass when only one judge ran
    results = panel.get("results") or []
    if cons_pass is None and results:
        first = next((r for r in results if r.get("verdict")), None)
        if first:
            agg = first.get("aggregate") or judge.aggregate(first["verdict"], rubric)
            cons_pass = agg.get("passing")
    pass_flag = "1" if cons_pass else "0"
    badge = ('<span class="badge pass">PASS</span>' if cons_pass
             else '<span class="badge fail">FAIL</span>')
    title = _first_line(messages[0]["content"]) if messages else "(no conversation found)"
    unstable = ' · <span class="rid">panel unstable</span>' if panel.get("judge_unstable") else ""

    reviews = "".join(_model_review_html(r, rubric, floors) for r in results) or \
        '<div class="err">No judge results in this row.</div>'
    chat = _chat_html(messages, base_messages) if messages else \
        '<div class="err">Conversation not found in corpus for this record_id.</div>'

    search_text = _esc((messages[0]["content"] if messages else "") + " " + rid).lower()
    prompt_tag = (f' · prompt {_esc(row["prompt_md5"][:8])}'
                  if row.get("prompt_md5") else "")
    inj_chip = ""
    if injection:
        label = _esc(injection) + (" · baseline" if group_size > 1 and not variant else "")
        inj_chip = f'<span class="inj">{label}</span>'
    css_class = "record variant" if variant else "record"
    return (
        f'<details class="{css_class}" data-pass="{pass_flag}" data-text="{search_text}">'
        f'<summary>{badge}<span class="title">{_esc(title)}</span>{inj_chip}'
        f'<span class="rid">{_esc(rid[:8])}{prompt_tag}{unstable}</span></summary>'
        f'<div class="body"><div class="col chat"><h3>Conversation</h3>{chat}</div>'
        f'<div class="col"><h3>Judge review</h3>{reviews}{_annotation_html(row)}</div></div>'
        f'</details>'
    )


def build_report(rows: list[dict], corpus: dict, rubric: dict, meta: dict,
                 audits: dict | None = None) -> str:
    floors = (rubric.get("aggregation") or {}).get("critical_floors") or {}
    audits = audits or {}

    # Group same-scenario records (injection variants of one dilemma) so each
    # variant renders as a diff against the group's first record.
    groups: dict[str, list[dict]] = {}
    for row in rows:
        rid = row.get("record_id", "")
        key = str(audits.get(rid, {}).get("scenario_id") or rid)
        groups.setdefault(key, []).append(row)

    sections = []
    for group in groups.values():
        baseline_messages = corpus.get(group[0].get("record_id", ""), {}).get("messages") or []
        for gi, row in enumerate(group):
            rid = row.get("record_id", "")
            messages = corpus.get(rid, {}).get("messages") or []
            is_variant = gi > 0 and bool(baseline_messages)
            injection = audits.get(rid, {}).get("injection_used")
            sections.append(_record_section(
                row, messages, rubric, floors,
                base_messages=baseline_messages if is_variant else None,
                injection=injection,
                variant=is_variant,
                group_size=len(group),
            ))
    summary_rows = "".join(
        f'<tr><td>{_esc(m)}</td><td>{_esc(s.get("pass_rate"))}</td>'
        f'<td>{_esc(s.get("mean_of_means"))}</td><td>{_esc(s.get("judge_errors"))}</td></tr>'
        for m, s in (meta.get("models") or {}).items()
    )
    cons = meta.get("consensus") or {}
    summary = ""
    if summary_rows or cons:
        summary = (
            '<div class="summary"><table><tr><th>model</th><th>pass rate</th>'
            '<th>mean</th><th>errors</th></tr>' + summary_rows + '</table>'
            + (f'<div class="sub" style="margin-top:8px">Consensus pass '
               f'<b>{_esc(cons.get("pass_rate"))}</b> · unstable {_esc(cons.get("unstable_rate"))} '
               f'· error {_esc(cons.get("error_rate"))}</div>' if cons else "")
            + '</div>'
        )

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DAD judge report — {_esc(meta.get('rubric_version'))}</title>
<style>{CSS}</style></head><body>
<header class="top">
  <h1>DAD judge report</h1>
  <div class="sub">rubric <b>{_esc(meta.get('rubric_version'))}</b> · {len(rows)} records · {_esc(meta.get('source'))}</div>
  <div class="controls">
    <input id="search" type="search" placeholder="Search conversations / record id…">
    <select id="filter"><option value="all">All</option><option value="pass">Pass only</option>
      <option value="fail">Fail only</option></select>
    <button id="expand">Expand all</button><button id="collapse">Collapse all</button>
  </div>
</header>
{summary}
<main>{"".join(sections)}</main>
<script>{JS}</script>
</body></html>"""


def _latest_version_dir(judge_root: Path, requested: str | None) -> Path | None:
    if requested:
        d = judge_root / requested
        return d if (d / "verdicts.jsonl").exists() else None
    # newest by mtime, not name — lexicographic ordering breaks at dad-v10 vs dad-v5
    candidates = sorted((p.parent for p in judge_root.glob("*/verdicts.jsonl")),
                        key=lambda d: (d / "verdicts.jsonl").stat().st_mtime)
    return candidates[-1] if candidates else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Render DAD judge verdicts to an HTML report.")
    parser.add_argument("--input", required=True, help="Path to the dad_corpus.jsonl that was judged")
    parser.add_argument("--rubric-version", default=None,
                        help="Which judge/<version>/ to render (default: latest present)")
    parser.add_argument("--out", default=None, help="Output HTML path (default: report.html in the judge dir)")
    args = parser.parse_args()

    corpus_path = Path(args.input)
    judge_root = corpus_path.parent / "judge"
    version_dir = _latest_version_dir(judge_root, args.rubric_version)
    if version_dir is None:
        sys.exit(f"No verdicts found under {judge_root} — run evals/score_dad.py first.")

    rows = utils.load_jsonl(version_dir / "verdicts.jsonl")
    corpus = {r["record_id"]: r for r in utils.load_jsonl(corpus_path) if "record_id" in r}
    # Current 3-step runs write rewrite audits to step3/; legacy 7-step runs to step6/.
    audit_path = corpus_path.parent.parent / "step3" / "rewrites.jsonl"
    if not audit_path.exists():
        audit_path = corpus_path.parent.parent / "step6" / "rewrites.jsonl"
    audits = ({r["record_id"]: r for r in utils.load_jsonl(audit_path) if "record_id" in r}
              if audit_path.exists() else {})
    # Prefer the rubric snapshot saved with the verdicts (evals/score_dad.py), so
    # gates and floors match what actually judged these rows.
    snapshot = version_dir / "rubric.yaml"
    rubric = judge.load_rubric(snapshot) if snapshot.exists() else judge.load_rubric()
    summary_path = version_dir / "summary.json"
    meta = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    meta.setdefault("rubric_version", version_dir.name)
    meta["source"] = str(version_dir.relative_to(corpus_path.parents[2])) \
        if corpus_path.parents[2] in version_dir.parents else str(version_dir)

    out = Path(args.out) if args.out else version_dir / "report.html"
    out.write_text(build_report(rows, corpus, rubric, meta, audits))
    print(f"Wrote {len(rows)}-record report to {out}")


if __name__ == "__main__":
    main()
