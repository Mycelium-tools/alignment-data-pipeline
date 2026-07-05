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

def _doc_title(content: str) -> str:
    """First meaningful line of the document, cleaned of markdown markers."""
    for line in (content or "").splitlines():
        line = line.strip().lstrip("#").strip().strip("*").strip()
        if line:
            return line[:90]
    return "(untitled)"


def _pick_document(options: list[str], labels: dict[str, str], noun: str) -> str | None:
    """Document dropdown, seeded from the ?doc= query param.

    The widget needs a stable key: without one, Streamlit derives its identity
    from its parameters INCLUDING `index`, and since we compute `index` from
    the query param, every selection changed the identity on the next rerun and
    orphaned the user's choice (the select-twice bug). The key is scoped to the
    run so switching runs starts fresh."""
    if not options:
        st.caption(f"No {noun}s match the current filters.")
        return None
    key = f"doc_pick_{run.pipeline}_{run.run_id}"
    if st.session_state.get(key) not in options:
        st.session_state.pop(key, None)  # stale value (e.g. filters changed) — reseed below
    qp_doc = st.query_params.get("doc")
    choice = st.selectbox(
        f"{noun.capitalize()} ({len(options)})", options,
        index=options.index(qp_doc) if qp_doc in options else 0,
        format_func=lambda i: labels.get(i, str(i)),
        key=key,
    )
    st.query_params["doc"] = choice
    return choice


# --- Document selection ---
selected_id = None
if not finals:
    st.info("No final corpus in this run yet (incomplete run).")
elif run.pipeline == "sdf":
    subtypes = {s["subtype_id"]: s for s in loader.load_stage(run.run_dir, "sdf", "layer2")}
    f1, f2 = st.columns([3, 1])
    all_types = sorted({subtypes.get(d.get("subtype_id"), {}).get("type_name", "") for d in finals})
    type_filter = f1.multiselect(
        "Filter by document type (from Layer 1)", all_types, placeholder="All types",
        help="Top-level document categories generated in Layer 1.",
    )
    min_score = f2.slider("Min score (from Layer 5)", 1, 10, 1,
                          help="Minimum alignment and realism scores assigned in Layer 5.")

    options, labels = [], {}
    for d in sorted(finals, key=lambda d: str(d.get("subtype_id", ""))):
        st_rec = subtypes.get(d.get("subtype_id"), {})
        scores = d.get("scores", {})
        if type_filter and st_rec.get("type_name", "") not in type_filter:
            continue
        if (scores.get("alignment") or 0) < min_score or (scores.get("realism") or 0) < min_score:
            continue
        options.append(d["doc_id"])
        labels[d["doc_id"]] = f"{_doc_title(d.get('content'))}   —   {st_rec.get('subtype_name', '?')}"

    st.caption("Dropdown labels: *document title — subtype (from Layer 2)*")
    selected_id = _pick_document(options, labels, "document")
else:
    dad_legacy = loader.dad_is_legacy(run.run_dir)
    audits = {a["record_id"]: a for a in loader.load_stage(
        run.run_dir, "dad", "step6" if dad_legacy else "step3_rewrites")}

    if dad_legacy:
        injections = sorted({a.get("injection_used", "") for a in audits.values() if a.get("injection_used")})
        inj_filter = st.multiselect(
            "Filter by injection", injections, placeholder="All injections",
            help="The system-prompt injection active when the draft response was sampled.",
        )
        keep = lambda audit: not inj_filter or audit.get("injection_used", "?") in inj_filter
        suffix = lambda audit: audit.get("injection_used", "?")
        sort_key = lambda rec: audits.get(rec.get("record_id"), {}).get("injection_used", "")
        st.caption("Dropdown labels: *user message — injection (from the response sampling step)*")
    else:
        all_tensions = sorted({t for a in audits.values() for t in a.get("tensions", [])})
        tension_filter = st.multiselect(
            "Filter by tension", all_tensions, placeholder="All tensions",
            help="The compendium tensions tagged for this dilemma in step 2a.",
        )
        keep = lambda audit: not tension_filter or any(t in tension_filter for t in audit.get("tensions", []))
        suffix = lambda audit: (audit.get("annotation") or {}).get("direction") or "?"
        sort_key = lambda rec: str(audits.get(rec.get("record_id"), {}).get("prompt_id", ""))
        st.caption("Dropdown labels: *user message — direction (from the step-1 annotation)*")

    options, labels = [], {}
    for rec in sorted(finals, key=sort_key):
        audit = audits.get(rec.get("record_id"), {})
        if not keep(audit):
            continue
        user_msg = rec["messages"][0]["content"] if rec.get("messages") else ""
        options.append(rec["record_id"])
        labels[rec["record_id"]] = f"{_doc_title(user_msg)}   —   {suffix(audit)}"

    selected_id = _pick_document(options, labels, "record")


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
        if lin.get("format") == "v2":
            ann = audit.get("annotation") or {}
            tensions = ", ".join(audit.get("tensions", [])) or "—"
            st.caption(f"prompt `{audit.get('prompt_id')}` · {ann.get('direction') or '?'} "
                       f"· {ann.get('leverage') or '?'} · tensions: {tensions}")
        else:
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
            if lin.get("format") == "v2":
                def step1_output():
                    d = lin.get("dilemma")
                    if not d:
                        st.caption("dilemma record not found")
                        return
                    st.code(d.get("user_message", ""), language=None, wrap_lines=True)
                    st.json(d.get("annotation", {}), expanded=False)
                stage_expander("Step 1 — dilemma prompt (spec-driven)", "step1_dilemmas", lin, step1_output)

                stage_expander("Step 2a — tension tagging", "step2_tag", lin,
                               lambda: st.json(lin.get("tension_tag"))
                               if lin.get("tension_tag") else st.caption("not reached"))
                stage_expander("Step 2b — response from the compendium", "step2_respond", lin,
                               lambda: st.code((lin.get("response") or {}).get("assistant_response", ""),
                                               language=None, wrap_lines=True)
                               if lin.get("response") else st.caption("not reached"))

                def step3_output():
                    if not audit:
                        st.caption("not reached")
                        return
                    common.show_diff(audit["draft_response"], audit["rewritten_response"],
                                     "draft response", "rewritten response", key="s3")
                stage_expander("Step 3 — rewrite against the distilled principles", "step3_rewrite", lin, step3_output)

                pb = lin.get("pushback")
                if pb:
                    stage_expander("Step 4a — pushback turn", "step4_pushback", lin,
                                   lambda: st.code(pb.get("pushback_message", ""), language=None, wrap_lines=True))
                    stage_expander("Step 4b — response under pushback", "step4_response", lin,
                                   lambda: st.code(pb.get("pushback_response", ""), language=None, wrap_lines=True))
            else:
                # Legacy 7-step runs (pre-spec pipeline)
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

                # Historical runs only — ruthless sampling was later removed from the pipeline
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
