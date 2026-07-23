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


def _grouped_barh(df: pd.DataFrame, cat_field: str, cat_title: str) -> alt.Chart:
    """Horizontal plain-vs-pipeline grouped bars, one group per category,
    sorted by count. Backs the tracked-tic frequency view that replaces the
    old wall of gray detail captions."""
    return alt.Chart(df).mark_bar().encode(
        y=alt.Y(f"{cat_field}:N", title=cat_title, sort="-x"),
        yOffset=alt.YOffset("arm:N", sort=list(rendering.AUDIT_ARM_COLUMNS)),
        x=alt.X("count:Q", title="responses"),
        color=alt.Color("arm:N", title="", scale=alt.Scale(
            domain=list(rendering.AUDIT_ARM_COLUMNS),
            range=list(rendering.AUDIT_ARM_COLORS))),
        tooltip=[alt.Tooltip(cat_field, title=cat_title or "phrase"), "arm",
                 alt.Tooltip("count", title="count")],
    )


# --- shared redundancy/spread/cloud charts, used by BOTH the semantic and the
# lexical diversity sections (same visuals, different feature space) -----------

def _nn_hist(sims: list, rule_at: float, x_title: str) -> alt.Chart:
    bars = alt.Chart(pd.DataFrame({"sim": sims})).mark_bar(color="#4C78A8").encode(
        x=alt.X("sim:Q", bin=alt.Bin(maxbins=20), title=x_title, scale=alt.Scale(domain=[0, 1])),
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
        tooltip=[alt.Tooltip("id", title="record"), alt.Tooltip("snippet", title="text")],
    ).properties(height=210)


def _shared_phrase_bars(top_shared: dict) -> alt.Chart | None:
    """Horizontal bar of the most over-represented phrases (n-gram → #prompts
    sharing it) — the lexical section's interpretable counterpart to the
    semantic cluster/cloud charts, naming the fingerprints directly."""
    rows = []
    for order in ("4", "3"):
        for phrase, count in (top_shared.get(order) or []):
            rows.append({"phrase": phrase, "prompts": count, "n-gram": f"{order}-gram"})
    if not rows:
        return None
    df = pd.DataFrame(rows).drop_duplicates("phrase").nlargest(12, "prompts")
    return alt.Chart(df).mark_bar(color="#8B5CF6").encode(
        y=alt.Y("phrase:N", title="", sort="-x"),
        x=alt.X("prompts:Q", title="prompts sharing it"),
        tooltip=[alt.Tooltip("phrase", title="phrase"),
                 alt.Tooltip("prompts", title="# prompts"),
                 alt.Tooltip("n-gram", title="length")],
    ).properties(height=210)


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

