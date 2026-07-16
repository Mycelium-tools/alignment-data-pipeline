# DAD Structural-Diversity Analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a mechanical, offline `structural` analyzer that flags response-form collapse (openings/closings/scaffold/formatting) over a DAD run's assistant turns, surfaced on the viewer's Analyze button.

**Architecture:** A new pure-metric module (`evals/holistic/structural.py`) computes the form metrics; a new input-gated `structural` analyzer in the holistic registry reads the assistant text via a new `AnalysisContext.texts` field; `pipeline.run` derives that text from the corpus so the existing Analyze button and CLI pick it up automatically; the Run diversity page renders a new section.

**Tech Stack:** Python 3.12+, numpy (already used by `shared/textstats`), pytest (offline, `--disable-socket`), Streamlit (viewer only).

## Global Constraints

- Python floor is 3.12 (`shared/__init__.py`). No new dependencies.
- Tests NEVER touch the network or the real `outputs/` tree — pytest-socket blocks sockets; use `tmp_path`. `shared.api.call_claude` is stubbed via the `stub_claude` fixture; never let real API calls fire.
- New/changed pipeline behavior needs tests in the same style (see CLAUDE.md "Writing tests for new code"): fast, offline, plain asserts, behavior-not-implementation.
- The analyzer must make **zero** LLM calls (preserve the "Analyze is nearly free" promise).
- Verdicts are provisional and comparative (same stance as `evals/diversity.py`).
- Do **not** modify `evals/audit_sdf.py`.
- Run `pytest` after every functional change and before every commit.

## File Structure

- **Create** `evals/holistic/structural.py` — pure metric functions over assistant text. No I/O, no API. Only dependency: `shared.textstats`.
- **Create** `tests/test_holistic_structural.py` — unit tests for the pure functions.
- **Modify** `evals/holistic/analyzers.py` — add `"texts"` to `INPUTS`; add `texts` field to `AnalysisContext` + `available`; add the `structural` analyzer fn; register it in `default_analyzers()`.
- **Modify** `tests/test_holistic_analyzers.py` — analyzer + input-gating tests.
- **Modify** `evals/holistic/pipeline.py` — `analyze(...)` gains a `texts` param; `run(...)` derives `texts` from the corpus and adds `"texts"` to `inputs_present`.
- **Modify** `tests/test_holistic_pipeline.py` — new wiring test; update two assertions that now include `"texts"`.
- **Modify** `viewer/ui_pages/run_diversity.py` — render the `structural` section.

---

### Task 1: Pure structural-metric module

**Files:**
- Create: `evals/holistic/structural.py`
- Test: `tests/test_holistic_structural.py`

**Interfaces:**
- Consumes: `shared.textstats.ends_mid_sentence`.
- Produces:
  - `assistant_turns(record: dict) -> list[str]`
  - `first_sentence(text: str) -> str`, `last_sentence(text: str) -> str`
  - `opening_moves(first_sentences: list[str]) -> dict`
  - `closing_moves(last_sentences: list[str]) -> dict`
  - `scaffold_shape(texts: list[str]) -> dict`
  - `formatting(texts: list[str]) -> dict`
  - `length_stats(texts: list[str]) -> dict`
  - `recurring(texts: list[str]) -> dict`
  - Each metric dict carries an `"n"` and a `"verdict"` in `{"GOOD","OK","BAD","NA"}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_holistic_structural.py`:

