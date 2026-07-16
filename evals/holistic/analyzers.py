"""Analyzers — pluggable, input-gated units of corpus-level analysis.

Each ``Analyzer`` declares the inputs it needs (``tags`` always available;
``annotations`` for spec-driven runs; ``verdicts`` after the quality judge ran) and a
function over an ``AnalysisContext`` returning a JSON-able stats fragment. The runner
executes only those analyzers whose inputs are present, so the report degrades
gracefully under the three-input model. Adding or replacing an analysis is a single
registry call. ``default_analyzers()`` ships the built-in set — distribution,
evenness, coverage-vs-target, Cramér's V correlation, t-wise combination coverage,
intent→realization drift, the categorical × embedding-cluster bridge, and the
structural text signals — and the axes YAML's ``analysis`` block selects which run.
"""

from __future__ import annotations

import collections
import math
from dataclasses import dataclass, field as _dc_field
from typing import Callable

from . import structural as _structural_mod
from ._registry import OrderedRegistry
from .fields import FieldRegistry

INPUTS = ("tags", "annotations", "verdicts", "clusters", "texts")


@dataclass
class AnalysisContext:
    """Everything an analyzer may read. ``records`` are the extraction tag rows;
    ``annotations`` / ``verdicts`` are ``record_id -> data`` maps or None;
    ``clusters`` is the semantic lane's ``record_id -> k-means cluster`` map
    (diversity_report.json) or None; ``texts`` is a ``record_id -> list[str]``
    map of assistant-turn contents or None."""

    records: list[dict]
    fields: FieldRegistry
    annotations: dict | None = None
    verdicts: dict | None = None
    clusters: dict | None = None
    texts: dict | None = None
    config: dict = _dc_field(default_factory=dict)

    @property
    def available(self) -> set[str]:
        avail = {"tags"}
        if self.annotations:
            avail.add("annotations")
        if self.verdicts:
            avail.add("verdicts")
        if self.clusters:
            avail.add("clusters")
        if self.texts:
            avail.add("texts")
        return avail


@dataclass(frozen=True)
class Analyzer:
    name: str
    fn: Callable[[AnalysisContext], dict]
    requires: tuple[str, ...] = ("tags",)

    def __post_init__(self) -> None:
        bad = set(self.requires) - set(INPUTS)
        if bad:
            raise ValueError(f"Analyzer {self.name!r}: unknown inputs {sorted(bad)}")


class AnalyzerRegistry(OrderedRegistry[Analyzer]):
    """Ordered, mutable set of ``Analyzer``s (see ``OrderedRegistry``)."""


def run_analyzers(ctx: AnalysisContext, registry: AnalyzerRegistry) -> dict:
    """Run every analyzer whose inputs are present; skip (with a reason) the rest.
    Returns ``{"analyses": {name: fragment}, "skipped": {name: reason}}``."""
    analyses: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    for a in registry.all():
        missing = set(a.requires) - ctx.available
        if missing:
            skipped[a.name] = f"missing inputs: {sorted(missing)}"
            continue
        analyses[a.name] = a.fn(ctx)
    return {"analyses": analyses, "skipped": skipped}


# ---------------------------------------------------------------- seed analyzers

def _distribution(ctx: AnalysisContext) -> dict:
    """Per-field value counts across the corpus. Generic over the field registry —
    works for any field set. The richer per-axis metrics (richness, Pielou evenness,
    quota flags) are added later as their own analyzers on top of this."""
    out: dict[str, dict] = {}
    for fld in ctx.fields.all():
        counts: collections.Counter = collections.Counter()
        for rec in ctx.records:
            val = rec.get(fld.name)
            if isinstance(val, list):
                # dedup within a record; count only hashable scalar members
                counts.update({x for x in val if isinstance(x, (str, int, bool))})
            elif isinstance(val, (str, int, bool)):
                counts[val] += 1
            # dict/None/other (e.g. object fields) are not categorical here — skip
        out[fld.name] = dict(counts)
    return out


# ---------------------------------------------------------------- verdict framing

def _verdict(value: float | None, good: float, ok: float,
             higher_better: bool = False) -> str:
    """A GOOD / OK / BAD / NA label for a metric — same signature and vocabulary as
    ``evals/diversity.py::_verdict`` so both diversity tools read alike. Thresholds are
    provisional (tune in the brainstorm)."""
    if value is None:
        return "NA"
    if higher_better:
        return "GOOD" if value >= good else ("OK" if value >= ok else "BAD")
    return "GOOD" if value <= good else ("OK" if value <= ok else "BAD")


