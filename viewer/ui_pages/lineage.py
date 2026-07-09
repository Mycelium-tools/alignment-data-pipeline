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


def _goal_label(annotation: dict | None, fallback_text: str) -> str:
    """Label a DAD record by its annotated goal — the one-line 'what is being
    decided' from the 1b anatomy — falling back to the user message's opening
    when absent (seed prompts, runs predating the anatomy fields)."""
    goal = str(((annotation or {}).get("dilemma_anatomy") or {}).get("goal") or "").strip()
    return goal[:90] if goal else _doc_title(fallback_text)


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
dad_by_prompt = False  # incomplete DAD run: enumerate step-1 prompts, not final records
if run.pipeline == "dad" and not finals:
    dilemmas = loader.load_stage(run.run_dir, "dad", "step1_dilemmas")
    if dilemmas:
        dad_by_prompt = True
        st.info("No responses generated yet — showing the step-1 dilemma prompts.")
        options, labels = [], {}
        for d in dilemmas:
            pid = d.get("prompt_id")
            options.append(pid)
            labels[pid] = _goal_label(d.get("annotation"), d.get("user_message"))
        selected_id = _pick_document(options, labels, "prompt")
    else:
        st.info("No dilemmas generated in this run yet.")
elif not finals:
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
        # Current-format runs: label each record by its annotated goal — the
        # axes and the full prompt live in the step expanders, not the dropdown.
        keep = lambda audit: True
        suffix = None
        sort_key = lambda rec: str(audits.get(rec.get("record_id"), {}).get("prompt_id", ""))

    options, labels = [], {}
    for rec in sorted(finals, key=sort_key):
        audit = audits.get(rec.get("record_id"), {})
        if not keep(audit):
            continue
        user_msg = rec["messages"][0]["content"] if rec.get("messages") else ""
        options.append(rec["record_id"])
        if suffix:
            labels[rec["record_id"]] = f"{_doc_title(user_msg)}   —   {suffix(audit)}"
        else:
            labels[rec["record_id"]] = _goal_label(audit.get("annotation"), user_msg)

    selected_id = _pick_document(options, labels, "record")


def _call_stats_line(cost_stage: str, item_id: str | None) -> str | None:
    """One-line summary of the API call(s) behind a stage: model · cost ·
    wall-clock · retries. Falls back to model-only for runs logged before
    per-record stats existed."""
    s = loader.call_stats(run.run_dir, cost_stage, item_id)
    if s is None:
        return None
    models = ", ".join(s["models"])
    if not s["per_item"]:
        return f"{models} · per-record cost/time/retries not recorded in this run"
    bits = [models, f"${s['cost_usd']:.4f}"]
    if s.get("duration_s") is not None:
        bits.append(f"{s['duration_s']:.1f}s")
    if s.get("retries") is not None:
        bits.append("no retries" if s["retries"] == 0
                    else f"{s['retries']} retr{'y' if s['retries'] == 1 else 'ies'}")
    if s["calls"] > 1:
        bits.append(f"{s['calls']} calls")
    if s.get("batch_size", 1) > 1:
        bits.append(f"one call drafted a batch of {s['batch_size']} (cost/time are the whole batch's)")
    return " · ".join(bits)


def stage_expander(title: str, stage: str, lineage: dict, output_fn,
                   stats: tuple[str, str | None] | None = None):
    """One stage: call stats, the rendered prompt, then the output it produced.
    `stats` is (cost-log stage tag, item id) for the API call(s) behind the stage."""
    with st.expander(f":blue[{title}]"):
        if stats:
            line = _call_stats_line(*stats)
            if line:
                st.caption(f":material/speed: {line}")
        rendered = rendering.render_prompt(run.pipeline, stage, run.run_dir, manifest, lineage)
        common.show_rendered_prompt(rendered, key=stage, show_run_warnings=False)
        st.markdown("##### Output at this stage")
        output_fn()


# --- Side-by-side: document (left) vs prompts (right) ---
if selected_id is None:
    if finals or dad_by_prompt:
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
                           lambda: common.json_block(lin["doc_type"], key="l1", label="document type", expanded=True)
                           if lin["doc_type"] else st.caption("not found"))
            stage_expander("Layer 2 — subtype", "layer2", lin,
                           lambda: common.json_block(lin["subtype"], key="l2", label="subtype", expanded=True)
                           if lin["subtype"] else st.caption("not found"))
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
                           lambda: common.json_block((lin["score"] or {}).get("scores", {}),
                                                     key="l5", label="scores", expanded=True)
                           if lin["score"] else st.caption("not reached"))
