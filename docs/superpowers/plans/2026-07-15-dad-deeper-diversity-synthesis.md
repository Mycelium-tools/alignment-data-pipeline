# Deeper LLM Diversity Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the holistic-diversity LLM judge produce a longer, sectioned analysis that reasons over every Run-diversity graph — including the semantic/embedding diversity it currently can't see — while keeping its input aggregate so it scales to thousands of examples.

**Architecture:** Feed `synthesize.synthesize` a bounded semantic summary alongside the existing categorical `stats` (merged in `pipeline.run`, never persisted into `report["stats"]`). Change the synthesis output schema from a single `prose` string to `verdict` + labelled `sections` + the unchanged `top_issues`. Rewrite the editable prompt to emit that schema and reason per graph family. Update the viewer to render the new shape with a fallback for old `prose` reports.

**Tech Stack:** Python 3.12, pytest (offline, `stub_claude`), Streamlit + Altair viewer. No new dependencies.

## Global Constraints

- Tests NEVER hit the network: stub the model via the `stub_claude` fixture (patches `shared.api.call_claude`, the single chokepoint; `shared.providers.call_model` routes through it for the default model). Assert uuid/timestamps by shape.
- Offline suite must stay green; run `pytest` from the repo root after every functional change.
- No new dependencies.
- Scale rule: the synthesis input must stay **aggregate and bounded by vocabulary, never per-record**. The semantic summary MUST exclude the two O(records) arrays (`projection`, `clusters.assignments`).
- Match existing style in `evals/holistic/`; the synthesis prompt stays an editable template with the single `{{STATS}}` token.

---

## File structure

- `evals/holistic/synthesize.py` — new output schema (`verdict`/`sections`/`top_issues`), validation, `max_tokens` default 8000.
- `evals/holistic/pipeline.py` — new `_load_semantic_summary(base_dir)`; merge it into the synthesis input in `run()`.
- `prompts/tools/dad_holistic_synthesis.txt` — rewritten prompt (sectioned schema, semantic-aware).
- `viewer/ui_pages/run_diversity.py` — render verdict + sections + issues, fallback to old `prose`.
- `tests/test_holistic_config.py` — synthesis schema tests.
- `tests/test_holistic_pipeline.py` — bounded-semantic-merge test.

---

### Task 1: Sectioned synthesis schema + validation

**Files:**
- Modify: `evals/holistic/synthesize.py`
- Test: `tests/test_holistic_config.py`

**Interfaces:**
- Produces: `synthesize.synthesize(stats: dict, *, template: str, model: str | None = None, max_tokens: int = 8000, temperature: float = 0.0) -> dict` returning `{"verdict": str, "sections": list[dict], "top_issues": list[dict], "raw": str, "errors": list[str]}`. Each `sections` item is `{"title": str, "body": str}`.

- [ ] **Step 1: Update the three existing synthesis tests to the new schema**

In `tests/test_holistic_config.py`, replace the bodies of the three synthesis tests:

```python
def test_synthesize_runs_the_editable_holistic_prompt_over_the_stats(stub_claude):
    calls = stub_claude(['{"verdict": "Skewed but usable.", '
                         '"sections": [{"title": "Categorical balance & coverage", '
                         '"body": "Domain is skewed."}], '
                         '"top_issues": [{"axis": "domain", "kind": "balance", "severity": "high"}]}'])
    out = synthesize.synthesize({"analyses": {"distribution": {}}},
                                template="Assess this run:\n{{STATS}}")
    assert out["verdict"] == "Skewed but usable."
    assert out["sections"][0]["title"] == "Categorical balance & coverage"
    assert out["sections"][0]["body"] == "Domain is skewed."
    assert out["top_issues"][0]["axis"] == "domain"
    assert out["errors"] == []
    assert "{{STATS}}" not in calls[0]["user_message"]   # token was expanded
    assert "distribution" in calls[0]["user_message"]    # stats were injected


def test_synthesis_prompt_template_requires_stats_token():
    with pytest.raises(ValueError, match=r"\{\{STATS\}\}"):
        synthesize.synthesize({"analyses": {}}, template="No stats token")


def test_synthesize_marks_unparseable_output_explicitly(stub_claude):
    stub_claude(["not json at all"])
    out = synthesize.synthesize({"analyses": {}}, template="Stats:\n{{STATS}}")
    assert out["errors"] == ["unparseable synthesis model output"]
    assert out["verdict"] == ""
    assert out["sections"] == []
    assert out["top_issues"] == []
```

