"""Corpus text statistics: truncation repair and near-duplicate detection.

Deliberately embedding-free: near-duplicate detection uses cosine similarity
over hashed word-shingle count vectors (crc32 feature hashing), which is
deterministic across sessions, needs no GPU and no new heavy dependencies, and
catches the duplication that matters most in synthetic training data — same
skeleton, same phrasing. It will not catch pure paraphrase-level semantic
duplication; the audit tool's LLM pattern pass covers that angle.

Scale envelope: the pairwise scan is O(n²) in documents with hashed vectors of
dimension 16384 (float32), comfortable to ~10k documents on a laptop. Beyond
that, subsample (see evals/audit_sdf.py --dup-sample) or move to embeddings.
"""

from __future__ import annotations

import re
import zlib

import numpy as np

# Sentence-final characters: a document ending on one of these is treated as
# complete. Includes closing quotes/brackets/ellipsis so quoted or parenthesized
# endings don't count as truncation.
_TERMINAL_CHARS = '.!?"\'”’)…]:'

_WORD_RE = re.compile(r"[\w']+")

DIM = 1 << 14  # 16384 hashed shingle buckets


def trim_unfinished(text: str) -> str:
    """Cut a token-capped output back to its last complete sentence.

    Outputs that hit a max-token cap end mid-sentence, and a mid-sentence
    cutoff is exactly the artifact we don't want a model trained on this
    corpus to learn. Only trims when a sentence boundary exists in the second
    half of the text, so a legitimately unpunctuated text is left alone.
    """
    if not text:
        return text
    t = text.rstrip()
    if not t or t[-1] in _TERMINAL_CHARS:
        return t
    cut = max(t.rfind("."), t.rfind("!"), t.rfind("?"), t.rfind("\n"))
    if cut > len(t) * 0.5:
        return t[: cut + 1].rstrip()
    return t


_SEPARATOR_LINE_RE = re.compile(r"^[\s\-=*_~#]+$")


def strip_trailing_separators(text: str) -> str:
    """Drop trailing lines that are only separator characters (---, ***, ===).

    Generators sometimes close a document with a bare horizontal rule; that is
    a delimiter artifact, not a mid-sentence truncation, and the two need to be
    reported separately.
    """
    lines = (text or "").rstrip().splitlines()
    while lines and _SEPARATOR_LINE_RE.match(lines[-1]):
        lines.pop()
    return "\n".join(lines).rstrip()


def ends_mid_sentence(text: str) -> bool:
    """True if the text ends without sentence-final punctuation (truncation tell).

    Trailing separator-only lines are ignored — see strip_trailing_separators.
    """
    t = strip_trailing_separators(text)
    return bool(t) and t[-1] not in _TERMINAL_CHARS


def has_trailing_separator(text: str) -> bool:
    """True if the text ends with one or more separator-only lines (--- etc.)."""
    t = (text or "").rstrip()
    return bool(t) and t != strip_trailing_separators(text)


def normalize_for_match(text: str) -> str:
    """Collapse whitespace and case for verbatim-containment checks."""
    return re.sub(r"\s+", " ", (text or "")).strip().casefold()


def _shingles(text: str, n: int = 3):
    words = _WORD_RE.findall((text or "").casefold())
    if not words:
        return
    if len(words) < n:
        yield " ".join(words)
        return
    for i in range(len(words) - n + 1):
        yield " ".join(words[i : i + n])


def shingle_vector(text: str, n: int = 3) -> np.ndarray:
    """L2-normalized hashed word-n-gram count vector (deterministic via crc32)."""
    v = np.zeros(DIM, dtype=np.float32)
    for g in _shingles(text, n):
        v[zlib.crc32(g.encode("utf-8")) % DIM] += 1.0
    norm = float(np.linalg.norm(v))
    if norm > 0:
        v /= norm
    return v


def shingle_matrix(texts: list[str], n: int = 3) -> np.ndarray:
    return np.stack([shingle_vector(t, n) for t in texts]) if texts else np.zeros((0, DIM), np.float32)


def near_dup_filter(
    texts: list[str], threshold: float, n: int = 3
) -> tuple[list[int], list[dict]]:
    """Greedy keep-first near-duplicate filter.

    Returns (keep_indices, dropped) where each dropped entry is
    {"index", "kept_index", "similarity"}: texts[index] was dropped for being
    within `threshold` cosine of the earlier kept texts[kept_index]. Greedy
    keep-first makes the result order-stable, so resumed runs and reruns drop
    the same items.
    """
    keep: list[int] = []
    dropped: list[dict] = []
    if not texts:
        return keep, dropped
    X = shingle_matrix(texts, n)
    kept_rows = np.zeros((len(texts), DIM), dtype=np.float32)
    for i in range(len(texts)):
        if keep:
            sims = kept_rows[: len(keep)] @ X[i]
            j = int(np.argmax(sims))
            if float(sims[j]) >= threshold:
                dropped.append(
                    {"index": i, "kept_index": keep[j], "similarity": round(float(sims[j]), 4)}
                )
                continue
        kept_rows[len(keep)] = X[i]
        keep.append(i)
    return keep, dropped


def nearest_neighbor_sims(texts: list[str], n: int = 3, block: int = 512) -> np.ndarray:
    """Cosine similarity of each text to its nearest neighbor (for audit stats)."""
    if len(texts) < 2:
        return np.zeros(len(texts), dtype=np.float32)
    X = shingle_matrix(texts, n)
    out = np.empty(len(texts), dtype=np.float32)
    for i in range(0, len(texts), block):
        sims = X[i : i + block] @ X.T
        rows = sims.shape[0]
        sims[np.arange(rows), np.arange(i, i + rows)] = -1.0  # mask self-similarity
        out[i : i + rows] = sims.max(axis=1)
    return out
