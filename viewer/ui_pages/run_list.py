"""Run list: every run of both pipelines with run-level details on click."""

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


def run_details(run: loader.RunInfo) -> None:
    st.markdown(f"**{run.label or run.run_id}** · `{run.run_id}` · git `{run.git_commit}`"
                + (" (dirty tree at run time)" if run.git_dirty else ""))
    st.markdown("**Records per stage**")
    st.dataframe(pd.DataFrame([run.counts]), width="stretch", hide_index=True)
    breakdown = loader.cost_by_stage(run.run_dir)
    if breakdown:
        st.markdown("**Cost by stage**")
        st.dataframe(pd.DataFrame([
            {"stage": stage, "calls": agg["calls"], "cost ($)": agg["cost_usd"],
             "model(s)": ", ".join(agg["models"])}
            for stage, agg in breakdown.items()
        ]), width="stretch", hide_index=True)
    st.markdown("**Config**")
    st.json(run.config, expanded=False)
    if st.button(":material/account_tree: View documents", type="primary", key=f"open_{run.run_id}"):
        st.query_params["pipeline"] = run.pipeline
        st.query_params["run"] = run.run_id
        st.switch_page("ui_pages/lineage.py")


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
        "pass rate": f"{r.pass_rate:.0%}" if r.pass_rate is not None else "—",
        "cost ($)": r.total_cost,
        "model": r.model,
        "snapshot": "✓" if r.has_snapshot else "✗",
    } for r in pipeline_runs])

    event = st.dataframe(
        df, width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row",
        key=f"runs_{pipeline}",
    )
    if event.selection.rows:
        run_details(pipeline_runs[event.selection.rows[0]])
