"""Pure data access for the run viewer. No streamlit imports — reusable from
any frontend (or a future API server)."""

import json
import os
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import utils
from evals.holistic import bundle as _bundle   # pure file I/O, no streamlit

REPO_ROOT = Path(__file__).parent.parent
OUTPUTS_ROOT = Path(os.environ.get("PIPELINE_OUTPUTS_ROOT", REPO_ROOT / "outputs"))

PIPELINES = ("sdf", "dad")

STAGE_FILES = {
    "sdf": {
        "layer1": "layer1/document_types.jsonl",
        "layer2": "layer2/subtypes.jsonl",
        "layer3": "layer3/drafts.jsonl",
        "layer4": "layer4/rewrites.jsonl",
        "layer5": "layer5/scores.jsonl",
        "final": "final/sdf_corpus.jsonl",
    },
    "dad": {
        "step1": "step1/principles.jsonl",
        "step2": "step2/scenarios.jsonl",
        "step3": "step3/prompts.jsonl",
        "step4": "step4/refined_prompts.jsonl",
        "step5": "step5/responses.jsonl",
        "step6": "step6/rewrites.jsonl",
        "step7": "step7/pushbacks.jsonl",
        "final": "final/dad_corpus.jsonl",
    },
}


@dataclass
class RunInfo:
    pipeline: str
    run_id: str
    run_dir: Path
    label: str | None
    model: str | None
    created_at: str | None
    git_commit: str | None
    git_dirty: bool | None  # None = pre-v2 manifest (unknown)
    has_snapshot: bool
    config: dict
    counts: dict[str, int] = field(default_factory=dict)
    pass_rate: float | None = None
    judge_pass_rate: float | None = None
    total_cost: float = 0.0


@lru_cache(maxsize=512)
def _cached_jsonl(path_str: str, mtime: float) -> tuple:
    return tuple(utils.load_jsonl(path_str))


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return list(_cached_jsonl(str(path), path.stat().st_mtime))


def load_manifest(run_dir: Path) -> dict:
    path = Path(run_dir) / "run_manifest.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def load_stage(run_dir: Path, pipeline: str, stage: str) -> list[dict]:
    rel = STAGE_FILES[pipeline].get(stage)
    if rel is None:
        return []
    return _load_jsonl(Path(run_dir) / rel)


def load_final(run_dir: Path, pipeline: str) -> list[dict]:
    return load_stage(run_dir, pipeline, "final")


def total_cost(run_dir: Path) -> float:
    total = 0.0
    for rec in _load_jsonl(Path(run_dir) / "cost_log.jsonl"):
        total += rec.get("cost_usd", 0.0)
    return round(total, 4)


def _pass_rate(run_dir: Path, pipeline: str) -> float | None:
    if pipeline == "sdf":
        scored = load_stage(run_dir, pipeline, "layer5")
        final = load_final(run_dir, pipeline)
        return len(final) / len(scored) if scored else None
    responses = load_stage(run_dir, pipeline, "step5")
    if not responses:
        return None
    return sum(1 for r in responses if r.get("kept")) / len(responses)


def list_bundles(run_dir: Path) -> list[_bundle.BundleInfo]:
    """Provenance bundles for a run's holistic lane, newest first — including the
    implicit read-only 'legacy' entry for pre-bundle flat results."""
    run_dir = Path(run_dir)
    return _bundle.list_bundles(run_dir / "holistic",
                                run_dir / "audit" / "category_records.jsonl")


def latest_bundle_id(run_dir: Path) -> str | None:
    """The bundle the run's `latest` symlink points at (the most recent Tag)."""
    return _bundle.latest_bundle_id(Path(run_dir) / "holistic")