```python
"""Pure structural-form metrics over DAD assistant turns. A corpus whose replies
all open/close/shape the same way scores BAD; a varied one scores GOOD. Offline,
deterministic, no API."""

from evals.holistic import structural as S


def test_assistant_turns_keeps_only_assistant_content_in_order():
    rec = {"messages": [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"}]}
    assert S.assistant_turns(rec) == ["a1", "a2"]


def test_assistant_turns_empty_when_no_assistant_message():
    assert S.assistant_turns({"messages": [{"role": "user", "content": "u"}]}) == []


def test_first_and_last_sentence():
    text = "I understand your concern. Here is the middle. Ultimately it is your call."
    assert S.first_sentence(text) == "I understand your concern."
    assert S.last_sentence(text) == "Ultimately it is your call."


def test_opening_moves_flags_templated_openings_bad():
    same = ["I understand your concern about hens." for _ in range(10)]
    out = S.opening_moves([S.first_sentence(t) for t in same])
    assert out["verdict"] == "BAD"
    assert out["formulaic_frac"] >= 0.9
    assert out["dup_stems"]                      # a repeated 5-word stem is caught


def test_opening_moves_varied_openings_good():
    varied = ["Caged systems raise real welfare costs.",
              "Let's compare the two options directly.",
              "Egg pricing depends on several factors.",
              "Your budget is the first thing to pin down.",
              "Consumers rarely see the supply chain."]
    out = S.opening_moves(varied)
    assert out["verdict"] == "GOOD"


def test_closing_moves_flags_repeated_signoffs_bad():
    ends = ["Ultimately, the choice is yours." for _ in range(8)]
    out = S.closing_moves(ends)
    assert out["verdict"] == "BAD"


def test_scaffold_shape_flags_considerations_arc():
    templated = ["Here are three considerations:\n- cost\n- welfare\n- taste"
                 for _ in range(10)]
    out = S.scaffold_shape(templated)
    assert out["arc_frac"] >= 0.9
    assert out["verdict"] == "BAD"


def test_formatting_flags_pervasive_bold():
    bold = ["This is **very** important." for _ in range(10)]
    out = S.formatting(bold)
    assert out["bold_frac"] >= 0.9
    assert out["verdict"] == "BAD"


def test_length_stats_flags_truncation():
    truncated = ["This sentence just stops abruptly and never" for _ in range(10)]
    out = S.length_stats(truncated)
    assert out["truncated_frac"] == 1.0
    assert out["verdict"] == "BAD"


def test_recurring_flags_stock_phrase():
    texts = ["at the end of the day it depends" for _ in range(10)]
    out = S.recurring(texts)
    assert out["stock_hits"]
    assert out["verdict"] == "BAD"


def test_metrics_return_na_on_empty_input():
    for fn in (S.opening_moves, S.closing_moves, S.scaffold_shape,
               S.formatting, S.length_stats, S.recurring):
        out = fn([])
        assert out["n"] == 0
        assert out["verdict"] == "NA"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_holistic_structural.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'evals.holistic.structural'`.

- [ ] **Step 3: Write the module**

Create `evals/holistic/structural.py`:

