"""SDF judge view (rendered inside the combined Judge page via render()).
Pick an SDF document (or paste one), edit the rubric live, run the panel, diff what
changed. The unit of judgment is a standalone pretraining-style document.

Judging engine: evals/judge_sdf.py; rubric: evals/rubric_sdf_v1.yaml (editable here).
"""

import hashlib
import sys
from pathlib import Path

import streamlit as st
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evals import judge_sdf
from shared import api
from viewer import loader
from viewer.ui_pages import common

RUBRIC_PATH = judge_sdf.DEFAULT_RUBRIC_PATH
KNOWN_MODELS = [
    "gemini-3.1-pro-preview", "gemini-3.5-flash", "gemini-2.5-pro", "gemini-2.5-flash",
    "claude-haiku-4-5", "claude-sonnet-4-6", "claude-sonnet-5",
    "claude-opus-4-8", "claude-fable-5",
]


@st.cache_resource
def _api_ready() -> bool:
    api.init(str(loader.REPO_ROOT / "config.yaml"))
    return True


def _doc_cell(run: loader.RunInfo, doc: dict) -> dict | None:
    """The generation cell for a document, joined from layer1/layer2."""
    subtypes = {s["subtype_id"]: s for s in loader.load_stage(run.run_dir, "sdf", "layer2")}
    st_row = subtypes.get(doc.get("subtype_id"))
    if not st_row:
        return None
    return {f: st_row.get(f) for f in judge_sdf.CELL_FIELDS}


def _verdict_table(verdict: dict, aggregate: dict) -> None:
    scores = verdict.get("dimension_scores") or {}
    st.table({"score": {d: str(v) for d, v in scores.items()}})
    st.markdown(f"**Depicted AI:** `{verdict.get('depicted_ai_alignment')}` · "
                f"**Cell:** `{verdict.get('cell_adherence')}` · "
                f"**No scaffolding leak:** `{verdict.get('no_scaffolding_leak')}`")
    if aggregate["passing"]:
        st.success(f"PASS — mean {aggregate['mean']}")
    else:
        st.error(f"FAIL — mean {aggregate['mean']}; "
                 + ("; ".join(aggregate["gate_failures"]) or "below threshold"))
    if aggregate.get("cell_mismatch"):
        st.warning("Cell mismatch — flagged for coverage stats, not a gate failure.")
    for s in verdict.get("signals_triggered") or []:
        st.markdown(f":small_red_triangle: `{s.get('dimension')}` — {s.get('signal')}  \n> {s.get('quote')}")
    if verdict.get("analysis"):
        with st.expander("Judge analysis"):
            st.markdown(verdict["analysis"])
    if verdict.get("notes"):
        st.caption(f"Notes: {verdict['notes']}")
    meta = verdict.get("metadata") or {}
    if meta:
        with st.expander("Metadata emitted"):
            st.json(meta)


def _pick_document(run: loader.RunInfo, finals: list[dict]) -> dict | None:
    """Document dropdown with a role filter, seeded from the ?doc= query param."""
    subtypes = {s["subtype_id"]: s for s in loader.load_stage(run.run_dir, "sdf", "layer2")}
    roles = sorted({s.get("role", "?") for s in subtypes.values()})
    role_filter = st.sidebar.multiselect("Filter by role", roles, placeholder="All roles")
    options, labels = [], {}
    for doc in finals:
        cell = subtypes.get(doc.get("subtype_id"), {})
        if role_filter and cell.get("role") not in role_filter:
            continue
        options.append(doc["doc_id"])
        labels[doc["doc_id"]] = (f"{common.doc_title(doc.get('content', ''))}   —   "
                                 f"{cell.get('subtype_name', '?')}")
    if not options:
        st.sidebar.caption("No documents match the current filters.")
        return None

    key = f"judge_sdf_doc_{run.run_id}"
    if st.session_state.get(key) not in options:
        st.session_state.pop(key, None)  # stale value (e.g. filters changed) — reseed below
    qp_doc = st.query_params.get("doc")
    doc_id = st.sidebar.selectbox(
        f"Document ({len(options)})", options,
        index=options.index(qp_doc) if qp_doc in options else 0,
        format_func=labels.get, key=key,
    )
    st.query_params["doc"] = doc_id
    return next(d for d in finals if d["doc_id"] == doc_id)