def pielou_evenness(counts: dict) -> float | None:
    """Pielou evenness J' = H / ln(k) over a value-count map. 1.0 = perfectly even,
    →0 = one value dominates, 0.0 = a single value (fully collapsed), None = no data.
    Decoupled from richness (k), which is reported alongside — Shannon alone conflates
    the two."""
    total = sum(counts.values())
    k = len(counts)
    if total == 0 or k == 0:
        return None
    if k == 1:
        return 0.0
    h = -sum((c / total) * math.log(c / total) for c in counts.values() if c > 0)
    return h / math.log(k)


_EVENNESS_NOTE = "GOOD = spread across values; BAD = one value dominates the axis"


def _evenness(ctx: AnalysisContext) -> dict:
    """Per-axis balance: richness (distinct values present) + Pielou evenness + a
    GOOD/OK/BAD verdict. The categorical analogue of CAML's topic-spread panel."""
    out: dict[str, dict] = {}
    for axis, counts in _distribution(ctx).items():
        even = pielou_evenness(counts)
        out[axis] = {
            "richness": len(counts),
            "n": sum(counts.values()),
            "evenness": None if even is None else round(even, 3),
            "verdict": _verdict(even, 0.75, 0.5, higher_better=True),
            "note": _EVENNESS_NOTE,
        }
    return out


# ---------------------------------------------------------------- coverage vs target

_COVERAGE_NOTE = "GOOD = distribution meets the axis's target quotas; BAD = a quota missed"


def _target_violations(field, counts: dict) -> list[str]:
    """Check a field's distribution ``counts`` against its ``target`` quota rules and
    return a list of human-readable violations (empty = all met). Supported rules:
    ``min_share``/``max_share`` (per named value), ``max_share_each`` (cap on every
    value), ``band_each`` ([lo, hi] on every value), ``require_all_values`` (every
    vocabulary value must appear)."""
    target = field.target
    total = sum(counts.values())
    shares = {v: c / total for v, c in counts.items()} if total else {}
    out: list[str] = []
    for val, frac in (target.get("min_share") or {}).items():
        if shares.get(val, 0.0) < frac:
            out.append(f"{val} {shares.get(val, 0.0):.2f} < min {frac}")
    for val, frac in (target.get("max_share") or {}).items():
        if shares.get(val, 0.0) > frac:
            out.append(f"{val} {shares.get(val, 0.0):.2f} > max {frac}")
    if "max_share_each" in target:
        cap = target["max_share_each"]
        out += [f"{v} {s:.2f} > max {cap}" for v, s in shares.items() if s > cap]
    if "band_each" in target:
        lo, hi = target["band_each"]
        # check every vocabulary value (a value at 0% share must still fail the floor);
        # fall back to observed values for free/multi fields with no declared vocabulary
        vals = field.values or list(shares)
        out += [f"{v} {shares.get(v, 0.0):.2f} outside [{lo}, {hi}]"
                for v in vals if not lo <= shares.get(v, 0.0) <= hi]
    if target.get("require_all_values"):
        out += [f"missing {v}" for v in field.values if counts.get(v, 0) == 0]
    return out


def _coverage_vs_target(ctx: AnalysisContext) -> dict:
    """Per-axis check of the realized distribution against the target quotas declared
    on each field (``Field.target`` in the axes YAML). Only fields with a target are
    reported. 'Did we hit our designed mix?'"""
    dist = _distribution(ctx)
    out: dict[str, dict] = {}
    for field in ctx.fields.all():
        if not field.target:
            continue
        counts = dist.get(field.name, {})
        n = sum(counts.values())
        if n == 0:
            out[field.name] = {"n": 0, "verdict": "NA", "violations": [],
                               "note": _COVERAGE_NOTE}
            continue
        violations = _target_violations(field, counts)
        out[field.name] = {
            "n": n,
            "verdict": "BAD" if violations else "GOOD",
            "violations": violations,
            "note": _COVERAGE_NOTE,
        }
    return out


# ---------------------------------------------------------------- correlation

_CORRELATION_NOTE = ("GOOD = axes independent; BAD = one axis predicts the other "
                     "(for attitude x direction this is the sycophancy tell)")


