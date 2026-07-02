"""Runs index: every run of both pipelines, newest first."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from viewer import loader

st.title("Pipeline runs")
st.caption("Every run under `outputs/`. Select a run on the Run detail page to browse its corpus and prompts.")

runs = loader.list_runs()
if not runs:
    st.info("No runs found under outputs/. Run a pipeline first.")
    st.stop()

for pipeline, title in [("sdf", "SDF — pretraining-style documents"),
                        ("dad", "DAD — difficult-advice chat transcripts")]:
    pipeline_runs = [r for r in runs if r.pipeline == pipeline]
    st.subheader(title)
    if not pipeline_runs:
        st.caption("No runs yet.")
        continue

    rows = []
    for r in pipeline_runs:
        row = {
            "run_id": r.run_id,
            "label": r.label,
            "model": r.model,
            "created": r.created_at,
            "final docs" if pipeline == "sdf" else "final records": r.counts.get("final", 0),
            "pass rate": f"{r.pass_rate:.0%}" if r.pass_rate is not None else "—",
            "cost ($)": r.total_cost,
            "prompts snapshot": "✓" if r.has_snapshot else "✗ (pre-snapshot)",
            "dirty tree": {True: "⚠️ yes", False: "no", None: "unknown"}[r.git_dirty],
            "commit": r.git_commit,
        }
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

st.divider()
st.markdown(
    "**Legend** — *prompts snapshot*: run carries its own frozen copy of prompts + constitution "
    "(runs made before this feature show ✗ and their prompts are reconstructed from git). "
    "*dirty tree*: uncommitted changes existed at run time, so git reconstruction may not "
    "match what actually ran."
)
