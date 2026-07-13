"""Run diversity page (spec §12.2): pick a DAD run, browse its holistic
categorical-diversity report, and build/refresh the extraction tag index — the same
index that powers the facet filters in Judge → "Score a run". Rendering only: the
engine, schema, and prompts are evals/holistic_dad.py and its editable files."""

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evals import holistic_dad
from evals.holistic import analyzers as analyzers_mod
from evals.holistic import bundle
from evals.holistic import fields as fields_mod
from evals.holistic import pipeline
from shared import api
from viewer import loader
from viewer.ui_pages import judge_dad

st.title("Run diversity")
st.caption("Categorical diversity of one DAD run: tag records with their axes "
           "(`evals/dad_axes.yaml`), then browse the analyzer report. Tagging is "
           "resume-safe (1 cheap call per untagged record); analysis is free except "
           "the one LLM synthesis call. Every tagging pass lands in a provenance "
           "bundle, so results from different axes/models sit side-by-side and are "
           "never overwritten.")

runs = [r for r in loader.list_runs() if r.pipeline == "dad"]
if not runs:
    st.info("No DAD runs found under outputs/.")
    st.stop()

run_ids = [r.run_id for r in runs]
qp_run = st.query_params.get("run")
run_id = st.selectbox("Run", run_ids,
                      index=run_ids.index(qp_run) if qp_run in run_ids else 0,
                      key="diversity_run")
st.query_params["pipeline"] = "dad"
st.query_params["run"] = run_id
run = next(r for r in runs if r.run_id == run_id)

bundles = loader.list_bundles(run.run_dir)
bundle_id = None
if bundles:
    infos = {b.bundle_id: b for b in bundles}
    ids = list(infos)
    default = loader.latest_bundle_id(run.run_dir)
    default = default if default in infos else ids[0]

    def _bundle_label(bid: str) -> str:
        if bid == "legacy":
            return "legacy (pre-bundle flat index)"
        m = infos[bid].manifest
        return (f"{bid} · {m.get('model') or 'config default'} · "
                f"{m.get('records_tagged', '?')} tagged")

    bundle_id = st.selectbox("Bundle", ids, index=ids.index(default),
                             key="diversity_bundle", format_func=_bundle_label)
    st.caption("Each **bundle** is one tagging pass, keyed by its exact axes + "
               "model + extraction prompt. Pick one to view its tags and report "
               "side-by-side with other variants; the default is *latest* — the "
               "most recently tagged one.")
    if bundle_id == "legacy":
        st.caption(":material/history: This is the **pre-bundle flat index** "
                   "(`audit/category_records.jsonl`) — it has no recorded "
                   "provenance. The next **Tag** creates the first real bundle; "
                   "its tags stay untouched, though **Analyze** still rewrites "
                   "`audit/holistic_dad_report.json` in place.")
    else:
        m = infos[bundle_id].manifest
        st.caption(f"model `{m.get('model') or 'config default'}` · created "
                   f"{m.get('created_at', '?')} · {m.get('records_tagged', '?')} "
                   f"tagged · commit `{m.get('git_commit') or '—'}`")

n_final = run.counts.get("final", 0)
tag_rows = loader.category_records(run.run_dir, bundle_id)
n_tagged = len({r.get("record_id") for r in tag_rows
                if "record_id" in r and "extract_error" not in r})
report = loader.holistic_report(run.run_dir, bundle_id)

m1, m2, m3 = st.columns(3)
m1.metric("Final records", n_final)
m2.metric("Tagged", n_tagged)
m3.metric("Report", "yes" if report else "—")


def _engine():
    """The same wiring as evals/holistic_dad.py main: schema, analyzer selection,
    and editable prompt templates."""
    api.init(str(loader.REPO_ROOT / "config.yaml"))
    fields = holistic_dad._load_fields(holistic_dad.DEFAULT_AXES)
    analysis_cfg = fields_mod.load_analysis_config(holistic_dad.DEFAULT_AXES)
    analyzers = analyzers_mod.select(analyzers_mod.default_analyzers(),
                                     analysis_cfg.get("analyzers"))
    return fields, analysis_cfg, analyzers


# Same picker as the judge pages: known models as options, custom ids accepted.
_CONFIG_DEFAULT = "config default (Claude)"
_model_choice = st.selectbox(
    "Model for tagging + synthesis", [_CONFIG_DEFAULT, *judge_dad.KNOWN_MODELS],
    accept_new_options=True,
    help="gemini-* models use GEMINI_API_KEY (or Vertex); anything else — or the "
         "config default — uses the Anthropic key and the config.yaml model. Cheap "
         "flash-tier models are fine for extraction.")
