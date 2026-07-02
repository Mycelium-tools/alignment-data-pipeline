"""Document lineage — the app's main page. Pick a run, click a document,
and see the final text plus every stage's prompt next to its output."""

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
common.run_provenance_note(run)

finals = loader.load_final(run.run_dir, run.pipeline)
id_key = "doc_id" if run.pipeline == "sdf" else "record_id"

# --- Documents table (master) ---
selected_id = None
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

    st.caption(f"{len(view)} documents — select one (checkbox on the left) to see its lineage")
    event = st.dataframe(
        view.drop(columns=["doc_id"]), width="stretch", hide_index=True, height=280,
        on_select="rerun", selection_mode="single-row", key="docs_sdf",
    )
    if event.selection.rows:
        selected_id = view.iloc[event.selection.rows[0]]["doc_id"]
else:
    audits = {a["record_id"]: a for a in loader.load_stage(run.run_dir, "dad", "step6")}
    df = pd.DataFrame([{
        "record_id": rec["record_id"],
        "injection": audits.get(rec.get("record_id"), {}).get("injection_used", ""),
        "scenario": str(audits.get(rec.get("record_id"), {}).get("scenario_id", "")),
        "preview": rec["messages"][0]["content"][:160] if rec.get("messages") else "",
    } for rec in finals])

    inj_filter = st.multiselect("Filter by injection",
                                sorted(x for x in df["injection"].unique() if x),
                                placeholder="All injections")
    view = df[df["injection"].isin(inj_filter)] if inj_filter else df

    st.caption(f"{len(view)} records — select one (checkbox on the left) to see its lineage")
    event = st.dataframe(
        view.drop(columns=["record_id"]), width="stretch", hide_index=True, height=280,
        on_select="rerun", selection_mode="single-row", key="docs_dad",
    )
    if event.selection.rows:
        selected_id = view.iloc[event.selection.rows[0]]["record_id"]

# Deep link: fall back to ?doc= when nothing is clicked yet
ids = [r[id_key] for r in finals]
if selected_id is None:
    qp_doc = st.query_params.get("doc")
    if qp_doc in ids:
        selected_id = qp_doc
if selected_id is not None:
    st.query_params["doc"] = selected_id


def stage_row(title: str, stage: str, lineage: dict, output_fn):
    """One stage: prompt on the left, the output it produced on the right."""
    with st.expander(title):
        rendered = rendering.render_prompt(run.pipeline, stage, run.run_dir, manifest, lineage)
        left, right = st.columns(2)
        with left:
            st.markdown("##### Prompt")
            common.show_rendered_prompt(rendered, key=stage, show_run_warnings=False)
        with right:
            st.markdown("##### Output")
            output_fn()


# --- Lineage (detail) ---
if selected_id is None:
    if finals:
        st.caption("Select a document above (checkbox at the left of a row) to see its lineage.")
elif run.pipeline == "sdf":
    lin = loader.sdf_lineage(run.run_dir, selected_id)
    subtype = lin.get("subtype") or {}

    st.divider()
    st.subheader(subtype.get("subtype_name") or f"Document {selected_id[:8]}")
    scores = (lin.get("final") or {}).get("scores", {})
    if scores:
        st.caption(f"alignment {scores.get('alignment')} · realism {scores.get('realism')} "
                   f"· diversity {scores.get('diversity')}")
    st.code((lin.get("final") or {}).get("content", ""), language=None, wrap_lines=True)

    st.subheader("Prompts")
    stage_row("Layer 1 — document type", "layer1", lin,
              lambda: st.json(lin["doc_type"]) if lin["doc_type"] else st.caption("not found"))
    stage_row("Layer 2 — subtype", "layer2", lin,
              lambda: st.json(lin["subtype"]) if lin["subtype"] else st.caption("not found"))
    stage_row("Layer 3 — draft", "layer3", lin,
              lambda: st.code(lin["draft"]["content"], language=None, wrap_lines=True)
              if lin["draft"] else st.caption("not reached"))

    def layer4_output():
        rw = lin["rewrite"]
        if not rw:
            st.caption("not reached")
            return
        if rw.get("review_notes"):
            st.info(f"Review notes: {rw['review_notes']}")
        common.show_diff(rw["original"], rw["rewritten"], "draft", "rewritten", key="l4")
    stage_row("Layer 4 — constitutional rewrite", "layer4", lin, layer4_output)

    stage_row("Layer 5 — scoring", "layer5", lin,
              lambda: st.json((lin["score"] or {}).get("scores", {}))
              if lin["score"] else st.caption("not reached"))
else:
    lin = loader.dad_lineage(run.run_dir, selected_id)
    audit = lin.get("rewrite") or {}
    scenario = lin.get("scenario") or {}

    st.divider()
    st.subheader(f"Record {selected_id[:8]}")
    st.caption(f"scenario `{audit.get('scenario_id')}` · injection `{audit.get('injection_used')}` "
               f"· principle {audit.get('principle_id')}")
    for msg in (lin.get("final") or {}).get("messages", []):
        st.markdown(f"**{msg['role']}**")
        st.code(msg["content"], language=None, wrap_lines=True)

    st.subheader("Prompts")
    stage_row("Step 1 — principle annotation", "step1", lin,
              lambda: st.json({k: v for k, v in (lin.get("principle") or {}).items() if k != "content"})
              if lin.get("principle") else st.caption("principle record not found"))
    stage_row("Step 2 — scenario", "step2", lin,
              lambda: st.json(scenario) if scenario else st.caption("not found"))
    stage_row("Step 3 — draft user prompt", "step3", lin,
              lambda: st.code((lin.get("prompt") or {}).get("user_message", "—"), language=None, wrap_lines=True))

    def step4_output():
        ref = lin.get("refined")
        if not ref:
            st.caption("not reached")
            return
        common.show_diff(ref["original"], ref["refined"], "draft prompt", "refined prompt", key="s4")
    stage_row("Step 4 — refine user prompt", "step4", lin, step4_output)

    def step5_output():
        resp = lin.get("response")
        if not resp:
            st.caption("not reached")
            return
        st.code(resp["assistant_response"], language=None, wrap_lines=True)
        st.markdown(f"**Kept:** {'✅' if resp.get('kept') else '❌ (ruthless judge rejected)'}")
    stage_row("Step 5 — response under injection", "step5", lin, step5_output)

    if (lin.get("response") or {}).get("injection_used") == "ruthless":
        stage_row("Step 5b — ruthless judge", "step5_judge", lin,
                  lambda: st.markdown(f"**Verdict (kept):** {(lin.get('response') or {}).get('kept')}"))

    def step6_output():
        if not audit:
            st.caption("not reached")
            return
        common.show_diff(audit["draft_response"], audit["rewritten_response"],
                         "draft response", "constitutional rewrite", key="s6")
    stage_row("Step 6 — constitutional rewrite (critical step)", "step6", lin, step6_output)

# --- Run-scoped template browser ---
st.divider()
with st.expander("All prompt templates for this run"):
    for template in rendering.list_templates(run.run_dir, run.git_commit, run.pipeline):
        st.markdown(f"**{template.name}**" + ("" if template.source == "snapshot" else f" · {template.source}"))
        if template.text is None:
            st.error("Not available in snapshot or git.")
        else:
            st.code(template.text, language=None, wrap_lines=True)