def _holistic_paths(run_dir: Path, bundle_id: str | None) -> tuple[Path, Path]:
    """(index_path, report_path) for the chosen bundle. None = latest bundle,
    falling back to the legacy flat files; 'legacy' forces the flat files. An
    explicit bundle id resolves inside holistic/ only — a missing (or
    path-shaped) id reads as empty rather than borrowing the legacy report."""
    run_dir = Path(run_dir)
    root = run_dir / "holistic"
    flat_index = run_dir / "audit" / "category_records.jsonl"
    flat_report = run_dir / "audit" / "holistic_dad_report.json"
    if bundle_id == _bundle.LEGACY_ID:
        return flat_index, flat_report
    if bundle_id is not None:
        if Path(bundle_id).name != bundle_id:
            bundle_id = "__invalid__"
        index = root / bundle_id / _bundle.INDEX_NAME
        return index, index.parent / _bundle.REPORT_NAME
    index = _bundle.reading_index_path(root, flat_index)
    if _bundle.bundle_dir_of(index):
        return index, index.parent / _bundle.REPORT_NAME
    return index, flat_report


def category_records(run_dir: Path, bundle_id: str | None = None) -> list[dict]:
    """The extraction tag index rows for the chosen bundle (None = latest, legacy
    flat fallback), or [] when the run has not been tagged."""
    index_path, _ = _holistic_paths(run_dir, bundle_id)
    return _load_jsonl(index_path)


def holistic_report(run_dir: Path, bundle_id: str | None = None) -> dict | None:
    """The chosen bundle's analyzer report, or None."""
    _, report_path = _holistic_paths(run_dir, bundle_id)
    if not report_path.exists():
        return None
    with open(report_path) as f:
        return json.load(f)


# extraction bookkeeping, not categorical facets
_TAG_META_KEYS = ("record_id", "extract_error", "_errors")


def combined_index(run_dir: Path, bundle_id: str | None = None) -> dict[str, dict]:
    """record_id -> combined facet row for selection (spec §12.1): realized
    extraction tags (any axis) overlaid on the legacy ``injection_used`` from the
    step3/step6 rewrite annotations. Spec-driven ``.annotation`` intent labels are
    deliberately NOT facets — only what the finished text realized is.
    ``bundle_id`` picks which tag bundle supplies the facets (None = latest)."""
    run_dir = Path(run_dir)
    idx: dict[str, dict] = {}
    for stage in ("step3", "step6"):
        for ann in _load_jsonl(run_dir / stage / "rewrites.jsonl"):
            rid = ann.get("record_id")
            if rid is None or not ann.get("injection_used"):
                continue
            idx.setdefault(rid, {"record_id": rid})["injection_used"] = ann["injection_used"]
    for tag in category_records(run_dir, bundle_id):
        rid = tag.get("record_id")
        if rid is None:
            continue
        row = idx.setdefault(rid, {"record_id": rid})
        row.update({k: v for k, v in tag.items() if k not in _TAG_META_KEYS})
    return idx


def facet_options(rows: list[dict], facets: list[str]) -> dict[str, dict]:
    """Per-facet observed value counts (most-common first) over combined-index rows.
    List values count once per element; non-categorical values are skipped."""
    out: dict[str, dict] = {}
    for facet in facets:
        counts: dict = {}
        for row in rows:
            val = row.get(facet)
            vals = [x for x in val if isinstance(x, (str, int, bool))] \
                if isinstance(val, list) else \
                [val] if isinstance(val, (str, int, bool)) else []
            for v in vals:
                counts[v] = counts.get(v, 0) + 1
        out[facet] = dict(sorted(counts.items(), key=lambda kv: -kv[1]))
    return out


def verdict_status(row: dict | None) -> str:
    """A saved judge-verdict row's status facet: not-yet-judged | passed | failed |
    error (a row whose panel reached no consensus, e.g. every judge errored)."""
    if row is None:
        return "not-yet-judged"
    passing = ((row.get("panel") or {}).get("consensus_aggregate") or {}).get("passing")
    if passing is True:
        return "passed"
    if passing is False:
        return "failed"
    return "error"