model = None if _model_choice in (None, _CONFIG_DEFAULT) else _model_choice.strip() or None

b1, b2 = st.columns(2)
b1.caption("**Tag** labels every final conversation with the categorical axes from "
           "`evals/dad_axes.yaml` (taxa, direction, posture, …) — one cheap LLM call "
           "per record. Results go into a **bundle** keyed by the exact axes + model "
           "+ prompt: the same inputs resume their existing bundle (already-tagged "
           "records are skipped — no re-paying), while any change to them starts a "
           "fresh bundle, so old results are never overwritten. The bundle's index "
           "powers the facet filters in *Judge → Score a run* and the analysis below.")
b2.caption("**Analyze** recomputes the diversity report of the **selected bundle** "
           "from its existing tags — distribution, evenness, coverage-vs-target, "
           "correlations, drift — plus one LLM synthesis call. Tags are untouched, "
           "so it's nearly free; rerun it after editing the `analysis:` block or "
           "quota targets. The bundle's manifest records which analysis config "
           "produced the current report.")
# A finished run is a prerequisite: tagging reads final/dad_corpus.jsonl.
if n_final == 0:
    b1.caption(":material/block: This run has **no final corpus** (it stopped "
               "before step 3 completed) — there is nothing to tag. Resume it "
               "with `python dad_pipeline/run.py --config config.yaml --resume "
               f"--run-id {run.run_id}` or pick a finished run above.")

force = b1.checkbox(
    # Keyed per run: a force flag checked for one run must not silently carry
    # over to the next (a full re-tag of a large run is a real bill).
    "Re-tag everything (ignore resume)", key=f"diversity_force_{run.run_id}",
    disabled=n_final == 0,
    help="Discard this bundle's existing tags for the current corpus and pay to "
         "re-tag every record. The normal Tag already retries error rows and picks "
         "up new records for free — only force a full re-tag to measure extraction "
         "consistency, or after a model behavior change that the bundle "
         "fingerprint can't see.")
if force:
    b1.warning(f"Re-tagging will re-bill all {n_final} record(s), replacing this "
               "bundle's existing tags for them. Tags for records outside this "
               "corpus are kept.")

if b1.button(":material/sell: Tag this run", type="primary", disabled=n_final == 0,
             help="Tag into the bundle matching the current axes + model + prompt "
                  "(resume-safe: already-tagged records are skipped, error rows "
                  "are retried; changed inputs start a fresh bundle)."):
    fields, _, _ = _engine()
    inputs = pipeline.resolve_inputs(run.run_dir)
    bar = st.progress(0.0, text=f"Tagging {len(inputs.corpus)} record(s)… "
                                "(resume-safe; rows save as they finish)")

    def _tick(done_n: int, total: int, rid: str) -> None:
        bar.progress(done_n / total, text=f"Tagged {done_n}/{total} — last: `{rid}`"
                                          + ("" if force else
                                             " (already-tagged records are skipped)"))

    try:
        written = pipeline.tag(
            inputs, fields, model=model, on_progress=_tick, resume=not force,
            extract_template=holistic_dad._read_if_exists(holistic_dad.DEFAULT_EXTRACT_PROMPT),
            axes_text=holistic_dad.DEFAULT_AXES.read_text())
    except Exception as e:  # auth/config errors otherwise render as a raw traceback
        bar.empty()
        st.error(f"Tagging stopped: {e}\n\nRows tagged before the failure are saved "
                 "and will be skipped on the next **Tag this run** (see README "
                 "\"Eval API keys\" for GEMINI_API_KEY / VERTEX_PROJECT / "
                 "ANTHROPIC_API_KEY setup; the viewer must be restarted after "
                 "editing `.env`).")
        st.stop()
    bar.empty()
    errors = sum(1 for r in written if "extract_error" in r)
    # Stash the outcome so it survives the rerun below (a bare st.success would
    # vanish instantly, which reads as "nothing happened").
    st.session_state["diversity_tag_result"] = (
        f"Tagged {len(written)} record(s)"
        + (f" — {errors} error row(s), retried on the next Tag" if errors else "")
        + f" → `{inputs.index_path}`"
        + ("" if written else " (everything in this bundle was already tagged)"))
    st.session_state.pop("diversity_bundle", None)   # jump to the bundle just tagged
    st.rerun()