else:
    lin = (loader.dad_lineage_by_prompt(run.run_dir, selected_id) if dad_by_prompt
           else loader.dad_lineage(run.run_dir, selected_id))
    audit = lin.get("rewrite") or {}
    dilemma = lin.get("dilemma") or {}
    st.divider()
    doc_col, prompts_col = st.columns(2)

    with doc_col:
        st.subheader(f"{'Prompt' if dad_by_prompt else 'Record'} {selected_id[:8]}")
        if lin.get("format") == "v2":
            st.caption("Step-1 dilemma prompt — no response generated yet" if dad_by_prompt
                       else "Final user prompt and assistant response, as written to the training corpus")
        else:
            st.caption(f"scenario `{audit.get('scenario_id')}` · injection `{audit.get('injection_used')}` "
                       f"· principle {audit.get('principle_id')}")
        with st.container(height=PANEL_HEIGHT):
            messages = (lin.get("final") or {}).get("messages", [])
            if messages:
                for msg in messages:
                    st.markdown(f"**{msg['role']}**")
                    st.code(msg["content"], language=None, wrap_lines=True)
            else:
                # Incomplete run: no final response yet — show the dilemma prompt itself.
                st.markdown("**user** *(dilemma prompt — no response generated yet)*")
                st.code(dilemma.get("user_message", ""), language=None, wrap_lines=True)
                common.json_block(dilemma.get("annotation", {}), key="doc_ann", label="annotation")

    with prompts_col:
        st.subheader("Prompts")
        st.caption("Each step's prompt and what it produced")
        with st.container(height=PANEL_HEIGHT):
            if lin.get("format") == "v2":
                # Ids linking each stage's expander to the cost-log rows of the
                # API call(s) that produced it (item_id, logged since 2026-07).
                scenario_id = dilemma.get("scenario_id")
                pid = dilemma.get("prompt_id") or audit.get("prompt_id")
                resp = lin.get("response") or {}
                resp_item = (f"{resp['prompt_id']}_s{resp.get('sample_index', 0)}"
                             if resp.get("prompt_id") else None)

                # Step 1a — scenario generation: pure sampling, no model call.
                with st.expander(":blue[Step 1a — scenario generation (sampled, no model call)]"):
                    sc = lin.get("scenario")
                    if sc:
                        st.caption("Stratified categorical assignment for this example, drawn by the "
                                   "sampler — no LLM call.")
                        common.json_block(sc, key="s1a", label="scenario")
                    else:
                        st.caption("scenario record not found (older run, or pre-scenario snapshot)")

                def step1b_output():
                    d = lin.get("dilemma") or {}
                    if not d:
                        st.caption("dilemma record not found")
                        return
                    # the 1b draft is draft_user_message when 1c ran, else the stored user_message
                    st.code(d.get("draft_user_message") or d.get("user_message", ""),
                            language=None, wrap_lines=True)
                    common.json_block(d.get("annotation", {}), key="s1b_ann", label="annotation")
                stage_expander("Step 1b — first attempt (draft)", "step1_dilemmas", lin, step1b_output,
                               stats=("prompt_draft", scenario_id))

                def step1c_output():
                    d = lin.get("dilemma") or {}
                    if d.get("draft_user_message") is None:
                        st.caption("not run (dad.dilemmas.refine was off for this run)")
                        return
                    if d.get("refine_notes"):
                        st.info(f"Notes: {d['refine_notes']}")
                    common.show_diff(d["draft_user_message"], d.get("user_message", ""),
                                     "1b draft", "1c refined", key="s1c")
                stage_expander("Step 1c — review & rewrite (optional)", "step1_refine", lin, step1c_output,
                               stats=("prompt_refine", scenario_id))

                def step2_scope_output():
                    rec = lin.get("scope") or {}
                    sc = rec.get("scope")
                    if sc:
                        common.json_block(sc, key="s2a", label="scope", expanded=True)
                    else:
                        st.caption("not reached")
                    # Library retrieval provenance: the full rows whose trigger
                    # conditions fired for this prompt (runs since retrieval).
                    trig = rec.get("triggered_entries")
                    if trig:
                        n = len(trig)
                        if rec.get("selection_fallback"):
                            st.caption(":material/warning: selection fallback — no usable "
                                       "triggered_entries from the scope output or the repair "
                                       "call, so the whole library was injected")
                        elif rec.get("selection_source") == "repair":
                            st.caption(":material/build: triggered_entries was missing from "
                                       "the scope output — recovered by a selection-only "
                                       "repair call (stage response_select in the cost log)")
                        common.json_block(trig, key="s2a_trig",
                                          label=f"triggered library entries ({n})")
                stage_expander("Step 2a — scope the case + trigger library entries",
                               "step2_scope", lin, step2_scope_output,
                               stats=("response_scope", pid))

                # Tension retrieval was removed from the pipeline; still shown for
                # older runs that recorded it, so their lineage stays complete.
                if lin.get("tension_tag"):
                    stage_expander("Tensions (retrieval — earlier pipeline)", "step2_tag", lin,
                                   lambda: common.json_block(lin.get("tension_tag"), key="s2tag",
                                                             label="tensions", expanded=True))

                stage_expander("Step 2b — response from the reasoning library", "step2_respond", lin,
                               lambda: st.code((lin.get("response") or {}).get("assistant_response", ""),
                                               language=None, wrap_lines=True)
                               if lin.get("response") else st.caption("not reached"),
                               stats=("response_draft", resp_item) if resp_item else None)

                def step3_output():
                    if not audit:
                        st.caption("not reached")
                        return
                    common.show_diff(audit["draft_response"], audit["rewritten_response"],
                                     "draft response", "rewritten response", key="s3")
                stage_expander("Step 3 — rewrite against the distilled principles", "step3_rewrite", lin,
                               step3_output,
                               stats=("constitution_rewrite", audit.get("response_id")) if audit else None)
            else:
                # Legacy 7-step runs (pre-spec pipeline)
                stage_expander("Step 1 — principle annotation", "step1", lin,
                               lambda: common.json_block(
                                   {k: v for k, v in (lin.get("principle") or {}).items() if k != "content"},
                                   key="leg_s1", label="principle", expanded=True)
                               if lin.get("principle") else st.caption("principle record not found"))
                stage_expander("Step 2 — scenario", "step2", lin,
                               lambda: common.json_block(lin.get("scenario"), key="leg_s2",
                                                         label="scenario", expanded=True)
                               if lin.get("scenario") else st.caption("not found"))
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
