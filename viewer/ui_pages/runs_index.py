"""Runs index: every run of both pipelines. Click a row to open the run."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from viewer import loader

st.title("Pipeline runs")

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

    df = pd.DataFrame([{
        "run": r.run_id,
        "label": r.label,
        "date": (r.created_at or "").replace("T", " ")[:16],
        "documents" if pipeline == "sdf" else "records": r.counts.get("final", 0),
        "cost ($)": r.total_cost,
    } for r in pipeline_runs])

    event = st.dataframe(
        df, width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row",
        key=f"runs_{pipeline}",
    )
    if event.selection.rows:
        selected = pipeline_runs[event.selection.rows[0]]
        st.query_params["pipeline"] = pipeline
        st.query_params["run"] = selected.run_id
        st.switch_page("ui_pages/run_detail.py")
