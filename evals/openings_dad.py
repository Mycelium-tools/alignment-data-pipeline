#!/usr/bin/env python3
"""Opening-shape audit for DAD runs: measures opener collapse across a corpus.

Per-response judges cannot see corpus properties, and the known failure here is
corpus-level: every reply entering through the same few moves ("you've already
answered your own question", "here's the thing", "let's separate two things") —
the reply-side analog of SDF's templated-openings failure. This script buckets
each response's first sentence into a small set of shape families (derived from
a survey of the July 2026 smoke runs; extend the list as new tics are found),
then reports the distribution, repeated openers, and — for multi-sample runs —
whether samples of the SAME case open differently (within-case spread, the
sharpest signal that opener variety is real rather than case-driven).

Offline and free by default. --embeddings adds a first-sentence semantic
near-dup check via OpenAI embeddings (OPENAI_API_KEY; cents, cached).

``evals/audit_dad.py`` renders these same checks (via ``stage_stats``) as
"Response openings" sections of the run's audit report, so the one-command
audit covers them; this standalone tool remains the deep dive — per-sentence
listings, --embeddings, and side-by-side multi-run comparison.

Usage:
    python evals/openings_dad.py --input outputs/dad/latest [--input <run> ...]
    python evals/openings_dad.py --input outputs/dad/latest --stage drafts
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import utils

# Shape families, first match wins. Patterns target the OBSERVED opener tics
# plus broad neutral families; "other" is the healthy bucket. Matched against a
# lightly normalized first sentence (lowercased, markdown emphasis stripped).
FAMILIES = [
    ("already-answered", re.compile(
        r"you('ve| have) ((basically|already|essentially) )*(answered|diagnosed|done|found|named|noticed|sensed?)"
        r"|you already (know|sense)")),
    ("heres-the-x", re.compile(r"^(ok(ay)?, )?here('s| is) (the|what|how|where|why|my)")),
    ("lets-separate", re.compile(
        r"^let'?s (separate|untangle|take|start|pull)"
        r"|(two|three) (separate|different) (things|questions|decisions)"
        r"|you('ve| have) (folded|bundled|stacked|tangled)")),
    ("validation", re.compile(
        r"^(this|that)('s| is) a ((genuinely|really) )?(good|great|fair|reasonable)"
        r"|^good (instinct|question|call)|^(a |what a )?(great|excellent) question")),
    ("x-is-right", re.compile(
        r"^your \w+('s| is)? (right|correct|wrong)|^you('re| are) (right|not wrong)")),
    ("reframe", re.compile(
        r"you('re| are) (framing|treating|weighing)|you('ve| have) framed"
        r"|the (actual|real) (decision|question|choice|issue) (here )?(is|isn)")),
    ("quoted-user", re.compile(r'^["“‘\']')),
    ("direct-address-of-ask", re.compile(r"^(yes|no|keep|flag|go|don'?t|it depends)\b")),
]


def first_sentence(text: str) -> str:
    """The response's first sentence, with markdown headers/emphasis stripped
    so '**The core issue.** ...' and 'The core issue. ...' bucket together."""
    t = (text or "").strip()
    t = re.sub(r"^#+\s*", "", t)          # markdown heading marker
    t = t.replace("**", "").replace("*", "")
    m = re.search(r"[.!?](\s|$)", t)
    return (t[: m.end()] if m else t[:200]).strip()


def family_of(sentence: str) -> str:
    s = sentence.lower().strip()
    for name, pat in FAMILIES:
        if pat.search(s):
            return name
    return "other"


# Words that never count as a hint card's distinctive wording on their own.
_ECHO_STOPWORDS = frozenset(
    "open with the a an of from or on by in to and it is as at for that then "
    "what where user user's reply case asked has been most".split())


def card_echoes(sentence: str, card: str) -> bool:
    """True when the opener shares a verbatim 3-word run with a drawn hint card
    — the card donating its WORDING rather than its shape (the failure the
    hint mechanism must not introduce). All-stopword runs don't count."""
    s = re.sub(r"[^a-z' ]", " ", sentence.lower())
    s_words = s.split()
    s_grams = {" ".join(s_words[i:i + 3]) for i in range(len(s_words) - 2)}
    c_words = re.sub(r"[^a-z' ]", " ", card.lower()).split()
    for i in range(len(c_words) - 2):
        gram = c_words[i:i + 3]
        if all(w in _ECHO_STOPWORDS for w in gram):
            continue
        if " ".join(gram) in s_grams:
            return True
    return False


