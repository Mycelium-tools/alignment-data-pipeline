"""Cross-record phrase repetition for DAD assistant responses.

The DAD counterpart of evals/audit_sdf.py's stock-phrase check: per-record judges
cannot see that every response reaches for the same idiom, so repetition is
measured over the corpus as a set. Two layers, both offline and free:

- a fixed lexicon of known assistant tics ("it's worth noting", ...) whose
  document frequency is a defect at any real rate, and
- discovery — every word 5-gram that recurs across multiple records — which
  catches the idioms nobody thought to blocklist ("this is a real nail-biter").

Shared topic makes some overlap normal (the discovery list is judged by eye);
the verdict keys off the lexicon and the worst discovery document-frequency.
"""

from __future__ import annotations

import collections
import math
import re

# Known assistant-response tics. English-only heuristic — non-English records
# simply won't hit them. The discovery layer below is the catch-all; add here
# only phrases confirmed as recurring tics so the verdict stays meaningful.
AI_STOCK_PHRASES = [
    "it's important to note", "it is important to note",
    "it's worth noting", "it is worth noting",
    "i want to acknowledge", "i hear you",
    "there's no easy answer", "there is no easy answer",
    "at the end of the day", "navigating this",
    "strikes a balance", "a testament to", "delve into",
    "ultimately, the decision is yours",
    "this is a genuinely difficult",
]

# Typographic apostrophes folded to ASCII so "it’s" hits the straight-quote
# lexicon; \w keeps non-ASCII letters (and digits) so non-English idioms still
# reach the discovery layer.
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'"})
_WORD_RE = re.compile(r"[\w']+")


def assistant_text(record: dict) -> str:
    return "\n".join(m.get("content") or "" for m in record.get("messages", [])
                     if m.get("role") == "assistant")


def phrase_report(texts: list[str], lexicon: list[str] = AI_STOCK_PHRASES, *,
                  gram_n: int = 5, top: int = 10) -> dict:
    """Lexicon hits + recurring n-gram discovery over one text per record.

    Document frequency (records containing the phrase), not raw counts — one
    response using an idiom five times is style; five responses sharing it is a
    template. Returns {"n", "lexicon_hits", "recurring_ngrams", "verdict"}.
    """
    n = len(texts)
    lowered = [t.lower().translate(_APOSTROPHES) for t in texts]

    lexicon_hits = {p: sum(1 for t in lowered if p in t) for p in lexicon}
    lexicon_hits = {p: c for p, c in lexicon_hits.items() if c}

    gram_df: collections.Counter = collections.Counter()
    for t in lowered:
        words = _WORD_RE.findall(t)
        grams = {" ".join(words[i:i + gram_n]) for i in range(len(words) - gram_n + 1)}
        gram_df.update(grams)
    floor = max(2, math.ceil(0.05 * n))  # 2 records minimum, ≥5% of corpus at scale
    recurring = [(g, c) for g, c in gram_df.most_common(500) if c >= floor][:top]

    worst = max([*lexicon_hits.values(),
                 *(c for _, c in recurring)], default=0)
    if n == 0:
        verdict = "NA"
    elif not lexicon_hits and worst <= max(2, 0.10 * n):
        verdict = "GOOD"
    elif worst <= max(2, 0.25 * n):
        verdict = "OK"
    else:
        verdict = "BAD"

    return {
        "n": n,
        "lexicon_hits": dict(sorted(lexicon_hits.items(), key=lambda kv: -kv[1])),
        "recurring_ngrams": [{"phrase": g, "records": c} for g, c in recurring],
        "verdict": verdict,
    }
