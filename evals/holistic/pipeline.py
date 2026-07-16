"""Orchestrator: resolve a run into the three inputs, tag it, analyze it.

Reads run layout with plain ``utils.load_jsonl`` (no viewer/streamlit dependency) so
it runs headless in CI. The run layout it understands is the spec-driven one, with a
legacy fallback for annotations:

    <run>/final/dad_corpus.jsonl              corpus  {record_id, messages}
    <run>/step3/rewrites.jsonl                annotations (spec-driven; .annotation)
    <run>/step6/rewrites.jsonl                annotations (legacy fallback)
    <run>/final/judge/<ver>/verdicts.jsonl    quality-judge verdicts (if run)
    <run>/holistic/<ts>_<fp8>/                the extraction tag bundles (this tool)
    <run>/audit/category_records.jsonl        legacy pre-bundle tag index (read-only)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from shared import api, utils

from . import bundle, extract, synthesize
from .analyzers import AnalysisContext, AnalyzerRegistry, default_analyzers, run_analyzers
from .fields import FieldRegistry, default_fields
from .structural import assistant_turns

# annotation source stages, spec-driven first then legacy
_ANNOTATION_STAGES = ("step3", "step6")


@dataclass
class Inputs:
    """Resolved per-run inputs. ``annotations`` / ``verdicts`` are
    ``record_id -> data`` maps, or None when that source is absent. ``index_path``
    points at the selected provenance bundle's tag index (the legacy flat path for
    pre-bundle runs); ``tag()`` re-points it at the bundle it writes into.
    ``clusters`` is the semantic lane's
    ``record_id -> k-means cluster`` map from audit/diversity_report.json (§18.1),
    or None when that report hasn't been run."""

    corpus: list[dict]
    run_dir: Path | None
    annotations: dict | None
    verdicts: dict | None
    index_path: Path
    clusters: dict | None = None
    #: root of the provenance-bundle store for this input (<run>/holistic, or
    #: <corpus-stem>.holistic beside a bare corpus). None only on hand-built
    #: Inputs, which keep the pre-bundle direct-write behavior.
    holistic_root: Path | None = None


# ---------------------------------------------------------------- run layout

def category_records_path(run_dir: str | Path) -> Path:
    """The pre-bundle flat tag index (read-only legacy location; new tags write
    into provenance bundles under <run>/holistic/)."""
    return Path(run_dir) / "audit" / "category_records.jsonl"


def _bundle_index_path(holistic_root: Path, legacy_index: Path,
                       bundle_id: str | None) -> Path:
    """Which tag index a read should see: an explicit bundle, else the latest
    (legacy flat fallback). ``"legacy"`` forces the pre-bundle flat path."""
    if bundle_id == bundle.LEGACY_ID:
        return legacy_index
    if bundle_id is not None:
        if Path(bundle_id).name != bundle_id:
            raise SystemExit(f"invalid bundle id: {bundle_id!r}")
        bdir = holistic_root / bundle_id
        if not (bdir / bundle.MANIFEST_NAME).exists():
            raise SystemExit(f"bundle {bundle_id!r} not found under {holistic_root}")
        return bdir / bundle.INDEX_NAME
    return bundle.reading_index_path(holistic_root, legacy_index)


_WMAG_RE = re.compile(
    r"^\s*(mild|moderate|severe)\s*x\s*(individual|group|population)\s*$", re.IGNORECASE)

_TAXA_NORMALIZE = {"farmed animals": "farmed"}


def parse_welfare_magnitude(value) -> tuple[str | None, str | None]:
    """Split generation's compound welfare axis "Severity x Scope" into its two
    components (canonical capitalization). (None, None) on any non-matching input."""
    if not isinstance(value, str):
        return (None, None)
    m = _WMAG_RE.match(value)
    if not m:
        return (None, None)
    return (m.group(1).capitalize(), m.group(2).capitalize())


def augment_annotations(base: dict, step_rows: list[dict],
                        dilemma_rows: list[dict]) -> dict:
    """New record_id -> {axis: value} map aligned with the judge schema
    (`evals/dad_axes.yaml`): the compound welfare axis split into severity/scope and
    the step-1 dilemma axes (taxa_category, systemic_ai) lifted onto each record so
    the drift analyzer can compare them. Base axes preserved, input not mutated."""
    rid_to_pid = {r["record_id"]: r.get("prompt_id")
                  for r in step_rows if "record_id" in r}
    pid_to_dilemma = {d["prompt_id"]: d for d in dilemma_rows if "prompt_id" in d}
    out: dict = {}
    for rid, ann in base.items():
        new = dict(ann)
        sev, scope = parse_welfare_magnitude(ann.get("welfare_magnitude"))
        if sev is not None:
            new["welfare_severity"] = sev
            new["welfare_scope"] = scope
        pid = rid_to_pid.get(rid)
        dilemma = pid_to_dilemma.get(pid) if pid is not None else None
        if dilemma is not None:
            if "taxa_category" in dilemma:
                taxa = dilemma["taxa_category"]
                new["taxa_category"] = _TAXA_NORMALIZE.get(taxa, taxa)
            if "systemic_ai" in dilemma:
                new["systemic_ai"] = dilemma["systemic_ai"]
        out[rid] = new
    return out


