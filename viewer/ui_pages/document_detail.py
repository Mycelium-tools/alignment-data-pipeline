"""Document detail: the full lineage of one document/record — every stage's
rendered prompt and output, in chronological order."""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from viewer import loader, rendering
from viewer.ui_pages import common

st.title("Document lineage")
run = common.pick_run()
if run is None:
    st.stop()

manifest = loader.load_manifest(run.run_dir)
finals = loader.load_final(run.run_dir, run.pipeline)
id_key = "doc_id" if run.pipeline == "sdf" else "record_id"
ids = [r[id_key] for r in finals]
if not ids:
    st.info("This run has no final corpus yet.")
    st.stop()

qp_doc = st.query_params.get("doc")
doc_id = st.selectbox(f"Document ({id_key})", ids,
                      index=ids.index(qp_doc) if qp_doc in ids else 0)
st.query_params["doc"] = doc_id


def stage_expander(title: str, stage: str, lineage: dict, output_fn, expanded=False):
    with st.expander(title, expanded=expanded):
        rendered = rendering.render_prompt(run.pipeline, stage, run.run_dir, manifest, lineage)
        st.markdown("##### Prompt")
        common.show_rendered_prompt(rendered)
        st.markdown("##### Output")
        output_fn()


if run.pipeline == "sdf":
    lin = loader.sdf_lineage(run.run_dir, doc_id)

    stage_expander("Layer 1 — document type", "layer1", lin,
                   lambda: st.json(lin["doc_type"]) if lin["doc_type"] else st.caption("not found"))
    stage_expander("Layer 2 — subtype", "layer2", lin,
                   lambda: st.json(lin["subtype"]) if lin["subtype"] else st.caption("not found"))
    stage_expander("Layer 3 — draft", "layer3", lin,
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
    stage_expander("Layer 4 — constitutional rewrite", "layer4", lin, layer4_output, expanded=True)

    def layer5_output():
        sc = lin["score"]
        if not sc:
            st.caption("not reached")
            return
        st.json(sc.get("scores", {}))
        st.markdown("**In final corpus:** " + ("✅ yes" if lin["final"] else "❌ filtered out"))
    stage_expander("Layer 5 — scoring", "layer5", lin, layer5_output)

else:
    lin = loader.dad_lineage(run.run_dir, doc_id)
    audit = lin.get("rewrite") or {}
    scenario = lin.get("scenario") or {}
    st.caption(f"scenario `{audit.get('scenario_id')}` · injection `{audit.get('injection_used')}` "
               f"· principle {audit.get('principle_id')} · source `{scenario.get('source', '?')}`")

    stage_expander("Step 1 — principle annotation", "step1", lin,
                   lambda: st.json({k: v for k, v in (lin.get("principle") or {}).items() if k != "content"})
                   if lin.get("principle") else st.caption("principle record not found"))
    stage_expander("Step 2 — scenario", "step2", lin,
                   lambda: st.json(scenario) if scenario else st.caption("not found"))
    stage_expander("Step 3 — draft user prompt", "step3", lin,
                   lambda: st.code((lin.get("prompt") or {}).get("user_message", "—"), language=None, wrap_lines=True))

    def step4_output():
        ref = lin.get("refined")
        if not ref:
            st.caption("not reached")
            return
        common.show_diff(ref["original"], ref["refined"], "draft prompt", "refined prompt", key="s4")
    stage_expander("Step 4 — refine user prompt", "step4", lin, step4_output)

    def step5_output():
        resp = lin.get("response")
        if not resp:
            st.caption("not reached")
            return
        st.code(resp["assistant_response"], language=None, wrap_lines=True)
        st.markdown(f"**Kept:** {'✅' if resp.get('kept') else '❌ (ruthless judge rejected)'}")
    stage_expander("Step 5 — response under injection", "step5", lin, step5_output)

    if (lin.get("response") or {}).get("injection_used") == "ruthless":
        stage_expander("Step 5b — ruthless judge", "step5_judge", lin,
                       lambda: st.markdown(f"**Verdict (kept):** {(lin.get('response') or {}).get('kept')}"))

    def step6_output():
        if not audit:
            st.caption("not reached")
            return
        common.show_diff(audit["draft_response"], audit["rewritten_response"],
                         "draft response", "constitutional rewrite", key="s6")
    stage_expander("Step 6 — constitutional rewrite (critical step)", "step6", lin, step6_output, expanded=True)

    if lin.get("final"):
        with st.expander("Final training record (what the model trains on)"):
            st.json(lin["final"])
