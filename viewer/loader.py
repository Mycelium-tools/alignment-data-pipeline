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
        # Current spec-driven pipeline (steps 1-4)
        "step1_scenarios": "step1/scenarios.jsonl",
        "step1_dilemmas": "step1/dilemmas.jsonl",
        "step1_batches": "step1/batches.jsonl",
        "step2_scopes": "step2/scopes.jsonl",
        "step2_tensions": "step2/tensions.jsonl",
        "step2_responses": "step2/responses.jsonl",
        "step3_rewrites": "step3/rewrites.jsonl",
        # Legacy 7-step pipeline (runs made before the dilemma spec)
        "step1": "step1/principles.jsonl",
        "step2": "step2/scenarios.jsonl",
        "step3": "step3/prompts.jsonl",
        "step4": "step4/refined_prompts.jsonl",
        "step5": "step5/responses.jsonl",
        "step6": "step6/rewrites.jsonl",
        "final": "final/dad_corpus.jsonl",
    },
}


def dad_is_legacy(run_dir: Path) -> bool:
    """Old 7-step DAD runs are recognized by their stage-1/2 output files."""
    run_dir = Path(run_dir)
    return (run_dir / "step1" / "principles.jsonl").exists() or \
           (run_dir / "step2" / "scenarios.jsonl").exists()


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
    responses = load_stage(run_dir, pipeline, "step2_responses") or load_stage(run_dir, pipeline, "step5")
    if not responses:
        return None
    return sum(1 for r in responses if r.get("kept")) / len(responses)


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
            # Zero-count stages are dropped: DAD stage keys span both the current
            # and the legacy pipeline layout, and a run only has one of them.
            counts = {
                stage: n
                for stage in STAGE_FILES[pipeline]
                if (n := len(load_stage(d, pipeline, stage))) or stage == "final"
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
    """Full lineage for one DAD training record (keyed by final record_id).
    The "format" key tells pages which stage chain this run used."""
    if dad_is_legacy(run_dir):
        return _dad_lineage_legacy(run_dir, record_id)

    final = _index(load_final(run_dir, "dad"), "record_id").get(record_id)
    audits = _index(load_stage(run_dir, "dad", "step3_rewrites"), "record_id")
    audit = audits.get(record_id)
    if audit is None:
        return {"format": "v2", "final": final}

    responses = _index(load_stage(run_dir, "dad", "step2_responses"), "response_id")
    dilemmas = _index(load_stage(run_dir, "dad", "step1_dilemmas"), "prompt_id")
    tension_tags = _index(load_stage(run_dir, "dad", "step2_tensions"), "prompt_id")
    scenarios = _index(load_stage(run_dir, "dad", "step1_scenarios"), "scenario_id")
    scope_recs = _index(load_stage(run_dir, "dad", "step2_scopes"), "prompt_id")

    dilemma = dilemmas.get(audit.get("prompt_id"))
    return {
        "format": "v2",
        "dilemma": dilemma,
        "scenario": scenarios.get((dilemma or {}).get("scenario_id")),
        "scope": scope_recs.get(audit.get("prompt_id")),
        "tension_tag": tension_tags.get(audit.get("prompt_id")),
        "response": responses.get(audit.get("response_id")),
        "rewrite": audit,
        "final": final,
    }


def dad_lineage_by_prompt(run_dir: Path, prompt_id: str) -> dict:
    """Lineage keyed by step-1 prompt_id, built forward through whatever stages
    exist. Used to view incomplete runs (e.g. --stop-after 1, before responses
    are generated); returns the same shape as dad_lineage with later stages None
    when not reached."""
    dilemmas = _index(load_stage(run_dir, "dad", "step1_dilemmas"), "prompt_id")
    tension_tags = _index(load_stage(run_dir, "dad", "step2_tensions"), "prompt_id")
    scenarios = _index(load_stage(run_dir, "dad", "step1_scenarios"), "scenario_id")
    scope_recs = _index(load_stage(run_dir, "dad", "step2_scopes"), "prompt_id")
    responses = [r for r in load_stage(run_dir, "dad", "step2_responses")
                 if r.get("prompt_id") == prompt_id]
    rewrite = next((a for a in load_stage(run_dir, "dad", "step3_rewrites")
                    if a.get("prompt_id") == prompt_id), None)
    final = None
    if rewrite:
        final = _index(load_final(run_dir, "dad"), "record_id").get(rewrite.get("record_id"))
    dilemma = dilemmas.get(prompt_id)
    return {
        "format": "v2",
        "dilemma": dilemma,
        "scenario": scenarios.get((dilemma or {}).get("scenario_id")),
        "scope": scope_recs.get(prompt_id),
        "tension_tag": tension_tags.get(prompt_id),
        "response": responses[0] if responses else None,
        "rewrite": rewrite,
        "final": final,
    }


def _dad_lineage_legacy(run_dir: Path, record_id: str) -> dict:
    audits = _index(load_stage(run_dir, "dad", "step6"), "record_id")
    audit = audits.get(record_id)
    if audit is None:
        return {"format": "legacy",
                "final": _index(load_final(run_dir, "dad"), "record_id").get(record_id)}

    responses = _index(load_stage(run_dir, "dad", "step5"), "response_id")
    refined = _index(load_stage(run_dir, "dad", "step4"), "prompt_id")
    prompts = _index(load_stage(run_dir, "dad", "step3"), "prompt_id")
    scenarios = _index(load_stage(run_dir, "dad", "step2"), "scenario_id")
    principles = _index(load_stage(run_dir, "dad", "step1"), "principle_id")

    return {
        "format": "legacy",
        "principle": principles.get(audit.get("principle_id")),
        "scenario": scenarios.get(audit.get("scenario_id")),
        "prompt": prompts.get(audit.get("prompt_id")),
        "refined": refined.get(audit.get("prompt_id")),
        "response": responses.get(audit.get("response_id")),
        "rewrite": audit,
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

    # DAD: audits carry prompt/scenario + injection identity
    def group_dad(run_dir, finals):
        exact, grouped = {}, {}
        if dad_is_legacy(run_dir):
            audits = _index(load_stage(run_dir, "dad", "step6"), "record_id")
            for rec in finals:
                audit = audits.get(rec.get("record_id"), {})
                sid = str(audit.get("scenario_id", ""))
                inj = audit.get("injection_used", "")
                if sid.startswith("manta_"):
                    exact.setdefault((sid, inj), []).append(rec)
                else:
                    grouped.setdefault((audit.get("principle_id"), inj), []).append(rec)
            return exact, grouped
        audits = _index(load_stage(run_dir, "dad", "step3_rewrites"), "record_id")
        for rec in finals:
            audit = audits.get(rec.get("record_id"), {})
            # AW-#### IDs are stable across runs of the same spec/seed set
            exact.setdefault((str(audit.get("prompt_id", "")), audit.get("sample_index", 0)), []).append(rec)
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