def _load_annotations(run_dir: Path) -> dict | None:
    for stage in _ANNOTATION_STAGES:
        rows = utils.load_jsonl(run_dir / stage / "rewrites.jsonl")
        ann = {r["record_id"]: r["annotation"]
               for r in rows if "record_id" in r and "annotation" in r}
        if ann:
            dilemmas = utils.load_jsonl(run_dir / "step1" / "dilemmas.jsonl")
            return augment_annotations(ann, rows, dilemmas)
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


def _load_clusters(base_dir: Path) -> dict | None:
    """Cluster assignments from the semantic lane's audit/diversity_report.json
    (written by evals/diversity.py), or None when it hasn't been run. Clusters are
    optional gated input, so a corrupt/truncated report degrades to None (with a
    warning) rather than blocking the non-cluster analyzers."""
    path = base_dir / "audit" / "diversity_report.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            report = json.load(f)
    except json.JSONDecodeError as err:
        print(f"WARNING: ignoring malformed {path} ({err}) — "
              "rerun evals/diversity.py to rebuild it")
        return None
    clusters = report.get("clusters") if isinstance(report, dict) else None
    assignments = clusters.get("assignments") if isinstance(clusters, dict) else None
    if isinstance(assignments, dict):
        return assignments or None
    # a dict report without a clusters section is a normal pre-§18.1 report — only
    # an unusable shape (non-dict report, or a malformed clusters section) warns
    if not isinstance(report, dict) or clusters is not None:
        print(f"WARNING: ignoring malformed {path} — "
              "rerun evals/diversity.py to rebuild it")
    return None


def _load_semantic_summary(base_dir: Path) -> dict | None:
    """Bounded aggregate summary of the semantic lane's audit/diversity_report.json
    for the synthesis judge — every aggregate field EXCEPT the two O(records) arrays
    (``projection`` and ``clusters.assignments``) and with ``top_pairs`` capped at 5,
    so the synthesis input stays ~constant size at any corpus size. None when the
    report is absent or malformed."""
    path = base_dir / "audit" / "diversity_report.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            report = json.load(f)
    except json.JSONDecodeError:
        return None
    if not isinstance(report, dict):
        return None
    clusters = report.get("clusters")
    clusters_summary = ({k: v for k, v in clusters.items() if k != "assignments"}
                        if isinstance(clusters, dict) else None)
    top_pairs = report.get("top_pairs")
    return {
        "embed_model": report.get("embed_model"),
        "n_embedded": report.get("n_embedded"),
        "n_empty": report.get("n_empty"),
        "vendi": report.get("vendi"),
        "mean_pairwise_cosine": report.get("mean_pairwise_cosine"),
        "nn": report.get("nn"),
        "clusters": clusters_summary,
        "top_pairs": top_pairs[:5] if isinstance(top_pairs, list) else None,
    }


def resolve_inputs(input_path: str | Path | Inputs, *,
                   judge_version: str | None = None,
                   bundle_id: str | None = None) -> Inputs:
    """Resolve a run directory (joins annotations + verdicts, tag index from the
    selected bundle (legacy audit/ fallback)) or a bare corpus ``.jsonl`` file
    (corpus only, bundles in a sibling `<stem>.holistic/` dir). An
    already-resolved ``Inputs`` passes through unchanged, so a caller that resolved
    once (e.g. for selection) can hand the same snapshot to ``run`` — re-resolving
    could race a moving ``latest`` symlink. ``bundle_id`` picks which provenance
    bundle reads see (None = latest, legacy flat fallback)."""
    if isinstance(input_path, Inputs):
        return input_path
    p = Path(input_path)
    if not p.exists():
        raise SystemExit(f"input not found: {p}")
    if p.is_dir():
        corpus_path = p / "final" / "dad_corpus.jsonl"
        if not corpus_path.exists():
            raise SystemExit(f"no final/dad_corpus.jsonl under run dir {p}")
        holistic_root = p / "holistic"
        index = _bundle_index_path(holistic_root, category_records_path(p), bundle_id)
        return Inputs(utils.load_jsonl(corpus_path), p,
                      _load_annotations(p), _load_verdicts(p, judge_version),
                      index, _load_clusters(p), holistic_root)
    holistic_root = p.with_name(p.stem + ".holistic")
    legacy = p.with_name(p.stem + ".category_records.jsonl")
    index = _bundle_index_path(holistic_root, legacy, bundle_id)
    return Inputs(utils.load_jsonl(p), None, None, None, index,
                  _load_clusters(p.parent), holistic_root)