if msg := st.session_state.pop("diversity_tag_result", None):
    st.success(msg)

if b2.button(":material/analytics: Analyze",
             help="Re-run the analyzers + LLM synthesis over the selected bundle's "
                  "existing tags (no re-tagging) and rewrite its report.",
             disabled=not tag_rows):
    fields, analysis_cfg, analyzers = _engine()
    synthesis_template = holistic_dad._read_if_exists(holistic_dad.DEFAULT_SYNTH_PROMPT)
    inputs = pipeline.resolve_inputs(run.run_dir, bundle_id=bundle_id)
    bdir = bundle.bundle_dir_of(inputs.index_path)
    if bdir is not None and bundle.snapshot_fields_differ(bdir, fields):
        st.warning("Analyzing this bundle with the current `evals/dad_axes.yaml`, "
                   "which differs from the bundle's own axes snapshot — the report "
                   "may mix schemas.")
    with st.spinner("Analyzing…"):
        new_report = pipeline.run(
            inputs, fields=fields, analyzers=analyzers, do_tag=False, model=model,
            synthesis_template=synthesis_template,
            config=analysis_cfg.get("params"))
    holistic_dad.write_report(holistic_dad.report_path_for(inputs), new_report)
    holistic_dad.record_bundle_analysis(inputs, analysis_cfg, analyzers, model,
                                        synthesis_template)
    st.rerun()

# ------------------------------------------------- semantic (embedding) lane
# Run-scoped, not bundle-scoped: embeddings read only the corpus text. Rendered
# before the tag-index gating below so it works on an untagged run too.

st.divider()
st.subheader("Semantic diversity (embedding space)")
st.caption("The meaning-space complement to the categorical axes above: embeds the "
           "final corpus with OpenAI `text-embedding-3-small` (needs `OPENAI_API_KEY` "
           "in `.env`; cents per run, cached per run dir) and reports semantic "
           "near-duplicates, the Vendi score (effective number of distinct records), "
           "and k-means topic spread. Its cluster assignments also feed the "
           "categorical×cluster **bridge** analyzer on the next **Analyze**.")

sem = loader.semantic_report(run.run_dir)

from shared import embeddings as embeddings_mod  # noqa: E402  (section-local lane)

local_embed = st.checkbox(
    "Use local embeddings (free — no API key)", key=f"diversity_local_{run.run_id}",
    disabled=n_final == 0,
    help="Runs `sentence-transformers/all-MiniLM-L6-v2` on this machine instead of "
         "the OpenAI API: needs `pip install sentence-transformers`, and the first "
         "use downloads the ~90MB model. Numbers are NOT comparable across embedding "
         "models — the report records which model produced it.")
embed_model = embeddings_mod.DEFAULT_LOCAL_MODEL if local_embed else embeddings_mod.DEFAULT_MODEL

if st.button(":material/scatter_plot: Run embedding audit", disabled=n_final == 0,
             help="Embed the final corpus and (re)write audit/diversity_report.json. "
                  "Embeddings are cached per model in the run dir, so reruns cost "
                  "nothing new."):
    from evals import diversity as diversity_mod
    try:
        if not local_embed:  # the local lane needs no key, no client, no cost log
            embeddings_mod.init(str(loader.REPO_ROOT / "config.yaml"))
        records, type_map, report_dir, corpus_name = diversity_mod.resolve_input(str(run.run_dir))
        with st.spinner(f"Embedding {len(records)} record(s) and computing metrics… "
                        + ("(local model — first use downloads it)" if local_embed else "")):
            diversity_mod.run_audit(records, type_map, report_dir, str(run.run_dir),
                                    corpus_name=corpus_name, embed_model=embed_model)
    except Exception as e:
        st.error(f"Embedding audit failed: {e}\n\n"
                 + ("Local lane: `pip install sentence-transformers` into the viewer's "
                    "venv, then restart the viewer." if local_embed else
                    "Most common cause: `OPENAI_API_KEY` missing from `.env` "
                    "(restart the viewer after adding it)."))
        st.stop()
    st.rerun()