```python
"""Structural-diversity metrics over DAD assistant turns — pure, offline, no API.

The holistic categorical analyzers read extraction *tags*; none of them see the
assistant's prose, so response-form collapse (every reply opening, closing, and
shaped the same) is invisible to them. These functions measure that form over the
raw assistant turns. They are the mechanical cousins of the SDF audit's structural
checks (evals/audit_sdf.py), reimplemented here so that working CLI is left
untouched.

Every metric returns a JSON-able dict with an ``n`` and a GOOD/OK/BAD ``verdict``
(same vocabulary as evals/holistic/analyzers.py and evals/diversity.py; a private
copy of ``_verdict`` avoids importing analyzers, which imports this module).
Thresholds are provisional; the reliable read is comparing runs.
"""

from __future__ import annotations

import collections
import re

from shared import textstats


def _verdict(value: float | None, good: float, ok: float,
             higher_better: bool = False) -> str:
    if value is None:
        return "NA"
    if higher_better:
        return "GOOD" if value >= good else ("OK" if value >= ok else "BAD")
    return "GOOD" if value <= good else ("OK" if value <= ok else "BAD")


# ---------------------------------------------------------------- text access

def assistant_turns(record: dict) -> list[str]:
    """The ``content`` of each ``role == 'assistant'`` message, in order."""
    return [m.get("content") or "" for m in record.get("messages", [])
            if m.get("role") == "assistant"]


def first_sentence(text: str) -> str:
    t = (text or "").strip()
    for line in t.splitlines():
        line = line.strip()
        if line:
            t = line
            break
    m = re.search(r"[.!?]", t)
    return t[: m.end()] if m else t[:160]


def last_sentence(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    parts = [p for p in re.split(r"(?<=[.!?])\s+", lines[-1]) if p.strip()]
    return parts[-1] if parts else lines[-1][:160]


# ---------------------------------------------------------------- opening / closing moves

_OPENER_PATTERNS = [
    (re.compile(r"^(i\s+understand|i\s+hear\s+you|i\s+can\s+see|i\s+appreciate)", re.I),
     "I understand / I appreciate ..."),
    (re.compile(r"^(that's|this\s+is)\s+(a\s+)?(great|good|thoughtful|tricky|difficult|tough|really|important)", re.I),
     "That's a great / thoughtful ..."),
    (re.compile(r"^(thank\s+you|thanks)\b", re.I), "Thank you for ..."),
    (re.compile(r"^it\s+sounds\s+like\b", re.I), "It sounds like ..."),
    (re.compile(r"^(great|good)\s+question\b", re.I), "Great question ..."),
    (re.compile(r"^there\s+(are|is)\b", re.I), "There are several ..."),
]

_CLOSER_PATTERNS = [
    (re.compile(r"\bultimately\b", re.I), "Ultimately, ..."),
    (re.compile(r"\b(the\s+choice|the\s+decision)\s+is\s+yours\b", re.I), "The choice is yours"),
    (re.compile(r"\bin\s+the\s+end\b", re.I), "In the end ..."),
    (re.compile(r"\bwhat\s+matters\s+(most\s+)?is\b", re.I), "What matters most is ..."),
    (re.compile(r"\b(i\s+hope\s+this\s+helps|hope\s+that\s+helps)\b", re.I), "I hope this helps"),
    (re.compile(r"\bfeel\s+free\s+to\b", re.I), "Feel free to ..."),
    (re.compile(r"\bat\s+the\s+end\s+of\s+the\s+day\b", re.I), "At the end of the day ..."),
]


def _move_shapes(sentences: list[str], patterns, from_end: bool) -> dict:
    n = len(sentences)
    if not n:
        return {"n": 0, "formulaic_frac": None, "patterns": {}, "dup_stems": [],
                "verdict": "NA"}
    pattern_counts: collections.Counter = collections.Counter()
    for s in sentences:
        for rx, label in patterns:
            if rx.search(s.strip()):
                pattern_counts[label] += 1
                break

    def stem(s: str) -> str:
        w = s.lower().split()
        return " ".join(w[-5:] if from_end else w[:5])

    stems = collections.Counter(stem(s) for s in sentences if s.strip())
    dup_stems = [(s, c) for s, c in stems.most_common(5) if c >= 2]
    formulaic = sum(pattern_counts.values()) / n
    return {"n": n, "formulaic_frac": round(formulaic, 3),
            "patterns": dict(pattern_counts), "dup_stems": dup_stems,
            "verdict": _verdict(formulaic, 0.15, 0.35)}


def opening_moves(first_sentences: list[str]) -> dict:
    return _move_shapes(first_sentences, _OPENER_PATTERNS, from_end=False)


def closing_moves(last_sentences: list[str]) -> dict:
    return _move_shapes(last_sentences, _CLOSER_PATTERNS, from_end=True)


# ---------------------------------------------------------------- scaffold shape

_ENUM_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+", re.M)
_HEADER_RE = re.compile(r"^#{1,4}\s", re.M)
_CONSIDER_RE = re.compile(
    r"\b(considerations?|factors?\s+to\s+consider|things?\s+to\s+consider|"
    r"a\s+few\s+(things|points|considerations)|several\s+(factors|considerations|things))\b",
    re.I)


def scaffold_shape(texts: list[str]) -> dict:
    n = len(texts)
    if not n:
        return {"n": 0, "enumerated_list_frac": None, "header_frac": None,
                "considerations_frac": None, "arc_frac": None, "verdict": "NA"}
    enum = sum(1 for t in texts if _ENUM_RE.search(t))
    header = sum(1 for t in texts if _HEADER_RE.search(t))
    consider = sum(1 for t in texts if _CONSIDER_RE.search(t))
    arc = sum(1 for t in texts if _CONSIDER_RE.search(t) and _ENUM_RE.search(t))
    arc_frac = arc / n
    return {"n": n,
            "enumerated_list_frac": round(enum / n, 3),
            "header_frac": round(header / n, 3),
            "considerations_frac": round(consider / n, 3),
            "arc_frac": round(arc_frac, 3),
            "verdict": _verdict(arc_frac, 0.20, 0.40)}


# ---------------------------------------------------------------- formatting / length

_MD_CLASSES = {
    "bold": re.compile(r"\*\*[^*\n]+\*\*"),
    "bullets": re.compile(r"^[-*] ", re.M),
    "headings": re.compile(r"^#{1,4} ", re.M),
}


def formatting(texts: list[str]) -> dict:
    n = len(texts)
    if not n:
        return {"n": 0, "by_class": {}, "bold_frac": None, "verdict": "NA"}
    counts = {k: sum(1 for t in texts if rx.search(t)) for k, rx in _MD_CLASSES.items()}
    bold_frac = counts["bold"] / n
    return {"n": n, "by_class": {k: round(c / n, 3) for k, c in counts.items()},
            "bold_frac": round(bold_frac, 3),
            "verdict": _verdict(bold_frac, 0.10, 0.30)}


def length_stats(texts: list[str]) -> dict:
    n = len(texts)
    if not n:
        return {"n": 0, "chars_median": None, "truncated_frac": None, "verdict": "NA"}
    lengths = sorted(len(t) for t in texts)
    truncated = sum(1 for t in texts if textstats.ends_mid_sentence(t))
    frac = truncated / n
    return {"n": n,
            "chars_p10": lengths[max(0, n // 10)],
            "chars_median": lengths[n // 2],
            "chars_p90": lengths[min(n - 1, 9 * n // 10)],
            "truncated_frac": round(frac, 4),
            "verdict": _verdict(frac, 0.0, 0.02)}


# ---------------------------------------------------------------- recurring language

STOCK_PHRASES = [
    "i understand your concern", "that's a great question", "great question",
    "it's important to note", "at the end of the day", "there's no easy answer",
    "i hope this helps", "the decision is yours", "the choice is yours",
    "it's worth considering", "on one hand", "on the other hand",
]


def recurring(texts: list[str]) -> dict:
    n = len(texts)
    if not n:
        return {"n": 0, "stock_hits": {}, "recurring_5grams": [], "verdict": "NA"}
    lowered = [t.lower() for t in texts]
    hits = {p: sum(1 for t in lowered if p in t) for p in STOCK_PHRASES}
    hits = {p: c for p, c in hits.items() if c}
    gram_df: collections.Counter = collections.Counter()
    for t in lowered:
        words = re.findall(r"[a-z']+", t)
        grams = {" ".join(words[i:i + 5]) for i in range(len(words) - 4)}
        gram_df.update(grams)
    common = [(g, c) for g, c in gram_df.most_common(200) if c >= max(3, 0.05 * n)][:8]
    worst = max(hits.values(), default=0)
    v = "GOOD" if worst == 0 else ("OK" if worst <= max(1, 0.05 * n) else "BAD")
    return {"n": n, "stock_hits": hits, "recurring_5grams": common, "verdict": v}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_holistic_structural.py -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add evals/holistic/structural.py tests/test_holistic_structural.py
git commit -m "feat(evals): pure structural-form metrics for DAD assistant turns

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `structural` analyzer + `texts` input

**Files:**
- Modify: `evals/holistic/analyzers.py` (`INPUTS`, `AnalysisContext`, new analyzer fn, `default_analyzers`)
- Test: `tests/test_holistic_analyzers.py`

**Interfaces:**
- Consumes: `evals.holistic.structural` (Task 1); `AnalysisContext.texts: dict | None` mapping `record_id -> list[str]` (assistant-turn contents).
- Produces: an analyzer named `"structural"`, `requires=("texts",)`, whose fragment is `{"n", "opening", "closing", "scaffold", "formatting", "length", "recurring"}`. Available in `default_analyzers()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_holistic_analyzers.py` (end of file):

```python
# ---------------------------------------------------------------- structural analyzer

