"""Batch-judge a whole DAD run from the viewer: narrow by filters, pick a subset,
see a live count + rough cost, then run the panel with progress/stop/resume — writing
verdicts in the same final/judge/<rubric_version>/ layout as evals/score_dad.py.

The judging engine, prompt manifest, summary and one-row-per-record invariant are all
borrowed from evals.score_dad / evals.judge so saved-verdict browsing, the run list and
report_dad keep working unchanged. DAD only for v1.
"""

import hashlib
import json
import sys
import types
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evals import holistic_dad, judge, score_dad, selection
from evals.holistic import fields as fields_mod
from shared import api, utils
from viewer import loader
from viewer.ui_pages import common, judge_dad

RUBRIC_PATH = judge.DEFAULT_RUBRIC_PATH
SECONDS_PER_CALL = 7  # rough wall-clock per judge call, for the time estimate
OUT_TOKENS_EST = 4000  # thinking judges spend most of max_tokens on thoughts; rough


# ---------------------------------------------------------------- pure logic
# (filtering + subset picking live in evals/selection.py, shared with the CLIs)

def row_models(row: dict) -> set[str]:
    return {r["model"] for r in (row.get("panel") or {}).get("results", [])}


def selection_rows(finals: list[dict], index: dict, saved_by_id: dict) -> list[dict]:
    """One facet row per final record (in finals order) for selection.filter_records:
    the combined-index facets plus the computed ``prev_verdict`` status facet (which
    deliberately wins over a like-named extraction axis — don't name an axis that)."""
    return [{**index.get(rec["record_id"], {"record_id": rec["record_id"]}),
             "prev_verdict": loader.verdict_status(saved_by_id.get(rec["record_id"]))}
            for rec in finals]


def needs_judging(row: dict | None, selected_models: list[str], rejudge: bool) -> bool:
    """A record is 'already judged' iff a row exists and the selected models are all
    present in it. Re-judge forces judging regardless."""
    if rejudge or row is None:
        return True
    return not set(selected_models).issubset(row_models(row))


def merge_results(old_results: list[dict], new_results: list[dict],
                  selected_models: list[str]) -> list[dict]:
    """Keep old results for models NOT in the selected panel; take fresh results for
    the selected models. Preserves the previous panel's other-model verdicts."""
    sel = set(selected_models)
    return [r for r in old_results if r["model"] not in sel] + new_results


def upsert_row(rows: list[dict], new_row: dict) -> list[dict]:
    """Replace the row for this record_id in place, or append if new. Keeps the
    one-row-per-record_id invariant summarize() and the done-set depend on."""
    for i, r in enumerate(rows):
        if r["record_id"] == new_row["record_id"]:
            rows[i] = new_row
            return rows
    rows.append(new_row)
    return rows


def estimate_cost(n_records: int, models: list[str], pricing: dict,
                  in_tokens: int, out_tokens: int) -> float:
    """Rough API cost: n_records × per-model (in·rate + out·rate). Unpriced models
    fall back to Sonnet rates (matches shared.api._log_usage)."""
    total = 0.0
    for m in models:
        pin, pout = pricing.get(m, (3.00, 15.00))
        total += n_records * (in_tokens / 1e6 * pin + out_tokens / 1e6 * pout)
    return total


# ---------------------------------------------------------------- judging

@st.cache_resource
def _api_ready() -> bool:
    api.init(str(loader.REPO_ROOT / "config.yaml"))
    return True


