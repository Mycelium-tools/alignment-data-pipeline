"""Corpus audit: the offline corpus-level audit report for the selected run.

Renders <run>/audit/audit_report.json. The report's ``sections`` (rows +
verdicts) are written by evals/audit_dad.py itself, so the thresholds live in
one place and this page shows exactly what the terminal report showed.
"""

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from viewer import loader, rendering
from viewer.ui_pages import common

st.title("Corpus audit")

run = common.pick_run()
if run is None:
    st.stop()

st.markdown(f"**{run.label or run.run_id}** · `{run.run_id}`")

_AUDIT_SCRIPTS = {"dad": "audit_dad.py", "sdf": "audit_sdf.py"}
cmd = f"python evals/{_AUDIT_SCRIPTS.get(run.pipeline, 'audit_dad.py')} --input {run.run_dir}"

def _grouped_arm_chart(rows: list[dict], value_label: str) -> alt.Chart:
    """Side-by-side plain-vs-pipeline bars. Built via Altair (not st.bar_chart)
    with interactivity OFF — the built-in charts scroll-zoom, which pans the
    y-axis into nonsense on an accidental scroll."""
    df = pd.DataFrame(rows).melt(id_vars="record", var_name="arm", value_name=value_label)
    return alt.Chart(df).mark_bar().encode(
        x=alt.X("record:N", title="record"),
        xOffset=alt.XOffset("arm:N", sort=list(rendering.AUDIT_ARM_COLUMNS)),
        y=alt.Y(f"{value_label}:Q", title=value_label),
        color=alt.Color("arm:N", title="", scale=alt.Scale(
            domain=list(rendering.AUDIT_ARM_COLUMNS),
            range=list(rendering.AUDIT_ARM_COLORS))),
        tooltip=["record", "arm", alt.Tooltip(value_label, title=value_label)],
    )


report = loader.load_audit(run.run_dir)
if report is None:
    st.info("No corpus audit for this run yet. It is offline and free — generate it with:")
    st.code(cmd, language="bash")
    st.stop()

sections = report.get("sections")
if not sections:
    if run.pipeline == "dad":
        st.warning("This report predates embedded verdicts — re-run the audit "
                   "(offline, free) to refresh it:")
        st.code(cmd, language="bash")
    else:
        st.caption("Native rendering exists for DAD audit reports only so far — raw report below.")
    common.json_block(report, f"audit_{run.run_id}", "Raw report JSON", expanded=True)
    st.stop()

st.caption(f"{report.get('n_prompts', '?')} prompts audited · "
           f"`{Path(run.run_dir) / 'audit' / 'audit_report.json'}`")

batch_totals = rendering.audit_batch_totals(report)
if batch_totals:
    st.subheader("Batch totals — plain Claude vs pipeline")
    st.caption("Summed over records where both arms exist; Δ % is relative to plain Claude.")
    st.dataframe(pd.DataFrame(batch_totals), width="stretch", hide_index=True)

for section in sections:
    title = section.get("title", "")
    st.subheader(title)
    rows = rendering.audit_section_table(section)
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    if title.startswith("Response lengths"):
        chart_rows = rendering.audit_length_chart_rows(
            (report.get("response_lengths") or {}).get("per_case") or {})
        if chart_rows:
            st.altair_chart(_grouped_arm_chart(chart_rows, "chars"),
                            use_container_width=True)

    if title.startswith("Moral-patient reasons"):
        mpr = report.get("moral_patient_reasons") or {}
        chart_rows = rendering.audit_reason_chart_rows(mpr.get("per_case") or {})
        if chart_rows:
            st.altair_chart(_grouped_arm_chart(chart_rows, "unique reasons"),
                            use_container_width=True)
        surv_rows = rendering.audit_survival_chart_rows(mpr.get("per_case") or {})
        if surv_rows:
            # Stacked survival chart — hover a segment to see WHICH reasons
            # sit in it. Bottom three segments sum to the plain arm's count.
            st.altair_chart(
                alt.Chart(pd.DataFrame(surv_rows)).mark_bar().encode(
                    x=alt.X("record:N", title="record"),
                    y=alt.Y("count:Q", title="reasons"),
                    color=alt.Color("category:N", title="", scale=alt.Scale(
                        domain=list(rendering.AUDIT_SURVIVAL_CATEGORIES),
                        range=list(rendering.AUDIT_SURVIVAL_COLORS)),
                        sort=list(rendering.AUDIT_SURVIVAL_CATEGORIES)),
                    order=alt.Order("stack_order:Q", sort="ascending"),
                    tooltip=[alt.Tooltip("record", title="record"),
                             alt.Tooltip("category", title="fate"),
                             alt.Tooltip("count", title="count"),
                             alt.Tooltip("reasons", title="which reasons")],
                ),
                use_container_width=True)
        for pid in sorted(mpr.get("per_case") or {}):
            with st.expander(f"{pid} — reasons kept / dropped / added (plain vs pipeline)"):
                common.show_reason_comparison(mpr["per_case"][pid])
        for arm, arm_title in (("plain", "Plain Claude"), ("pipeline", "Pipeline")):
            summary = mpr.get(arm) or {}
            corpus = summary.get("corpus_reasons") or []
            if corpus:
                with st.expander(f"Corpus-level distinct reasons — {arm_title} ({len(corpus)})"):
                    for reason in corpus:
                        st.markdown(f"- {reason}")

    for line in section.get("detail", []):
        st.caption(line)