def render() -> None:
    st.caption("Pick an SDF document (or paste one), edit the rubric, run the panel, "
               "diff the verdicts.")

    # -------------------------------------------------------------- inputs
    source = st.sidebar.radio("Document source", ["From a run", "Paste a document"])
    document, cell, record_key, legacy_scores = None, None, None, None

    if source == "From a run":
        runs = [r for r in loader.list_runs() if r.pipeline == "sdf"]
        if not runs:
            st.info("No SDF runs found under outputs/.")
        else:
            run_ids = [r.run_id for r in runs]
            qp_run = st.query_params.get("run")
            run_id = st.sidebar.selectbox(
                "Run", run_ids,
                index=run_ids.index(qp_run) if qp_run in run_ids else 0,
                key="judge_sdf_run",
            )
            st.query_params["pipeline"] = "sdf"
            st.query_params["run"] = run_id
            run = next(r for r in runs if r.run_id == run_id)
            finals = loader.load_final(run.run_dir, "sdf")
            if not finals:
                st.info("This run has no final documents.")
            else:
                doc = _pick_document(run, finals)
                if doc is not None:
                    document = doc.get("content", "")
                    cell = _doc_cell(run, doc)
                    record_key = f"{run_id}/{doc['doc_id'][:8]}"
                    legacy_scores = doc.get("scores")
                    if st.sidebar.button(":material/account_tree: View lineage"):
                        st.switch_page("ui_pages/lineage.py")
    else:
        pasted = st.sidebar.text_area("Document text", height=260,
                                      placeholder="Paste the full document…")
        document = pasted.strip() or None
        record_key = "pasted/" + hashlib.md5((pasted or "").encode()).hexdigest()[:8]

    panel = st.sidebar.multiselect("Judge panel", KNOWN_MODELS,
                                   default=["gemini-3.1-pro-preview"],
                                   accept_new_options=True)
    run_clicked = st.sidebar.button(":material/gavel: Run the judge", type="primary",
                                    disabled=not (document and panel))

    # -------------------------------------------------------------- rubric editor
    if "rubric_sdf_text" not in st.session_state:
        st.session_state.rubric_sdf_text = RUBRIC_PATH.read_text()

    with st.expander("Rubric (edit me, then re-run to see what changes)", expanded=False):
        st.session_state.rubric_sdf_text = st.text_area(
            "rubric yaml", st.session_state.rubric_sdf_text, height=420,
            label_visibility="collapsed")
        col_a, col_b, _ = st.columns([1, 1, 3])
        if col_a.button("Reload from file", key="sdf_rubric_reload"):
            st.session_state.rubric_sdf_text = RUBRIC_PATH.read_text()
            st.rerun()
        if col_b.button("Save to file", key="sdf_rubric_save"):
            try:
                yaml.safe_load(st.session_state.rubric_sdf_text)
                RUBRIC_PATH.write_text(st.session_state.rubric_sdf_text)
                st.success(f"Saved to {RUBRIC_PATH.relative_to(loader.REPO_ROOT)}")
            except yaml.YAMLError as e:
                st.error(f"Not saved — YAML error: {e}")

    try:
        rubric = yaml.safe_load(st.session_state.rubric_sdf_text)
        rubric_hash = hashlib.md5(st.session_state.rubric_sdf_text.encode()).hexdigest()[:8]
        st.caption(f"Rubric `{rubric.get('version', '?')}` · {len(rubric.get('dimensions', {}))} dimensions "
                   f"· edit-hash `{rubric_hash}`" +
                   ("" if st.session_state.rubric_sdf_text == RUBRIC_PATH.read_text() else " · **edited, unsaved**"))
    except yaml.YAMLError as e:
        st.error(f"Rubric YAML does not parse: {e}")
        rubric = None

    if document:
        if cell:
            st.caption("**Cell:** " + " · ".join(
                f"{f}=`{cell[f]}`" for f in ("type_name", "subtype_name", "role", "tone", "language")
                if cell.get(f)))
        if legacy_scores:
            st.caption(f"Legacy layer-5 scores: alignment `{legacy_scores.get('alignment')}` · "
                       f"realism `{legacy_scores.get('realism')}` · "
                       f"diversity `{legacy_scores.get('diversity')}`")
        with st.expander("Document", expanded=not run_clicked):
            st.code(document, language=None, wrap_lines=True)

    # -------------------------------------------------------------- run + display
    history = st.session_state.setdefault("judge_sdf_history", [])

    if run_clicked and rubric and document:
        _api_ready()
        principles = judge_sdf.load_principles()
        results = []
        with st.status(f"Judging with {len(panel)} model(s)...", expanded=True) as status:
            system = judge_sdf.build_system_prompt(rubric, principles)
            for model in panel:
                st.write(f"calling {model}...")
                res = judge_sdf.judge_document(document, cell, model, rubric, principles,
                                               system_prompt=system)
                if res.get("verdict"):
                    res["aggregate"] = judge_sdf.aggregate(res["verdict"], rubric)
                results.append(res)
            status.update(label="Done", state="complete", expanded=False)
        cons = judge_sdf.consensus(results, rubric)
        history.append({
            "record_key": record_key, "rubric_version": rubric.get("version"),
            "rubric_hash": rubric_hash, "results": results, "consensus": cons,
        })

    if history:
        entry = history[-1]
        st.subheader(f"Verdicts — {entry['record_key']} · rubric `{entry['rubric_hash']}`")
        cols = st.columns(max(len(entry["results"]), 1))
        for col, res in zip(cols, entry["results"]):
            with col:
                st.markdown(f"### {res['model']}")
                if res.get("verdict"):
                    _verdict_table(res["verdict"], res["aggregate"])
                else:
                    st.error(res.get("error") or "no verdict")
        if len(entry["results"]) > 1 and not entry["consensus"].get("judge_error"):
            c = entry["consensus"]
            st.markdown(f"**Panel consensus:** pass=`{c['consensus_aggregate']['passing']}` · "
                        f"unstable=`{c['judge_unstable']}` · per-model: `{c['per_model_passing']}`")

        # ---------------------------------------------------------- diff vs previous run
        same_record = [h for h in history if h["record_key"] == entry["record_key"]]
        if len(same_record) > 1:
            prev = same_record[-2]
            st.subheader(f"What changed vs previous run (rubric `{prev['rubric_hash']}` → `{entry['rubric_hash']}`)")
            rows = {}
            for res in entry["results"]:
                prev_res = next((r for r in prev["results"] if r["model"] == res["model"]), None)
                if not (res.get("verdict") and prev_res and prev_res.get("verdict")):
                    continue
                before = prev_res["verdict"].get("dimension_scores") or {}
                after = res["verdict"].get("dimension_scores") or {}
                for dim in after:
                    b, a = before.get(dim), after.get(dim)
                    if b != a:
                        rows.setdefault(dim, {})[res["model"]] = f"{b} → {a}"
                for field in ("depicted_ai_alignment", "cell_adherence", "no_scaffolding_leak"):
                    b, a = prev_res["verdict"].get(field), res["verdict"].get(field)
                    if b != a:
                        rows.setdefault(field, {})[res["model"]] = f"{b} → {a}"
            if rows:
                st.table(rows)
            else:
                st.caption("No verdict changes between the two runs.")

        if st.button("Clear history", key="sdf_clear_history"):
            st.session_state.judge_sdf_history = []
            st.rerun()