Then replace the wrong-shape test (currently `test_synthesize_marks_wrong_shape_explicitly` using `'{"prose": 1, "top_issues": {}}'`) with:

```python
def test_synthesize_marks_wrong_shape_explicitly(stub_claude):
    # sections must be a list of {title, body}; top_issues must be a list
    stub_claude(['{"verdict": "x", "sections": [{"title": "t"}], "top_issues": {}}'])
    out = synthesize.synthesize({"analyses": {}}, template="Stats:\n{{STATS}}")
    assert any("sections" in e for e in out["errors"])
    assert any("top_issues" in e for e in out["errors"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_holistic_config.py -k synthes -v`
Expected: FAIL (current code returns `prose`, has no `verdict`/`sections`).

- [ ] **Step 3: Rewrite `_shape_errors` and `synthesize` for the new schema**

In `evals/holistic/synthesize.py`, replace `_shape_errors` and `synthesize` with:

```python
def _shape_errors(parsed: dict) -> list[str]:
    errors: list[str] = []
    sections = parsed.get("sections")
    if not isinstance(sections, list):
        errors.append("sections: missing or not a list")
    elif not all(isinstance(s, dict) and isinstance(s.get("title"), str)
                 and isinstance(s.get("body"), str) for s in sections):
        errors.append("sections: every item must be an object with string title and body")
    if "verdict" in parsed and not isinstance(parsed.get("verdict"), str):
        errors.append("verdict: present but not a string")
    top_issues = parsed.get("top_issues")
    if not isinstance(top_issues, list):
        errors.append("top_issues: missing or not a list")
    elif not all(isinstance(issue, dict) for issue in top_issues):
        errors.append("top_issues: every item must be an object")
    return errors


def synthesize(stats: dict, *, template: str, model: str | None = None,
               max_tokens: int = 8000, temperature: float = 0.0) -> dict:
    """Run the editable holistic prompt over ``stats`` (which may carry a bounded
    ``semantic`` summary). Returns ``{"verdict": str, "sections": list, "top_issues":
    list, "raw": str, "errors": list}``. Unparseable/mis-shaped output yields empty
    best-effort fields plus an explicit ``errors`` list."""
    _require_template_tokens(template)
    prompt = template.replace(STATS_TOKEN, json.dumps(stats, indent=2, ensure_ascii=False))
    raw = providers.call_model(prompt, "", model,
                               max_tokens=max_tokens, temperature=temperature)
    parsed = extract.parse_json(raw)
    if not parsed:
        return {"verdict": "", "sections": [], "top_issues": [], "raw": raw,
                "errors": ["unparseable synthesis model output"]}
    return {
        "verdict": parsed.get("verdict", "") if isinstance(parsed.get("verdict"), str) else "",
        "sections": parsed.get("sections", []) if isinstance(parsed.get("sections"), list) else [],
        "top_issues": parsed.get("top_issues", []) if isinstance(parsed.get("top_issues"), list) else [],
        "raw": raw,
        "errors": _shape_errors(parsed),
    }
```

Also update the module docstring's one-line mention of the return shape if it names `prose` (change to `verdict`/`sections`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_holistic_config.py -k synthes -v`
Expected: PASS (all synthesis tests).

- [ ] **Step 5: Commit**

```bash
git add evals/holistic/synthesize.py tests/test_holistic_config.py
git commit -m "feat(holistic): sectioned synthesis schema (verdict + sections + issues)"
```

---

### Task 2: Bounded semantic summary fed to synthesis

**Files:**
- Modify: `evals/holistic/pipeline.py` (add `_load_semantic_summary`; edit the synthesis block in `run`)
- Test: `tests/test_holistic_pipeline.py`