def cramers_v(joint: dict) -> float | None:
    """Cramér's V over a joint count map ``{(a_value, b_value): count}``. 0 =
    independent, 1 = one variable fully determines the other, None = undefined
    (no data, or a variable with a single observed level)."""
    joint = {k: c for k, c in joint.items() if c > 0}   # drop zero/negative cells so
    n = sum(joint.values())                             # no level has a zero marginal
    # type-aware sort (same convention as drift's tie key): a coerced-but-invalid
    # tag can put an int among strings, and bare sorted() would TypeError
    def _level_key(x):
        return (type(x).__name__, str(x))
    a_levels = sorted({a for a, _ in joint}, key=_level_key)
    b_levels = sorted({b for _, b in joint}, key=_level_key)
    if n == 0 or len(a_levels) < 2 or len(b_levels) < 2:
        return None
    a_tot = {a: sum(c for (x, _), c in joint.items() if x == a) for a in a_levels}
    b_tot = {b: sum(c for (_, y), c in joint.items() if y == b) for b in b_levels}
    chi2 = 0.0
    for a in a_levels:
        for b in b_levels:
            expected = a_tot[a] * b_tot[b] / n
            observed = joint.get((a, b), 0)
            chi2 += (observed - expected) ** 2 / expected
    v2 = chi2 / (n * min(len(a_levels) - 1, len(b_levels) - 1))
    return math.sqrt(v2)


def _correlation(ctx: AnalysisContext) -> dict:
    """Cramér's V for each configured axis-pair (``config.important_pairs``). The
    anti-correlation checks: near-zero V is healthy; high V on attitude x direction
    means the user's attitude predicts the assistant's behavior. Records missing
    either axis (or with non-scalar values) are skipped."""
    out: dict[str, dict] = {}
    for pair in ctx.config.get("important_pairs") or []:
        a_axis, b_axis = _pair_axes(pair)
        joint: collections.Counter = collections.Counter()
        for rec in ctx.records:
            a, b = rec.get(a_axis), rec.get(b_axis)
            if isinstance(a, (str, int, bool)) and isinstance(b, (str, int, bool)):
                joint[(a, b)] += 1
        v = cramers_v(joint)
        out[f"{a_axis} x {b_axis}"] = {
            "n": sum(joint.values()),
            "cramers_v": None if v is None else round(v, 3),
            "verdict": _verdict(v, 0.2, 0.4),   # lower is better: V<=0.2 GOOD, <=0.4 OK
            "note": _CORRELATION_NOTE,
        }
    return out


# ---------------------------------------------------------------- combination (t-wise) coverage

_COMBO_NOTE = ("GOOD = most valid axis-pair cells occur; BAD = many designed "
               "combinations never appear (empty must-not-be-empty cells)")


def _axis_values(rec: dict, axis: str) -> set:
    """The scalar categorical value(s) a record carries on ``axis`` as a set — a bare
    scalar becomes a singleton, a multi list becomes its hashable members, anything
    else (missing / object / non-scalar) becomes the empty set."""
    val = rec.get(axis)
    if isinstance(val, list):
        return {x for x in val if isinstance(x, (str, int, bool))}
    if isinstance(val, (str, int, bool)):
        return {val}
    return set()


def _pair_axes(pair) -> tuple[str, str]:
    """Validate a ``important_pairs`` entry and return its two axis names. Any
    malformation (wrong shape, non-string axis names) raises ``ValueError`` so a
    config typo fails loudly rather than crashing later or passing as NA."""
    if not (isinstance(pair, (list, tuple)) and len(pair) == 2
            and all(isinstance(x, str) and x for x in pair)):
        raise ValueError(f"important_pairs entry must be [axis_a, axis_b]: {pair!r}")
    return pair[0], pair[1]


def _combination_coverage(ctx: AnalysisContext) -> dict:
    """t-wise (pairwise) coverage for each ``config.important_pairs``: the fraction of
    valid axis-pair cells (cartesian product of the two fields' vocabularies) that occur
    at least once, plus the list of missing cells and a GOOD/OK/BAD verdict. NA when
    either axis has no declared vocabulary, or when no record populates the pair. This is
    combinatorial-interaction-testing coverage — it surfaces must-not-be-empty
    combinations (``leverage=Systemic × direction=Over-weighting``)."""
    out: dict[str, dict] = {}
    for pair in ctx.config.get("important_pairs") or []:
        a_axis, b_axis = _pair_axes(pair)
        key = f"{a_axis} x {b_axis}"
        a_vals = tuple(ctx.fields.get(a_axis).values) if a_axis in ctx.fields else ()
        b_vals = tuple(ctx.fields.get(b_axis).values) if b_axis in ctx.fields else ()
        if not a_vals or not b_vals:
            out[key] = {"cells": 0, "filled": 0, "coverage": None, "n": 0,
                        "missing": [], "verdict": "NA", "note": _COMBO_NOTE}
            continue
        valid = {(a, b) for a in a_vals for b in b_vals}
        a_set, b_set = set(a_vals), set(b_vals)
        seen: set = set()
        n = 0
        for rec in ctx.records:
            avs = _axis_values(rec, a_axis) & a_set
            bvs = _axis_values(rec, b_axis) & b_set
            if avs and bvs:
                n += 1
                seen.update((a, b) for a in avs for b in bvs)
        if n == 0:
            # NA (no contributing records), but the missing-cell list is still the
            # whole valid grid — an empty list would read as "nothing missing"
            out[key] = {"cells": len(valid), "filled": 0, "coverage": None, "n": 0,
                        "missing": sorted(f"{a}×{b}" for a, b in valid),
                        "verdict": "NA", "note": _COMBO_NOTE}
            continue
        coverage = len(seen) / len(valid)
        out[key] = {
            "cells": len(valid),
            "filled": len(seen),
            "n": n,
            "coverage": round(coverage, 3),
            "missing": sorted(f"{a}×{b}" for a, b in valid - seen),
            "verdict": _verdict(coverage, 0.9, 0.7, higher_better=True),
            "note": _COMBO_NOTE,
        }
    return out


