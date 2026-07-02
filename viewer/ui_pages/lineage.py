"""Document lineage — the app's main page. Pick a run, click a document row,
and read the final document side by side with the prompts that produced it."""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from viewer import loader, rendering
from viewer.ui_pages import common

PANEL_HEIGHT = 750  # px; the two comparison panels scroll independently

run = common.pick_run()
if run is None:
    st.stop()

manifest = loader.load_manifest(run.run_dir)
st.title(run.label or run.run_id)
st.caption((run.created_at or "").replace("T", " ")[:16])
common.run_provenance_note(run)

finals = loader.load_final(run.run_dir, run.pipeline)
id_key = "doc_id" if run.pipeline == "sdf" else "record_id"
ids = [r[id_key] for r in finals]

selected_id = st.session_state.get("lineage_doc")
if selected_id not in ids:
    selected_id = st.query_params.get("doc")
    if selected_id not in ids:
        selected_id = None

def _doc_title_and_preview(content: str) -> tuple[str, str]:
    """First meaningful line of the document as its title, next text as preview."""
    lines = [l.strip().lstrip("#").strip().strip("*").strip()
             for l in (content or "").splitlines()]
    lines = [l for l in lines if l]
    title = lines[0][:90] if lines else "(untitled)"
    preview = " ".join(lines[1:3])[:110] if len(lines) > 1 else ""
    return title, preview


def _row_button(item_id: str, label: str) -> None:
    global selected_id
    if st.button(label, key=f"row_{item_id}", width="stretch",
                 type="primary" if item_id == selected_id else "tertiary"):
        selected_id = item_id
        st.session_state["lineage_doc"] = item_id


# --- Document list (whole row clickable, grouped) ---
if not finals:
    st.info("No final corpus in this run yet (incomplete run).")
elif run.pipeline == "sdf":
    subtypes = {s["subtype_id"]: s for s in loader.load_stage(run.run_dir, "sdf", "layer2")}
    f1, f2 = st.columns([3, 1])
    all_types = sorted({subtypes.get(d.get("subtype_id"), {}).get("type_name", "") for d in finals})
    type_filter = f1.multiselect("Filter by type", all_types, placeholder="All types")
    min_score = f2.slider("Min score", 1, 10, 1)

    # group documents by subtype so identical-subtype docs sit under one header
    groups: dict[str, list] = {}
    kept = 0
    for d in finals:
        st_rec = subtypes.get(d.get("subtype_id"), {})
        scores = d.get("scores", {})
        if type_filter and st_rec.get("type_name", "") not in type_filter:
            continue
        if (scores.get("alignment") or 0) < min_score or (scores.get("realism") or 0) < min_score:
            continue
        group = st_rec.get("subtype_name", "ungrouped")
        groups.setdefault(group, []).append(d)
        kept += 1

    st.caption(f"{kept} documents — click one to open it")
    with st.container(height=min(400, 52 * kept + 34 * len(groups) + 20)):
        for group, docs in groups.items():
            st.caption(f":material/folder: {group}")
            for d in docs:
                title, preview = _doc_title_and_preview(d.get("content"))
                _row_button(d["doc_id"], f"**{title}**" + (f" — {preview}…" if preview else ""))
else:
    audits = {a["record_id"]: a for a in loader.load_stage(run.run_dir, "dad", "step6")}
    injections = sorted({a.get("injection_used", "") for a in audits.values() if a.get("injection_used")})
    inj_filter = st.multiselect("Filter by injection", injections, placeholder="All injections")

    groups: dict[str, list] = {}
    kept = 0
    for rec in finals:
        audit = audits.get(rec.get("record_id"), {})
        inj = audit.get("injection_used", "?")
        if inj_filter and inj not in inj_filter:
            continue
        groups.setdefault(inj, []).append((rec, audit))
        kept += 1

    st.caption(f"{kept} records — click one to open it")
    with st.container(height=min(400, 52 * kept + 34 * len(groups) + 20)):
        for inj, recs in groups.items():
            st.caption(f":material/vaccines: injection: {inj}")
            for rec, audit in recs:
                user_msg = rec["messages"][0]["content"] if rec.get("messages") else ""
                title, preview = _doc_title_and_preview(user_msg)
                _row_button(rec["record_id"], f"**{title}**" + (f" — {preview}…" if preview else ""))