def load_responses(run_dir: Path, stage: str) -> list[dict]:
    """[{prompt_id, sample_index, text, opening_hints}] for one stage
    ('drafts' or 'finals'). Hints ride only the draft records — step 3
    preserves openers, so echo is measured where it is introduced."""
    if stage == "drafts":
        return [
            {"prompt_id": r.get("prompt_id"), "sample_index": r.get("sample_index", 0),
             "text": r.get("assistant_response", ""),
             "opening_hints": r.get("opening_hints", "")}
            for r in utils.load_jsonl(run_dir / "step2" / "responses.jsonl")
        ]
    rewrites = {r.get("record_id"): r for r in utils.load_jsonl(run_dir / "step3" / "rewrites.jsonl")}
    out = []
    for rec in utils.load_jsonl(run_dir / "final" / "dad_corpus.jsonl"):
        audit = rewrites.get(rec.get("record_id"), {})
        msgs = rec.get("messages") or []
        out.append({"prompt_id": audit.get("prompt_id"), "sample_index": audit.get("sample_index", 0),
                    "text": msgs[1]["content"] if len(msgs) > 1 else ""})
    return out


def stage_stats(rows: list[dict]) -> dict:
    """Aggregate one stage's responses (no printing): opener families,
    within-case spread, repeated first-3-word runs, and hint-card echo. The
    pure half of ``report``; ``evals/audit_dad.py`` renders these same numbers
    as sections of the run's audit report."""
    sentences = [first_sentence(r["text"]) for r in rows]
    fams = [family_of(s) for s in sentences]
    counts = Counter(fams)
    top_fam, top_n = counts.most_common(1)[0]

    # within-case spread: for multi-sample runs, do samples of one case differ?
    by_case = defaultdict(list)
    for r, f in zip(rows, fams):
        by_case[r["prompt_id"]].append(f)
    multi = {pid: fs for pid, fs in by_case.items() if len(fs) > 1}
    case_spread = ({pid: f"{len(set(fs))}/{len(fs)} distinct" for pid, fs in sorted(multi.items())}
                   if multi else None)

    trigrams = Counter(" ".join(s.split()[:3]).lower() for s in sentences)
    repeated = {k: v for k, v in trigrams.most_common(5) if v > 1}

    # hint-echo rate per card: of the responses that DREW a card, how many
    # openers borrowed its wording (runs before hint sampling have no draws)
    draws, echoes = Counter(), Counter()
    for r, s in zip(rows, sentences):
        for card in filter(None, (r.get("opening_hints") or "").split("; ")):
            draws[card] += 1
            if card_echoes(s, card):
                echoes[card] += 1

    return {"n": len(rows), "families": dict(counts), "fams": fams,
            "top_family": top_fam, "top_share": top_n / len(rows),
            "case_spread": case_spread, "repeated_first3": repeated,
            "hint_echo": {c: (echoes[c], draws[c]) for c in echoes},
            "hint_draws": dict(draws), "sentences": sentences}


def report(run_dir: Path, stage: str) -> dict:
    """Print one stage's opening-shape report; return the stats for callers/tests."""
    rows = [r for r in load_responses(run_dir, stage) if r["text"].strip()]
    if not rows:
        print(f"  [{stage}] no responses found")
        return {"n": 0}
    stats = stage_stats(rows)
    counts = Counter(stats["families"])
    print(f"  [{stage}] {stats['n']} responses | families: "
          + ", ".join(f"{f} {n}" for f, n in counts.most_common())
          + f" | top family {max(counts.values())}/{stats['n']}")
    if stats["case_spread"]:
        print("    within-case spread: "
              + ", ".join(f"{p}: {v}" for p, v in stats["case_spread"].items()))
    if stats["repeated_first3"]:
        print(f"    repeated first-3-words: {stats['repeated_first3']}")
    if stats["hint_echo"]:
        print("    hint-echo (card wording in opener / times drawn): "
              + ", ".join(f"{c!r} {e}/{d}" for c, (e, d) in stats["hint_echo"].items()))
    for s, f in zip(stats["sentences"], stats["fams"]):
        print(f"      [{f:>22}] {s[:100]}")
    return stats