# ---------------------------------------------------------------- intent -> realization drift

_DRIFT_NOTE = ("GOOD = extraction matches the generator's intent; BAD = systematic "
               "disagreement — either generation drift or extraction-judge bias "
               "(route to a human)")


def _as_label_set(v) -> set[str]:
    if isinstance(v, list):
        return {str(x) for x in v}
    return set() if v is None else {str(v)}


def _drift(ctx: AnalysisContext) -> dict:
    """Per-axis confusion between the intended label (generation annotation) and the
    realized label (extraction tag). Scalar axes compare by exact (type-strict) match;
    multi-valued axes compare as sets (agreement = exact-set rate, plus mean Jaccard
    overlap). For each axis, over records present on both sides, report agreement,
    the top confusion pairs, and a GOOD/OK/BAD verdict — a low agreement is flagged
    for a human as *either* generation drift *or* extraction-judge bias. Axes never
    comparably intended+realized are omitted. Needs input 2 (annotations)."""
    out: dict[str, dict] = {}
    anns = ctx.annotations or {}
    for fld in ctx.fields.all():
        axis = fld.name
        confusion: collections.Counter = collections.Counter()
        matches = 0
        n = 0
        jaccard = 0.0
        for rec in ctx.records:
            ann = anns.get(rec.get("record_id"))
            if not ann:
                continue
            intended, realized = ann.get(axis), rec.get(axis)
            if fld.kind == "multi":
                a, j = _as_label_set(intended), _as_label_set(realized)
                if not a and not j:
                    continue
                n += 1
                if a == j:
                    matches += 1
                    jaccard += 1.0
                else:
                    jaccard += len(a & j) / len(a | j)
                    confusion[(", ".join(sorted(a)), ", ".join(sorted(j)))] += 1
            elif isinstance(intended, (str, int, bool)) and isinstance(realized, (str, int, bool)):
                n += 1
                # type-strict: True == 1 in Python, but a bool/int mismatch is a
                # disagreement, not an agreement
                if intended == realized and type(intended) is type(realized):
                    matches += 1
                else:
                    confusion[(intended, realized)] += 1
        if n == 0:
            continue
        # canonical order: count desc, then type+lexicographic — most_common alone
        # breaks ties by input order, which would make reports differ across
        # reorderings (type name included: str(True) == str("True"))
        def _tie_key(kv):
            (i, r), c = kv
            return (-c, type(i).__name__, str(i), type(r).__name__, str(r))
        top = sorted(confusion.items(), key=_tie_key)
        # multi axes get verdicts from mean Jaccard (exact-set match is harsher
        # than the per-label agreement it sits next to); scalars from agreement
        score = jaccard / n if fld.kind == "multi" else matches / n
        out[axis] = {
            "n": n,
            "agreement": round(matches / n, 3),
            "disagreements": [{"intended": i, "realized": r, "count": c}
                              for (i, r), c in top[:5]],
            "verdict": _verdict(score, 0.8, 0.6, higher_better=True),
            "note": _DRIFT_NOTE,
        }
        if fld.kind == "multi":
            out[axis]["mean_jaccard"] = round(jaccard / n, 3)
    return out


# ---------------------------------------------------------------- categorical × cluster bridge

_BRIDGE_NOTE = ("GOOD = the axis's categories land in distinct embedding clusters; "
                "BAD = the axis varies on paper but the text sounds the same "
                "(label-only diversity)")