**Interfaces:**
- Consumes: `synthesize.synthesize` (Task 1).
- Produces: `pipeline._load_semantic_summary(base_dir: Path) -> dict | None` — bounded summary (keys: `embed_model`, `n_embedded`, `n_empty`, `vendi`, `mean_pairwise_cosine`, `nn`, `clusters` (without `assignments`), `top_pairs` (≤5)); `None` if the report is absent or malformed. `run()` passes `{**stats, "semantic": <summary|None>}` to `synthesize`, leaving `report["stats"]` unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_holistic_pipeline.py`:

```python
def test_run_feeds_bounded_semantic_summary_to_synthesis(tmp_path, stub_claude):
    run = _make_run(tmp_path)
    audit = run / "audit"
    audit.mkdir()
    (audit / "diversity_report.json").write_text(json.dumps({
        "embed_model": "stub-embed",
        "n_embedded": 3, "n_empty": 0,
        "vendi": {"score": 2.5},
        "mean_pairwise_cosine": 0.21,
        "nn": {"over_0.90": 0.0},
        "clusters": {"k": 2, "clusters": 2, "evenness": 0.9, "verdict": "GOOD",
                     "assignments": {"a": 0, "b": 1}},
        "top_pairs": [{"similarity": 0.9, "a": "a", "b": "b"}] * 7,   # >5
        "projection": [{"id": "ZZZPROJVAL", "x": 0.1, "y": 0.2, "cluster": 0}],
    }))
    # run(): one tag call (GOOD_JSON) then one synthesis call.
    calls = stub_claude([GOOD_JSON,
                         '{"verdict": "ok", "sections": [], "top_issues": []}'])
    report = pipeline.run(run, synthesis_template="S:\n{{STATS}}")

    synth_prompt = calls[1]["user_message"]
    assert "stub-embed" in synth_prompt          # bounded summary reached the judge
    assert "mean_pairwise_cosine" in synth_prompt
    assert '"projection"' not in synth_prompt     # O(records) array excluded
    assert "ZZZPROJVAL" not in synth_prompt
    assert "assignments" not in synth_prompt      # O(records) cluster map excluded
    assert synth_prompt.count('"similarity"') == 5   # top_pairs capped at 5
    assert "semantic" not in report["stats"]      # persisted stats stay pure