if selected_id is not None:
    st.query_params["doc"] = selected_id


def stage_expander(title: str, stage: str, lineage: dict, output_fn):
    """One stage: the rendered prompt, then the output it produced."""
    with st.expander(title):
        rendered = rendering.render_prompt(run.pipeline, stage, run.run_dir, manifest, lineage)
        common.show_rendered_prompt(rendered, key=stage, show_run_warnings=False)
        st.markdown("##### Output at this stage")
        output_fn()


# --- Side-by-side: document (left) vs prompts (right) ---
if selected_id is None:
    if finals:
        st.caption("Click a document above to open it.")
elif run.pipeline == "sdf":
    lin = loader.sdf_lineage(run.run_dir, selected_id)
    subtype = lin.get("subtype") or {}
    st.divider()
    doc_col, prompts_col = st.columns(2)

    with doc_col:
        st.subheader(subtype.get("subtype_name") or f"Document {selected_id[:8]}")
        with st.container(height=PANEL_HEIGHT):
            st.code((lin.get("final") or {}).get("content", ""), language=None, wrap_lines=True)

    with prompts_col:
        st.subheader("Prompts")
        st.caption("Each layer's prompt and what it produced")
        with st.container(height=PANEL_HEIGHT):
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
            stage_expander("Layer 4 — constitutional rewrite", "layer4", lin, layer4_output)

            stage_expander("Layer 5 — scoring", "layer5", lin,
                           lambda: st.json((lin["score"] or {}).get("scores", {}))
                           if lin["score"] else st.caption("not reached"))
else:
    lin = loader.dad_lineage(run.run_dir, selected_id)
    audit = lin.get("rewrite") or {}
    st.divider()
    doc_col, prompts_col = st.columns(2)

    with doc_col:
        st.subheader(f"Record {selected_id[:8]}")
        st.caption(f"scenario `{audit.get('scenario_id')}` · injection `{audit.get('injection_used')}` "
                   f"· principle {audit.get('principle_id')}")
        with st.container(height=PANEL_HEIGHT):
            for msg in (lin.get("final") or {}).get("messages", []):
                st.markdown(f"**{msg['role']}**")
                st.code(msg["content"], language=None, wrap_lines=True)

    with prompts_col:
        st.subheader("Prompts")
        st.caption("Each step's prompt and what it produced")
        with st.container(height=PANEL_HEIGHT):
            stage_expander("Step 1 — principle annotation", "step1", lin,
                           lambda: st.json({k: v for k, v in (lin.get("principle") or {}).items() if k != "content"})
                           if lin.get("principle") else st.caption("principle record not found"))
            stage_expander("Step 2 — scenario", "step2", lin,
                           lambda: st.json(lin.get("scenario")) if lin.get("scenario") else st.caption("not found"))
            stage_expander("Step 3 — draft user prompt", "step3", lin,
                           lambda: st.code((lin.get("prompt") or {}).get("user_message", "—"),
                                           language=None, wrap_lines=True))

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
            stage_expander("Step 6 — constitutional rewrite (critical step)", "step6", lin, step6_output)

# --- Run-scoped template browser ---
st.divider()
with st.expander("All prompt templates for this run"):
    for template in rendering.list_templates(run.run_dir, run.git_commit, run.pipeline):
        st.markdown(f"**{template.name}**" + ("" if template.source == "snapshot" else f" · {template.source}"))
        if template.text is None:
            st.error("Not available in snapshot or git.")
        else:
            st.code(template.text, language=None, wrap_lines=True)