def _atomic_save_jsonl(rows: list[dict], path: Path) -> None:
    """Write via a temp file + rename so a mid-write failure can't truncate the only
    verdict file (the whole file is rewritten after every record)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    utils.save_jsonl(rows, tmp)
    tmp.replace(path)


def _judge_one(batch: dict, rec: dict, rubric: dict, principles: list[dict],
               prompt_md5: str, annotations: dict, verdicts_path: Path) -> str:
    """Judge one record, merge/replace its row, persist, and return pass|fail|error."""
    models = batch["models"]
    rows = utils.load_jsonl(verdicts_path)
    existing = next((r for r in rows if r["record_id"] == rec["record_id"]), None)

    fresh = judge.panel_judge(rec["messages"], models, rubric, principles)
    if existing and not batch["rejudge"]:
        merged = merge_results(existing["panel"]["results"], fresh["results"], models)
        cons = judge.consensus(merged, rubric)
        panel = {**cons, "results": merged, "response_words": fresh["response_words"]}
    else:
        panel = fresh

    row = {"record_id": rec["record_id"], "rubric_version": rubric["version"],
           "prompt_md5": prompt_md5, "panel": panel}
    upstream = annotations.get(rec["record_id"])
    if upstream:
        first = next((r["verdict"] for r in panel["results"] if r.get("verdict")), None)
        if first:
            row["annotation_comparison"] = judge.compare_annotation(first, upstream)

    rows = upsert_row(rows, row)
    _atomic_save_jsonl(rows, verdicts_path)
    all_models = sorted({r["model"] for row_ in rows for r in row_["panel"]["results"]})
    report = score_dad.summarize(rows, all_models, rubric)
    (verdicts_path.parent / "summary.json").write_text(json.dumps(report, indent=2))

    if panel.get("judge_error"):
        return "error"
    return "pass" if panel["consensus_aggregate"]["passing"] else "fail"


def _run_batch_step(run: loader.RunInfo) -> None:
    """Judge exactly one queued record, then rerun. Stop is checked between records."""
    batch = st.session_state.judge_batch_state
    rubric = judge.load_rubric(RUBRIC_PATH)
    principles = judge.load_principles()
    out_dir = Path(run.run_dir) / "final" / "judge" / rubric["version"]
    verdicts_path = out_dir / "verdicts.jsonl"
    corpus = Path(run.run_dir) / "final" / "dad_corpus.jsonl"
    annotations = judge.find_annotations(corpus)
    finals = {r["record_id"]: r for r in loader.load_final(run.run_dir, "dad")}

    rid = batch["queue"][0]
    outcome = _judge_one(batch, finals[rid], rubric, principles,
                         batch["prompt_md5"], annotations, verdicts_path)
    batch["tally"][outcome] += 1
    batch["done"] += 1
    batch["queue"].pop(0)
    if not batch["queue"]:
        batch["running"] = False
    st.rerun()


# ---------------------------------------------------------------- UI

def _handpick_table(finals: list[dict], index: dict, saved_by_id: dict,
                    ids: list[str], facets: list[str]) -> list[str]:
    by_id = {r["record_id"]: r for r in finals}

    def cell(rid: str, facet: str) -> str:
        val = (index.get(rid) or {}).get(facet)
        if isinstance(val, list):
            return ", ".join(str(v) for v in val)
        return "" if val is None else str(val)

    verdict_label = {"passed": "pass", "failed": "fail", "error": "error"}
    df = pd.DataFrame([{
        "record": common.doc_title(by_id[i]["messages"][0]["content"] if by_id[i].get("messages") else ""),
        "injection": (index.get(i) or {}).get("injection_used", "?"),
        "last verdict": verdict_label.get(
            loader.verdict_status(saved_by_id.get(i)), "—"),
        **{f: cell(i, f) for f in facets},
    } for i in ids])
    event = st.dataframe(df, width="stretch", hide_index=True,
                         on_select="rerun", selection_mode="multi-row",
                         key="handpick_table")
    return [ids[i] for i in event.selection.rows]


def render() -> None:
    st.caption("Batch-judge a DAD run: narrow, pick a subset, run the panel. Verdicts "
               "save to `final/judge/<rubric_version>/` as they finish — safe to close "
               "and resume. Uses the **saved** rubric file (edit it in the DAD tab first).")

    runs = [r for r in loader.list_runs() if r.pipeline == "dad"]
    if not runs:
        st.info("No DAD runs found under outputs/.")
        return

    run_ids = [r.run_id for r in runs]
    qp_run = st.query_params.get("run")
    run_id = st.selectbox("Run", run_ids,
                          index=run_ids.index(qp_run) if qp_run in run_ids else 0,
                          key="batch_run")
    st.query_params["pipeline"] = "dad"
    st.query_params["run"] = run_id
    run = next(r for r in runs if r.run_id == run_id)

    finals = loader.load_final(run.run_dir, "dad")
    if not finals:
        st.info("This run has no final records.")
        return
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

        bundle_id = st.selectbox("Tag bundle (facet source)", ids,
                                 index=ids.index(default), key="batch_bundle",
                                 format_func=_bundle_label)
        st.caption("The facet filters below read this **bundle**'s tag index — one "
                   "tagging pass keyed by its exact axes + model + prompt (build "
                   "bundles on the *Run diversity* page). The default is *latest*, "
                   "the most recently tagged one; *legacy* is a pre-bundle flat "
                   "index with no recorded provenance.")
    index = loader.combined_index(run.run_dir, bundle_id)

    try:
        rubric = judge.load_rubric(RUBRIC_PATH)
    except Exception as e:  # noqa: BLE001 — surface a bad rubric instead of crashing
        st.error(f"Could not load rubric {RUBRIC_PATH.name}: {e}")
        return

    # Skip logic must only see rows judged under THIS rubric version — judge_verdicts
    # returns every version's rows, and a record judged under an older rubric still
    # needs judging under the current one (its verdicts live in a different dir).
    saved_by_id = {row["record_id"]: row for row in loader.judge_verdicts(run.run_dir)
                   if row.get("_rubric_dir") == rubric["version"]}

    c1, c2 = st.columns([2, 3])
    c1.markdown(f"**{run.run_id}** · dad · {len(finals)} records · rubric "
                f"`{rubric.get('version', '?')}`")
    models = c2.multiselect(
        "Judge panel", judge_dad.KNOWN_MODELS, default=["gemini-3.1-pro-preview"],
        accept_new_options=True, key="batch_models",
        help="Mix providers freely: gemini-* judges use GEMINI_API_KEY (or Vertex), claude-* "
             "use ANTHROPIC_API_KEY. Each model routes to its own key and they're scored "
             "together into one consensus; a model whose key is missing just errors while the "
             "rest still score.")

    # ------------------------------------------------ 1 · narrow (optional)
    st.markdown("**1 · Narrow (optional)**")
    n1, n2 = st.columns(2)
    injections = sorted({row.get("injection_used", "") for row in index.values()
                         if row.get("injection_used")})
    inj_filter = n1.multiselect(
        "Injection (from step 6)", injections, placeholder="All injections", key="batch_inj",
        help="The DAD sampling condition (conglomerate / deference / transparency / plain) "
             "that shaped each draft. It's stripped from the final record, but step 6 logs "
             "which one produced it — pick some to judge only those records.")
    prev_verdict = n2.radio("Previous verdict",
                            ["All", "not-yet-judged", "failed", "passed", "error"],
                            horizontal=True, key="batch_prev")

    where: dict = {}
    if inj_filter:
        where["injection_used"] = inj_filter
    if prev_verdict != "All":
        where["prev_verdict"] = {prev_verdict}

    # facet axes from the extraction schema (edit evals/dad_axes.yaml to change),
    # narrowed to values the tag index actually observed
    try:
        facet_names = fields_mod.load_fields(holistic_dad.DEFAULT_AXES).names()
    except Exception as e:  # noqa: BLE001 — a bad schema disables facets, not the page
        facet_names = []
        st.caption(f"Facet schema unavailable ({e}).")
    observed = {f: c for f, c in
                loader.facet_options(list(index.values()), facet_names).items() if c}
    if observed:
        with st.expander(f"Facets from the tag index ({len(observed)} axes)"):
            cols = st.columns(3)
            for i, (facet, counts) in enumerate(observed.items()):
                sel = cols[i % 3].multiselect(
                    facet, list(counts), placeholder="All", key=f"batch_facet_{facet}",
                    format_func=lambda v, c=counts: f"{v} ({c[v]})")
                if sel:
                    where[facet] = sel
    elif facet_names:
        st.caption("No tag index yet — build it with `python evals/holistic_dad.py "
                   "--input <run> --extract-only` (or the Run diversity page) to "
                   "filter by facet here.")

    rows = selection_rows(finals, index, saved_by_id)
    matched = [r["record_id"] for r in selection.filter_records(rows, where)]
    st.caption(f"Matches **{len(matched)}** of {len(finals)} records.")
    if not matched:
        return

    # ------------------------------------------------ 2 · pick from the matches
    st.markdown("**2 · Pick from the matches**")
    mode = st.radio("Pick mode", ["All", "First N", "Range", "Random N", "Hand-pick"],
                    horizontal=True, key="batch_mode")
    kwargs: dict = {}
    if mode == "First N":
        kwargs["n"] = st.number_input("N", 1, len(matched), min(10, len(matched)),
                                      key="batch_firstn")
    elif mode == "Range":
        r1, r2 = st.columns(2)
        kwargs["start"] = r1.number_input("From (1-based)", 1, len(matched), 1, key="batch_from")
        kwargs["end"] = r2.number_input("To (inclusive)", kwargs["start"], len(matched),
                                        max(kwargs["start"], min(10, len(matched))),
                                        key="batch_to")
    elif mode == "Random N":
        rc1, rc2 = st.columns(2)
        kwargs["n"] = rc1.number_input("N", 1, len(matched), min(10, len(matched)),
                                       key="batch_randn")
        kwargs["seed"] = rc2.number_input("Seed", 0, 10_000, 0, key="batch_seed")
    elif mode == "Hand-pick":
        kwargs["handpicked"] = _handpick_table(finals, index, saved_by_id, matched,
                                               list(observed))

    picked = selection.pick_subset(matched, mode, **kwargs)

    # ------------------------------------------------ scope summary + cost
    to_judge = [i for i in picked
                if needs_judging(saved_by_id.get(i), models, st.session_state.get("batch_rejudge", False))]
    skipped = len(picked) - len(to_judge)
    n_calls = len(to_judge) * len(models)
    system_prompt = judge.build_system_prompt(rubric, judge.load_principles())
    in_tok = len(system_prompt) // 4 + 1000
    cost = estimate_cost(len(to_judge), models, api._PRICING, in_tok, OUT_TOKENS_EST)
    # panel_judge runs a record's models concurrently, so wall-clock ~= one call per record
    mins = len(to_judge) * SECONDS_PER_CALL / 60

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Will judge", len(to_judge))
    m2.metric("Already judged · skipped", skipped)
    m3.metric("API calls", n_calls)
    m4.metric("Est. cost · time", f"${cost:.2f}", f"~{mins:.0f} min", delta_color="off")
    st.caption("Rough API estimate.")

    st.checkbox("Re-judge already-judged records (replace their rows)", key="batch_rejudge")

    running = st.session_state.get("judge_batch_state", {}).get("running")
    start = st.button(":material/gavel: Start", type="primary",
                      disabled=running or not (to_judge and models))
    if start:
        _api_ready()
        out_dir = Path(run.run_dir) / "final" / "judge" / rubric["version"]
        out_dir.mkdir(parents=True, exist_ok=True)
        prompt_md5 = hashlib.md5(system_prompt.encode()).hexdigest()
        score_dad._record_prompt_manifest(
            out_dir, prompt_md5, system_prompt, rubric,
            types.SimpleNamespace(rubric=str(RUBRIC_PATH), judges=models, temperature=0.0))
        st.session_state.judge_batch_state = {
            "run_id": run.run_id, "queue": list(to_judge), "total": len(to_judge),
            "done": 0, "models": models, "rejudge": st.session_state.get("batch_rejudge", False),
            "prompt_md5": prompt_md5, "tally": {"pass": 0, "fail": 0, "error": 0},
            "running": True,
        }
        st.rerun()

    _render_running(run)


def _render_running(run: loader.RunInfo) -> None:
    batch = st.session_state.get("judge_batch_state")
    if not batch or batch["run_id"] != run.run_id:
        return

    done, total, t = batch["done"], batch["total"], batch["tally"]
    with st.container(border=True):
        st.progress(done / total if total else 1.0,
                    text=f"{done} / {total} judged")
        s1, s2, s3 = st.columns(3)
        s1.metric("pass", t["pass"])
        s2.metric("fail", t["fail"])
        s3.metric("error", t["error"])
        if batch["running"] and batch["queue"]:
            st.caption(f"Judging `{batch['queue'][0][:12]}`… verdicts save as they finish.")
            if st.button(":material/stop: Stop"):
                batch["running"] = False
                st.rerun()
        elif batch["running"]:
            batch["running"] = False
        else:
            st.success(f"Done — {done} judged ({t['pass']} pass · {t['fail']} fail · "
                       f"{t['error']} error). Written to final/judge/.")
            if st.button("Clear"):
                del st.session_state.judge_batch_state
                st.rerun()

    if batch["running"] and batch["queue"]:
        _run_batch_step(run)
