"""Judge playground: run the DAD judge panel on any record (from a run, or pasted),
edit the rubric live, re-run, and diff what changed. The rubric-iteration loop.

Judging engine: evals/judge.py; rubric: evals/rubric_dad_v1.yaml (editable here).
"""

import hashlib
import json
import sys
from pathlib import Path

import streamlit as st
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evals import judge
from shared import api
from viewer import loader
from viewer.ui_pages import common

RUBRIC_PATH = judge.DEFAULT_RUBRIC_PATH
KNOWN_MODELS = [
    "claude-haiku-4-5", "claude-sonnet-4-6", "claude-sonnet-5",
    "claude-opus-4-8", "claude-fable-5",
]

st.title("DAD judge")
st.caption("Pick a DAD record (or paste one), edit the rubric, run the panel, diff the verdicts.")


# ---------------------------------------------------------------- inputs

def _parse_pasted(text: str) -> list[dict] | None:
    """Accept a JSONL record, a messages list, or plain USER:/ASSISTANT: text."""
    text = text.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "messages" in obj:
            return obj["messages"]
        if isinstance(obj, list):
            return obj
    except json.JSONDecodeError:
        pass
    messages, role, buf = [], None, []
    for line in text.splitlines():
        upper = line.strip().upper()
        new_role = "user" if upper.startswith("USER:") else "assistant" if upper.startswith("ASSISTANT:") else None
        if new_role:
            if role and buf:
                messages.append({"role": role, "content": "\n".join(buf).strip()})
            role, buf = new_role, [line.split(":", 1)[1]]
        elif role:
            buf.append(line)
    if role and buf:
        messages.append({"role": role, "content": "\n".join(buf).strip()})
    return messages or None


source = st.sidebar.radio("Record source", ["From a run", "Paste a conversation"])
messages, record_key = None, None

if source == "From a run":
    runs = [r for r in loader.list_runs() if r.pipeline == "dad"]
    if not runs:
        st.info("No DAD runs found under outputs/.")
    else:
        run_ids = [r.run_id for r in runs]
        run_id = st.sidebar.selectbox("Run", run_ids)
        run = next(r for r in runs if r.run_id == run_id)
        finals = loader.load_final(run.run_dir, "dad")
        if not finals:
            st.info("This run has no final records.")
        else:
            labels = {
                r["record_id"]: f"{r['record_id'][:8]} — {r['messages'][0]['content'][:80]}"
                for r in finals
            }
            rid = st.sidebar.selectbox("Record", list(labels), format_func=labels.get)
            rec = next(r for r in finals if r["record_id"] == rid)
            messages, record_key = rec["messages"], f"{run_id}/{rid[:8]}"
else:
    pasted = st.sidebar.text_area(
        "Conversation", height=260,
        placeholder='{"messages": [...]}  |  [{"role": "user", ...}]  |  USER: ... / ASSISTANT: ...',
    )
    messages = _parse_pasted(pasted)
    if pasted and not messages:
        st.sidebar.error("Could not parse — paste a record JSON, a messages list, or USER:/ASSISTANT: text.")
    record_key = "pasted/" + hashlib.md5((pasted or "").encode()).hexdigest()[:8]

panel = st.sidebar.multiselect("Judge panel", KNOWN_MODELS, default=["claude-haiku-4-5"],
                               accept_new_options=True)
run_clicked = st.sidebar.button(":material/gavel: Run the judge", type="primary",
                                disabled=not (messages and panel))


# ---------------------------------------------------------------- rubric editor

if "rubric_text" not in st.session_state:
    st.session_state.rubric_text = RUBRIC_PATH.read_text()

with st.expander("Rubric (edit me, then re-run to see what changes)", expanded=False):
    st.session_state.rubric_text = st.text_area(
        "rubric yaml", st.session_state.rubric_text, height=420, label_visibility="collapsed")
    col_a, col_b, _ = st.columns([1, 1, 3])
    if col_a.button("Reload from file"):
        st.session_state.rubric_text = RUBRIC_PATH.read_text()
        st.rerun()
    if col_b.button("Save to file"):
        try:
            yaml.safe_load(st.session_state.rubric_text)
            RUBRIC_PATH.write_text(st.session_state.rubric_text)
            st.success(f"Saved to {RUBRIC_PATH.relative_to(loader.REPO_ROOT)}")
        except yaml.YAMLError as e:
            st.error(f"Not saved — YAML error: {e}")

try:
    rubric = yaml.safe_load(st.session_state.rubric_text)
    rubric_hash = hashlib.md5(st.session_state.rubric_text.encode()).hexdigest()[:8]
    st.caption(f"Rubric `{rubric.get('version', '?')}` · {len(rubric.get('dimensions', {}))} dimensions "
               f"· edit-hash `{rubric_hash}`" +
               ("" if st.session_state.rubric_text == RUBRIC_PATH.read_text() else " · **edited, unsaved**"))
except yaml.YAMLError as e:
    st.error(f"Rubric YAML does not parse: {e}")
    rubric = None

if messages:
    with st.expander("Conversation", expanded=not run_clicked):
        for m in messages:
            st.markdown(f"**{m['role'].upper()}**")
            st.code(m["content"], language=None, wrap_lines=True)


# ---------------------------------------------------------------- run + display

@st.cache_resource
def _api_ready() -> bool:
    api.init(str(loader.REPO_ROOT / "config.yaml"))
    return True


def _verdict_table(verdict: dict, aggregate: dict) -> None:
    scores = verdict.get("dimension_scores") or {}
    st.table({"score": {d: str(v) for d, v in scores.items()}})
    st.markdown(f"**Behavior:** `{verdict.get('autonomy_behavior')}` · "
                f"**Posture:** `{verdict.get('posture_class')}` · "
                f"**Self-contained:** `{verdict.get('self_contained')}`")
    if aggregate["passing"]:
        st.success(f"PASS — mean {aggregate['mean']}")
    else:
        st.error(f"FAIL — mean {aggregate['mean']}; " + "; ".join(aggregate["gate_failures"]) or "below threshold")
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


history = st.session_state.setdefault("judge_history", [])

if run_clicked and rubric and messages:
    _api_ready()
    principles = judge.load_principles()
    results = []
    with st.status(f"Judging with {len(panel)} model(s)...", expanded=True) as status:
        system = judge.build_system_prompt(rubric, principles)
        for model in panel:
            st.write(f"calling {model}...")
            res = judge.judge_record(messages, model, rubric, principles, system_prompt=system)
            if res.get("verdict"):
                res["aggregate"] = judge.aggregate(res["verdict"], rubric)
            results.append(res)
        status.update(label="Done", state="complete", expanded=False)
    cons = judge.consensus(results, rubric)
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

    # ------------------------------------------------------------ diff vs previous run
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
            for field in ("posture_class", "autonomy_behavior", "self_contained"):
                b, a = prev_res["verdict"].get(field), res["verdict"].get(field)
                if b != a:
                    rows.setdefault(field, {})[res["model"]] = f"{b} → {a}"
        if rows:
            st.table(rows)
        else:
            st.caption("No verdict changes between the two runs.")

    if st.button("Clear history"):
        st.session_state.judge_history = []
        st.rerun()
