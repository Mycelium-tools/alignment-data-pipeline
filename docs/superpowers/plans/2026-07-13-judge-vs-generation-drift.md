# Judge-vs-generation tagging drift — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure per-axis agreement between the DAD generation-time annotation and the diversity judge's independent tagging on a complete run, and emit a regenerable `drift_report.md`/`.html`.

**Architecture:** A new self-contained `evals/drift_report.py`. It reuses the existing holistic pipeline (`pipeline.resolve_inputs` → `pipeline.run` with the `drift`/`distribution`/`evenness` analyzers), inserting one augmentation step on the annotation map so both sides expose *identical* axes: split generation's compound `welfare_magnitude` into `welfare_severity`+`welfare_scope`, and lift `taxa_category` (normalized) + `systemic_ai` from the step-1 dilemma. No changes to the judge, `dad_axes.yaml`, or shared pipeline code.

**Tech Stack:** Python 3.12+, existing `evals/holistic/*` (pipeline, fields, analyzers), `shared/utils.py` (`load_jsonl`), pytest with `stub_claude`.

## Global Constraints

- Python floor 3.12 (`shared/__init__.py`); numpy-compatible.
- Tests NEVER call the Anthropic API: use the `stub_claude` fixture (`shared.api.call_claude` chokepoint); pytest-socket blocks the network; outputs go to `tmp_path`.
- The comparison must be like-for-like: axes compared must share name **and** vocabulary between the augmented annotation map and `evals/dad_axes.yaml`.
- Dataset for the real run: `outputs/dad/runs/2026-07-12_20-59_length-dice-smoke` (complete, 5 records). n=5 is anecdotal — report is a first look.
- Welfare vocab: severity ∈ {Mild, Moderate, Severe}; scope ∈ {Individual, Group, Population}. Generation `welfare_magnitude` is always `"{severity} x {scope}"`.
- Taxa normalization: generation `"farmed animals"` → judge `"farmed"` (only gap).
- Do not drop any existing annotation field when augmenting.

---

### Task 1: `parse_welfare_magnitude` helper

**Files:**
- Create: `evals/drift_report.py`
- Test: `tests/test_drift_report.py`

**Interfaces:**
- Produces: `parse_welfare_magnitude(value) -> tuple[str | None, str | None]` — splits `"Severe x Population"` into `("Severe", "Population")`; returns `(None, None)` for any non-matching input (fail-safe).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drift_report.py
"""Tests for evals/drift_report.py (fully offline; the judge tag call is stubbed).

The two pure helpers (welfare split, annotation augmentation) and the renderer are
tested directly; the CLI money path runs through main() with stub_claude.
"""

from evals import drift_report


