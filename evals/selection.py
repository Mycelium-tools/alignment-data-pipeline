"""Pure selection grammar over a run's records: filter by categorical facet, then
pick a subset. Shared by the holistic CLI, the quality-judge CLI, and the viewer's
batch page so "open a run and choose which examples to judge" behaves identically
everywhere. No I/O, no API — just lists in, ids out.

A "row" is any dict carrying ``record_id`` plus categorical fields (an extraction
tag row, a pipeline annotation, or a legacy step record). Facet matching handles both
scalar and list-valued fields.
"""

from __future__ import annotations

import argparse
import random
from typing import Iterable

PICK_MODES = ("All", "First N", "Range", "Random N", "Hand-pick")


# ---------------------------------------------------------------- filtering

def matches(row: dict, where: dict[str, Iterable]) -> bool:
    """True if ``row`` satisfies every facet. A facet ``axis -> allowed`` matches when
    the row's value is in ``allowed`` (scalar) or shares any element with it (list)."""
    for axis, allowed in where.items():
        # a bare string is a single allowed value, not a set of characters
        allowed = {allowed} if isinstance(allowed, str) else set(allowed)
        val = row.get(axis)
        if isinstance(val, list):
            if not set(val) & allowed:
                return False
        elif val not in allowed:
            return False
    return True


def filter_records(rows: list[dict], where: dict[str, Iterable] | None) -> list[dict]:
    """Rows matching all facets, in original order. Empty/None ``where`` = all rows."""
    if not where:
        return list(rows)
    return [r for r in rows if matches(r, where)]


# ---------------------------------------------------------------- picking

def pick_subset(ids: list[str], mode: str, *, n: int | None = None,
                start: int | None = None, end: int | None = None,
                handpicked: list[str] | None = None, seed: int = 0) -> list[str]:
    """Narrow ``ids`` to the chosen subset. ``Range`` is 1-based inclusive;
    ``Random N`` is seed-deterministic and preserves original order for readability."""
    if mode == "First N":
        return ids[: max(n or 0, 0)]
    if mode == "Range":
        lo = max((start or 1), 1) - 1
        return ids[lo: end if end is not None else len(ids)]
    if mode == "Random N":
        unique = list(dict.fromkeys(ids))          # dedup, order-preserving
        k = min(max(n or 0, 0), len(unique))
        chosen = set(random.Random(seed).sample(unique, k))
        return [i for i in unique if i in chosen]
    if mode == "Hand-pick":
        picked = set(handpicked or [])
        seen: set = set()
        return [i for i in ids if i in picked and not (i in seen or seen.add(i))]
    return list(ids)  # All


# ---------------------------------------------------------------- composition

def select(rows: list[dict], *, where: dict[str, Iterable] | None = None,
           mode: str = "All", **pick_kwargs) -> list[str]:
    """Filter then pick, returning record_ids."""
    ids = [r["record_id"] for r in filter_records(rows, where)]
    return pick_subset(ids, mode, **pick_kwargs)


# ---------------------------------------------------------------- CLI grammar

def parse_where(entries: list[str] | None) -> dict[str, set[str]]:
    """``--where axis=v1,v2`` flags (repeatable) -> a ``where`` mapping. Repeated
    flags for the same axis union their values. Malformed entries fail loudly."""
    where: dict[str, set[str]] = {}
    for entry in entries or []:
        axis, sep, raw = entry.partition("=")
        values = {v.strip() for v in raw.split(",") if v.strip()}
        if not sep or not axis.strip() or not values:
            raise ValueError(
                f"--where expects axis=value[,value...], got {entry!r}")
        where.setdefault(axis.strip(), set()).update(values)
    return where


def nonneg_int(raw: str) -> int:
    """argparse type for ``--limit``/``--sample``: a negative value is a typo that
    would otherwise silently select zero records."""
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {raw}")
    return value


def parse_ids(raw: str | None) -> list[str] | None:
    """``--ids a,b,c`` -> ['a', 'b', 'c']; empty/None -> None (no id filter)."""
    if not raw:
        return None
    return [i.strip() for i in raw.split(",") if i.strip()]


def apply_cli_selection(records: list[dict], *, index: dict[str, dict] | None = None,
                        where: dict[str, Iterable] | None = None,
                        ids: list[str] | None = None, sample: int | None = None,
                        seed: int = 0, limit: int | None = None) -> list[dict]:
    """The shared CLI narrowing: filter ``records`` by facets (matched against the
    ``index`` row when given — e.g. corpus records faceted by their extraction tags —
    else against the record itself), keep only ``ids`` if given, then pick First-
    ``limit`` or seeded Random-``sample``. Order-preserving and pure."""
    out = records
    if where:
        rows = out if index is None else [index.get(r.get("record_id"), {}) for r in out]
        out = [rec for rec, row in zip(out, rows) if matches(row, where)] \
            if index is not None else filter_records(out, where)
    if ids is not None:
        wanted = set(ids)
        out = [r for r in out if r.get("record_id") in wanted]
    if limit is not None:
        out = out[: max(limit, 0)]
    if sample is not None:
        # Sample positions, not ids: a duplicate record_id (corrupt corpus) must not
        # re-expand one chosen id into several rows and exceed the requested N.
        positions = pick_subset([str(i) for i in range(len(out))], "Random N",
                                n=sample, seed=seed)
        out = [out[int(i)] for i in positions]
    return list(out)