if "moral_patient_reasons" not in report:
    st.caption("Moral-patient reason extraction hasn't run for this report — add it "
               "(costs API calls) with:")
    st.code(f"{cmd} --reasons", language="bash")

# Semantic diversity (embeddings) — a separate report file, rendered here when
# evals/diversity.py has run on this run dir.
diversity = loader.load_diversity(run.run_dir)
if diversity is None:
    st.caption("No semantic diversity report yet — generate it (embedding cents) with:")
    st.code(f"python evals/diversity.py --input {run.run_dir} --ideas", language="bash")
else:
    st.header("Semantic diversity (embeddings)")
    st.caption(f"model `{diversity.get('embed_model')}` · numbers are only comparable "
               "across runs using the same embedding model")
    for section in diversity.get("sections") or []:
        st.subheader(section.get("title", ""))
        rows = rendering.audit_section_table(section)
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        for line in section.get("detail", []):
            st.caption(line)

    def _nn_hist(sims: list, rule_at: float, x_title: str) -> alt.Chart:
        bars = alt.Chart(pd.DataFrame({"sim": sims})).mark_bar(color="#4C78A8").encode(
            x=alt.X("sim:Q", bin=alt.Bin(maxbins=20), title=x_title,
                    scale=alt.Scale(domain=[0, 1])),
            y=alt.Y("count()", title="records"))
        rule = alt.Chart(pd.DataFrame({"x": [rule_at]})).mark_rule(
            strokeDash=[5, 3], color="#E5484D").encode(x="x:Q")
        return (bars + rule).properties(height=210)

    def _cluster_bars(sizes: list) -> alt.Chart:
        df = pd.DataFrame({"cluster (sorted)": range(1, len(sizes) + 1), "size": sizes})
        return alt.Chart(df).mark_bar(color="#3FB366").encode(
            x=alt.X("cluster (sorted):O", axis=alt.Axis(labels=len(sizes) <= 12)),
            y="size:Q").properties(height=210)

    def _cloud_scatter(cloud: list) -> alt.Chart:
        return alt.Chart(pd.DataFrame(cloud)).mark_circle(size=70, color="#D97757").encode(
            x=alt.X("x:Q", title="PC1", axis=alt.Axis(labels=False, ticks=False)),
            y=alt.Y("y:Q", title="PC2", axis=alt.Axis(labels=False, ticks=False)),
            tooltip=[alt.Tooltip("id", title="record"),
                     alt.Tooltip("snippet", title="text")],
        ).properties(height=210)

    scopes = diversity.get("scopes") or {}
    scope_order = [("prompts", "Prompts (user messages)"),
                   ("responses", "Responses (assistant messages)"),
                   ("combined", "Combined (user + assistant)"
                    if len(scopes) > 1 else "Documents")]
    shown = [(k, label) for k, label in scope_order if k in scopes]
    if shown:
        st.subheader("Diversity charts by scope")
        st.caption("Per scope: nearest-neighbour redundancy (dashed line = the >0.90 "
                   "near-dup verdict threshold) · topic spread (sorted cluster sizes) · "
                   "document cloud (2-D PCA; hover for the record).")
        for key, label in shown:
            blk = scopes[key]
            c = blk.get("clusters") or {}
            st.markdown(f"**{label}** — near-dup>0.90 {blk['over']['0.90']:.0%} · "
                        f"topic evenness {c.get('evenness', 0):.3f} "
                        f"(largest {c.get('largest_share', 0):.0%}) · "
                        f"Vendi ratio {blk.get('vendi_ratio', 0):.2f}")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.altair_chart(_nn_hist(blk.get("nn_sims") or [], 0.90,
                                         "nearest-neighbour cosine"),
                                use_container_width=True)
            with col2:
                st.altair_chart(_cluster_bars(c.get("sizes") or []),
                                use_container_width=True)
            with col3:
                st.altair_chart(_cloud_scatter(blk.get("cloud") or []),
                                use_container_width=True)

    ideas = diversity.get("ideas") or {}
    if ideas.get("nn_sims"):
        st.markdown(f"**Idea-level diversity** — {ideas['n']} one-line scenario summaries; "
                    f"{ideas.get('over_0.95', 0):.0%} share their core idea with another "
                    "(dashed line = the >0.95 re-skinned-idea threshold)")
        st.altair_chart(_nn_hist(ideas["nn_sims"], 0.95,
                                 "nearest-neighbour similarity of idea summaries"),
                        use_container_width=True)
    elif not ideas:
        st.caption("Idea-level pass not run — add `--ideas` for re-skinned-scenario detection.")

common.json_block(report, f"audit_{run.run_id}", "Raw report JSON")