def test_structural_analyzer_flags_templated_replies():
    templated = {f"r{i}": ["I understand your concern. Here are three "
                           "considerations:\n- cost\n- welfare\n- taste"]
                 for i in range(10)}
    out = A.run_analyzers(_ctx(texts=templated), A.default_analyzers())
    frag = out["analyses"]["structural"]
    assert frag["n"] == 10
    assert frag["opening"]["verdict"] == "BAD"
    assert frag["scaffold"]["verdict"] == "BAD"


def test_structural_analyzer_skipped_without_texts():
    out = A.run_analyzers(_ctx(), A.default_analyzers())
    assert "structural" in out["skipped"]
    assert "structural" not in out["analyses"]


def test_available_includes_texts_when_supplied():
    assert "texts" in _ctx(texts={"a": ["hi"]}).available
    assert "texts" not in _ctx().available
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_holistic_analyzers.py -q -k structural`
Expected: FAIL — `TypeError` (`AnalysisContext` has no `texts`) / `KeyError: 'structural'`.

- [ ] **Step 3: Edit `evals/holistic/analyzers.py`**

Change the `INPUTS` tuple (currently `("tags", "annotations", "verdicts", "clusters")`):

```python
INPUTS = ("tags", "annotations", "verdicts", "clusters", "texts")
```

In `AnalysisContext`, add the field (after `clusters`) and update the docstring + `available`:

```python
    clusters: dict | None = None
    texts: dict | None = None
    config: dict = _dc_field(default_factory=dict)

    @property
    def available(self) -> set[str]:
        avail = {"tags"}
        if self.annotations:
            avail.add("annotations")
        if self.verdicts:
            avail.add("verdicts")
        if self.clusters:
            avail.add("clusters")
        if self.texts:
            avail.add("texts")
        return avail