if sem:
    nn = sem.get("nn") or {}
    vendi = sem.get("vendi") or {}
    clusters = sem.get("clusters") or {}
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Vendi (effective docs)",
              f"{vendi.get('score', 0):g} / {sem.get('n_embedded', '?')}",
              help="exp of the similarity-spectrum entropy: N for N orthogonal "
                   "records, 1 for N identical ones. Higher = more distinct.")
    s2.metric("Mean pairwise cosine", f"{sem.get('mean_pairwise_cosine', 0):.3f}",
              help="How tightly the corpus clusters overall — the corpus shares one "
                   "topic by design, so track the trend across runs, not the level.")
    s3.metric("Near-dups (>0.90)", f"{nn.get('over_0.90', 0):.1%}",
              help="Fraction of records whose nearest neighbor is near-verbatim in "
                   "meaning-space. The headline redundancy number.")
    s4.metric("Topic evenness", f"{clusters.get('evenness', 0):.2f}" if clusters else "—",
              help="Pielou evenness of k-means cluster sizes (1 = topics spread "
                   "evenly, 0 = collapse onto a few).")
    verdict_bits = [f"near-dup {nn.get('over_0.90', 0):.1%}"]
    if clusters:
        verdict_bits.append(f"cluster spread **{clusters.get('verdict', '?')}** "
                            f"({clusters.get('clusters', '?')} of k={clusters.get('k', '?')})")
    st.caption(f"model `{sem.get('embed_model', '?')}` · {sem.get('n_embedded', '?')} embedded "
               f"({sem.get('n_empty', 0)} empty skipped) · " + " · ".join(verdict_bits)
               + " · on disk `" + str(Path(run.run_dir).name) + "/audit/diversity_report.json`")
    pairs = sem.get("top_pairs") or []
    if pairs:
        with st.expander(f"Most-similar pairs ({len(pairs)})"):
            st.dataframe(pd.DataFrame([
                {"similarity": p.get("similarity"), "a": p.get("a"), "b": p.get("b"),
                 "a snippet": p.get("a_snippet"), "b snippet": p.get("b_snippet")}
                for p in pairs]), width="stretch", hide_index=True,
                column_config={"similarity": st.column_config.ProgressColumn(
                    "similarity", min_value=0.0, max_value=1.0, format="%.3f")})
    st.download_button(":material/download: Semantic report (JSON)",
                       json.dumps(sem, indent=2, ensure_ascii=False),
                       file_name=f"{run.run_id}_semantic_diversity.json",
                       mime="application/json")
else:
    st.caption("No embedding audit yet for this run — **Run embedding audit** computes "
               "it (equivalent CLI: `python evals/diversity.py --input "
               f"outputs/dad/runs/{run.run_id}`).")

st.divider()


def _download_row(with_report: bool) -> None:
    """Download what exists so far: the tag index, and the report once computed."""
    stem = f"{run.run_id}_{bundle_id or 'latest'}"
    d1, d2 = st.columns(2)
    d1.download_button(
        ":material/download: Tag index (JSONL)",
        "\n".join(json.dumps(r, ensure_ascii=False) for r in tag_rows) + "\n",
        file_name=f"{stem}_tag_index.jsonl", mime="application/jsonl")
    if with_report:
        d2.download_button(
            ":material/download: Diversity report (JSON)",
            json.dumps(report, indent=2, ensure_ascii=False),
            file_name=f"{stem}_diversity_report.json", mime="application/json")
    index_path, report_path = loader._holistic_paths(run.run_dir, bundle_id)
    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(loader.REPO_ROOT))
        except ValueError:
            return str(p)
    st.caption("On disk: tags `" + _rel(index_path) + "`"
               + (" · report `" + _rel(report_path) + "`" if with_report else ""))


if not tag_rows:
    st.info("This bundle has no extraction tag index yet — **Tag this run** builds "
            "one (it also enables the facet filters in Judge → Score a run).")
    st.stop()
if not report:
    st.info("Tag index present but this bundle has no report yet — **Analyze** "
            "computes it.")
    _download_row(with_report=False)
    st.stop()

# ---------------------------------------------------------------- report

st.caption(f"Report over **{report.get('records', '?')}** tagged records · inputs: "
           f"{', '.join(report.get('inputs_present', []))}")
_download_row(with_report=True)
analyses = (report.get("stats") or {}).get("analyses", {})