def _cluster_bridge(ctx: AnalysisContext) -> dict:
    """§18.1 categorical × embedding-cluster cross-tab: per axis, Cramér's V between
    the axis's categorical values and the semantic lane's k-means cluster assignments
    (``evals/diversity.py`` → diversity_report.json). The inverse read of
    ``correlation``: here LOW V is the problem — categorical diversity that never
    shows up in meaning-space. Multi-valued axes contribute one occurrence per value
    (so ``n`` counts occurrences, like ``_distribution``). NA when an axis (or the
    clustering) has a single observed level; axes never populated alongside a
    cluster are omitted. No API."""
    clusters = ctx.clusters or {}
    out: dict[str, dict] = {}
    for fld in ctx.fields.all():
        joint: collections.Counter = collections.Counter()
        for rec in ctx.records:
            cluster = clusters.get(rec.get("record_id"))
            if cluster is None:
                continue
            for val in _axis_values(rec, fld.name):
                joint[(val, cluster)] += 1
        if not joint:
            continue
        v = cramers_v(joint)
        out[fld.name] = {
            "n": sum(joint.values()),
            "cramers_v": None if v is None else round(v, 3),
            "verdict": _verdict(v, 0.3, 0.15, higher_better=True),
            "note": _BRIDGE_NOTE,
        }
    return out


# ---------------------------------------------------------------- structural (response form)

def _structural(ctx: AnalysisContext) -> dict:
    """Response-FORM diversity over the assistant turns (``ctx.texts``: record_id ->
    list of assistant-turn strings). Opening/closing are read from the first assistant
    turn (the primary training answer); scaffold/formatting/length/recurring over all
    turns of the record joined. Mechanical and offline — no API. Blind spot of every
    tag-based analyzer: a corpus can be perfectly varied in topic yet write every reply
    the same way."""
    texts_map = ctx.texts or {}
    first_sents, last_sents, joined = [], [], []
    for turns in texts_map.values():
        if not turns:
            continue
        first_sents.append(_structural_mod.first_sentence(turns[0]))
        last_sents.append(_structural_mod.last_sentence(turns[0]))
        joined.append("\n\n".join(turns))
    return {
        "n": len(joined),
        "opening": _structural_mod.opening_moves(first_sents),
        "closing": _structural_mod.closing_moves(last_sents),
        "scaffold": _structural_mod.scaffold_shape(joined),
        "formatting": _structural_mod.formatting(joined),
        "length": _structural_mod.length_stats(joined),
        "recurring": _structural_mod.recurring(joined),
    }


# ---------------------------------------------------------------- registry helpers

def select(registry: AnalyzerRegistry, names: list[str] | None) -> AnalyzerRegistry:
    """A registry with only the named analyzers (registry order preserved). ``None``
    keeps all. Raises on an unknown name so a config typo fails loudly."""
    if not names:
        return registry
    chosen = set(names)
    unknown = chosen - set(registry.names())
    if unknown:
        raise ValueError(f"unknown analyzer(s): {', '.join(sorted(unknown))}")
    out = AnalyzerRegistry()
    for a in registry.all():
        if a.name in chosen:
            out.add(a)
    return out


def default_analyzers() -> AnalyzerRegistry:
    """A fresh registry of the built-in analyzers: per-field value counts
    (``distribution``), per-axis evenness (``evenness``), coverage-vs-target quota
    checks (``coverage_vs_target``), Cramér's V anti-correlation (``correlation``),
    t-wise pair coverage (``combination_coverage``), intent→realization drift
    (``drift``, needs annotations), the categorical × embedding-cluster bridge
    (``cluster_bridge``, needs the semantic lane's cluster assignments), and the
    structural text signals (``structural``, needs texts). Register
    more on top; the axes YAML's ``analysis`` block selects which run."""
    reg = AnalyzerRegistry()
    reg.add(Analyzer(name="distribution", requires=("tags",), fn=_distribution))
    reg.add(Analyzer(name="evenness", requires=("tags",), fn=_evenness))
    reg.add(Analyzer(name="coverage_vs_target", requires=("tags",), fn=_coverage_vs_target))
    reg.add(Analyzer(name="correlation", requires=("tags",), fn=_correlation))
    reg.add(Analyzer(name="combination_coverage", requires=("tags",),
                     fn=_combination_coverage))
    reg.add(Analyzer(name="drift", requires=("tags", "annotations"), fn=_drift))
    reg.add(Analyzer(name="cluster_bridge", requires=("tags", "clusters"),
                     fn=_cluster_bridge))
    reg.add(Analyzer(name="structural", requires=("texts",), fn=_structural))
    return reg