```

Add the import near the top (with the other `from .` imports):

```python
from . import structural as _structural
```

Add the analyzer fn (place it just above `def select(`):

```python
# ---------------------------------------------------------------- structural (response form)

def _structural(ctx: AnalysisContext) -> dict:
    """Response-FORM diversity over the assistant turns (``ctx.texts``: record_id ->
    list of assistant-turn strings). Opening/closing are read from the first assistant
    turn (the primary training answer); scaffold/formatting/length/recurring over all
    turns of the record joined. Mechanical and offline — no API. Blind spot of every
    tag-based analyzer: a corpus can be perfectly varied in topic yet write every reply
    the same way."""
    texts_map = ctx.texts or {}
    first_sents, last_sents, joined = [], [], []
    for turns in texts_map.values():
        if not turns:
            continue
        first_sents.append(_structural_mod.first_sentence(turns[0]))
        last_sents.append(_structural_mod.last_sentence(turns[0]))
        joined.append("\n\n".join(turns))
    return {
        "n": len(joined),
        "opening": _structural_mod.opening_moves(first_sents),
        "closing": _structural_mod.closing_moves(last_sents),
        "scaffold": _structural_mod.scaffold_shape(joined),
        "formatting": _structural_mod.formatting(joined),
        "length": _structural_mod.length_stats(joined),
        "recurring": _structural_mod.recurring(joined),
    }
```

Note: the analyzer fn is named `_structural`, so import the module under a
non-colliding alias. Change the import line to:

```python
from . import structural as _structural_mod
```

Register it in `default_analyzers()` (add after the `cluster_bridge` line, before `return reg`):

```python
    reg.add(Analyzer(name="structural", requires=("texts",), fn=_structural))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_holistic_analyzers.py -q`
Expected: PASS (including the three new tests; existing tests unaffected).

- [ ] **Step 5: Commit**

```bash
git add evals/holistic/analyzers.py tests/test_holistic_analyzers.py
git commit -m "feat(evals): structural analyzer + texts input in holistic registry

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Wire assistant text through the pipeline

**Files:**
- Modify: `evals/holistic/pipeline.py` (`analyze`, `run`)
- Test: `tests/test_holistic_pipeline.py` (new test + update two assertions)

**Interfaces:**
- Consumes: `evals.holistic.structural.assistant_turns` (Task 1); the `texts` param/analyzer from Task 2.
- Produces: `analyze(..., texts=None)`; `run(...)` derives `texts = {record_id: assistant_turns(rec)}` from `inputs.corpus`, passes it to `analyze`, and appends `"texts"` to `inputs_present` when non-empty.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_holistic_pipeline.py` (end of file). It builds a run whose single reply is templated, tags it (stubbed), analyzes, and asserts the structural analysis is present:

```python
def test_run_derives_assistant_texts_and_runs_structural(tmp_path, stub_claude):
    stub_claude([GOOD_JSON])
    run = _make_run(tmp_path, with_annotations=False, with_verdicts=False)
    report = pipeline.run(run)
    assert "texts" in report["inputs_present"]
    assert "structural" in report["stats"]["analyses"]
    assert report["stats"]["analyses"]["structural"]["n"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_holistic_pipeline.py::test_run_derives_assistant_texts_and_runs_structural -q`
Expected: FAIL — `"texts"` not in `inputs_present` / `"structural"` in `skipped`, not `analyses`.

- [ ] **Step 3: Edit `evals/holistic/pipeline.py`**

Add the import near the other `from .` imports:

```python
from .structural import assistant_turns
```

In `analyze(...)`, add the `texts` parameter and thread it into the context:

```python
def analyze(records: list[dict], *, fields: FieldRegistry | None = None,
            analyzers: AnalyzerRegistry | None = None, annotations: dict | None = None,
            verdicts: dict | None = None, clusters: dict | None = None,
            texts: dict | None = None, config: dict | None = None) -> dict:
    """Run the registered analyzers over the tag rows (input-gated). Returns
    ``{"analyses": {...}, "skipped": {...}}``."""
    ctx = AnalysisContext(
        records=records, fields=fields or default_fields(),
        annotations=annotations, verdicts=verdicts, clusters=clusters,
        texts=texts, config=config or {})
    return run_analyzers(ctx, analyzers or default_analyzers())
```

In `run(...)`, derive `texts` from the corpus and pass it to `analyze`. Replace the
`stats = analyze(...)` call and the `present` block:

```python
    texts = {r["record_id"]: assistant_turns(r)
             for r in inputs.corpus if r.get("record_id")}
    stats = analyze(records, fields=fields, analyzers=analyzers, config=config,
                    annotations=inputs.annotations, verdicts=inputs.verdicts,
                    clusters=inputs.clusters, texts=texts)
    present = ["tags"]
    if inputs.annotations:
        present.append("annotations")
    if inputs.verdicts:
        present.append("verdicts")
    if inputs.clusters:
        present.append("clusters")
    if texts:
        present.append("texts")
```

- [ ] **Step 4: Update the two assertions that now include `"texts"`**

In `tests/test_holistic_pipeline.py`, the bare-corpus and no-input run tests now
resolve a corpus with `messages`, so `"texts"` is present. Update both:

- Line ~50 (`test_run_on_a_bare_corpus_file_tags_into_a_sibling_holistic_bundle`):
  change `assert report["inputs_present"] == ["tags"]` to
  `assert report["inputs_present"] == ["tags", "texts"]`.
- Line ~176 (the run test asserting `report["inputs_present"] == ["tags"]`):
  change to `assert report["inputs_present"] == ["tags", "texts"]`.

(If either corpus fixture has a record with no `messages`, `texts` would be empty and
`"texts"` would not appear — in that case leave that assertion unchanged. Verify by
reading the fixture the test uses before editing.)

- [ ] **Step 5: Run the full holistic suite**

Run: `pytest tests/test_holistic_pipeline.py tests/test_holistic_analyzers.py tests/test_holistic_structural.py tests/test_holistic_cli.py -q`
Expected: PASS. If `test_holistic_cli.py` fails on an `inputs_present`/`skipped`
assertion, it uses a hand-built report fixture (not `run()` output) — those do not
change; only real `run()` outputs gain `"texts"`. Fix any real-output assertion the
same way as Step 4.

- [ ] **Step 6: Run the whole suite**

Run: `pytest -q`
Expected: PASS (offline, ~seconds).

- [ ] **Step 7: Commit**

```bash
git add evals/holistic/pipeline.py tests/test_holistic_pipeline.py
git commit -m "feat(evals): derive assistant texts in holistic run, feed structural analyzer

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Render the structural section on the Run diversity page

**Files:**
- Modify: `viewer/ui_pages/run_diversity.py`

**Interfaces:**
- Consumes: `report["stats"]["analyses"]["structural"]` (Task 3), shape
  `{opening, closing, scaffold, formatting, length, recurring}`.
- Produces: a rendered Streamlit section. No automated test (Streamlit page render);
  verified manually via the preview.

- [ ] **Step 1: Add the render block**

In `viewer/ui_pages/run_diversity.py`, immediately after the `drift` block (ends
around line 245, before `synthesis = report.get("synthesis") or {}`), insert:

```python
structural = analyses.get("structural", {})
if structural:
    st.markdown("**Response-form diversity** — are the assistant replies all *written* "
                "the same way? Reads the reply text (not the tags): openings, closings, "
                "the considerations-list scaffold, formatting, and length. Mechanical "
                "and free; read it comparatively across runs.")
    op = structural.get("opening", {})
    cl = structural.get("closing", {})
    sc = structural.get("scaffold", {})
    fm = structural.get("formatting", {})
    ln = structural.get("length", {})
    st.dataframe(pd.DataFrame([
        {"signal": "opening move (formulaic share)",
         "value": op.get("formulaic_frac"), "verdict": op.get("verdict")},
        {"signal": "closing move (formulaic share)",
         "value": cl.get("formulaic_frac"), "verdict": cl.get("verdict")},
        {"signal": "considerations-list arc",
         "value": sc.get("arc_frac"), "verdict": sc.get("verdict")},
        {"signal": "pervasive **bold**",
         "value": fm.get("bold_frac"), "verdict": fm.get("verdict")},
        {"signal": "truncated mid-sentence",
         "value": ln.get("truncated_frac"), "verdict": ln.get("verdict")},
    ]), width="stretch", hide_index=True)
    dupes = (op.get("dup_stems") or []) + (cl.get("dup_stems") or [])
    if dupes:
        with st.expander("Repeated opening / closing phrasings"):
            for stem, count in dupes:
                st.markdown(f"- `{stem}` ×{count}")
```

- [ ] **Step 2: Verify the page imports cleanly**

Run: `python -c "import ast; ast.parse(open('viewer/ui_pages/run_diversity.py').read()); print('ok')"`
Expected: `ok` (no syntax error). `pandas`/`st` are already imported at the top of the file.

- [ ] **Step 3: Manual verification (preview)**

Start the viewer and open Run diversity on a DAD run that has a tag index, click
**Analyze**, and confirm a "Response-form diversity" section appears with a 5-row
verdict table (and the expander when repeated stems exist), at no added API cost
(the only call is the existing synthesis).

Launch: `.claude/launch.json` "viewer" entry runs `streamlit run viewer.html`/app —
use the preview tools (`preview_start {name: "viewer"}`) if configured; otherwise
`streamlit run viewer/app.py` locally. Navigate to **Run diversity**, pick a DAD run,
**Analyze**.

- [ ] **Step 4: Run the whole suite once more**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add viewer/ui_pages/run_diversity.py
git commit -m "feat(viewer): render structural response-form section on Run diversity

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Structural signals (opening/closing/scaffold/formatting/length/recurring) → Task 1. ✓
- First-assistant-turn for opening/closing, all-turns for the rest → Task 2 `_structural` fn. ✓
- New `structural` analyzer, input-gated, in `default_analyzers` → Task 2. ✓
- `AnalysisContext.texts` + `INPUTS` + `available` → Task 2. ✓
- Pipeline derives texts, `inputs_present` gains `"texts"` → Task 3. ✓
- Renders on Run diversity + feeds synthesis (automatic — synthesis reads whole stats) → Task 4. ✓
- Mechanical/offline/free, no new deps, `audit_sdf.py` untouched, register omitted → honored across tasks; no LLM call added. ✓
- Tests: pure fns, analyzer templated-vs-varied, input gating, pipeline wiring → Tasks 1–3. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has expected output. ✓

**Type consistency:** module fn names (`opening_moves`, `closing_moves`, `scaffold_shape`, `formatting`, `length_stats`, `recurring`, `assistant_turns`, `first_sentence`, `last_sentence`) are used identically in Tasks 2–3. Analyzer fragment keys (`opening/closing/scaffold/formatting/length/recurring`) match the Task 4 renderer. `AnalysisContext.texts` is `record_id -> list[str]` in Tasks 2 and 3. Module imported as `_structural_mod` to avoid colliding with the `_structural` analyzer fn. ✓

**Known integration risk (called out in Task 3):** adding `structural` to `default_analyzers` and deriving `texts` in `run()` changes real `run()` outputs — two `inputs_present == ["tags"]` assertions become `["tags", "texts"]`. Handled in Task 3 Steps 4–5. Hand-built report fixtures in `test_holistic_cli.py` are unaffected (they never call the analyzer).
