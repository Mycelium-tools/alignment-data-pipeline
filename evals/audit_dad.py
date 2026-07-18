#!/usr/bin/env python3
"""Corpus-level audit of DAD step-1 prompts: structural repetition and realization.

The per-example step-1 checklist (``dad_pipeline/step1_dilemmas.checklist``) audits
the ANNOTATION — the label the model wrote alongside each draft — not the shipped
``user_message``. So it is blind to text-level, corpus-level failures: many prompts
sharing one structural skeleton (the "must produce/decide something by a deadline"
shape), the same opener or closer across the set, a dealt ``frontier_frame`` that
never surfaces in the text, or a taxa/locale pairing that does not cohere. This
tool reads the shipped prompt text AS A SET, the reply-side analog of what
``evals/audit_sdf.py`` does for the SDF corpus.

Offline and free — no API calls — so it can run after every step 1. Each check
prints a GOOD/OK/BAD verdict where a threshold is meaningful; the run's
``audit/audit_report.json`` is written for run-over-run comparison.

The length-class realization check is delegated to
``evals/openings_dad.prompt_length_report`` (dealt class vs realized chars), which
already owns it — this tool does not reimplement it.

Usage:
  python evals/audit_dad.py                                  # audits outputs/dad/latest
  python evals/audit_dad.py --input outputs/dad/runs/<id>    # a specific run dir
  python evals/audit_dad.py --input some/dilemmas.jsonl      # a bare step-1 jsonl
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import utils

# ---------------------------------------------------------------- verdicts


def _verdict(value: float, good: float, ok: float, higher_better: bool = False) -> str:
    if higher_better:
        return "GOOD" if value >= good else ("OK" if value >= ok else "BAD")
    return "GOOD" if value <= good else ("OK" if value <= ok else "BAD")


def _fmt(label: str, value: str, verdict: str | None = None, note: str = "") -> str:
    tail = f"  [{verdict}]" if verdict else ""
    tail += f"  {note}" if note else ""
    return f"   {label:<34} {value}{tail}"


# ---------------------------------------------------------------- input resolution


def resolve_input(input_arg: str) -> tuple[list[dict], Path, Path | None]:
    """Return (records, report_dir, run_dir). Accepts a run dir or a JSONL file.

    run_dir is the run directory when the input resolves to one (so the length
    report can find ``step1/dilemmas.jsonl``), else None for a bare file."""
    path = Path(input_arg)
    if path.is_dir():
        dilemmas = path / "step1" / "dilemmas.jsonl"
        if not dilemmas.exists():
            raise SystemExit(f"No step1/dilemmas.jsonl under {path}")
        return utils.load_jsonl(dilemmas), path / "audit", path
    if not path.exists():
        raise SystemExit(f"Input not found: {path}")
    return utils.load_jsonl(path), path.parent / "audit", None


def _messages(records: list[dict]) -> list[str]:
    return [str(r.get("user_message") or "").strip() for r in records
            if str(r.get("user_message") or "").strip()]


# ---------------------------------------------------------------- skeletons

# Structural tics the reviewer flagged (the opus-10 run converged on the
# "produce/decide something by a deadline" shape). First match wins per prompt;
# "other" is the healthy bucket. Matched against the lowercased message.
_SKELETONS = [
    ("deadline/time-pressure", re.compile(
        r"\bdue (by |on |this )?\w+|by (mon|tues|wednes|thurs|fri|satur|sun)day"
        r"|\b(this|next) (week|weekend)\b|\bby (tonight|tomorrow|the weekend|the deadline)\b"
        r"|\bdeadline\b|\bmeet(s|ing)? (next|this) week\b|\bbefore (the|our|my|it) \w+ (meet|gather|start|arriv)")),
    ("asked-to-produce", re.compile(
        r"\basked to (write|make|draft|prepare|sign|recommend|put together|argue|pitch)\b"
        r"|\bwrite (it |the |a |up|-up)\b|\bwrite up\b|\bmake the case\b|\bsign off\b"
        r"|\bget the wording right\b|\bdraft(ed|ing)? (the|a|up|our|my)\b")),
    ("two-paths-choice", re.compile(
        r"\btwo (paths|options|choices|roads)\b|\bone is to .*(the other|or )"
        r"|\beither .* or (i|we|to)\b")),
    ("validation-seeking", re.compile(
        r"\bam i (overthinking|being (crazy|ridiculous|unreasonable|paranoid|silly)|losing my mind|wrong)\b"
        r"|\btell me i'?m not\b|\bneed someone to tell me\b")),
]


def _skeleton_of(msg: str) -> str:
    s = msg.lower()
    for name, pat in _SKELETONS:
        if pat.search(s):
            return name
    return "other"


def audit_skeletons(records: list[dict], report: dict) -> None:
    print(" Structural skeletons")
    msgs = _messages(records)
    if not msgs:
        print(_fmt("prompts", "0"))
        report["skeletons"] = {"n": 0}
        return
    fams = [_skeleton_of(m) for m in msgs]
    counts = Counter(fams)
    n = len(msgs)
    # The named failure is the produce-by-deadline skeleton: the share of prompts
    # hitting the deadline OR asked-to-produce family (co-firing counts once).
    produce_by_deadline = sum(
        1 for m in msgs
        if _SKELETONS[0][1].search(m.lower()) or _SKELETONS[1][1].search(m.lower()))
    top_fam, top_n = counts.most_common(1)[0]
    non_other = {f: c for f, c in counts.items() if f != "other"}
    worst_fam, worst_n = (max(non_other.items(), key=lambda kv: kv[1])
                          if non_other else ("—", 0))

    print(_fmt("families", ", ".join(f"{f} {c}" for f, c in counts.most_common())))
    print(_fmt("produce-by-deadline share", f"{produce_by_deadline}/{n} ({produce_by_deadline / n:.0%})",
               _verdict(produce_by_deadline / n, 0.30, 0.50)))
    print(_fmt("top non-'other' skeleton", f"{worst_fam} {worst_n}/{n} ({worst_n / n:.0%})",
               _verdict(worst_n / n, 0.30, 0.50)))
    report["skeletons"] = {
        "n": n, "families": dict(counts),
        "produce_by_deadline": produce_by_deadline,
        "produce_by_deadline_share": produce_by_deadline / n,
        "top_family": top_fam, "top_share": top_n / n,
    }


# ---------------------------------------------------------------- openers & closers


def _first_words(msg: str, k: int = 3) -> str:
    words = re.sub(r"[^a-z' ]", " ", msg.lower()).split()
    return " ".join(words[:k])


def _last_sentence(msg: str) -> str:
    t = msg.strip()
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", t) if p.strip()]
    return parts[-1] if parts else t


def audit_openers_closers(records: list[dict], report: dict) -> None:
    print(" Openers & closers")
    msgs = _messages(records)
    if not msgs:
        print(_fmt("prompts", "0"))
        report["openers_closers"] = {"n": 0}
        return
    n = len(msgs)
    openers = Counter(_first_words(m) for m in msgs)
    # closer families: repeated final-sentence 3-word runs, and the "am I
    # overthinking"-style closing question the reviewer called out.
    closers = Counter(_first_words(_last_sentence(m)) for m in msgs)
    rep_open = {k: v for k, v in openers.most_common(5) if v > 1}
    rep_close = {k: v for k, v in closers.most_common(5) if v > 1}
    top_open = openers.most_common(1)[0][1] if openers else 0
    top_close = closers.most_common(1)[0][1] if closers else 0

    print(_fmt("distinct opening 3-words", f"{len(openers)}/{n}",
               _verdict(len(openers) / n, 0.90, 0.75, higher_better=True)))
    if rep_open:
        print(_fmt("repeated openers", str(rep_open)))
    print(_fmt("distinct closing 3-words", f"{len(closers)}/{n}",
               _verdict(len(closers) / n, 0.90, 0.75, higher_better=True)))
    if rep_close:
        print(_fmt("repeated closers", str(rep_close)))
    report["openers_closers"] = {
        "n": n, "distinct_openers": len(openers), "distinct_closers": len(closers),
        "top_opener_count": top_open, "top_closer_count": top_close,
        "repeated_openers": rep_open, "repeated_closers": rep_close,
    }


# ---------------------------------------------------------------- unrealized dealt details

# Distinctive words we expect to surface (in some form) when a frontier frame is
# dealt. Keyed by a stable substring of the frame text (robust to renumbering /
# rewording of the frame list), matched against the record's stored
# ``frontier_frame`` string. A record whose text contains NONE of its frame's
# keywords is flagged for review — heuristic, so a lexical miss is a prompt to
# eyeball, not a hard failure.
_FRONTIER_KEYWORDS = {
    "genetic engineering": ("engineer", "disenhance", "bred", "breed", "strain", "gene", "modif", "crispr"),
    "space or off-world": ("space", "off-world", "off world", "orbit", "station", "terraform",
                           "colony", "colonis", "coloniz", "surface", "mars", "lunar", "moon", "spaceship", "shuttle"),
    "digital emulation": ("upload", "emulat", "simulat", "connectome", "digital", "brain scan", "neural"),
    "simulated or video-game": ("game", "video", "virtual", "simulat", "npc", "in-world", "in game", "avatar"),
    "time-travel": ("time travel", "time-travel", "counterfactual", "timeline", "go back", "the past", "the future"),
    "second non-human agent": ("another ai", "second ai", "other ai", "the agent", "robot",
                               "the system", "engineered organism", "another model"),
}


def _frame_keywords(frame: str) -> tuple | None:
    f = (frame or "").lower()
    for key, words in _FRONTIER_KEYWORDS.items():
        if key in f:
            return words
    return None


def audit_unrealized_details(records: list[dict], report: dict) -> None:
    print(" Unrealized dealt details (frontier frame)")
    dealt = [r for r in records
             if str(r.get("frontier_frame") or "").strip()
             and str(r.get("user_message") or "").strip()]
    if not dealt:
        print(_fmt("prompts with a frontier frame", "0", note="(none dealt — nothing to check)"))
        report["unrealized_frontier"] = {"n_dealt": 0}
        return
    unrealized = []
    unmapped = 0
    for r in dealt:
        words = _frame_keywords(r.get("frontier_frame"))
        if words is None:
            unmapped += 1
            continue
        msg = str(r["user_message"]).lower()
        if not any(w in msg for w in words):
            unrealized.append(r.get("prompt_id") or r.get("scenario_id") or "?")
    checked = len(dealt) - unmapped
    frac = (len(unrealized) / checked) if checked else 0.0
    print(_fmt("frontier frames dealt", str(len(dealt))))
    print(_fmt("no lexical trace in text", f"{len(unrealized)}/{checked} ({frac:.0%})",
               _verdict(frac, 0.10, 0.30), note=(", ".join(unrealized) if unrealized else "")))
    if unmapped:
        print(_fmt("frames with no keyword map", str(unmapped),
                   note="(add to _FRONTIER_KEYWORDS to check)"))
    report["unrealized_frontier"] = {
        "n_dealt": len(dealt), "n_checked": checked,
        "unrealized_ids": unrealized, "unrealized_share": frac, "unmapped": unmapped,
    }


# ---------------------------------------------------------------- locale/taxa plausibility

# Warm/tropical cultural settings where cold-climate practices read as implausible.
_WARM_SETTINGS = frozenset({
    "Mediterranean Europe", "South Asia", "East Asia", "Southeast Asia",
    "Middle East / North Africa", "West Africa", "East Africa", "Southern Africa",
    "the Caribbean", "Central America", "Andean South America", "Pacific Islands",
})
# (taxa substring the record's taxa_subcategory contains) -> implausible settings +
# a one-line reason. Small and static by design; extend as real mismatches surface.
_LOCALE_TAXA_FLAGS = [
    ("fur animals", _WARM_SETTINGS, "fur farming (mink/foxes) is a cold-climate practice"),
    ("reindeer", _WARM_SETTINGS, "reindeer herding is a cold-climate practice"),
    ("yak", _WARM_SETTINGS, "yak husbandry is a highland/cold-climate practice"),
]


def audit_locale_taxa(records: list[dict], report: dict) -> None:
    print(" Locale / taxa plausibility")
    flags = []
    for r in records:
        sub = str(r.get("taxa_subcategory") or "").lower()
        setting = str(r.get("cultural_setting") or "").strip()
        if not sub or not setting:
            continue
        for needle, bad_settings, reason in _LOCALE_TAXA_FLAGS:
            if needle in sub and setting in bad_settings:
                flags.append({
                    "id": r.get("prompt_id") or r.get("scenario_id") or "?",
                    "taxa_subcategory": r.get("taxa_subcategory"),
                    "cultural_setting": setting, "reason": reason,
                })
    verdict = "GOOD" if not flags else "BAD"
    print(_fmt("implausible taxa×locale pairings", str(len(flags)), verdict))
    for f in flags:
        print(f"      {f['id']}: {f['taxa_subcategory']} in {f['cultural_setting']} — {f['reason']}")
    report["locale_taxa"] = {"n_flagged": len(flags), "flags": flags}


# ---------------------------------------------------------------- library selection


def audit_library_selection(run_dir: Path | None, report: dict) -> None:
    """Step 2a.5 selection sizes: how many reasoning-library rows each case
    pulled. Reads step2/scopes.jsonl (entry_ids + selection_source); the target
    after the selective-prompt change is typical selections well under half the
    library, with the fail-open full-library fallback staying rare."""
    print(" Reasoning-library selection (2a.5)")
    if run_dir is None:
        print(_fmt("selection report", "skipped", note="(bare-file input; pass a run dir)"))
        return
    scopes = utils.load_jsonl(run_dir / "step2" / "scopes.jsonl")
    rows = [(str(s.get("prompt_id") or "?"), len(s.get("entry_ids") or []),
             s.get("selection_source")) for s in scopes if s.get("entry_ids") is not None]
    if not rows:
        print(_fmt("scoped cases", "0", note="(no step 2 in this run — nothing to check)"))
        report["library_selection"] = {"n": 0}
        return
    # Library size from the run's frozen prompt snapshot when present, so old
    # runs are judged against the library they actually ran with.
    from dad_pipeline import reasoning_library
    lib_dir = run_dir / "inputs" / "prompts"
    if not reasoning_library.resolve_path(lib_dir).exists():
        lib_dir = Path(__file__).parent.parent / "prompts" / "dad"
    total = len(reasoning_library.all_ids(reasoning_library.load(lib_dir)))

    sizes = sorted(n for _, n, _ in rows)
    median = sizes[len(sizes) // 2]
    fallbacks = sum(1 for _, _, src in rows if src == "full_library")
    share = median / total if total else 0.0
    print(_fmt("cases scoped", str(len(rows))))
    print(_fmt("rows pulled (of library)", f"min {sizes[0]} / median {median} / max {sizes[-1]} of {total}",
               _verdict(share, 0.50, 0.70)))
    print(_fmt("full-library fallbacks", f"{fallbacks}/{len(rows)}",
               _verdict(fallbacks / len(rows), 0.0, 0.2)))
    print("      " + ", ".join(f"{pid} {n}" for pid, n, _ in rows))
    report["library_selection"] = {
        "n": len(rows), "library_size": total, "sizes": sizes,
        "median": median, "median_share": share, "fallbacks": fallbacks,
        "per_case": {pid: n for pid, n, _ in rows},
    }


# ---------------------------------------------------------------- jargon in responses

# Insider / academic register that shouldn't surface in a user-facing reply —
# the reasoning library is sampling scaffolding, so its vocabulary must be
# translated, not echoed. Matched case-insensitively against the assistant turn.
# Kept as word-boundaried patterns so plain uses ("marginally", "a neglected
# corner") don't false-positive; welfare words like "sentient"/"suffering" are
# deliberately NOT here — they are legitimate, only the jargon labels leak.
_JARGON_PATTERNS = [
    (t, re.compile(p, re.IGNORECASE)) for t, p in [
        ("counterfactual", r"counterfactual"),
        ("moral weight", r"moral weight"),
        ("cluelessness", r"clueless"),
        ("marginal effect", r"marginal (effect|contribution|impact|harm)"),
        ("tractability", r"\btractab"),
        ("neglectedness", r"neglectedness"),
        ("fungible", r"\bfungib"),
        ("welfare sign", r"welfare sign|sign of (the |their )?welfare"),
        ("net-negative", r"net[- ]negative|net[- ]positive"),
        ("universalization", r"universaliz"),
        ("option value", r"option value"),
        ("objective function", r"objective function"),
        ("species multiplier", r"species multiplier|moral multiplier"),
        ("valenced", r"valenc"),
        # related insider language picked up from the library / EA register
        ("expected value", r"expected value|in expectation"),
        ("second/first-order", r"\b(second|first)-order\b"),
        ("r-selected", r"\br-select"),
        ("moral status", r"moral status"),
        ("moral patient", r"moral patient"),
        ("moral circle", r"moral circle"),
        ("hedonic", r"\bhedonic"),
        ("disvalue", r"\bdisvalue"),
        ("lock-in", r"lock-in|lock in (the|a) "),
    ]
]


def _assistant_texts(run_dir: Path, rel: str, field_path) -> dict:
    """{prompt_id or record_id: assistant text} from a run's final corpus or
    baseline arm — empty when the file is absent (step-1-only runs)."""
    out = {}
    for r in utils.load_jsonl(run_dir / rel):
        text = field_path(r)
        if text:
            out[r.get("record_id") or r.get("prompt_id")] = text
    return out


def _scan_jargon(texts: dict) -> tuple:
    counts, cases = {}, {}
    for t in texts.values():
        for term, pat in _JARGON_PATTERNS:
            n = len(pat.findall(t))
            if n:
                counts[term] = counts.get(term, 0) + n
                cases[term] = cases.get(term, 0) + 1
    return counts, cases


def audit_jargon(run_dir: Path | None, report: dict) -> None:
    """How much insider/library vocabulary leaks into the shipped responses,
    and — when the baseline arm ran — how much of it the pipeline ADDS over
    plain Claude (the real signal: terms present in the pipeline but not the
    plain answer are scaffolding bleed, not model style)."""
    print(" Insider-vocabulary leak (responses)")
    if run_dir is None:
        print(_fmt("jargon report", "skipped", note="(bare-file input; pass a run dir)"))
        return
    pipe = _assistant_texts(run_dir, "final/dad_corpus.jsonl",
                            lambda r: (r.get("messages") or [{}, {}])[1].get("content", ""))
    if not pipe:
        print(_fmt("responses", "0", note="(no final corpus — nothing to scan)"))
        report["jargon"] = {"n": 0}
        return
    plain = _assistant_texts(run_dir, "baseline/baseline_responses.jsonl",
                             lambda r: r.get("baseline_response", ""))
    p_counts, p_cases = _scan_jargon(pipe)
    b_counts, _ = _scan_jargon(plain) if plain else ({}, {})
    n = len(pipe)
    total = sum(p_counts.values())
    excess = total - sum(b_counts.values())  # pipeline minus plain (same prompts)
    rate = total / n

    print(_fmt("responses scanned", str(n)))
    print(_fmt("jargon occurrences", f"{total} ({rate:.1f}/response)", _verdict(rate, 0.5, 1.5)))
    if plain:
        print(_fmt("vs plain baseline", f"pipeline {total} / plain {sum(b_counts.values())} "
                                        f"(pipeline adds {excess:+d})",
                   _verdict(max(excess, 0) / n, 0.3, 1.0)))
    for term, c in sorted(p_counts.items(), key=lambda kv: -kv[1]):
        print(f"      {term:<20} {c}x  in {p_cases[term]} response(s)"
              + (f"  (plain: {b_counts.get(term, 0)})" if plain else ""))
    report["jargon"] = {
        "n": n, "total": total, "per_response": rate,
        "pipeline_terms": p_counts, "plain_terms": b_counts,
        "pipeline_excess_vs_plain": excess if plain else None,
    }


# ---------------------------------------------------------------- length (delegated)


def audit_lengths(run_dir: Path | None, report: dict) -> None:
    print(" Length-class realization")
    if run_dir is None:
        print(_fmt("length report", "skipped", note="(bare-file input; pass a run dir)"))
        return
    from evals.openings_dad import prompt_length_report
    stats = prompt_length_report(run_dir)
    report["prompt_lengths"] = stats


# ---------------------------------------------------------------- main


def main() -> None:
    parser = argparse.ArgumentParser(description="Corpus-level audit of DAD step-1 prompts.")
    parser.add_argument("--input", default="outputs/dad/latest",
                        help="Run directory or step1/dilemmas.jsonl path")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    records, report_dir, run_dir = resolve_input(args.input)
    if args.limit:
        records = records[: args.limit]
    if not records:
        raise SystemExit("No step-1 prompts found — nothing to audit.")

    print(f"=== DAD prompt audit: {args.input} ({len(records)} prompts) ===\n")
    report: dict = {"input": str(args.input), "n_prompts": len(records)}
    audit_skeletons(records, report)
    print()
    audit_openers_closers(records, report)
    print()
    audit_unrealized_details(records, report)
    print()
    audit_locale_taxa(records, report)
    print()
    audit_library_selection(run_dir, report)
    print()
    audit_jargon(run_dir, report)
    print()
    audit_lengths(run_dir, report)

    utils.ensure_dir(report_dir)
    out = report_dir / "audit_report.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nReport written to {out}")


if __name__ == "__main__":
    main()