def load_category_records(inputs: Inputs) -> list[dict]:
    """The extraction tag index for this input, or [] if it has not been built yet."""
    return utils.load_jsonl(inputs.index_path)


# ---------------------------------------------------------------- stages

def tag(inputs: Inputs, fields: FieldRegistry | None = None, *,
        model: str | None = None, resume: bool = True,
        extract_template: str | None = None,
        axes_text: str | None = None, on_progress=None) -> list[dict]:
    """Run the extraction judge over the corpus. The write is routed through the
    provenance bundle matching this (fields, model, prompt) fingerprint — resumed
    if it exists, created otherwise — and ``inputs.index_path`` is updated to
    point inside it so callers (and the analyze step) read the same bundle.
    ``axes_text`` is the verbatim axes file to snapshot into a new bundle. A
    hand-built Inputs without ``holistic_root`` keeps the legacy direct write."""
    fields = fields or default_fields()
    # Fingerprint (and record) the model that will actually run — the config
    # default when no override is given — so the bundle key can't read "" while
    # the effective model comes from config.yaml (changing that default would
    # otherwise silently resume the previous model's tags).
    model = api.resolve_model(model)
    paths = None
    if inputs.holistic_root is not None:
        paths = bundle.resolve_bundle(
            inputs.holistic_root, fields, model=model,
            extract_template=extract_template, axes_text=axes_text, create=True)
        inputs.index_path = paths.index_path
    rows = extract.extract_corpus(
        inputs.corpus, fields, inputs.index_path, model=model, resume=resume,
        template=extract_template, on_progress=on_progress)
    if paths is not None:
        bundle.update_records_tagged(paths.bundle_dir)
    return rows


def analyze(records: list[dict], *, fields: FieldRegistry | None = None,
            analyzers: AnalyzerRegistry | None = None, annotations: dict | None = None,
            verdicts: dict | None = None, clusters: dict | None = None,
            texts: dict | None = None, config: dict | None = None) -> dict:
    """Run the registered analyzers over the tag rows (input-gated). Returns
    ``{"analyses": {...}, "skipped": {...}}``."""
    ctx = AnalysisContext(
        records=records, fields=fields or default_fields(),
        annotations=annotations, verdicts=verdicts, clusters=clusters,
        texts=texts, config=config or {})
    return run_analyzers(ctx, analyzers or default_analyzers())


def run(input_path: str | Path | Inputs, *, fields: FieldRegistry | None = None,
        analyzers: AnalyzerRegistry | None = None, model: str | None = None,
        resume: bool = True, do_tag: bool = True, extract_template: str | None = None,
        synthesis_template: str | None = None, judge_version: str | None = None,
        config: dict | None = None, axes_text: str | None = None) -> dict:
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
        tag(inputs, fields, model=model, resume=resume, extract_template=extract_template,
            axes_text=axes_text)
    records = load_category_records(inputs)
    if not do_tag and not records and inputs.corpus:
        raise SystemExit(
            f"No tag index at {inputs.index_path} but the corpus has "
            f"{len(inputs.corpus)} records — run without --analyze-only first to tag it.")
    texts = {r["record_id"]: assistant_turns(r)
             for r in inputs.corpus if r.get("record_id")}
    stats = analyze(records, fields=fields, analyzers=analyzers, config=config,
                    annotations=inputs.annotations, verdicts=inputs.verdicts,
                    clusters=inputs.clusters, texts=texts)
    present = ["tags"]
    if inputs.annotations:
        present.append("annotations")
    if inputs.verdicts:
        present.append("verdicts")
    if inputs.clusters:
        present.append("clusters")
    if texts:
        present.append("texts")
    report = {
        "run_id": inputs.run_dir.name if inputs.run_dir else None,
        "records": len(records),
        "inputs_present": present,
        "stats": stats,
    }
    if synthesis_template is not None:
        synth_input = dict(stats)
        synth_input["semantic"] = (_load_semantic_summary(inputs.run_dir)
                                   if inputs.run_dir is not None else None)
        report["synthesis"] = synthesize.synthesize(synth_input,
                                                     template=synthesis_template, model=model)
    return report
