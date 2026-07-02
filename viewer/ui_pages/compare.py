"""Compare two runs: prompt-template diffs + matched outputs side by side."""

import difflib
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from viewer import loader, rendering
from viewer.ui_pages import common

st.title("Compare runs")
st.caption("Diff the prompts between two runs of the same pipeline, next to the outputs they produced.")

runs = loader.list_runs()
if len(runs) < 2:
    st.info("Need at least two runs to compare.")
    st.stop()

pipelines = sorted({r.pipeline for r in runs})
pipeline = st.selectbox("Pipeline", pipelines)
pipeline_runs = [r for r in runs if r.pipeline == pipeline]
if len(pipeline_runs) < 2:
    st.info(f"Only one {pipeline} run exists — nothing to compare against.")
    st.stop()

col_a, col_b = st.columns(2)
ids = [r.run_id for r in pipeline_runs]
run_a_id = col_a.selectbox("Run A (older/baseline)", ids, index=min(1, len(ids) - 1))
run_b_id = col_b.selectbox("Run B (newer)", ids, index=0)
run_a = next(r for r in pipeline_runs if r.run_id == run_a_id)
run_b = next(r for r in pipeline_runs if r.run_id == run_b_id)
if run_a_id == run_b_id:
    st.warning("Pick two different runs.")
    st.stop()

st.header("Prompt differences")
templates_a = {t.name: t for t in rendering.list_templates(run_a.run_dir, run_a.git_commit, pipeline)}
templates_b = {t.name: t for t in rendering.list_templates(run_b.run_dir, run_b.git_commit, pipeline)}
any_diff = False
for name in sorted(set(templates_a) | set(templates_b)):
    ta, tb = templates_a.get(name), templates_b.get(name)
    text_a = ta.text if ta else None
    text_b = tb.text if tb else None
    if text_a == text_b:
        continue
    any_diff = True
    label = name
    if text_a is None:
        label += " (only in B)"
    elif text_b is None:
        label += " (only in A)"
    with st.expander(label, expanded=True):
        badges = []
        if ta:
            badges.append(f"A: {common.source_badge(ta.source, run_a.git_commit)}")
        if tb:
            badges.append(f"B: {common.source_badge(tb.source, run_b.git_commit)}")
        st.markdown(" · ".join(badges))
        diff = "\n".join(difflib.unified_diff(
            (text_a or "").splitlines(), (text_b or "").splitlines(),
            fromfile=f"A/{name}", tofile=f"B/{name}", lineterm="",
        ))
        st.code(diff, language="diff", wrap_lines=True)
if not any_diff:
    st.success("No prompt/constitution differences between these runs — output differences come from sampling.")

st.header("Matched outputs")
pairs = loader.match_outputs(run_a.run_dir, run_b.run_dir, pipeline)
if not pairs:
    st.info("No matching outputs between the two runs (different types/scenarios, or a run has no final corpus).")
    st.stop()

quality_note = {"exact": "", "positional": " :orange-badge[positional match]", "group": " :gray-badge[grouped]"}
content_of = (lambda rec: rec.get("content", "")) if pipeline == "sdf" else \
             (lambda rec: rec["messages"][1]["content"] if rec.get("messages") else "")

for pair in pairs:
    with st.expander(f"{pair.key} — {len(pair.a)} vs {len(pair.b)}{quality_note.get(pair.quality, '')}"):
        n = min(len(pair.a), len(pair.b))
        for i in range(n):
            ca, cb = st.columns(2)
            with ca:
                st.markdown(f"**A: {run_a_id}**")
                st.code(content_of(pair.a[i]), language=None, wrap_lines=True)
            with cb:
                st.markdown(f"**B: {run_b_id}**")
                st.code(content_of(pair.b[i]), language=None, wrap_lines=True)
        if len(pair.a) != len(pair.b):
            st.caption(f"Unpaired extras: A has {len(pair.a)}, B has {len(pair.b)}.")
