"""Shared helpers for the viewer pages."""

import difflib
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from viewer import loader

FOLD_THRESHOLD = 2000  # chars; variable values longer than this get folded out of prompts

_SOURCE_BADGES = {
    "snapshot": ":green-badge[snapshot]",
    "git": ":orange-badge[reconstructed from git]",
    "missing": ":red-badge[missing]",
}


def source_badge(source: str, commit: str | None = None) -> str:
    badge = _SOURCE_BADGES.get(source, source)
    if source == "git" and commit:
        badge += f" :gray-badge[{commit}]"
    return badge


def pick_run(pipeline_key: str = "pipeline", run_key: str = "run") -> loader.RunInfo | None:
    """Run selector seeded from query params; keeps params in sync."""
    runs = loader.list_runs()
    if not runs:
        st.info("No runs found under outputs/. Run a pipeline first.")
        return None

    pipelines = sorted({r.pipeline for r in runs})
    qp_pipeline = st.query_params.get(pipeline_key)
    pipeline = st.selectbox(
        "Pipeline", pipelines,
        index=pipelines.index(qp_pipeline) if qp_pipeline in pipelines else 0,
        key=f"sel_{pipeline_key}",
    )

    pipeline_runs = [r for r in runs if r.pipeline == pipeline]
    run_ids = [r.run_id for r in pipeline_runs]
    qp_run = st.query_params.get(run_key)
    run_id = st.selectbox(
        "Run", run_ids,
        index=run_ids.index(qp_run) if qp_run in run_ids else 0,
        key=f"sel_{run_key}",
    )

    st.query_params[pipeline_key] = pipeline
    st.query_params[run_key] = run_id
    return next(r for r in pipeline_runs if r.run_id == run_id)


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


def show_rendered_prompt(rendered, key: str = "") -> None:
    """Render a RenderedPrompt: warnings, sources, system + user with folding.
    `key` must be unique per prompt on the page (e.g. the stage name)."""
    for w in rendered.warnings:
        st.warning(w)
    if rendered.template_sources:
        st.markdown(" ".join(
            f"`{t.name}` {source_badge(t.source)}" for t in rendered.template_sources
        ))
    if not rendered.is_llm_call:
        st.caption("No LLM call at this stage for this record.")
        return

    folded_all = {}
    if rendered.system:
        sys_text, folded = fold_long_values(rendered.system, {"system prompt (full constitution)": rendered.system})
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
