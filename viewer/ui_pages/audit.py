"""Corpus audit: the offline corpus-level audit report for the selected run.

Renders <run>/audit/audit_report.json. The report's ``sections`` (rows +
verdicts + group/gloss) are written by evals/audit_dad.py itself, so the
thresholds live in one place and this page shows exactly what the terminal
report showed.

New audit sections need no viewer change: give ``_section()`` a ``group`` and
``gloss`` in the eval and this page buckets, glosses, and tallies them
automatically (old reports fall back to ``rendering.AUDIT_SECTION_META``).
Only add a block here when a section needs a custom chart.
"""

import re
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


def _section_table(section: dict) -> None:
    """Render one section's rows as a dataframe, with per-row notes moved below
    it as captions — long notes truncate badly inside a stretched table."""
    rows = rendering.audit_section_table(section)
    if not rows:
        return
    notes = []
    for r in rows:
        note = r.pop("note", None)
        if note:
            notes.append((r.get("check", ""), note))
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    for check, note in notes:
        st.caption(f"↳ **{check}** {note}")


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

# Run cost — the pipeline calls that produced this run (from its own
# cost_log.jsonl). The paid --reasons eval isn't billed here; its cost shows
# inside the Moral-patient reasons section (it logs to the global eval log).
run_cost = loader.total_cost(run.run_dir)
cost_stages = loader.cost_by_stage(run.run_dir)
if run_cost or cost_stages:
    st.metric("Run cost (pipeline)", f"${run_cost:.2f}")
    with st.expander("Cost by stage"):
        st.dataframe(pd.DataFrame([
            {"stage": stage, "calls": agg["calls"], "cost ($)": agg["cost_usd"],
             "model(s)": ", ".join(agg["models"])}
            for stage, agg in cost_stages.items()
        ]), width="stretch", hide_index=True)

# Per-record charts label records by their stable example gid (E-####) when
# the run carries them; pre-gid runs keep the per-run prompt id.
labels = loader.dad_example_labels(run.run_dir) if run.pipeline == "dad" else {}


