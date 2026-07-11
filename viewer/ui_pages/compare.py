"""Compare two runs: run facts + prompt-template diffs + matched outputs.

DAD matches examples by a *content* key (default: the user message) rather than
the AW-#### id, so a side-by-side pair is guaranteed to be the same case. A
comparison holds one dimension fixed (the key) and diffs the rest: fix the
prompt to tune responses, or fix the scenario to tune the prompts themselves.
"""

import difflib
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from viewer import loader, rendering
from viewer.ui_pages import common

st.title("Compare runs")

runs = loader.list_runs()
if len(runs) < 2:
    st.info("Need at least two runs to compare.")
    st.stop()

pipelines = [p for p in loader.PIPELINES if any(r.pipeline == p for r in runs)]
pipeline = st.sidebar.selectbox("Pipeline", pipelines)
pipeline_runs = [r for r in runs if r.pipeline == pipeline]
if len(pipeline_runs) < 2:
    st.info(f"Only one {pipeline} run exists — nothing to compare against.")
    st.stop()

ids = [r.run_id for r in pipeline_runs]
run_a_id = st.sidebar.selectbox("Run A (baseline)", ids, index=min(1, len(ids) - 1))
run_b_id = st.sidebar.selectbox("Run B", ids, index=0)
run_a = next(r for r in pipeline_runs if r.run_id == run_a_id)
run_b = next(r for r in pipeline_runs if r.run_id == run_b_id)
if run_a_id == run_b_id:
    st.warning("Pick two different runs.")
    st.stop()


def _run_facts(run: loader.RunInfo, side: str) -> None:
    """The run-list facts for one run, so you know what you're comparing."""
    st.markdown(f"**{side}: {run.label or run.run_id}**")
    st.caption(
        f"`{run.run_id}` · {(run.created_at or '').replace('T', ' ')[:16]}\n\n"
        f"model **{run.model or '?'}** · **{run.counts.get('final', 0)}** records · "
        f"${run.total_cost:.2f} · git `{run.git_commit}`"
        + (" · ⚠ dirty tree at run time" if run.git_dirty else "")
    )


fa, fb = st.columns(2)
with fa:
    _run_facts(run_a, "A")
with fb:
    _run_facts(run_b, "B")

if not (run_a.has_snapshot and run_b.has_snapshot):
    st.caption(":material/history: One or both runs predate prompt snapshots — "
               "their templates are reconstructed from git and may not match what actually ran.")

# --- Prompt-template differences (whole-file, incl. the system/user split marker) ---
st.header("Prompt differences")
templates_a = {t.name: t for t in rendering.list_templates(run_a.run_dir, run_a.git_commit, pipeline)}
templates_b = {t.name: t for t in rendering.list_templates(run_b.run_dir, run_b.git_commit, pipeline)}
changed = []
for name in sorted(set(templates_a) | set(templates_b)):
    ta, tb = templates_a.get(name), templates_b.get(name)
    text_a = ta.text if ta else None
    text_b = tb.text if tb else None
    if text_a != text_b:
        changed.append((name, text_a, text_b))

if not changed:
    st.success("No prompt or constitution differences — output differences come from sampling alone.")
for i, (name, text_a, text_b) in enumerate(changed):
    label = name + (" (only in B)" if text_a is None else " (only in A)" if text_b is None else "")
    with st.expander(label, expanded=(i == 0)):
        diff = "\n".join(difflib.unified_diff(
            (text_a or "").splitlines(), (text_b or "").splitlines(),
            fromfile=f"A/{name}", tofile=f"B/{name}", lineterm="",
        ))
        st.code(diff, language="diff", wrap_lines=True)

st.header("Matched outputs")

# --- SDF: unchanged positional/name matching ---
if pipeline != "dad":
    pairs = loader.match_outputs(run_a.run_dir, run_b.run_dir, pipeline)
    if not pairs:
        st.info("No matching outputs between the two runs.")
        st.stop()
    note = {"positional": " · positional match", "group": " · grouped by principle"}
    for pair in pairs:
        with st.expander(f"{pair.key}{note.get(pair.quality, '')}"):
            for i in range(min(len(pair.a), len(pair.b))):
                ca, cb = st.columns(2)
                with ca:
                    st.markdown(f"**A: {run_a_id}**")
                    st.code(pair.a[i].get("content", ""), language=None, wrap_lines=True)
                with cb:
                    st.markdown(f"**B: {run_b_id}**")
                    st.code(pair.b[i].get("content", ""), language=None, wrap_lines=True)
            if len(pair.a) != len(pair.b):
                st.caption(f"Unpaired extras: A has {len(pair.a)}, B has {len(pair.b)}.")
    st.stop()

