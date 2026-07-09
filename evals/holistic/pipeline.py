"""Orchestrator: resolve a run into the three inputs, tag it, analyze it.

Reads run layout with plain ``utils.load_jsonl`` (no viewer/streamlit dependency) so
it runs headless in CI. The run layout it understands is the spec-driven one, with a
legacy fallback for annotations:

    <run>/final/dad_corpus.jsonl              corpus  {record_id, messages}
    <run>/step3/rewrites.jsonl                annotations (spec-driven; .annotation)
    <run>/step6/rewrites.jsonl                annotations (legacy fallback)
    <run>/final/judge/<ver>/verdicts.jsonl    quality-judge verdicts (if run)
    <run>/audit/category_records.jsonl        the extraction tag index (this tool)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shared import utils

from . import extract, synthesize
from .analyzers import AnalysisContext, AnalyzerRegistry, default_analyzers, run_analyzers
from .fields import FieldRegistry, default_fields

# annotation source stages, spec-driven first then legacy
_ANNOTATION_STAGES = ("step3", "step6")


@dataclass
class Inputs:
    """Resolved per-run inputs for the three-input model. ``annotations`` /
    ``verdicts`` are ``record_id -> data`` maps, or None when that source is absent.
    ``index_path`` is where the extraction tag index lives for this input (the run's
    audit/ dir, or a sibling file for a bare corpus)."""

    corpus: list[dict]
    run_dir: Path | None
    annotations: dict | None
    verdicts: dict | None
    index_path: Path


# ---------------------------------------------------------------- run layout

def category_records_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "audit" / "category_records.jsonl"


def _load_annotations(run_dir: Path) -> dict | None:
    for stage in _ANNOTATION_STAGES:
        rows = utils.load_jsonl(run_dir / stage / "rewrites.jsonl")
        ann = {r["record_id"]: r["annotation"]
               for r in rows if "record_id" in r and "annotation" in r}
        if ann:
            return ann
    return None


def _load_verdicts(run_dir: Path, judge_version: str | None = None) -> dict | None:
    judge_root = run_dir / "final" / "judge"
    if not judge_root.is_dir():
        return None
    if judge_version:
        verdict_path = judge_root / judge_version / "verdicts.jsonl"
        if not verdict_path.exists():
            raise SystemExit(
                f"judge verdicts not found for version {judge_version!r}: {verdict_path}")
        files = [verdict_path]
    else:
        files = sorted(judge_root.glob("*/verdicts.jsonl"))
        if len(files) > 1:
            versions = ", ".join(f.parent.name for f in files)
            raise SystemExit(
                f"multiple judge verdict versions found under {judge_root}: {versions}. "
                "Pass --judge-version to choose one.")
    if not files:
        return None
    rows = utils.load_jsonl(files[0])
    verdicts = {r["record_id"]: r for r in rows if "record_id" in r}
    return verdicts or None


def resolve_inputs(input_path: str | Path | Inputs, *,
                   judge_version: str | None = None) -> Inputs:
    """Resolve a run directory (joins annotations + verdicts, tag index in audit/) or
    a bare corpus ``.jsonl`` file (corpus only, tag index in a sibling file). An
    already-resolved ``Inputs`` passes through unchanged, so a caller that resolved
    once (e.g. for selection) can hand the same snapshot to ``run`` — re-resolving
    could race a moving ``latest`` symlink."""
    if isinstance(input_path, Inputs):
        return input_path
    p = Path(input_path)
    if not p.exists():
        raise SystemExit(f"input not found: {p}")
    if p.is_dir():
        corpus_path = p / "final" / "dad_corpus.jsonl"
        if not corpus_path.exists():
            raise SystemExit(f"no final/dad_corpus.jsonl under run dir {p}")
        return Inputs(utils.load_jsonl(corpus_path), p,
                      _load_annotations(p), _load_verdicts(p, judge_version),
                      category_records_path(p))
    index = p.with_name(p.stem + ".category_records.jsonl")
    return Inputs(utils.load_jsonl(p), None, None, None, index)


def load_category_records(inputs: Inputs) -> list[dict]:
    """The extraction tag index for this input, or [] if it has not been built yet."""
    return utils.load_jsonl(inputs.index_path)


# ---------------------------------------------------------------- stages

def tag(inputs: Inputs, fields: FieldRegistry | None = None, *,
        model: str | None = None, resume: bool = True,
        extract_template: str | None = None) -> list[dict]:
    """Run the extraction judge over the corpus, writing the tag index to
    ``inputs.index_path`` (the run's audit/ dir, or a sibling of a bare corpus file)."""
    fields = fields or default_fields()
    return extract.extract_corpus(
        inputs.corpus, fields, inputs.index_path, model=model, resume=resume,
        template=extract_template)


def analyze(records: list[dict], *, fields: FieldRegistry | None = None,
            analyzers: AnalyzerRegistry | None = None, annotations: dict | None = None,
            verdicts: dict | None = None, config: dict | None = None) -> dict:
    """Run the registered analyzers over the tag rows (input-gated). Returns
    ``{"analyses": {...}, "skipped": {...}}``."""
    ctx = AnalysisContext(
        records=records, fields=fields or default_fields(),
        annotations=annotations, verdicts=verdicts, config=config or {})
    return run_analyzers(ctx, analyzers or default_analyzers())


def run(input_path: str | Path | Inputs, *, fields: FieldRegistry | None = None,
        analyzers: AnalyzerRegistry | None = None, model: str | None = None,
        resume: bool = True, do_tag: bool = True, extract_template: str | None = None,
        synthesis_template: str | None = None, judge_version: str | None = None,
        config: dict | None = None) -> dict:
    """Full pass over a run dir: resolve inputs → (optionally) tag → analyze →
    (optionally) synthesize → report. ``do_tag=False`` analyzes an existing index
    without touching the API; a pre-resolved ``Inputs`` (possibly with a narrowed
    ``corpus`` — only those records get *tagged*; analysis always reads the whole
    existing index) passes through unchanged; ``synthesis_template`` (when given)
    runs the holistic LLM pass over the stats; ``config`` carries analysis params
    into ``ctx.config``."""
    fields = fields or default_fields()
    inputs = resolve_inputs(input_path, judge_version=judge_version)
    if do_tag:
        tag(inputs, fields, model=model, resume=resume, extract_template=extract_template)
    records = load_category_records(inputs)
    if not do_tag and not records and inputs.corpus:
        raise SystemExit(
            f"No tag index at {inputs.index_path} but the corpus has "
            f"{len(inputs.corpus)} records — run without --analyze-only first to tag it.")
    stats = analyze(records, fields=fields, analyzers=analyzers, config=config,
                    annotations=inputs.annotations, verdicts=inputs.verdicts)
    present = ["tags"]
    if inputs.annotations:
        present.append("annotations")
    if inputs.verdicts:
        present.append("verdicts")
    report = {
        "run_id": inputs.run_dir.name if inputs.run_dir else None,
        "records": len(records),
        "inputs_present": present,
        "stats": stats,
    }
    if synthesis_template is not None:
        report["synthesis"] = synthesize.synthesize(stats, template=synthesis_template,
                                                     model=model)
    return report