# --- Headline: important considerations (the dataset's usefulness, up top) ---
# Combines the two paid signals — welfare reasons + humane alternatives weighed —
# into one parent metric with the two as subsets. A health check, not a target;
# the detailed reasons/alternatives sections render lower down unchanged.
_ic = report.get("important_considerations") or {}
if _ic.get("available"):
    st.header("Important considerations")
    st.caption("The dataset's usefulness in one view. Each bar is one arm; its two segments — "
               "**welfare considerations** + **alternatives weighed** (an alternative IS a "
               "welfare consideration) — stack to that arm's total distinct considerations per "
               "answer. A health check, not a target.")
    # Stacked bar so the parent reads as the SUM of its two parts (not three
    # independent measurements): one bar per arm, segments = the two subsets,
    # total labelled at the end.
    _subs = _ic["subsets"]
    _rows = [{"arm": arm_col, "component": s["name"], "value": s[arm_key]}
             for s in _subs
             for arm_key, arm_col in (("plain", "plain Claude"), ("pipeline", "pipeline"))]
    _arms = ["plain Claude", "pipeline"]
    _comp_domain = [s["name"] for s in _subs]
    _comp_range = ["#2a78d6", "#8256b8"][:len(_comp_domain)]  # not the arm terracotta/green
    _bars = alt.Chart(pd.DataFrame(_rows)).mark_bar().encode(
        y=alt.Y("arm:N", title="", sort=_arms),
        x=alt.X("value:Q", title="distinct considerations per answer (stacked)", stack="zero"),
        color=alt.Color("component:N", title="",
                        scale=alt.Scale(domain=_comp_domain, range=_comp_range)),
        order=alt.Order("component:N"),
        tooltip=["arm", "component", alt.Tooltip("value:Q", title="per answer", format=".2f")],
    )
    _totals = pd.DataFrame([{"arm": "plain Claude", "total": _ic["parent"]["plain"]},
                            {"arm": "pipeline", "total": _ic["parent"]["pipeline"]}])
    _labels = alt.Chart(_totals).mark_text(align="left", dx=5, fontWeight="bold").encode(
        y=alt.Y("arm:N", sort=_arms), x=alt.X("total:Q"),
        text=alt.Text("total:Q", format=".1f"))
    st.altair_chart((_bars + _labels).properties(height=150), use_container_width=True)
    _bits = []
    if _ic.get("length_ratio"):
        _bits.append(f"**{_ic['length_ratio']:.2f}× longer** than plain")
    if _ic.get("retained_share") is not None:
        _frag = f"keeps **{_ic['retained_share']:.0%}** of the considerations plain raised"
        if _ic.get("added_total"):
            _frag += f" and adds **{_ic['added_total']}** more"
        _bits.append(_frag)
    if _bits:
        st.markdown("Length is earned — " + " · ".join(_bits)
                    + ". The extra length is *additive* (it doesn't drop plain's points), not "
                    "padding. Read these together; none is a target to maximize.")
    st.divider()
elif _ic.get("available") is False:
    st.info("Run the audit with `--reasons` to populate the important-considerations "
            "summary (welfare reasons + humane alternatives weighed).")

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

# prompt_id -> this run's stable gids, so the per-case audit charts and
# breakdowns label by the record they're about — responses by R-####, the
# finished example by E-#### — not the per-run prompt id. Loaded once from
# the run's rewrites.
_gids_by_pid = ({r.get("prompt_id"): {"response": r.get("response_gid"),
                                      "example": r.get("example_gid")}
                 for r in loader.load_stage(run.run_dir, "dad", "step3_rewrites")
                 if r.get("prompt_id")} if run.pipeline == "dad" else {})


def _label_responses(rows: list[dict], key: str = "record") -> list[dict]:
    """Relabel a per-case chart's id (prompt_id) with its response gid (R-####)
    so response-level charts read in stable ids; unmapped ids stay as-is."""
    for row in rows:
        row[key] = (_gids_by_pid.get(row[key]) or {}).get("response") or row[key]
    return rows


def _resp_label(pid: str) -> str:
    """Stable-id label for one record's picker entry (response R-#### · example
    E-####); the per-run prompt_id only shows when a record has no gids."""
    gids = _gids_by_pid.get(pid) or {}
    ids = [gids.get("response"), gids.get("example")]
    return " · ".join(x for x in ids if x) or pid


