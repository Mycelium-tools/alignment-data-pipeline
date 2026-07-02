"""Run detail: the run's documents front and center; metadata tucked away."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from viewer import loader, rendering
from viewer.ui_pages import common

run = common.pick_run()
if run is None:
    st.stop()

manifest = loader.load_manifest(run.run_dir)
st.title(run.label or run.run_id)
st.caption((run.created_at or "").replace("T", " ")[:16])


@st.dialog("Document", width="large")
def show_document(record: dict, pipeline: str):
    if pipeline == "sdf":
        scores = record.get("scores", {})
        if scores:
            st.caption(f"alignment {scores.get('alignment')} · realism {scores.get('realism')} "
                       f"· diversity {scores.get('diversity')}")
        st.code(record.get("content", ""), language=None, wrap_lines=True)
        record_id = record["doc_id"]
    else:
        for msg in record.get("messages", []):
            st.markdown(f"**{msg['role']}**")
            st.code(msg["content"], language=None, wrap_lines=True)
        record_id = record["record_id"]
    if st.button(":material/account_tree: View full lineage (prompts at every stage)"):
        st.query_params["doc"] = record_id
        st.switch_page("ui_pages/document_detail.py")


docs_tab, prompts_tab = st.tabs(["Documents", "Prompts"])

with docs_tab:
    finals = loader.load_final(run.run_dir, run.pipeline)
    if not finals:
        st.info("No final corpus in this run yet (incomplete run).")
    elif run.pipeline == "sdf":
        subtypes = {s["subtype_id"]: s for s in loader.load_stage(run.run_dir, "sdf", "layer2")}
        df = pd.DataFrame([{
            "doc_id": d["doc_id"],
            "type": subtypes.get(d.get("subtype_id"), {}).get("type_name", ""),
            "subtype": subtypes.get(d.get("subtype_id"), {}).get("subtype_name", ""),
            "align": d.get("scores", {}).get("alignment"),
            "realism": d.get("scores", {}).get("realism"),
            "preview": (d.get("content") or "")[:160],
        } for d in finals])

        f1, f2 = st.columns([3, 1])
        type_filter = f1.multiselect("Filter by type", sorted(df["type"].unique()),
                                     placeholder="All types")
        min_score = f2.slider("Min score", 1, 10, 1)
        view = df[df["type"].isin(type_filter)] if type_filter else df
        view = view[(view["align"].fillna(0) >= min_score) & (view["realism"].fillna(0) >= min_score)]

        st.caption(f"{len(view)} documents — click a row to read")
        event = st.dataframe(
            view.drop(columns=["doc_id"]), width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row", key="sdf_docs",
        )
        if event.selection.rows:
            doc_id = view.iloc[event.selection.rows[0]]["doc_id"]
            show_document(next(d for d in finals if d["doc_id"] == doc_id), "sdf")
    else:
        audits = {a["record_id"]: a for a in loader.load_stage(run.run_dir, "dad", "step6")}
        df = pd.DataFrame([{
            "record_id": rec["record_id"],
            "injection": audits.get(rec.get("record_id"), {}).get("injection_used", ""),
            "scenario": str(audits.get(rec.get("record_id"), {}).get("scenario_id", "")),
            "preview": rec["messages"][0]["content"][:160] if rec.get("messages") else "",
        } for rec in finals])

        inj_filter = st.multiselect("Filter by injection", sorted(x for x in df["injection"].unique() if x),
                                    placeholder="All injections")
        view = df[df["injection"].isin(inj_filter)] if inj_filter else df

        st.caption(f"{len(view)} records — click a row to read")
        event = st.dataframe(
            view.drop(columns=["record_id"]), width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row", key="dad_docs",
        )
        if event.selection.rows:
            record_id = view.iloc[event.selection.rows[0]]["record_id"]
            show_document(next(r for r in finals if r["record_id"] == record_id), "dad")

with prompts_tab:
    common.run_provenance_note(run)
    for template in rendering.list_templates(run.run_dir, run.git_commit, run.pipeline):
        with st.expander(template.name):
            if template.text is None:
                st.error("Not available in snapshot or git.")
            else:
                st.code(template.text, language=None, wrap_lines=True)

with st.expander(":material/info: Run info"):
    info_cols = st.columns(4)
    info_cols[0].metric("Model", run.model or "—")
    info_cols[1].metric("Cost", f"${run.total_cost:.2f}")
    info_cols[2].metric("Pass rate", f"{run.pass_rate:.0%}" if run.pass_rate is not None else "—")
    info_cols[3].metric("Prompts snapshot", "yes" if run.has_snapshot else "no")
    st.markdown(f"**Run ID** `{run.run_id}` · **git** `{run.git_commit}`"
                + (" (dirty tree at run time)" if run.git_dirty else ""))
    st.markdown("**Records per stage**")
    st.dataframe(pd.DataFrame([run.counts]), width="stretch", hide_index=True)
    if run.pipeline == "sdf":
        scores = loader.load_stage(run.run_dir, "sdf", "layer5")
        if scores:
            sdf_scores = pd.DataFrame([s["scores"] for s in scores if "scores" in s])
            numeric = sdf_scores.select_dtypes("number")
            if not numeric.empty:
                st.markdown("**Score distributions (all scored docs, incl. filtered-out)**")
                st.dataframe(numeric.describe().loc[["mean", "min", "max"]], width="stretch")
    else:
        responses = loader.load_stage(run.run_dir, "dad", "step5")
        if responses:
            by_inj = pd.DataFrame(responses).groupby("injection_used")["kept"].agg(["count", "sum"])
            by_inj.columns = ["generated", "kept"]
            st.markdown("**Step-5 responses by injection**")
            st.dataframe(by_inj, width="stretch")
    st.markdown("**Full config**")
    st.json(run.config, expanded=False)
