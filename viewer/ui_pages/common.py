"""Shared helpers for the viewer pages."""

import difflib
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from viewer import loader

FOLD_THRESHOLD = 2000  # chars; variable values longer than this get folded out of prompts


def pick_run(sidebar: bool = True) -> loader.RunInfo | None:
    """Run selector seeded from query params; keeps params in sync.
    Renders in the sidebar by default so the content area stays clean."""
    container = st.sidebar if sidebar else st
    runs = loader.list_runs()
    if not runs:
        st.info("No runs found under outputs/. Run a pipeline first.")
        return None

    # loader.PIPELINES order puts SDF first (the default)
    pipelines = [p for p in loader.PIPELINES if any(r.pipeline == p for r in runs)]
    qp_pipeline = st.query_params.get("pipeline")
    pipeline = container.selectbox(
        "Pipeline", pipelines,
        index=pipelines.index(qp_pipeline) if qp_pipeline in pipelines else 0,
        key="sel_pipeline",
    )

    pipeline_runs = [r for r in runs if r.pipeline == pipeline]
    run_ids = [r.run_id for r in pipeline_runs]
    qp_run = st.query_params.get("run")
    run_id = container.selectbox(
        "Run", run_ids,
        index=run_ids.index(qp_run) if qp_run in run_ids else 0,
        key="sel_run",
    )

    st.query_params["pipeline"] = pipeline
    st.query_params["run"] = run_id
    return next(r for r in pipeline_runs if r.run_id == run_id)


def run_provenance_note(run: loader.RunInfo) -> None:
    """One-line provenance caveat, shown at most once per page."""
    if not run.has_snapshot:
        st.caption(f":material/history: Prompts for this run are reconstructed from git "
                   f"commit `{run.git_commit}`" +
                   (" — repo had uncommitted changes at run time, so they may differ from what actually ran."
                    if run.git_dirty else "."))


def fold_long_values(text: str, variables: dict) -> tuple[str, dict[str, str]]:
    """Replace very long substituted values (constitution, preamble) with a
    short marker so the prompt stays readable; return (folded_text, folded)."""
    folded = {}
    for name, value in variables.items():
        if isinstance(value, str) and len(value) > FOLD_THRESHOLD and value in text:
            marker = f"⟨{name}: {len(value):,} chars — expand below⟩"
            text = text.replace(value, marker)
            folded[name] = value
    return text, folded


def show_rendered_prompt(rendered, key: str = "", show_run_warnings: bool = True) -> None:
    """Render a RenderedPrompt: system + user with long values folded.
    `key` must be unique per prompt on the page (e.g. the stage name).
    Run-level provenance warnings are suppressed when show_run_warnings=False
    (pages show them once at the top instead)."""
    run_level = ("Pre-snapshot run", "Repo was dirty")
    for w in rendered.warnings:
        if any(w.startswith(prefix) for prefix in run_level):
            if show_run_warnings:
                st.warning(w)
        else:
            st.warning(w)
    if not rendered.is_llm_call:
        st.caption("No LLM call at this stage for this record.")
        return

    folded_all = {}
    if rendered.system:
        sys_text, folded = fold_long_values(rendered.system, {rendered.system_label: rendered.system})
        folded_all.update(folded)
        st.markdown("**System prompt**")
        st.code(sys_text, language=None, wrap_lines=True)
    if rendered.user:
        user_text, folded = fold_long_values(rendered.user, rendered.variables)
        folded_all.update(folded)
        st.markdown("**User message**")
        st.code(user_text, language=None, wrap_lines=True)
    for name, value in folded_all.items():
        if st.toggle(f"Show {name} ({len(value):,} chars)", key=f"fold_{key}_{rendered.stage}_{name}"):
            st.code(value, language=None, wrap_lines=True)


def show_diff(before: str, after: str, from_label: str, to_label: str, key: str) -> None:
    """Unified diff with an optional side-by-side toggle."""
    if before == after:
        st.caption("No changes — output identical to input.")
        return
    side_by_side = st.toggle("Side-by-side", key=f"diff_{key}")
    if side_by_side:
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"**{from_label}**")
            st.code(before, language=None, wrap_lines=True)
        with col_b:
            st.markdown(f"**{to_label}**")
            st.code(after, language=None, wrap_lines=True)
    else:
        diff = "\n".join(difflib.unified_diff(
            before.splitlines(), after.splitlines(),
            fromfile=from_label, tofile=to_label, lineterm="",
        ))
        st.code(diff, language="diff", wrap_lines=True)