def _slug(title: str) -> str:
    """Anchor id for a section subheader, so the verdict summary can link to it."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


# Sections measured by the eval but deliberately not displayed on this page
# (their data stays in the report JSON and the terminal output).
_NOT_DISPLAYED = ("Structural variation",)
# Alternatives + stance ride the same paid pass as the reasons section; they
# render right after it so the judge's outputs read together.
_PAID_COMPANIONS = ("Humane alternatives", "Response stance", "Reasoning-composition")
# Sections whose detail lines are replaced by a richer custom view below, so
# the generic gray-caption dump is suppressed for them. "Stock phrases" is the
# legacy pre-tics name; old reports keep it.
_CUSTOM_DETAIL = ("Tracked tics", "Stock phrases")

def _render_health_overview() -> None:
    """Verdict overview table + batch totals. A health-check summary, so it
    renders in the health-check tail below the dataset-usefulness sections."""
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
# breakdowns, and the trigger-count toggle.
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

    # Cumulative first (the headline for this subset), then the per-response
    # detail — so the summary reads before the 40-bar breakdown.
    p_mean = (mpr.get("pipeline") or {}).get("mean_unique")
    b_mean = (mpr.get("plain") or {}).get("mean_unique")
    if p_mean is not None and b_mean is not None:
        st.markdown("**Cumulative** — mean distinct welfare considerations per answer")
        _cum = pd.DataFrame([{"arm": "plain Claude", "mean": b_mean},
                             {"arm": "pipeline", "mean": p_mean}])
        st.altair_chart(alt.Chart(_cum).mark_bar().encode(
            x=alt.X("mean:Q", title="mean per answer"),
            y=alt.Y("arm:N", title="", sort=list(rendering.AUDIT_ARM_COLUMNS)),
            color=alt.Color("arm:N", title="", scale=alt.Scale(
                domain=list(rendering.AUDIT_ARM_COLUMNS),
                range=list(rendering.AUDIT_ARM_COLORS))),
            tooltip=["arm", alt.Tooltip("mean:Q", format=".2f")]).properties(height=110),
            use_container_width=True)
        added = (mpr.get("survival") or {}).get("added_total")
        n_pipe = (mpr.get("pipeline") or {}).get("n")
        n_plain = (mpr.get("plain") or {}).get("n")
        bits = []
        if added:
            bits.append(f"the pipeline adds **{added}** considerations beyond plain (net, across the corpus)")
        if n_pipe is not None and n_plain is not None:
            bits.append(f"means over pipeline {n_pipe} / plain {n_plain} answers extracted")
        if bits:
            st.caption(" · ".join(bits) + ".")

    # Extraction failures leave a record with no bar for that arm — say so
    # plainly (and which records), so a missing bar never reads as "the pipeline
    # dropped everything here." Retries + object-unwrap recovery mean a fresh
    # --reasons run usually clears these; the excluded records are named.
    failures = mpr.get("failures") or 0
    if failures:
        missing = []
        for pid, e in per_case.items():
            gaps = [arm for arm in ("plain", "pipeline")
                    if (e.get(arm) or {}).get("reasons") is None]
            for arm in gaps:
                missing.append(f"{(_gids_by_pid.get(pid) or {}).get('response') or pid} ({arm})")
        st.warning(
            f"⚠️ {failures} extraction failure(s) — those records have no bar for the "
            "affected arm and are **excluded from the means above** (not a zero). "
            + (f"Missing: {', '.join(sorted(missing))}. " if missing else "")
            + "Re-run `--reasons` to retry them.")

    chart_rows = _label_responses(rendering.audit_reason_chart_rows(per_case))
    if chart_rows:
        st.markdown("**Per response** — pipeline vs plain, one pair per record "
                    "(spot a specific answer that runs lean, or an extraction gap where a bar "
                    "is missing).")
        st.altair_chart(_grouped_arm_chart(chart_rows, "unique reasons"),
                        use_container_width=True)
    surv_rows = _label_responses(rendering.audit_survival_chart_rows(per_case))
    if surv_rows:
        st.caption("**Retention of plain's considerations** — *dropped* means a consideration "
                   "**plain Claude** raised that this pipeline answer didn't echo (a "
                   "no-regression check on plain's points), NOT a lost pipeline reason. "
                   "*added* = new considerations the pipeline brought.")
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
    pull_rows = _label_responses(rendering.audit_pull_count_rows(pulls))
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

    # Collapse the per-response breakdowns under one drop-down with a picker
    # inside it (Streamlit forbids nested expanders) — saves the vertical
    # space of one expander per response. Each is labelled by its stable ids
    # (response R-#### · example E-####) so it matches the charts above and
    # the lineage dropdown.
    pids = sorted(per_case)
    if pids:
        with st.expander(f"Per-response reason breakdowns ({len(pids)})", expanded=False):
            choice = st.selectbox("Response", pids, format_func=_resp_label,
                                  key="reasons_percase_pick")
            st.caption(f"{_resp_label(choice)} — reasons kept / weakened / dropped / "
                       "added (plain vs pipeline)")
            common.show_reason_comparison(per_case[choice])
            entry_ids = pulls.get(choice) or []
            # Folded behind its own toggle: the pulled rows are context, not
            # the comparison the drop-down is opened for.
            if entry_ids and st.toggle(
                    f"Library entries pulled at 2a.5 ({len(entry_ids)}) — "
                    "id + transferable move",
                    value=False, key=f"lib_pulls_{choice}"):
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


def _render_alternatives_section(section: dict) -> None:
    """Humane alternatives (LLM): per-record chart + collapsed per-response
    citations (mirrors the reasons breakdown)."""
    title = section.get("title", "")
    st.subheader(title, anchor=_slug(title))
    gloss = rendering.audit_section_gloss(section)
    if gloss:
        st.caption(gloss)
    _section_table(section)
    moves_pc = (report.get("moves") or {}).get("per_case") or {}
    alt_rows = _label_responses(rendering.audit_alternative_chart_rows(moves_pc))
    if alt_rows:
        st.caption("Concrete lower-harm alternatives each arm proposes, per response "
                   "(actions, not considerations). The pipeline-over-plain gap is the "
                   "\"how, not whether\" signal.")
        st.altair_chart(_grouped_arm_chart(alt_rows, "alternatives"),
                        use_container_width=True)
    # Per-response citations under one collapsed drop-down (mirrors the
    # reasons breakdown): which alternatives each arm actually offered.
    pids = sorted(moves_pc)
    if pids:
        with st.expander(f"Per-response alternatives ({len(pids)})", expanded=False):
            choice = st.selectbox("Response", pids, format_func=_resp_label,
                                  key="alts_percase_pick")
            st.caption(f"{_resp_label(choice)} — plain Claude's alternatives judged against "
                       "the pipeline's response, plus what the pipeline added.")
            groups = rendering.audit_alternative_groups(
                (moves_pc[choice] or {}).get("alternatives") or {})
            for gtitle, items in groups or []:
                st.markdown(f"**{gtitle}**")
                if items:
                    st.markdown("\n".join(f"- {a}" for a in items))
                else:
                    st.caption("none")
    for line in section.get("detail", []):
        st.caption(line)


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
        scatter_rows = _label_responses(rendering.audit_pull_scatter_rows(per_case, pulls))
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
        chart_rows = _label_responses(rendering.audit_length_chart_rows(
            (report.get("response_lengths") or {}).get("per_case") or {}))
        if chart_rows:
            st.altair_chart(_grouped_arm_chart(chart_rows, "chars"),
                            use_container_width=True)

    if title.startswith(_CUSTOM_DETAIL):
        sp = report.get("tracked_tics") or report.get("stock_phrases") or {}
        phrase_rows = rendering.audit_tracked_tic_rows(sp)
        if phrase_rows:
            n_pipe, n_plain = sp.get("n_pipeline") or 0, sp.get("n_plain") or 0
            st.caption("Recurring phrases by arm — the pipeline-vs-plain gap is the "
                       "training-data signal. Sorted by pipeline frequency.")
            st.dataframe(pd.DataFrame(
                [{"phrase": r["phrase"], "origin": r["origin"],
                  "pipeline": f"{r['pipeline']}/{n_pipe}",
                  "plain": f"{r['plain']}/{n_plain}"} for r in phrase_rows]),
                width="stretch", hide_index=True)
            top = phrase_rows[:12]
            long = [{"phrase": r["phrase"], "arm": arm_col, "count": r[arm_key]}
                    for r in top
                    for arm_key, arm_col in (("plain", "plain Claude"),
                                             ("pipeline", "pipeline"))]
            st.altair_chart(_grouped_barh(pd.DataFrame(long), "phrase", ""),
                            use_container_width=True)

    if title.startswith("Lexical diversity — prompts"):
        st.caption("**Wording/surface diversity of the prompts** — the phrases the corpus "
                   "over-uses and a style Vendi over character n-grams. This is about *how the "
                   "prompts are written*, not what they're about. For topic/meaning diversity see "
                   "**Semantic diversity (embeddings)** at the bottom.")
        ld = report.get("lexical_diversity") or {}
        if ld.get("cloud"):
            st.markdown(f"**Surface-form layout** — near-dup>0.90 (char n-gram) "
                        f"{ld.get('over_0.90', 0):.0%} · style Vendi ratio "
                        f"{ld.get('style_vendi_ratio', 0):.2f}")
            st.caption("Same charts as the semantic section, but in char-n-gram (writing form) "
                       "space: nearest-neighbour redundancy (dashed line = >0.90) · document "
                       "cloud (2-D PCA of surface features; hover for the record). The over-used "
                       "phrase list is demoted (mostly common English) — see the **Style "
                       "fingerprint** section for curated tic/move reuse.")
            c1, c2 = st.columns(2)
            with c1:
                st.altair_chart(_nn_hist(ld.get("nn_sims") or [], 0.90,
                                         "nearest-neighbour surface cosine"),
                                use_container_width=True)
            with c2:
                st.altair_chart(_cloud_scatter(ld["cloud"]), use_container_width=True)

    if title.startswith("Style fingerprint"):
        fp = (report.get("style_fingerprint") or {}).get("pipeline") or {}
        if fp.get("points"):
            st.caption("Each dot is one response in curated-feature space (tracked tics + "
                       "rhetorical moves — no common words); dots that overlap share a "
                       "tic/move fingerprint. Dashed line on the histogram = near-twin >0.95.")
            c1, c2 = st.columns(2)
            with c1:
                st.altair_chart(_nn_hist([p["nn"] for p in fp["points"]], 0.95,
                                         "nearest-neighbour fingerprint cosine"),
                                use_container_width=True)
            with c2:
                st.altair_chart(_cloud_scatter(
                    [{"id": p["id"], "x": p["x"], "y": p["y"],
                      "snippet": ", ".join(p["features"]) or "(no tics/moves)"}
                     for p in fp["points"]]), use_container_width=True)

    if title.startswith("Reasoning-composition"):
        rc = report.get("reason_composition") or {}
        pt = (rc.get("pipeline") or {})
        if pt.get("points"):
            st.caption("Each response's mix of reason TYPES as a point (2-D PCA); dots that "
                       "overlap reason in the same shape. Bars: mean share of each reason type "
                       "(which reasoning moves the corpus leans on, and which are thin).")
            share = (pt.get("mean_share") or {})
            bar_rows = [{"reason type": t, "mean share": share[t]}
                        for t in (rc.get("types") or []) if share.get(t)]
            c1, c2 = st.columns(2)
            with c1:
                if bar_rows:
                    st.altair_chart(alt.Chart(pd.DataFrame(bar_rows)).mark_bar(
                        color="#4C78A8").encode(
                        x=alt.X("mean share:Q", axis=alt.Axis(format="%")),
                        y=alt.Y("reason type:N", sort="-x", title=""),
                        tooltip=["reason type", alt.Tooltip("mean share:Q", format=".0%")],
                    ).properties(height=210), use_container_width=True)
            with c2:
                st.altair_chart(_cloud_scatter(
                    [{"id": p["id"], "x": p["x"], "y": p["y"],
                      "snippet": ", ".join(f"{k} {v:.0%}" for k, v in (p.get("comp") or {}).items())}
                     for p in pt["points"]]), use_container_width=True)

    if not suppress_detail:
        for line in section.get("detail", []):
            st.caption(line)


# --- Dataset usefulness cluster (top): Important considerations (above) → its
# detailed subsets, all measured on the RESPONSES (final assistant replies):
# welfare considerations (the reasons pass) + humane alternatives, then the
# reasoning-composition mix. Section renamed 2026-07-23; match both the new and
# legacy titles so old reports still render richly. ---
_REASONS_TITLES = ("Welfare considerations", "Moral-patient reasons")

st.subheader("Response detail — pipeline vs plain Claude")
st.caption("The breakdown behind the headline, all measured on the **final responses**: the "
           "welfare considerations they raise, the humane alternatives they weigh, and the mix "
           "of reasoning types they draw on.")

reasons_section = next((s for s in sections
                        if s.get("title", "").startswith(_REASONS_TITLES)), None)
if reasons_section:
    _render_reasons_section(reasons_section)
elif "moral_patient_reasons" not in report:
    st.caption("Welfare-consideration extraction hasn't run for this report — add it "
               "(costs API calls) with:")
    st.code(f"{cmd} --reasons", language="bash")

for section in sections:
    if section.get("title", "").startswith("Humane alternatives"):
        _render_alternatives_section(section)

# Reasoning-composition diversity sits below the two detailed subsets (it reads
# the same reasons, sliced by type).
composition_section = next((s for s in sections
                            if s.get("title", "").startswith("Reasoning-composition")), None)
if composition_section:
    _render_section(composition_section)

# --- Semantic diversity (embeddings) — a separate report file, rendered when
# evals/diversity.py has run on this run dir. Sits with the usefulness cluster,
# above the Health check tail. The lexical sections point here for topic/meaning
# diversity.
diversity = loader.load_diversity(run.run_dir)
if diversity is None:
    st.caption("No semantic diversity report yet — generate it (embedding cents) with:")
    st.code(f"python evals/diversity.py --input {run.run_dir} --ideas", language="bash")
else:
    st.header("Semantic diversity (embeddings)")
    st.caption("**What this measures: topic/meaning diversity** — are the documents *about "
               "different things*? Similarity here is **embedding cosine** (meaning), so two "
               "records count as alike when they cover the same subject even in different words. "
               "It is largely set by the scenarios dealt at step 1a and is ≈fixed no matter how "
               "the text is phrased.")
    st.caption("**Not** the same as the other diversity views: *wording/surface* variety lives "
               "in the **Lexical diversity** sections (Health check), and *argument-structure* "
               "variety lives in **Rhetorical moves**. This one is purely about subject matter.")
    st.caption(f"model `{diversity.get('embed_model')}` · numbers are only comparable "
               "across runs using the same embedding model")
    for section in diversity.get("sections") or []:
        st.subheader(section.get("title", ""))
        _section_table(section)
        for line in section.get("detail", []):
            st.caption(line)

    scopes = diversity.get("scopes") or {}
    scope_order = [("prompts", "Prompts (user messages)"),
                   ("responses", "Responses (assistant messages)"),
                   ("combined", "Combined (user + assistant)"
                    if len(scopes) > 1 else "Documents")]
    shown = [(k, label) for k, label in scope_order if k in scopes]
    if shown:
        st.subheader("Diversity charts by scope")
        st.caption("Measured separately on the **prompts** (user dilemmas, P-####), the "
                   "**responses** (assistant replies, R-####), and the **combined** record "
                   "(E-####) — so you can see whether it's the questions or the answers that "
                   "repeat. Each row: nearest-neighbour redundancy (dashed line = the >0.90 "
                   "near-dup threshold) · topic spread (sorted cluster sizes) · a 2-D PCA cloud "
                   "(hover a dot for its record and text).")
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

# --- Health check (everything else): the overview table, batch totals, the
# stance/moralizing tripwire, then the bucketed prompt/response/library checks.
# These catch drift; they are not the dataset's usefulness story above. ---
st.header("Health check")
st.caption("Drift and quality tripwires — read for regressions across runs, not as targets.")
_render_health_overview()
for section in sections:
    if section.get("title", "").startswith("Response stance"):
        _render_section(section)

# _NOT_DISPLAYED sections are deliberately hidden (still measured — report JSON
# and terminal keep them). The usefulness cluster + stance are rendered above.
_SKIP_SECTIONS = (("Important considerations",) + _REASONS_TITLES
                  + _PAID_COMPANIONS + _NOT_DISPLAYED)
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

for group in rendering.AUDIT_GROUP_ORDER:
    group_sections = _by_group.get(group) or []
    if not group_sections:
        continue
    st.header(_GROUP_HEADERS[group])
    for section in group_sections:
        _render_section(section)

common.json_block(report, f"audit_{run.run_id}", "Raw report JSON")