def judge_verdicts(run_dir: Path) -> list[dict]:
    """All saved judge verdict rows for a run (written by evals/score_dad.py to
    final/judge/<rubric_version>/verdicts.jsonl), tagged with their rubric dir."""
    rows = []
    judge_root = Path(run_dir) / "final" / "judge"
    if judge_root.is_dir():
        for vfile in sorted(judge_root.glob("*/verdicts.jsonl")):
            for row in _load_jsonl(vfile):
                rows.append({**row, "_rubric_dir": vfile.parent.name})
    return rows


def judge_pass_rate(run_dir: Path) -> float | None:
    """Consensus pass rate from the newest rubric version's judge summary, if scored."""
    summaries = sorted((Path(run_dir) / "final" / "judge").glob("*/summary.json"))
    if not summaries:
        return None
    try:
        with open(summaries[-1]) as f:
            report = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return (report.get("consensus") or {}).get("pass_rate")


def list_runs(outputs_root: Path = OUTPUTS_ROOT) -> list[RunInfo]:
    """All runs across both pipelines, newest first. A run is a non-symlink
    directory under outputs/<pipeline>/runs/ containing run_manifest.json."""
    runs = []
    for pipeline in PIPELINES:
        runs_root = Path(outputs_root) / pipeline / "runs"
        if not runs_root.is_dir():
            continue
        for d in sorted(runs_root.iterdir(), reverse=True):
            if d.is_symlink() or not d.is_dir():
                continue
            manifest = load_manifest(d)
            if not manifest:
                continue
            counts = {
                stage: len(load_stage(d, pipeline, stage))
                for stage in STAGE_FILES[pipeline]
            }
            runs.append(RunInfo(
                pipeline=pipeline,
                run_id=d.name,
                run_dir=d,
                label=manifest.get("label"),
                model=manifest.get("model"),
                created_at=manifest.get("created_at"),
                git_commit=manifest.get("git_commit"),
                git_dirty=manifest.get("git_dirty"),
                has_snapshot=(d / "inputs" / "prompts").is_dir(),
                config=manifest.get("config", {}),
                counts=counts,
                pass_rate=_pass_rate(d, pipeline),
                judge_pass_rate=judge_pass_rate(d),
                total_cost=total_cost(d),
            ))
    return runs


def get_run(pipeline: str, run_id: str, outputs_root: Path = OUTPUTS_ROOT) -> RunInfo | None:
    for run in list_runs(outputs_root):
        if run.pipeline == pipeline and run.run_id == run_id:
            return run
    return None


def _index(records: list[dict], key: str) -> dict:
    return {r[key]: r for r in records if key in r}


def sdf_lineage(run_dir: Path, doc_id: str) -> dict:
    """Full lineage for one SDF document. Values are None when a stage was
    not reached or the join key is missing."""
    drafts = _index(load_stage(run_dir, "sdf", "layer3"), "doc_id")
    rewrites = _index(load_stage(run_dir, "sdf", "layer4"), "doc_id")
    scores = _index(load_stage(run_dir, "sdf", "layer5"), "doc_id")
    finals = _index(load_final(run_dir, "sdf"), "doc_id")

    draft = drafts.get(doc_id)
    anchor = draft or rewrites.get(doc_id) or scores.get(doc_id) or finals.get(doc_id) or {}
    subtypes = _index(load_stage(run_dir, "sdf", "layer2"), "subtype_id")
    doc_types = _index(load_stage(run_dir, "sdf", "layer1"), "type_id")

    return {
        "doc_type": doc_types.get(anchor.get("type_id")),
        "subtype": subtypes.get(anchor.get("subtype_id")),
        "draft": draft,
        "rewrite": rewrites.get(doc_id),
        "score": scores.get(doc_id),
        "final": finals.get(doc_id),
    }