class TestParseWelfareMagnitude:
    def test_splits_severity_and_scope(self):
        assert drift_report.parse_welfare_magnitude("Severe x Population") == ("Severe", "Population")
        assert drift_report.parse_welfare_magnitude("Mild x Individual") == ("Mild", "Individual")

    def test_tolerates_extra_spacing_and_case(self):
        assert drift_report.parse_welfare_magnitude("moderate   x   group") == ("Moderate", "Group")

    def test_returns_none_on_malformed(self):
        assert drift_report.parse_welfare_magnitude("garbage") == (None, None)
        assert drift_report.parse_welfare_magnitude("") == (None, None)
        assert drift_report.parse_welfare_magnitude(None) == (None, None)
        assert drift_report.parse_welfare_magnitude("Severe / Population") == (None, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_drift_report.py::TestParseWelfareMagnitude -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.drift_report'` (or AttributeError).

- [ ] **Step 3: Write minimal implementation**

```python
# evals/drift_report.py
"""Judge-vs-generation tagging drift for a complete spec-driven DAD run.

Compares the generation-time annotation (dealt at step 1, carried to step 3) with
the diversity judge's independent tagging of the final record, per axis. Reuses the
holistic pipeline; the only new logic is aligning the two axis schemas so the
comparison is like-for-like (welfare split + two lifted dilemma axes).

    python evals/drift_report.py --input outputs/dad/runs/<run>
"""

from __future__ import annotations

import re

_WMAG_RE = re.compile(
    r"^\s*(mild|moderate|severe)\s*x\s*(individual|group|population)\s*$", re.IGNORECASE)


def parse_welfare_magnitude(value) -> tuple[str | None, str | None]:
    """Split generation's compound welfare axis "Severity x Scope" into its two
    components (canonical capitalization). (None, None) on any non-matching input."""
    if not isinstance(value, str):
        return (None, None)
    m = _WMAG_RE.match(value)
    if not m:
        return (None, None)
    return (m.group(1).capitalize(), m.group(2).capitalize())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_drift_report.py::TestParseWelfareMagnitude -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add evals/drift_report.py tests/test_drift_report.py
git commit -m "feat(evals): welfare-magnitude split helper for drift report"
```

---

### Task 2: `augment_annotations` — align the annotation schema to the judge

**Files:**
- Modify: `evals/drift_report.py`
- Test: `tests/test_drift_report.py`

**Interfaces:**
- Consumes: `parse_welfare_magnitude` (Task 1).
- Produces: `augment_annotations(base: dict, step3_rows: list[dict], dilemma_rows: list[dict]) -> dict` — returns a new `record_id -> {axis: value}` map: every base annotation copied, plus `welfare_severity`/`welfare_scope` (when `welfare_magnitude` parses) and `taxa_category` (normalized) / `systemic_ai` (lifted via `step3.prompt_id → dilemma.prompt_id`). Existing axes preserved; records with no dilemma match keep their base annotation untouched.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_drift_report.py
class TestAugmentAnnotations:
    def test_splits_welfare_and_lifts_dilemma_axes(self):
        base = {"r1": {"visibility": "Explicit", "welfare_magnitude": "Severe x Group"}}
        step3 = [{"record_id": "r1", "prompt_id": "AW-0001"}]
        dilemmas = [{"prompt_id": "AW-0001", "taxa_category": "farmed animals",
                     "systemic_ai": False}]
        out = drift_report.augment_annotations(base, step3, dilemmas)
        assert out["r1"]["welfare_severity"] == "Severe"
        assert out["r1"]["welfare_scope"] == "Group"
        assert out["r1"]["taxa_category"] == "farmed"          # normalized
        assert out["r1"]["systemic_ai"] is False
        assert out["r1"]["visibility"] == "Explicit"           # preserved
        assert base["r1"] == {"visibility": "Explicit",        # input not mutated
                              "welfare_magnitude": "Severe x Group"}

    def test_keeps_record_when_welfare_malformed_or_no_dilemma_match(self):
        base = {"r2": {"welfare_magnitude": "garbage"}}
        out = drift_report.augment_annotations(base, [], [])
        assert "welfare_severity" not in out["r2"]             # malformed → not added
        assert out["r2"]["welfare_magnitude"] == "garbage"     # nothing dropped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_drift_report.py::TestAugmentAnnotations -v`
Expected: FAIL with `AttributeError: module 'evals.drift_report' has no attribute 'augment_annotations'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to evals/drift_report.py
_TAXA_NORMALIZE = {"farmed animals": "farmed"}


def augment_annotations(base: dict, step3_rows: list[dict],
                        dilemma_rows: list[dict]) -> dict:
    """New record_id -> {axis: value} map with the welfare split and the two lifted
    dilemma axes; base axes preserved, input not mutated."""
    rid_to_pid = {r["record_id"]: r.get("prompt_id")
                  for r in step3_rows if "record_id" in r}
    pid_to_dilemma = {d["prompt_id"]: d for d in dilemma_rows if "prompt_id" in d}
    out: dict = {}
    for rid, ann in base.items():
        new = dict(ann)
        sev, scope = parse_welfare_magnitude(ann.get("welfare_magnitude"))
        if sev is not None:
            new["welfare_severity"] = sev
            new["welfare_scope"] = scope
        dilemma = pid_to_dilemma.get(rid_to_pid.get(rid))
        if dilemma is not None:
            if "taxa_category" in dilemma:
                taxa = dilemma["taxa_category"]
                new["taxa_category"] = _TAXA_NORMALIZE.get(taxa, taxa)
            if "systemic_ai" in dilemma:
                new["systemic_ai"] = dilemma["systemic_ai"]
        out[rid] = new
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_drift_report.py::TestAugmentAnnotations -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add evals/drift_report.py tests/test_drift_report.py
git commit -m "feat(evals): augment annotations to align schema with the judge"
```

---

### Task 3: `render_report` — markdown + HTML artifact

**Files:**
- Modify: `evals/drift_report.py`
- Test: `tests/test_drift_report.py`

**Interfaces:**
- Consumes: the `drift` analyzer output shape — `{axis: {"n": int, "agreement": float, "disagreements": [{"intended", "realized", "count"}], "verdict": str}}` — and the `distribution` output `{axis: {value: count}}`.
- Produces: `render_report(drift: dict, distribution: dict, run_id: str) -> tuple[str, str]` — `(markdown, html)`. Axes sorted worst-agreement-first; headline line with mean agreement and the lowest-agreement axis.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_drift_report.py
class TestRenderReport:
    def test_lists_each_axis_agreement_and_headline(self):
        drift = {
            "visibility": {"n": 5, "agreement": 0.8,
                           "disagreements": [{"intended": "Explicit",
                                              "realized": "Implicit", "count": 1}],
                           "verdict": "OK"},
            "welfare_severity": {"n": 5, "agreement": 0.6,
                                 "disagreements": [], "verdict": "BAD"},
        }
        md, html = drift_report.render_report(drift, {}, "length-dice-smoke")
        assert "length-dice-smoke" in md
        assert "visibility" in md and "welfare_severity" in md
        assert "80%" in md and "60%" in md                     # agreement rendered as pct
        assert "Explicit" in md and "Implicit" in md           # confusion pair shown
        # worst axis first: welfare_severity (0.60) appears before visibility (0.80)
        assert md.index("welfare_severity") < md.index("visibility")
        assert "<table" in html and "welfare_severity" in html

    def test_handles_empty_drift(self):
        md, html = drift_report.render_report({}, {}, "empty")
        assert "empty" in md
        assert "<table" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_drift_report.py::TestRenderReport -v`
Expected: FAIL with `AttributeError: ... 'render_report'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to evals/drift_report.py

def _pct(x) -> str:
    return f"{round(x * 100)}%"


def render_report(drift: dict, distribution: dict, run_id: str) -> tuple[str, str]:
    """(markdown, html) for the intended-vs-realized drift table, worst first."""
    rows = sorted(drift.items(), key=lambda kv: kv[1].get("agreement", 1.0))
    agreements = [m.get("agreement") for _, m in rows if m.get("agreement") is not None]
    mean_ag = sum(agreements) / len(agreements) if agreements else None

    # ---- markdown ----
    md = [f"# Judge-vs-generation tagging drift — {run_id}", ""]
    if mean_ag is not None:
        worst = rows[0][0]
        md.append(f"**Mean agreement across {len(rows)} axes: {_pct(mean_ag)}** "
                  f"(lowest: `{worst}` at {_pct(rows[0][1]['agreement'])}).")
    else:
        md.append("_No comparable axes (no annotations joined)._")
    md += ["", "| axis | n | agreement | verdict | top confusions (intended → realized) |",
           "|---|---|---|---|---|"]
    for axis, m in rows:
        conf = "; ".join(f"{d['intended']} → {d['realized']} ×{d['count']}"
                         for d in m.get("disagreements", [])[:3]) or "—"
        md.append(f"| {axis} | {m.get('n', 0)} | {_pct(m.get('agreement', 0))} "
                  f"| {m.get('verdict', '')} | {conf} |")
    md_text = "\n".join(md) + "\n"

    # ---- html (self-contained) ----
    trs = []
    for axis, m in rows:
        conf = "; ".join(f"{d['intended']} → {d['realized']} ×{d['count']}"
                         for d in m.get("disagreements", [])[:3]) or "—"
        trs.append(f"<tr><td>{axis}</td><td>{m.get('n', 0)}</td>"
                   f"<td>{_pct(m.get('agreement', 0))}</td>"
                   f"<td>{m.get('verdict', '')}</td><td>{conf}</td></tr>")
    headline = (f"Mean agreement across {len(rows)} axes: {_pct(mean_ag)}"
                if mean_ag is not None else "No comparable axes.")
    html = (
        f"<!doctype html><meta charset=utf-8>"
        f"<title>Drift — {run_id}</title>"
        f"<style>body{{font:14px system-ui;margin:2rem;}}"
        f"table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:4px 8px}}</style>"
        f"<h1>Judge-vs-generation tagging drift — {run_id}</h1>"
        f"<p><b>{headline}</b></p>"
        f"<table><tr><th>axis</th><th>n</th><th>agreement</th><th>verdict</th>"
        f"<th>top confusions</th></tr>{''.join(trs)}</table>")
    return md_text, html
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_drift_report.py::TestRenderReport -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add evals/drift_report.py tests/test_drift_report.py
git commit -m "feat(evals): render drift report as markdown + html"
```

---

### Task 4: CLI `main` — resolve, augment, run, write

**Files:**
- Modify: `evals/drift_report.py`
- Test: `tests/test_drift_report.py`

**Interfaces:**
- Consumes: `augment_annotations`, `render_report`; `evals.holistic.pipeline` (`resolve_inputs`, `run`), `evals.holistic.fields.load_fields`, `evals.holistic.analyzers` (`select`, `default_analyzers`), `shared.utils.load_jsonl`, `shared.api`.
- Produces: `main(argv=None) -> dict` — parses `--input <run_dir>` (and optional `--model`), tags + runs `drift`/`distribution`/`evenness`, writes `drift_report.md` and `drift_report.html` into the run dir, returns the pipeline report dict.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_drift_report.py
import json
from shared import utils

_JUDGE = ('{"visibility": "Explicit", "user_attitude": "Concerned", '
          '"conflict": "Divergent", "direction": "Mixed", "user_stakes": "Medium", '
          '"leverage": "Individual", "welfare_severity": "Severe", '
          '"welfare_scope": "Group", "taxa_category": "farmed", "systemic_ai": false}')


def _make_complete_run(tmp_path):
    run = tmp_path / "2026-01-01_00-00_drift-test"
    (run / "final").mkdir(parents=True)
    (run / "step3").mkdir()
    (run / "step1").mkdir()
    msgs = [{"role": "user", "content": "Switch to caged hens?"},
            {"role": "assistant", "content": "Weighing it..."}]
    utils.append_jsonl({"record_id": "r1", "messages": msgs},
                       run / "final" / "dad_corpus.jsonl")
    utils.append_jsonl({"record_id": "r1", "prompt_id": "AW-0001",
                        "annotation": {"visibility": "Explicit",
                                       "user_attitude": "Concerned",
                                       "conflict": "Divergent", "direction": "Mixed",
                                       "user_stakes": "Medium", "leverage": "Individual",
                                       "welfare_magnitude": "Severe x Group"}},
                       run / "step3" / "rewrites.jsonl")
    utils.append_jsonl({"prompt_id": "AW-0001", "taxa_category": "farmed animals",
                        "systemic_ai": False}, run / "step1" / "dilemmas.jsonl")
    return run


class TestMainCLI:
    def test_writes_report_and_computes_drift(self, tmp_path, stub_claude, monkeypatch):
        monkeypatch.setattr("shared.api.init", lambda *a, **k: None)
        stub_claude([_JUDGE])                                   # one judge tag for r1
        run = _make_complete_run(tmp_path)
        report = drift_report.main(["--input", str(run)])
        assert (run / "drift_report.md").exists()
        assert (run / "drift_report.html").exists()
        drift = report["stats"]["analyses"]["drift"]
        # welfare split + lifted axes are compared and agree (annotation == judge tag)
        assert drift["welfare_severity"]["agreement"] == 1.0
        assert drift["taxa_category"]["agreement"] == 1.0      # both normalized to "farmed"
        assert drift["visibility"]["agreement"] == 1.0
        assert "welfare_severity" in (run / "drift_report.md").read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_drift_report.py::TestMainCLI -v`
Expected: FAIL with `AttributeError: ... 'main'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add imports at top of evals/drift_report.py, below `import re`
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.holistic import analyzers as analyzers_mod
from evals.holistic import fields as fields_mod
from evals.holistic import pipeline
from shared import api, utils

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AXES = ROOT / "evals" / "dad_axes.yaml"
_ANALYZERS = ["drift", "distribution", "evenness"]


# add at the bottom of evals/drift_report.py
def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description="Judge-vs-generation tagging drift report.")
    ap.add_argument("--input", required=True, help="run dir (complete spec-driven run)")
    ap.add_argument("--model", default=None, help="override the extraction judge model")
    args = ap.parse_args(argv)

    api.init()
    run_dir = Path(args.input)
    inputs = pipeline.resolve_inputs(run_dir)
    step3_rows = utils.load_jsonl(run_dir / "step3" / "rewrites.jsonl")
    dilemma_rows = utils.load_jsonl(run_dir / "step1" / "dilemmas.jsonl")
    inputs.annotations = augment_annotations(inputs.annotations or {},
                                             step3_rows, dilemma_rows)

    fields = fields_mod.load_fields(DEFAULT_AXES)
    analyzers = analyzers_mod.select(analyzers_mod.default_analyzers(), _ANALYZERS)
    report = pipeline.run(inputs, fields=fields, analyzers=analyzers,
                          model=args.model, axes_text=DEFAULT_AXES.read_text())

    analyses = report["stats"]["analyses"]
    md, html = render_report(analyses.get("drift", {}),
                             analyses.get("distribution", {}),
                             report.get("run_id") or run_dir.name)
    (run_dir / "drift_report.md").write_text(md)
    (run_dir / "drift_report.html").write_text(html)
    print(f"drift report written to {run_dir}/drift_report.md")
    return report


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_drift_report.py::TestMainCLI -v`
Expected: PASS. If the extraction is parallelized and the FIFO stub errors, switch `stub_claude([_JUDGE])` to a callable dispatcher returning `_JUDGE` for any prompt (see `tests/conftest.py`).

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all pass (no network, ~seconds).

- [ ] **Step 6: Commit**

```bash
git add evals/drift_report.py tests/test_drift_report.py
git commit -m "feat(evals): drift_report CLI — judge-vs-generation agreement"
```

---

### Task 5: Real run on `length-dice-smoke` + inspect

**Files:** none (verification + data artifact).

- [ ] **Step 1: Ensure the run is in the tree**

Run: `ls outputs/dad/runs/2026-07-12_20-59_length-dice-smoke/final/dad_corpus.jsonl`
Expected: the file exists (already checked out from `origin/constance/dad-refinement4`).

- [ ] **Step 2: Run the drift report for real (costs ~5 judge calls, a few cents)**

Run: `python evals/drift_report.py --input outputs/dad/runs/2026-07-12_20-59_length-dice-smoke`
Expected: prints "drift report written to …/drift_report.md"; no traceback.

- [ ] **Step 3: Inspect the artifact**

Run: `cat outputs/dad/runs/2026-07-12_20-59_length-dice-smoke/drift_report.md`
Expected: a table with the ~10 compared axes (`visibility, user_attitude, conflict, direction, user_stakes, leverage, welfare_severity, welfare_scope, taxa_category, systemic_ai`), each with n=5, an agreement %, verdict, and confusion pairs, plus the mean-agreement headline. Confirm welfare and taxa rows are present (proves the augmentation wired through).

- [ ] **Step 4: Sanity-check the numbers**

Confirm every listed axis reports `n=5` (all records joined). If any axis is missing, the annotation/tag names diverged — re-check `augment_annotations` output against `dad_axes.yaml` axis names.

- [ ] **Step 5: Report the headline to the user** (mean agreement + which axes drift most). No commit of the generated `drift_report.*` unless the user asks to keep it as a reviewable artifact.

---

## Self-Review

**Spec coverage:**
- Dataset (complete length-dice-smoke, n=5 caveat) → Task 5. ✓
- Welfare split (no judge/yaml change) → Tasks 1–2. ✓
- Lift + normalize taxa_category / systemic_ai → Task 2. ✓
- 6 identical scalars pass through (compared by `drift` as-is) → exercised in Task 4 test + Task 5. ✓
- Reuse `resolve_inputs` + `drift` (no shared-code change) → Task 4. ✓
- Markdown + HTML in run dir → Task 3 + Task 4. ✓
- Out-of-scope multi/free axes: `drift` compares scalars only, so `domain`/`user_goal`/`values_in_tension`/`moral_patients` are naturally excluded — no code needed. ✓
- Offline tests for the two pure helpers + renderer + CLI money path → Tasks 1–4. ✓
- Cost ~5 calls → Task 5. ✓

**Placeholder scan:** none — every code step shows complete code; every run step shows the command + expected output.

**Type consistency:** `parse_welfare_magnitude` returns `(str|None, str|None)` used in `augment_annotations`; `augment_annotations(base, step3_rows, dilemma_rows)` signature identical in Task 2 definition, Task 4 call, and tests; `render_report(drift, distribution, run_id)` signature identical across Task 3 and Task 4; `main(argv=None)` matches the CLI test call `main(["--input", str(run)])`. `inputs.annotations` is a mutable dataclass field (confirmed non-frozen), so direct assignment in Task 4 is valid.