def embedding_report(run_dir: Path, stage: str, threshold: float = 0.9) -> None:
    """Optional paid check: pairwise cosine of first sentences (regex families
    can miss a collapse that keeps the wording but changes the surface form)."""
    from shared import embeddings
    rows = [r for r in load_responses(run_dir, stage) if r["text"].strip()]
    sents = [first_sentence(r["text"]) for r in rows]
    if len(sents) < 2:
        return
    x = embeddings.embed_texts(sents)
    sims = x @ x.T
    pairs = [(i, j, float(sims[i, j])) for i in range(len(sents))
             for j in range(i + 1, len(sents)) if sims[i, j] > threshold]
    mean_off = float((sims.sum() - len(sents)) / (len(sents) * (len(sents) - 1)))
    print(f"    embeddings: mean pairwise cosine {mean_off:.3f}, "
          f"{len(pairs)} first-sentence pairs above {threshold}")
    for i, j, s in sorted(pairs, key=lambda p: -p[2])[:5]:
        print(f"      {s:.3f}  {sents[i][:60]!r} ~ {sents[j][:60]!r}")


def prompt_length_report(run_dir: Path) -> dict:
    """User-message length audit for step 1: overall char spread, plus — on runs
    whose records carry a dealt ``length_class`` — realized chars per class. The
    dealt length register is an instruction to the model, not an enforced band,
    so this is purely descriptive: it shows what each register realized as,
    never a pass/fail against a target."""
    recs = [r for r in utils.load_jsonl(run_dir / "step1" / "dilemmas.jsonl")
            if (r.get("user_message") or "").strip()]
    if not recs:
        print("  [prompt lengths] no dilemmas found")
        return {"n": 0}
    lens = sorted(len(r["user_message"].strip()) for r in recs)
    median = lens[len(lens) // 2]
    print(f"  [prompt lengths] {len(recs)} prompts | chars min {lens[0]} / "
          f"median {median} / max {lens[-1]} | {sum(l > 1000 for l in lens)} over 1000")

    by_class: dict = defaultdict(list)
    for r in recs:
        if r.get("length_class"):
            by_class[r["length_class"]].append(len(r["user_message"].strip()))
    # short → long: order classes by their realized median (no bands to sort by)
    for cls in sorted(by_class, key=lambda c: sorted(by_class[c])[len(by_class[c]) // 2]):
        vals = sorted(by_class[cls])
        print(f"    {cls:>16}: n={len(vals)}, chars {vals[0]}-{vals[-1]}, "
              f"median {vals[len(vals) // 2]}")
    if not by_class:
        print("    (records carry no length_class — pre-dice run)")
    return {"n": len(recs), "median": median, "min": lens[0], "max": lens[-1],
            "over_1000": sum(l > 1000 for l in lens),
            "by_class": {c: sorted(v) for c, v in by_class.items()}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Opening-shape audit for DAD runs.")
    parser.add_argument("--input", action="append", required=True,
                        help="Run dir (or outputs/dad/latest); repeat to compare runs.")
    parser.add_argument("--stage", choices=("drafts", "finals", "both"), default="both")
    parser.add_argument("--embeddings", action="store_true",
                        help="Add the paid first-sentence semantic near-dup check.")
    args = parser.parse_args()

    stages = ("drafts", "finals") if args.stage == "both" else (args.stage,)
    for inp in args.input:
        run_dir = Path(inp).resolve()
        print(f"\n=== {run_dir.name} ===")
        prompt_length_report(run_dir)
        for stage in stages:
            report(run_dir, stage)
            if args.embeddings:
                embedding_report(run_dir, stage)


if __name__ == "__main__":
    main()