def dad_lineage(run_dir: Path, record_id: str) -> dict:
    """Full lineage for one DAD training record (keyed by final record_id)."""
    audits = _index(load_stage(run_dir, "dad", "step6"), "record_id")
    audit = audits.get(record_id)
    if audit is None:
        return {"final": _index(load_final(run_dir, "dad"), "record_id").get(record_id)}

    responses = _index(load_stage(run_dir, "dad", "step5"), "response_id")
    refined = _index(load_stage(run_dir, "dad", "step4"), "prompt_id")
    prompts = _index(load_stage(run_dir, "dad", "step3"), "prompt_id")
    scenarios = _index(load_stage(run_dir, "dad", "step2"), "scenario_id")
    principles = _index(load_stage(run_dir, "dad", "step1"), "principle_id")

    return {
        "principle": principles.get(audit.get("principle_id")),
        "scenario": scenarios.get(audit.get("scenario_id")),
        "prompt": prompts.get(audit.get("prompt_id")),
        "refined": refined.get(audit.get("prompt_id")),
        "response": responses.get(audit.get("response_id")),
        "rewrite": audit,
        "pushback": _index(load_stage(run_dir, "dad", "step7"), "record_id").get(record_id),
        "final": _index(load_final(run_dir, "dad"), "record_id").get(record_id),
    }


@dataclass
class MatchedPair:
    key: str
    quality: str  # "exact" | "positional" | "group"
    a: list[dict]
    b: list[dict]


def _sdf_match_key(run_dir: Path, doc: dict) -> tuple[str, str] | None:
    subtypes = _index(load_stage(run_dir, "sdf", "layer2"), "subtype_id")
    st = subtypes.get(doc.get("subtype_id"))
    if st:
        return (st.get("type_name", ""), st.get("subtype_name", ""))
    return None


def match_outputs(run_a: Path, run_b: Path, pipeline: str) -> list[MatchedPair]:
    """Pair up final outputs of two runs for side-by-side comparison."""
    finals_a = load_final(run_a, pipeline)
    finals_b = load_final(run_b, pipeline)
    pairs: list[MatchedPair] = []

    if pipeline == "sdf":
        def group(run_dir, finals):
            by_name, by_pos = {}, {}
            for doc in finals:
                name_key = _sdf_match_key(run_dir, doc)
                if name_key:
                    by_name.setdefault(name_key, []).append(doc)
                by_pos.setdefault(doc.get("subtype_id"), []).append(doc)
            return by_name, by_pos

        names_a, pos_a = group(run_a, finals_a)
        names_b, pos_b = group(run_b, finals_b)
        matched_b_names = set()
        for key, docs_a in names_a.items():
            if key in names_b:
                matched_b_names.add(key)
                pairs.append(MatchedPair(" / ".join(key), "exact", docs_a, names_b[key]))
        # Positional fallback for name keys that didn't line up
        matched_a_ids = {d.get("subtype_id") for p in pairs for d in p.a}
        for sid, docs_a in pos_a.items():
            if sid in matched_a_ids or sid not in pos_b:
                continue
            pairs.append(MatchedPair(f"subtype_id {sid}", "positional", docs_a, pos_b[sid]))
        return pairs

    # DAD: audits carry scenario/injection identity
    def group_dad(run_dir, finals):
        audits = _index(load_stage(run_dir, "dad", "step6"), "record_id")
        exact, grouped = {}, {}
        for rec in finals:
            audit = audits.get(rec.get("record_id"), {})
            sid = str(audit.get("scenario_id", ""))
            inj = audit.get("injection_used", "")
            if sid.startswith("manta_"):
                exact.setdefault((sid, inj), []).append(rec)
            else:
                grouped.setdefault((audit.get("principle_id"), inj), []).append(rec)
        return exact, grouped

    exact_a, grouped_a = group_dad(run_a, finals_a)
    exact_b, grouped_b = group_dad(run_b, finals_b)
    for key, recs_a in exact_a.items():
        if key in exact_b:
            pairs.append(MatchedPair(f"{key[0]} [{key[1]}]", "exact", recs_a, exact_b[key]))
    for key, recs_a in grouped_a.items():
        if key in grouped_b:
            pairs.append(MatchedPair(f"principle {key[0]} [{key[1]}]", "group", recs_a, grouped_b[key]))
    return pairs
