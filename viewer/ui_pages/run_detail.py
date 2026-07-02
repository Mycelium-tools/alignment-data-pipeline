"""Run detail: corpus browser, prompt templates, and stats for one run."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from viewer import loader, rendering
from viewer.ui_pages import common

st.title("Run detail")
run = common.pick_run()
if run is None:
    st.stop()

manifest = loader.load_manifest(run.run_dir)

meta_cols = st.columns(5)
meta_cols[0].metric("Final", run.counts.get("final", 0))
meta_cols[1].metric("Pass rate", f"{run.pass_rate:.0%}" if run.pass_rate is not None else "—")
meta_cols[2].metric("Cost", f"${run.total_cost:.2f}")
meta_cols[3].metric("Model", run.model or "—")
meta_cols[4].metric("Snapshot", "yes" if run.has_snapshot else "no")
if run.git_dirty:
    st.warning(f"Repo had uncommitted changes at run time: {', '.join(manifest.get('git_dirty_files', [])[:10])}")
with st.expander("Config snapshot"):
    st.json(run.config)

corpus_tab, prompts_tab, stats_tab = st.tabs(["Corpus", "Prompts", "Stats"])

with corpus_tab:
    finals = loader.load_final(run.run_dir, run.pipeline)
    if not finals:
        st.info("No final corpus in this run (incomplete run?). Per-stage counts are on the Stats tab.")
    elif run.pipeline == "sdf":
        subtypes = {s["subtype_id"]: s for s in loader.load_stage(run.run_dir, "sdf", "layer2")}
        rows = []
        for d in finals:
            st_rec = subtypes.get(d.get("subtype_id"), {})
            rows.append({
                "doc_id": d["doc_id"],
                "type": st_rec.get("type_name", ""),
                "subtype": st_rec.get("subtype_name", ""),
                "lang": d.get("language", ""),
                "alignment": d.get("scores", {}).get("alignment"),
                "realism": d.get("scores", {}).get("realism"),
                "diversity": d.get("scores", {}).get("diversity"),
                "preview": (d.get("content") or "")[:120],
            })
        df = pd.DataFrame(rows)
        f1, f2, f3 = st.columns(3)
        type_filter = f1.multiselect("Type", sorted(df["type"].unique()))
        lang_filter = f2.multiselect("Language", sorted(df["lang"].unique()))
        min_score = f3.slider("Min alignment & realism", 1, 10, 1)
        if type_filter:
            df = df[df["type"].isin(type_filter)]
        if lang_filter:
            df = df[df["lang"].isin(lang_filter)]
        df = df[(df["alignment"].fillna(0) >= min_score) & (df["realism"].fillna(0) >= min_score)]
        st.dataframe(df, width='stretch', hide_index=True)
        choice = st.selectbox("Inspect document", df["doc_id"].tolist(),
                              format_func=lambda i: f"{i[:8]} — {df[df.doc_id == i]['subtype'].iloc[0][:60]}")
        if choice:
            selected = next(d for d in finals if d["doc_id"] == choice)
            st.markdown("#### Final document")
            st.code(selected.get("content", ""), language=None, wrap_lines=True)
        if st.button("Open lineage view (prompts + all stages)", type="primary"):
            st.query_params["doc"] = choice
            st.switch_page("ui_pages/document_detail.py")
    else:
        audits = {a["record_id"]: a for a in loader.load_stage(run.run_dir, "dad", "step6")}
        rows = []
        for rec in finals:
            audit = audits.get(rec.get("record_id"), {})
            rows.append({
                "record_id": rec["record_id"],
                "injection": audit.get("injection_used", ""),
                "principle": audit.get("principle_id", ""),
                "scenario": str(audit.get("scenario_id", "")),
                "user preview": rec["messages"][0]["content"][:120] if rec.get("messages") else "",
            })
        df = pd.DataFrame(rows)
        f1, f2 = st.columns(2)
        inj_filter = f1.multiselect("Injection", sorted(df["injection"].unique()))
        source_filter = f2.multiselect("Source", ["manta", "generated"])
        if inj_filter:
            df = df[df["injection"].isin(inj_filter)]
        if source_filter:
            is_manta = df["scenario"].str.startswith("manta_")
            df = df[is_manta if source_filter == ["manta"] else ~is_manta if source_filter == ["generated"] else is_manta | ~is_manta]
        st.dataframe(df, width='stretch', hide_index=True)
        choice = st.selectbox("Inspect record", df["record_id"].tolist(),
                              format_func=lambda i: i[:8])
        if choice:
            selected = next(r for r in finals if r["record_id"] == choice)
            st.markdown("#### Final training record")
            for msg in selected.get("messages", []):
                st.markdown(f"**{msg['role']}**")
                st.code(msg["content"], language=None, wrap_lines=True)
        if st.button("Open lineage view (prompts + all stages)", type="primary"):
            st.query_params["doc"] = choice
            st.switch_page("ui_pages/document_detail.py")

with prompts_tab:
    if not run.has_snapshot:
        st.warning("Pre-snapshot run: templates below are reconstructed from git commit "
                   f"`{run.git_commit}` and may not match what actually ran.")
    for template in rendering.list_templates(run.run_dir, run.git_commit, run.pipeline):
        with st.expander(f"{template.name} — {template.source}"):
            st.markdown(common.source_badge(template.source, run.git_commit))
            if template.text is None:
                st.error("Not available in snapshot or git.")
            else:
                st.code(template.text, language=None, wrap_lines=True)

with stats_tab:
    st.markdown("**Records per stage**")
    st.dataframe(pd.DataFrame([run.counts]), width='stretch', hide_index=True)
    st.markdown(f"**Total API cost:** ${run.total_cost:.4f}")
    if run.pipeline == "sdf":
        scores = loader.load_stage(run.run_dir, "sdf", "layer5")
        if scores:
            sdf_scores = pd.DataFrame([s["scores"] for s in scores if "scores" in s])
            st.markdown("**Score distributions (all scored docs, incl. filtered-out)**")
            st.dataframe(sdf_scores.describe().loc[["mean", "min", "max"]], width='stretch')
    else:
        responses = loader.load_stage(run.run_dir, "dad", "step5")
        if responses:
            by_inj = pd.DataFrame(responses).groupby("injection_used")["kept"].agg(["count", "sum"])
            by_inj.columns = ["generated", "kept"]
            st.markdown("**Step-5 responses by injection (ruthless is filtered by judge)**")
            st.dataframe(by_inj, width='stretch')
