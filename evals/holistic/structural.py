"""Structural-diversity metrics over DAD assistant turns — pure, offline, no API.

The holistic categorical analyzers read extraction *tags*; none of them see the
assistant's prose, so response-form collapse (every reply opening, closing, and
shaped the same) is invisible to them. These functions measure that form over the
raw assistant turns. They are the mechanical cousins of the SDF audit's structural
checks (evals/audit_sdf.py), reimplemented here so that working CLI is left
untouched.

Every metric returns a JSON-able dict with an ``n`` and a GOOD/OK/BAD ``verdict``
(same vocabulary as evals/holistic/analyzers.py and evals/diversity.py; a private
copy of ``_verdict`` avoids importing analyzers, which imports this module).
Thresholds are provisional; the reliable read is comparing runs.
"""

from __future__ import annotations

import collections
import re

from shared import textstats


def _verdict(value: float | None, good: float, ok: float,
             higher_better: bool = False) -> str:
    if value is None:
        return "NA"
    if higher_better:
        return "GOOD" if value >= good else ("OK" if value >= ok else "BAD")
    return "GOOD" if value <= good else ("OK" if value <= ok else "BAD")


# ---------------------------------------------------------------- text access

def assistant_turns(record: dict) -> list[str]:
    """The ``content`` of each ``role == 'assistant'`` message, in order."""
    return [m.get("content") or "" for m in record.get("messages", [])
            if m.get("role") == "assistant"]


def first_sentence(text: str) -> str:
    t = (text or "").strip()
    for line in t.splitlines():
        line = line.strip()
        if line:
            t = line
            break
    m = re.search(r"[.!?]", t)
    return t[: m.end()] if m else t[:160]


def last_sentence(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    parts = [p for p in re.split(r"(?<=[.!?])\s+", lines[-1]) if p.strip()]
    return parts[-1] if parts else lines[-1][:160]


# ---------------------------------------------------------------- closing moves
# Opening detection is intentionally NOT here: the corpus's `response_opening_move`
# categorical axis (LLM-tagged) covers opening *strategy*, and evals/holistic/phrases.py
# catches verbatim opener repetition. This module owns the response-form signals those
# do not: closing templating, the considerations-list scaffold, markdown, and truncation.

_CLOSER_PATTERNS = [
    (re.compile(r"\bultimately\b", re.I), "Ultimately, ..."),
    (re.compile(r"\b(the\s+choice|the\s+decision)\s+is\s+yours\b", re.I), "The choice is yours"),
    (re.compile(r"\bin\s+the\s+end\b", re.I), "In the end ..."),
    (re.compile(r"\bwhat\s+matters\s+(most\s+)?is\b", re.I), "What matters most is ..."),
    (re.compile(r"\b(i\s+hope\s+this\s+helps|hope\s+that\s+helps)\b", re.I), "I hope this helps"),
    (re.compile(r"\bfeel\s+free\s+to\b", re.I), "Feel free to ..."),
    (re.compile(r"\bat\s+the\s+end\s+of\s+the\s+day\b", re.I), "At the end of the day ..."),
]


def _move_shapes(sentences: list[str], patterns, from_end: bool) -> dict:
    n = len(sentences)
    if not n:
        return {"n": 0, "formulaic_frac": None, "patterns": {}, "dup_stems": [],
                "verdict": "NA"}
    pattern_counts: collections.Counter = collections.Counter()
    for s in sentences:
        for rx, label in patterns:
            if rx.search(s.strip()):
                pattern_counts[label] += 1
                break

    def stem(s: str) -> str:
        w = s.lower().split()
        return " ".join(w[-5:] if from_end else w[:5])

    stems = collections.Counter(stem(s) for s in sentences if s.strip())
    dup_stems = [(s, c) for s, c in stems.most_common(5) if c >= 2]
    formulaic = sum(pattern_counts.values()) / n
    return {"n": n, "formulaic_frac": round(formulaic, 3),
            "patterns": dict(pattern_counts), "dup_stems": dup_stems,
            "verdict": _verdict(formulaic, 0.15, 0.35)}


def closing_moves(last_sentences: list[str]) -> dict:
    return _move_shapes(last_sentences, _CLOSER_PATTERNS, from_end=True)


# ---------------------------------------------------------------- scaffold shape

_ENUM_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+", re.M)
_HEADER_RE = re.compile(r"^#{1,4}\s", re.M)
_CONSIDER_RE = re.compile(
    r"\b(considerations?|factors?\s+to\s+consider|things?\s+to\s+consider|"
    r"a\s+few\s+(things|points|considerations)|several\s+(factors|considerations|things))\b",
    re.I)


def scaffold_shape(texts: list[str]) -> dict:
    n = len(texts)
    if not n:
        return {"n": 0, "enumerated_list_frac": None, "header_frac": None,
                "considerations_frac": None, "arc_frac": None, "verdict": "NA"}
    enum = sum(1 for t in texts if _ENUM_RE.search(t))
    header = sum(1 for t in texts if _HEADER_RE.search(t))
    consider = sum(1 for t in texts if _CONSIDER_RE.search(t))
    arc = sum(1 for t in texts if _CONSIDER_RE.search(t) and _ENUM_RE.search(t))
    arc_frac = arc / n
    return {"n": n,
            "enumerated_list_frac": round(enum / n, 3),
            "header_frac": round(header / n, 3),
            "considerations_frac": round(consider / n, 3),
            "arc_frac": round(arc_frac, 3),
            "verdict": _verdict(arc_frac, 0.20, 0.40)}


# ---------------------------------------------------------------- formatting / length

_MD_CLASSES = {
    "bold": re.compile(r"\*\*[^*\n]+\*\*"),
    "bullets": re.compile(r"^[-*] ", re.M),
    "headings": re.compile(r"^#{1,4} ", re.M),
}


def formatting(texts: list[str]) -> dict:
    n = len(texts)
    if not n:
        return {"n": 0, "by_class": {}, "bold_frac": None, "verdict": "NA"}
    counts = {k: sum(1 for t in texts if rx.search(t)) for k, rx in _MD_CLASSES.items()}
    bold_frac = counts["bold"] / n
    return {"n": n, "by_class": {k: round(c / n, 3) for k, c in counts.items()},
            "bold_frac": round(bold_frac, 3),
            "verdict": _verdict(bold_frac, 0.10, 0.30)}


def length_stats(texts: list[str]) -> dict:
    n = len(texts)
    if not n:
        return {"n": 0, "chars_median": None, "truncated_frac": None, "verdict": "NA"}
    lengths = sorted(len(t) for t in texts)
    truncated = sum(1 for t in texts if textstats.ends_mid_sentence(t))
    frac = truncated / n
    return {"n": n,
            "chars_p10": lengths[max(0, n // 10)],
            "chars_median": lengths[n // 2],
            "chars_p90": lengths[min(n - 1, 9 * n // 10)],
            "truncated_frac": round(frac, 4),
            "verdict": _verdict(frac, 0.0, 0.02)}