def test_run_semantic_summary_is_null_without_an_audit(tmp_path, stub_claude):
    run = _make_run(tmp_path)   # no audit/diversity_report.json
    calls = stub_claude([GOOD_JSON,
                         '{"verdict": "ok", "sections": [], "top_issues": []}'])
    pipeline.run(run, synthesis_template="S:\n{{STATS}}")
    assert '"semantic": null' in calls[1]["user_message"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_holistic_pipeline.py -k semantic -v`
Expected: FAIL (`_load_semantic_summary` not defined / semantic not in prompt).

- [ ] **Step 3: Add `_load_semantic_summary` and merge it in `run`**

In `evals/holistic/pipeline.py`, add this helper immediately after `_load_clusters`:

```python
def _load_semantic_summary(base_dir: Path) -> dict | None:
    """Bounded aggregate summary of the semantic lane's audit/diversity_report.json
    for the synthesis judge — every aggregate field EXCEPT the two O(records) arrays
    (``projection`` and ``clusters.assignments``) and with ``top_pairs`` capped at 5,
    so the synthesis input stays ~constant size at any corpus size. None when the
    report is absent or malformed."""
    path = base_dir / "audit" / "diversity_report.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            report = json.load(f)
    except json.JSONDecodeError:
        return None
    if not isinstance(report, dict):
        return None
    clusters = report.get("clusters")
    clusters_summary = ({k: v for k, v in clusters.items() if k != "assignments"}
                        if isinstance(clusters, dict) else None)
    top_pairs = report.get("top_pairs")
    return {
        "embed_model": report.get("embed_model"),
        "n_embedded": report.get("n_embedded"),
        "n_empty": report.get("n_empty"),
        "vendi": report.get("vendi"),
        "mean_pairwise_cosine": report.get("mean_pairwise_cosine"),
        "nn": report.get("nn"),
        "clusters": clusters_summary,
        "top_pairs": top_pairs[:5] if isinstance(top_pairs, list) else None,
    }
```

Then, in `run()`, replace the synthesis block:

```python
    if synthesis_template is not None:
        report["synthesis"] = synthesize.synthesize(stats, template=synthesis_template,
                                                     model=model)
```

with (shallow-copy so `report["stats"]` is never mutated):

```python
    if synthesis_template is not None:
        synth_input = dict(stats)
        synth_input["semantic"] = (_load_semantic_summary(inputs.run_dir)
                                   if inputs.run_dir is not None else None)
        report["synthesis"] = synthesize.synthesize(synth_input,
                                                     template=synthesis_template, model=model)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_holistic_pipeline.py -k semantic -v`
Expected: PASS (both new tests).

- [ ] **Step 5: Commit**

```bash
git add evals/holistic/pipeline.py tests/test_holistic_pipeline.py
git commit -m "feat(holistic): feed a bounded semantic summary to the synthesis judge"
```

---

### Task 3: Rewrite the synthesis prompt template

**Files:**
- Modify: `prompts/tools/dad_holistic_synthesis.txt`

**Interfaces:**
- Consumes: the enriched stats dict (categorical `analyses` + optional `semantic`).
- Produces: model output matching the Task 1 schema.

- [ ] **Step 1: Replace the prompt file contents**

Overwrite `prompts/tools/dad_holistic_synthesis.txt` with:

```
You are auditing the DIVERSITY of a synthetic training-data run for animal-welfare
alignment. You are given precomputed statistics over the whole run — you do NOT see
the raw conversations; reason only from these numbers.

The stats cover several "graphs":
- distribution / evenness / coverage_vs_target: how records spread across each
  categorical axis and whether the run hit its designed quotas.
- correlation: Cramer's V between axis pairs. High V = one axis predicts the other;
  attitude x direction predicting each other is the sycophancy tell.
- combination_coverage: which designed axis-pair cells actually occur; filled_cells
  vs missing show combinatorial collapse.
- drift: extraction label vs the generator's intended annotation, per axis.
- structural: whether the assistant replies are all WRITTEN the same way
  (openings, closings, considerations-list scaffold, bold, truncation).
- semantic: meaning-space diversity from embeddings — Vendi score (effective number
  of distinct records), mean pairwise cosine, near-duplicate fractions (nn), and
  k-means cluster spread. This key may be null if the embedding audit hasn't run —
  if so, do not invent a semantic section; reason only from the categorical stats.

A healthy run is diverse and balanced across its axes, has no forbidden correlations
(above all, the user's attitude must NOT predict the assistant's direction), leaves
no important slice empty (Systemic leverage, edge-of-sentience taxa, Hidden
visibility, non-canonical surface forms), is not templated in response form, and is
spread out in meaning-space (high Vendi, low near-dup rate, even clusters).

STATS:
{{STATS}}

Output ONLY a single JSON object:
{
  "verdict": "<one line: overall diversity-health call>",
  "sections": [
    {"title": "<graph family>", "body": "<1-3 paragraphs reasoning about that graph's signal>"}
  ],
  "top_issues": [
    {"axis": "<field or pair>", "kind": "coverage|balance|correlation|combo|drift|semantic|structural",
     "severity": "high|medium|low", "detail": "<what's wrong>", "suggested_fix": "<what to change in generation>"}
  ]
}

Guidance:
- Emit one section PER graph family that has data, in this order when present:
  "Categorical balance & coverage", "Correlations (sycophancy tell)",
  "Combination gaps", "Intent -> realization drift", "Semantic diversity",
  "Response form". Skip a family whose stats are absent or empty (e.g. omit
  "Semantic diversity" when semantic is null).
- In each section name the specific values that drive your read (which axis, which
  cell, which V, which cluster) and what it implies for the trained model.
- Then rank the concrete problems in top_issues, most severe first, each with a
  generation-side fix.
```

- [ ] **Step 2: Verify the token is present and the suite is green**

Run: `grep -c '{{STATS}}' prompts/tools/dad_holistic_synthesis.txt`
Expected: `1` (at least one occurrence).

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (full offline suite; no test asserts the prompt's prose, and the token check in `test_holistic_config.py` still holds).

- [ ] **Step 3: Commit**

```bash
git add prompts/tools/dad_holistic_synthesis.txt
git commit -m "feat(holistic): sectioned, graph-aware synthesis prompt"
```

---

### Task 4: Viewer renders verdict + sections (fallback to prose)

**Files:**
- Modify: `viewer/ui_pages/run_diversity.py` (the synthesis-rendering block near the end of the report section)

**Interfaces:**
- Consumes: `report["synthesis"]` with keys `verdict`, `sections`, `top_issues`, `errors` (Task 1), or an older report with `prose`.

- [ ] **Step 1: Replace the synthesis-rendering block**

Find the current block:

```python
synthesis = report.get("synthesis") or {}
if synthesis.get("top_issues"):
    st.markdown("**Top issues** (LLM synthesis over the stats)")
    for issue in synthesis["top_issues"]:
        fix = issue.get("suggested_fix")
        st.markdown(f"- **[{issue.get('severity', '?')}]** "
                    f"`{issue.get('axis', '?')}` — {issue.get('detail', '')}"
                    + (f" *Fix: {fix}*" if fix else ""))
if synthesis.get("prose"):
    with st.expander("Synthesis assessment", expanded=not synthesis.get("top_issues")):
        st.markdown(synthesis["prose"])
if synthesis.get("errors"):
    st.warning("Synthesis errors: " + "; ".join(synthesis["errors"]))
```

Replace it with:

```python
synthesis = report.get("synthesis") or {}
if synthesis.get("verdict"):
    st.markdown(f"**Overall:** {synthesis['verdict']}")
if synthesis.get("top_issues"):
    st.markdown("**Top issues** (LLM synthesis over the stats)")
    for issue in synthesis["top_issues"]:
        fix = issue.get("suggested_fix")
        st.markdown(f"- **[{issue.get('severity', '?')}]** "
                    f"`{issue.get('axis', '?')}` — {issue.get('detail', '')}"
                    + (f" *Fix: {fix}*" if fix else ""))
_sections = synthesis.get("sections") or []
for i, section in enumerate(_sections):
    with st.expander(section.get("title", "section"),
                     expanded=(i == 0 and not synthesis.get("top_issues"))):
        st.markdown(section.get("body", ""))
if synthesis.get("prose") and not _sections:   # older reports predate sections
    with st.expander("Synthesis assessment", expanded=not synthesis.get("top_issues")):
        st.markdown(synthesis["prose"])
if synthesis.get("errors"):
    st.warning("Synthesis errors: " + "; ".join(synthesis["errors"]))
```

- [ ] **Step 2: Verify the module parses and the suite is green**

Run: `.venv/bin/python -c "import ast; ast.parse(open('viewer/ui_pages/run_diversity.py').read())"`
Expected: no output (valid syntax).

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (full suite).

- [ ] **Step 3: Live-verify in the viewer**

Start the viewer, open Run diversity on a run with a report, press **Analyze** (with a valid model key) to generate a fresh sectioned synthesis, and confirm the page shows the **Overall** verdict line, the **Top issues** list, and one expander per section — and that an older report still shows its **Synthesis assessment** prose. Capture a screenshot.

- [ ] **Step 4: Commit**

```bash
git add viewer/ui_pages/run_diversity.py
git commit -m "feat(viewer): render sectioned synthesis (verdict + sections, prose fallback)"
```

---

## Self-review

- **Spec coverage:** §1 semantic summary → Task 2 (`_load_semantic_summary`, excludes `projection`/`assignments`, caps `top_pairs`). §2 merge without polluting stats → Task 2 `run()` shallow-copy + `"semantic" not in report["stats"]` assertion. §3 sectioned schema → Task 1 (schema/validation) + Task 3 (prompt). §4 validation/prompt/token budget → Task 1 (`_shape_errors`, `max_tokens=8000`) + Task 3 (prompt). §5 viewer → Task 4. Testing bullets → Task 1 & Task 2 tests. Scale rule → Task 2 exclusion asserts.
- **Placeholder scan:** none — every code step shows full code and exact commands.
- **Type consistency:** `synthesize` returns `verdict`/`sections`/`top_issues`/`raw`/`errors` in Task 1; Task 2 tests and Task 4 viewer consume exactly those keys; `_load_semantic_summary` key set is identical in the helper (Task 2 Step 3) and the asserted substrings (Task 2 Step 1).