evenness = analyses.get("evenness", {})
if evenness:
    st.markdown("**Per-axis balance** — richness (distinct values) + Pielou evenness "
                "(1 = spread across values, 0 = one value dominates)")
    st.dataframe(pd.DataFrame([
        {"axis": axis, "richness": m.get("richness"), "n": m.get("n"),
         "evenness": m.get("evenness"), "verdict": m.get("verdict")}
        for axis, m in evenness.items()]),
        width="stretch", hide_index=True,
        column_config={"evenness": st.column_config.ProgressColumn(
            "evenness", min_value=0.0, max_value=1.0, format="%.2f")})

coverage = analyses.get("coverage_vs_target", {})
if coverage:
    st.markdown("**Coverage vs target** — did the run hit its designed mix "
                "(`target:` quotas in the axes file)?")
    st.dataframe(pd.DataFrame([
        {"axis": axis, "n": m.get("n"), "verdict": m.get("verdict"),
         "violations": "; ".join(m.get("violations", []))}
        for axis, m in coverage.items()]), width="stretch", hide_index=True)

correlation = analyses.get("correlation", {})
if correlation:
    st.markdown("**Axis correlations (Cramér's V)** — near 0 is healthy; high V "
                "means one axis predicts the other (attitude × direction = the "
                "sycophancy tell)")
    st.dataframe(pd.DataFrame([
        {"pair": pair, "n": m.get("n"), "cramers_v": m.get("cramers_v"),
         "verdict": m.get("verdict")}
        for pair, m in correlation.items()]),
        width="stretch", hide_index=True,
        column_config={"cramers_v": st.column_config.ProgressColumn(
            "Cramér's V", min_value=0.0, max_value=1.0, format="%.2f")})

bridge = analyses.get("cluster_bridge", {})
if bridge:
    st.markdown("**Categorical × embedding-cluster bridge** — does each axis's "
                "variety show up in meaning-space? Low V = the axis varies on paper "
                "but the text sounds the same (run `evals/diversity.py` to refresh "
                "the clusters)")
    st.dataframe(pd.DataFrame([
        {"axis": axis, "n": m.get("n"), "cramers_v": m.get("cramers_v"),
         "verdict": m.get("verdict")}
        for axis, m in bridge.items()]),
        width="stretch", hide_index=True,
        column_config={"cramers_v": st.column_config.ProgressColumn(
            "Cramér's V", min_value=0.0, max_value=1.0, format="%.2f")})

combos = analyses.get("combination_coverage", {})
if combos:
    st.markdown("**Combination coverage** — designed axis-pair cells that actually occur")
    st.dataframe(pd.DataFrame([
        {"pair": pair, "filled": f"{m.get('filled')}/{m.get('cells')}",
         "coverage": m.get("coverage"), "verdict": m.get("verdict")}
        for pair, m in combos.items()]), width="stretch", hide_index=True)
    missing = {pair: m["missing"] for pair, m in combos.items() if m.get("missing")}
    if missing:
        with st.expander("Missing cells"):
            for pair, cells in missing.items():
                st.markdown(f"**{pair}**: " + ", ".join(f"`{c}`" for c in cells))

drift = analyses.get("drift", {})
if drift:
    st.markdown("**Intent → realization drift** — extraction label vs the generator's "
                "annotation (low agreement = generation drift OR extractor bias; "
                "route to a human)")
    st.dataframe(pd.DataFrame([
        {"axis": axis, "n": m.get("n"), "agreement": m.get("agreement"),
         "verdict": m.get("verdict"),
         "top confusions": "; ".join(
             f"{d['intended']}→{d['realized']} ×{d['count']}"
             for d in m.get("disagreements", [])[:3])}
        for axis, m in drift.items()]), width="stretch", hide_index=True)

synthesis = report.get("synthesis") or {}
if synthesis.get("top_issues"):
    st.markdown("**Top issues** (LLM synthesis over the stats)")
    for issue in synthesis["top_issues"]:
        fix = issue.get("suggested_fix")
        st.markdown(f"- **[{issue.get('severity', '?')}]** "
                    f"`{issue.get('axis', '?')}` — {issue.get('detail', '')}"
                    + (f" *Fix: {fix}*" if fix else ""))
if synthesis.get("prose"):
    with st.expander("Synthesis assessment", expanded=not synthesis.get("top_issues")):
        st.markdown(synthesis["prose"])
if synthesis.get("errors"):
    st.warning("Synthesis errors: " + "; ".join(synthesis["errors"]))

skipped = (report.get("stats") or {}).get("skipped", {})
if skipped:
    st.caption("Skipped analyzers: " +
               "; ".join(f"{name} ({reason})" for name, reason in skipped.items()))