# --- DAD: content-aware matching ---
KEY_LABELS = {
    "user_message": "user message  (same prompt → compare responses)",
    "scenario_id": "scenario id  (same scenario → compare prompts too)",
    "prompt_id": "AW-#### id  (positional — may pair unrelated prompts)",
}
have_scen = loader.run_has_scenario_ids(run_a.run_dir) and loader.run_has_scenario_ids(run_b.run_dir)
key_options = [k for k in loader.DAD_MATCH_KEYS if k != "scenario_id" or have_scen]
key_by = st.sidebar.radio(
    "Match examples by", key_options,
    format_func=lambda k: KEY_LABELS[k],
    help="How to decide two examples are 'the same' for side-by-side comparison.",
)
if not have_scen:
    st.sidebar.caption(":material/info: *scenario id* is unavailable — one or both runs' "
                       "dilemmas didn't record a scenario_id (older/reused prompt sets).")

matched, only_a, only_b = loader.match_dad(run_a.run_dir, run_b.run_dir, key_by)
if not matched:
    st.info("No examples matched on this key. Try a different match key, or the two runs "
            "share no common examples.")
if only_a or only_b:
    st.caption(f":material/join_inner: Matched **{len(matched)}** · only in A **{len(only_a)}** · "
               f"only in B **{len(only_b)}** (unmatched examples aren't shown).")

if matched:
    matched.sort(key=lambda m: m.label.lower())
    idx = st.selectbox(
        "Example", range(len(matched)),
        format_func=lambda i: ("⚠ " if not matched[i].same_prompt else "") + matched[i].label,
    )
    m = matched[idx]
    a, b = m.a, m.b
    st.caption(f"A `{a.prompt_id}`  ·  B `{b.prompt_id}`  ·  "
               + ("✓ same user prompt" if m.same_prompt
                  else "⚠ **different user prompt** — matched on "
                       f"{key_by.replace('_', ' ')}, but the prompts differ"))

    # Prompt: always available for reference; low-emphasis when identical.
    st.markdown("#### User prompt")
    if m.same_prompt:
        if st.toggle("Show user prompt (identical in A and B)", key=f"um_{idx}"):
            st.code(a.user_message, language=None, wrap_lines=True)
    else:
        common.show_diff(a.user_message, b.user_message,
                         f"A: {run_a_id}", f"B: {run_b_id}", key=f"um_{idx}")

    # Response: the payload in response-tuning mode.
    st.markdown("#### Response")
    if not (a.has_final and b.has_final):
        st.caption(":material/warning: One or both responses fell back to the pre-final draft "
                   "(step-3 rewrite produced no final record).")
    common.show_diff(a.response, b.response, f"A: {run_a_id}", f"B: {run_b_id}", key=f"resp_{idx}")

    # Inputs by stage: reconstruct the system + user prompt each run actually
    # sent at every step-2/3 stage, and diff them (split-aware render_prompt).
    st.markdown("#### Inputs by stage")
    manifest_a, manifest_b = loader.load_manifest(run_a.run_dir), loader.load_manifest(run_b.run_dir)
    lin_a = loader.dad_lineage_by_prompt(run_a.run_dir, a.prompt_id)
    lin_b = loader.dad_lineage_by_prompt(run_b.run_dir, b.prompt_id)
    stages = [("step2_scope", "Step 2a — scope"),
              ("step2_select", "Step 2a.5 — library selection"),
              ("step2_respond", "Step 2b — response draft"),
              ("step3_rewrite", "Step 3 — constitution rewrite")]
    for stage, title in stages:
        ra = rendering.render_prompt("dad", stage, run_a.run_dir, manifest_a, lin_a)
        rb = rendering.render_prompt("dad", stage, run_b.run_dir, manifest_b, lin_b)
        if not (ra.is_llm_call or rb.is_llm_call):
            continue
        with st.expander(title):
            st.markdown("**System prompt**")
            common.show_diff(ra.system or "", rb.system or "",
                             f"A: {run_a_id}", f"B: {run_b_id}", key=f"{stage}_sys_{idx}")
            st.markdown("**User prompt**")
            common.show_diff(ra.user or "", rb.user or "",
                             f"A: {run_a_id}", f"B: {run_b_id}", key=f"{stage}_usr_{idx}")

if only_a or only_b:
    with st.expander(f"Unmatched — only in A ({len(only_a)}) / only in B ({len(only_b)})"):
        ca, cb = st.columns(2)
        with ca:
            st.markdown(f"**Only in A: {run_a_id}**")
            for ex in sorted(only_a, key=lambda e: e.goal.lower()):
                st.caption(f"`{ex.prompt_id}` — {ex.goal}")
        with cb:
            st.markdown(f"**Only in B: {run_b_id}**")
            for ex in sorted(only_b, key=lambda e: e.goal.lower()):
                st.caption(f"`{ex.prompt_id}` — {ex.goal}")