def _slug(title: str) -> str:
    """Anchor id for a section subheader, so the verdict summary can link to it."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


# Sections measured by the eval but deliberately not displayed on this page
# (their data stays in the report JSON and the terminal output).
_NOT_DISPLAYED = ("Structural variation",)

summary = rendering.audit_verdict_summary(report)
if summary:
    def _summary_line(row: dict) -> str:
        title = row["section"]
        shown = not title.startswith(_NOT_DISPLAYED)
        cell = f"[{title}](#{_slug(title)})" if shown else f"{title} *(not displayed)*"
        if row["skipped"]:
            verdict = "— skipped"
        elif row["worst"] is None:
            verdict = "— informational"
        else:
            badge = {"GOOD": "🟢", "OK": "🟠", "BAD": "🔴"}[row["worst"]]
            verdict = f"{badge} {row['worst']}"
        counts = " ".join(f"{n} {b}" for v, b in (("GOOD", "🟢"), ("OK", "🟠"), ("BAD", "🔴"))
                          if (n := row["counts"][v]))
        return f"| {cell} | {row['group']} | {verdict} | {counts} |"

    st.markdown("\n".join(
        ["| section | group | worst verdict | checks |", "|---|---|---|---|"]
        + [_summary_line(r) for r in summary]))

batch_totals = rendering.audit_batch_totals(report)
if batch_totals:
    st.subheader("Batch totals — plain Claude vs pipeline")
    st.caption("Summed over records where both arms exist; Δ % is relative to plain Claude.")
    st.dataframe(pd.DataFrame(batch_totals), width="stretch", hide_index=True)

# The reasoning-library retrieval picture (per-record 2a.5 pulls, all entry
# ids, id -> transferable move) — rides the reasons chart, the per-record
# expanders, and the trigger-count toggle.
pulls, library_ids, lib_moves = (loader.dad_library_info(run.run_dir)
                                 if run.pipeline == "dad" else ({}, [], {}))


def _render_reasons_section(section: dict) -> None:
    """The paid moral-patient reasons section, charts before tables."""
    title = section.get("title", "")
    st.subheader(title, anchor=_slug(title))
    gloss = rendering.audit_section_gloss(section)
    if gloss:
        st.caption(gloss)
    mpr = report.get("moral_patient_reasons") or {}
    per_case = mpr.get("per_case") or {}
    cost = mpr.get("cost_usd")
    if cost is not None:
        st.caption(f"Paid pass cost: ${cost:.4f} · model `{mpr.get('model') or '?'}`")

    chart_rows = rendering.audit_reason_chart_rows(per_case, labels)
    if chart_rows:
        st.altair_chart(_grouped_arm_chart(chart_rows, "unique reasons"),
                        use_container_width=True)
    surv_rows = rendering.audit_survival_chart_rows(per_case, labels)
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

    # Third chart: library rows pulled per record, right under the two reason
    # charts so per-record retrieval width reads in the same glance.
    pull_rows = rendering.audit_pull_count_rows(pulls, labels)
    if pull_rows:
        st.caption("Library rows pulled at 2a.5 per record — hover a bar for "
                   "which entries.")
        st.altair_chart(
            alt.Chart(pd.DataFrame(pull_rows)).mark_bar(
                color=rendering.AUDIT_PULL_COLOR).encode(
                x=alt.X("record:N", title="record"),
                y=alt.Y("count:Q", title="rows pulled"),
                tooltip=[alt.Tooltip("record", title="record"),
                         alt.Tooltip("count", title="rows pulled"),
                         alt.Tooltip("entries", title="which entries")],
            ),
            use_container_width=True)

    _section_table(section)
    for line in section.get("detail", []):
        st.caption(line)

    for pid in sorted(per_case):
        label = rendering.audit_record_label(pid, labels)
        with st.expander(f"{label} — reasons kept / dropped / added (plain vs pipeline)"):
            common.show_reason_comparison(per_case[pid])
            entry_ids = pulls.get(pid) or []
            # Folded behind its own toggle (expanders can't nest): the pulled
            # rows are context, not the comparison the expander is opened for.
            if entry_ids and st.toggle(
                    f"Library entries pulled at 2a.5 ({len(entry_ids)}) — "
                    "id + transferable move",
                    value=False, key=f"lib_pulls_{pid}"):
                for eid in entry_ids:
                    move = lib_moves.get(eid, "")
                    st.markdown(f"- **{eid}**{' — ' + move if move else ''}")
    for arm, arm_title in (("plain", "Plain Claude"), ("pipeline", "Pipeline")):
        summary = mpr.get(arm) or {}
        corpus = summary.get("corpus_reasons") or []
        if corpus:
            with st.expander(f"Corpus-level distinct reasons — {arm_title} ({len(corpus)})"):
                for reason in corpus:
                    st.markdown(f"- {reason}")


# --- Moral-patient reasons first (the paid, decision-grade section) ---
reasons_section = next((s for s in sections
                        if s.get("title", "").startswith("Moral-patient reasons")), None)
if reasons_section:
    _render_reasons_section(reasons_section)
elif "moral_patient_reasons" not in report:
    st.caption("Moral-patient reason extraction hasn't run for this report — add it "
               "(costs API calls) with:")
    st.code(f"{cmd} --reasons", language="bash")

# --- Semantic diversity (embeddings) second — a separate report file,
# rendered when evals/diversity.py has run on this run dir. Charts first.
diversity = loader.load_diversity(run.run_dir)
if diversity is None:
    st.caption("No semantic diversity report yet — generate it (embedding cents) with:")
    st.code(f"python evals/diversity.py --input {run.run_dir} --ideas", language="bash")
else:
    st.header("Semantic diversity (embeddings)")
    st.caption(f"model `{diversity.get('embed_model')}` · numbers are only comparable "
               "across runs using the same embedding model")

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

    for section in diversity.get("sections") or []:
        st.subheader(section.get("title", ""))
        _section_table(section)
        for line in section.get("detail", []):
            st.caption(line)

# --- The remaining audit sections, bucketed prompt / response / library ---
# Moral-patient reasons is rendered above; _NOT_DISPLAYED sections are
# deliberately hidden (still measured — report JSON and terminal keep them).
_SKIP_SECTIONS = ("Moral-patient reasons",) + _NOT_DISPLAYED
# Sections whose detail lines are replaced by a richer custom view below, so
# the generic gray-caption dump is suppressed for them.
_CUSTOM_DETAIL = ("Stock phrases",)
_GROUP_HEADERS = {
    "prompt": "Prompt side — the shipped user messages",
    "response": "Response side — final replies vs the plain-Claude control",
    "library": "Reasoning library — selection & coverage",
    "paid": "Paid LLM checks",
    "other": "Other checks",
}

_by_group: dict = {}
for section in sections:
    if not section.get("title", "").startswith(_SKIP_SECTIONS):
        _by_group.setdefault(rendering.audit_section_group(section), []).append(section)


def _render_section(section: dict) -> None:
    title = section.get("title", "")
    st.subheader(title, anchor=_slug(title))
    gloss = rendering.audit_section_gloss(section)
    if gloss:
        st.caption(gloss)
    _section_table(section)
    suppress_detail = title.startswith(_CUSTOM_DETAIL)

    if title.startswith("Reasoning-library selection"):
        if pulls and library_ids:
            # Corpus-level trigger counts, behind a toggle so the page stays
            # compact; the per-record pull chart lives under the reasons block.
            if st.toggle("Reasoning-library trigger counts — every entry across "
                         "this corpus", value=False, key="lib_trigger_counts"):
                trigger_rows = rendering.audit_trigger_count_rows(pulls, library_ids,
                                                                  lib_moves)
                st.caption(f"Cases (of {len(pulls)} scoped) whose 2a.5 selection "
                           "pulled each entry, in library order — zero bars are "
                           "entries this corpus never triggered. Hover for the "
                           "entry's transferable move.")
                st.altair_chart(
                    alt.Chart(pd.DataFrame(trigger_rows)).mark_bar(
                        color=rendering.AUDIT_PULL_COLOR).encode(
                        x=alt.X("entry:N", title="library entry", sort=library_ids),
                        y=alt.Y("cases:Q", title="cases pulled"),
                        tooltip=[alt.Tooltip("entry", title="entry"),
                                 alt.Tooltip("cases", title="cases"),
                                 alt.Tooltip("move", title="transferable move")],
                    ),
                    use_container_width=True)
        if pulls:
            suppress_detail = True  # the per-record chart (reasons block) replaces the dump

    if title.startswith("Reasoning-library coverage"):
        # Retrieval width vs added reasoning — the correlation view: does
        # pulling more library rows at 2a.5 come with more pipeline-added
        # reasons? (Needs the paid --reasons survival data.)
        per_case = (report.get("moral_patient_reasons") or {}).get("per_case") or {}
        scatter_rows = rendering.audit_pull_scatter_rows(per_case, pulls, labels)
        if scatter_rows:
            df = pd.DataFrame(scatter_rows)
            r = (df["pulled"].corr(df["added"])
                 if len(df) >= 3 and df["pulled"].nunique() > 1 else None)
            st.caption("Each point is one record: library rows pulled at 2a.5 (x) vs "
                       "reasons the pipeline added beyond plain Claude (y, from the "
                       "survival judge). Hover for the record and which entries."
                       + (f" Pearson r = {r:.2f} over {len(df)} records."
                          if r is not None and not pd.isna(r) else ""))
            points = alt.Chart(df).mark_circle(
                color=rendering.AUDIT_PULL_COLOR, size=70, opacity=0.7).encode(
                x=alt.X("pulled:Q", title="library rows pulled (2a.5)"),
                y=alt.Y("added:Q", title="pipeline-added reasons"),
                tooltip=[alt.Tooltip("record", title="record"),
                         alt.Tooltip("pulled", title="rows pulled"),
                         alt.Tooltip("added", title="added reasons"),
                         alt.Tooltip("entries", title="which entries")],
            )
            trend = points.transform_regression("pulled", "added").mark_line(
                color=rendering.AUDIT_PULL_COLOR, strokeDash=[4, 3])
            st.altair_chart((points + trend).properties(height=260),
                            use_container_width=True)

    if title.startswith("Response lengths"):
        chart_rows = rendering.audit_length_chart_rows(
            (report.get("response_lengths") or {}).get("per_case") or {}, labels)
        if chart_rows:
            st.altair_chart(_grouped_arm_chart(chart_rows, "chars"),
                            use_container_width=True)

    if title.startswith("Stock phrases"):
        sp = report.get("stock_phrases") or {}
        phrase_rows = rendering.audit_stock_phrase_rows(sp)
        if phrase_rows:
            n_pipe, n_plain = sp.get("n_pipeline") or 0, sp.get("n_plain") or 0
            st.caption("Recurring phrases by arm — the pipeline-vs-plain gap is the "
                       "training-data signal. Sorted by pipeline frequency.")
            st.dataframe(pd.DataFrame(
                [{"phrase": r["phrase"], "origin": r["origin"],
                  "pipeline": f"{r['pipeline']}/{n_pipe}",
                  "plain": f"{r['plain']}/{n_plain}"} for r in phrase_rows]),
                width="stretch", hide_index=True)

    if not suppress_detail:
        for line in section.get("detail", []):
            st.caption(line)


for group in rendering.AUDIT_GROUP_ORDER:
    group_sections = _by_group.get(group) or []
    if not group_sections:
        continue
    st.header(_GROUP_HEADERS[group])
    for section in group_sections:
        _render_section(section)

common.json_block(report, f"audit_{run.run_id}", "Raw report JSON")
