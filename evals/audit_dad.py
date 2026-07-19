#!/usr/bin/env python3
"""Corpus-level audit of a DAD run: prompt-side repetition/realization plus the
response-side diversity battery (lengths, phrases, structure, openings, library
coverage), each vs the plain-baseline arm where one ran.

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
import math
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


def effective_number(counts) -> float:
    """exp(Shannon entropy) of a count distribution: how many EQUALLY-common
    categories would produce this much variety. 1.0 = total collapse; equals
    the category count when perfectly even. Reads the whole distribution where
    top-share only reads the biggest bucket ([40,10x6] ≈ 5.7 vs [40,40,20] ≈
    2.9 — same top-share, half the variety)."""
    vals = [c for c in counts if c > 0]
    total = sum(vals)
    if not vals or total == 0:
        return 0.0
    ps = [c / total for c in vals]
    return float(math.exp(-sum(p * math.log(p) for p in ps)))


def _fmt(label: str, value: str, verdict: str | None = None, note: str = "") -> str:
    tail = f"  [{verdict}]" if verdict else ""
    tail += f"  {note}" if note else ""
    return f"   {label:<34} {value}{tail}"


# Every printed line is also recorded into report["sections"] so the JSON file
# carries the exact display rows (labels, values, verdicts, detail lines) the
# terminal showed — the viewer's Corpus audit page renders from there rather
# than duplicating the threshold logic above.


def _section(report: dict, title: str) -> dict:
    sec: dict = {"title": title, "rows": []}
    report.setdefault("sections", []).append(sec)
    print(f" {title}")
    return sec


def _row(sec: dict, label: str, value: str, verdict: str | None = None,
         note: str = "", echo: bool = True) -> None:
    sec["rows"].append({"label": label, "value": value, "verdict": verdict, "note": note})
    if echo:
        print(_fmt(label, value, verdict, note))


def _detail(sec: dict, line: str, echo: bool = True) -> None:
    sec.setdefault("detail", []).append(line)
    if echo:
        print(f"      {line}")


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
    sec = _section(report, "Structural skeletons")
    msgs = _messages(records)
    if not msgs:
        _row(sec, "prompts", "0")
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

    _row(sec, "families", ", ".join(f"{f} {c}" for f, c in counts.most_common()))
    _row(sec, "produce-by-deadline share", f"{produce_by_deadline}/{n} ({produce_by_deadline / n:.0%})",
         _verdict(produce_by_deadline / n, 0.30, 0.50))
    _row(sec, "top non-'other' skeleton", f"{worst_fam} {worst_n}/{n} ({worst_n / n:.0%})",
         _verdict(worst_n / n, 0.30, 0.50))
    eff = effective_number(counts.values())
    _row(sec, "effective families", f"{eff:.1f} of {len(counts)} distinct",
         note="(exp-entropy: reads the whole spread, not just the top bucket)")
    report["skeletons"] = {
        "n": n, "families": dict(counts),
        "produce_by_deadline": produce_by_deadline,
        "produce_by_deadline_share": produce_by_deadline / n,
        "top_family": top_fam, "top_share": top_n / n,
        "effective_families": round(eff, 2),
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
    sec = _section(report, "Openers & closers")
    msgs = _messages(records)
    if not msgs:
        _row(sec, "prompts", "0")
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

    _row(sec, "distinct opening 3-words", f"{len(openers)}/{n}",
         _verdict(len(openers) / n, 0.90, 0.75, higher_better=True))
    if rep_open:
        _row(sec, "repeated openers", str(rep_open))
    _row(sec, "distinct closing 3-words", f"{len(closers)}/{n}",
         _verdict(len(closers) / n, 0.90, 0.75, higher_better=True))
    if rep_close:
        _row(sec, "repeated closers", str(rep_close))
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
    sec = _section(report, "Unrealized dealt details (frontier frame)")
    dealt = [r for r in records
             if str(r.get("frontier_frame") or "").strip()
             and str(r.get("user_message") or "").strip()]
    if not dealt:
        _row(sec, "prompts with a frontier frame", "0", note="(none dealt — nothing to check)")
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
    _row(sec, "frontier frames dealt", str(len(dealt)))
    _row(sec, "no lexical trace in text", f"{len(unrealized)}/{checked} ({frac:.0%})",
         _verdict(frac, 0.10, 0.30), note=(", ".join(unrealized) if unrealized else ""))
    if unmapped:
        _row(sec, "frames with no keyword map", str(unmapped),
             note="(add to _FRONTIER_KEYWORDS to check)")
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
    sec = _section(report, "Locale / taxa plausibility")
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
    _row(sec, "implausible taxa×locale pairings", str(len(flags)), verdict)
    for f in flags:
        _detail(sec, f"{f['id']}: {f['taxa_subcategory']} in {f['cultural_setting']} — {f['reason']}")
    report["locale_taxa"] = {"n_flagged": len(flags), "flags": flags}


# ---------------------------------------------------------------- library selection


def audit_library_selection(run_dir: Path | None, report: dict) -> None:
    """Step 2a.5 selection sizes: how many reasoning-library rows each case
    pulled. Reads step2/scopes.jsonl (entry_ids + selection_source); the target
    after the selective-prompt change is typical selections well under half the
    library, with the fail-open full-library fallback staying rare."""
    sec = _section(report, "Reasoning-library selection (2a.5)")
    if run_dir is None:
        _row(sec, "selection report", "skipped", note="(bare-file input; pass a run dir)")
        return
    scopes = utils.load_jsonl(run_dir / "step2" / "scopes.jsonl")
    rows = [(str(s.get("prompt_id") or "?"), len(s.get("entry_ids") or []),
             s.get("selection_source")) for s in scopes if s.get("entry_ids") is not None]
    if not rows:
        _row(sec, "scoped cases", "0", note="(no step 2 in this run — nothing to check)")
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
    _row(sec, "cases scoped", str(len(rows)))
    _row(sec, "rows pulled (of library)", f"min {sizes[0]} / median {median} / max {sizes[-1]} of {total}",
         _verdict(share, 0.50, 0.70))
    _row(sec, "full-library fallbacks", f"{fallbacks}/{len(rows)}",
         _verdict(fallbacks / len(rows), 0.0, 0.2))
    _detail(sec, ", ".join(f"{pid} {n}" for pid, n, _ in rows))
    report["library_selection"] = {
        "n": len(rows), "library_size": total, "sizes": sizes,
        "median": median, "median_share": share, "fallbacks": fallbacks,
        "per_case": {pid: n for pid, n, _ in rows},
    }


# ---------------------------------------------------------------- library coverage


def audit_library_coverage(run_dir: Path | None, report: dict) -> None:
    """Layer-3 conceptual coverage: which reasoning-library entries the run's
    2a.5 selections exercised across the corpus. The library IS the defined
    concept space for responses, so never-selected entries are starved moves.
    Small runs starve entries naturally — judge at 40-example scale and watch
    the never-selected set shrink (or not) across runs."""
    sec = _section(report, "Reasoning-library coverage")
    if run_dir is None:
        _row(sec, "coverage report", "skipped", note="(bare-file input; pass a run dir)")
        return
    scopes = utils.load_jsonl(run_dir / "step2" / "scopes.jsonl")
    rows = [s for s in scopes if s.get("entry_ids") is not None]
    if not rows:
        _row(sec, "scoped cases", "0", note="(no step 2 in this run — nothing to check)")
        report["library_coverage"] = {"n_cases": 0}
        return
    from dad_pipeline import reasoning_library
    lib_dir = run_dir / "inputs" / "prompts"
    if not reasoning_library.resolve_path(lib_dir).exists():
        lib_dir = Path(__file__).parent.parent / "prompts" / "dad"
    all_ids = [str(e) for e in reasoning_library.all_ids(reasoning_library.load(lib_dir))]

    fires: Counter = Counter()
    for s in rows:
        for eid in set(s.get("entry_ids") or []):
            fires[str(eid)] += 1
    used = [e for e in all_ids if fires.get(e)]
    never = [e for e in all_ids if not fires.get(e)]
    top_eid, top_c = fires.most_common(1)[0]

    share = len(used) / len(all_ids)
    # The verdict only attaches at 20+ cases: below that, starvation is mostly
    # sampling, not a trigger problem, and a red badge would cry wolf.
    verdict = _verdict(share, 0.85, 0.60, higher_better=True) if len(rows) >= 20 else None
    _row(sec, "library entries", str(len(all_ids)))
    _row(sec, "coverage (selected at least once)",
         f"{len(used)}/{len(all_ids)} ({share:.0%})", verdict,
         note=("" if verdict else
               "(verdict attaches at 20+ cases — small runs starve entries naturally)"))
    _row(sec, "most-selected entry", f"{top_eid} in {top_c}/{len(rows)} cases")
    _detail(sec, "fires: " + ", ".join(f"{e} {c}" for e, c in fires.most_common()))
    if never:
        _detail(sec, "never selected: " + ", ".join(never))
    report["library_coverage"] = {
        "n_cases": len(rows), "library_size": len(all_ids), "used": len(used),
        "never_selected": never, "fires": dict(fires),
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
        ("r-selected", r"\br-select"),
        ("moral status", r"moral status"),
        ("moral patient", r"moral patient"),
        ("moral circle", r"moral circle"),
        ("hedonic", r"\bhedonic"),
        ("disvalue", r"\bdisvalue"),
        # NB: "second-order" and "lock-in" are deliberately NOT flagged — judged
        # acceptable plain-enough language.
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
    sec = _section(report, "Insider-vocabulary leak (responses)")
    if run_dir is None:
        _row(sec, "jargon report", "skipped", note="(bare-file input; pass a run dir)")
        return
    pipe = _assistant_texts(run_dir, "final/dad_corpus.jsonl",
                            lambda r: (r.get("messages") or [{}, {}])[1].get("content", ""))
    if not pipe:
        _row(sec, "responses", "0", note="(no final corpus — nothing to scan)")
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

    _row(sec, "responses scanned", str(n))
    _row(sec, "jargon occurrences", f"{total} ({rate:.1f}/response)", _verdict(rate, 0.5, 1.5))
    if plain:
        _row(sec, "vs plain baseline", f"pipeline {total} / plain {sum(b_counts.values())} "
                                       f"(pipeline adds {excess:+d})",
             _verdict(max(excess, 0) / n, 0.3, 1.0))
    for term, c in sorted(p_counts.items(), key=lambda kv: -kv[1]):
        _detail(sec, f"{term:<20} {c}x  in {p_cases[term]} response(s)"
                + (f"  (plain: {b_counts.get(term, 0)})" if plain else ""))
    report["jargon"] = {
        "n": n, "total": total, "per_response": rate,
        "pipeline_terms": p_counts, "plain_terms": b_counts,
        "pipeline_excess_vs_plain": excess if plain else None,
    }


# ---------------------------------------------------------------- response lengths


def _final_by_prompt_id(run_dir: Path) -> dict:
    """{prompt_id: final assistant text} — joins final/dad_corpus.jsonl (keyed
    by record_id) through step3/rewrites.jsonl, which carries both ids."""
    finals = {r.get("record_id"): (r.get("messages") or [{}, {}])[1].get("content", "")
              for r in utils.load_jsonl(run_dir / "final" / "dad_corpus.jsonl")}
    out = {}
    for rw in utils.load_jsonl(run_dir / "step3" / "rewrites.jsonl"):
        text = finals.get(rw.get("record_id"))
        if text and rw.get("prompt_id"):
            out[rw["prompt_id"]] = text
    return out


def _baseline_by_prompt_id(run_dir: Path) -> dict:
    return {r["prompt_id"]: str(r.get("baseline_response") or "")
            for r in utils.load_jsonl(run_dir / "baseline" / "baseline_responses.jsonl")
            if r.get("prompt_id") and r.get("baseline_response")}


def audit_response_lengths(run_dir: Path | None, report: dict) -> None:
    """Final response lengths vs the plain-baseline arm, per prompt. Length is
    a usability constraint (long replies stop getting read), so the median
    pipeline/plain ratio carries the verdict."""
    sec = _section(report, "Response lengths (vs plain baseline)")
    if run_dir is None:
        _row(sec, "length comparison", "skipped", note="(bare-file input; pass a run dir)")
        return
    pipe = _final_by_prompt_id(run_dir)
    if not pipe:
        _row(sec, "responses", "0", note="(no final corpus — nothing to measure)")
        report["response_lengths"] = {"n": 0}
        return
    plain = {pid: len(text) for pid, text in _baseline_by_prompt_id(run_dir).items()}
    per_case = {pid: {"pipeline": len(text), "plain": plain.get(pid)}
                for pid, text in sorted(pipe.items())}
    p_lens = sorted(v["pipeline"] for v in per_case.values())
    p_median = p_lens[len(p_lens) // 2]
    _row(sec, "responses measured", str(len(per_case)))
    _row(sec, "pipeline median chars", str(p_median))
    b_median = ratio = None
    both = [v["plain"] for v in per_case.values() if v["plain"]]
    if both:
        b_lens = sorted(both)
        b_median = b_lens[len(b_lens) // 2]
        ratio = p_median / b_median if b_median else 0.0
        _row(sec, "plain-baseline median chars", str(b_median))
        _row(sec, "median length ratio (pipeline/plain)", f"{ratio:.2f}x",
             _verdict(ratio, 1.5, 2.5))
        # batch totals over paired records only (both arms present)
        paired = [v for v in per_case.values() if v["plain"] is not None]
        pipe_t = sum(v["pipeline"] for v in paired)
        plain_t = sum(v["plain"] for v in paired)
        diff = pipe_t - plain_t
        _row(sec, "total chars (batch)",
             f"pipeline {pipe_t:,} / plain {plain_t:,} "
             f"({diff:+,} / {diff / plain_t:+.1%})" if plain_t else
             f"pipeline {pipe_t:,} / plain 0")
    else:
        _row(sec, "plain baseline", "absent", note="(no baseline arm in this run — no comparison)")
    report["response_lengths"] = {
        "n": len(per_case), "pipeline_median": p_median,
        "plain_median": b_median, "median_ratio": ratio, "per_case": per_case,
    }


# ---------------------------------------------------------------- stock phrases (responses)

# Known recurring phrases ("engrams") in the shipped responses, measured in
# BOTH arms every run: the pipeline-vs-plain differential is the training-data
# signal, and plain Claude's own tics matter too — they show what the pipeline
# suppresses or inherits. Seeded from the Opus-era sweep (runs from 2026-07-17
# on; earlier eras deliberately ignored — different model, different prompts).
# Grow a side when the discovery lines below surface a new recurring phrase.
_STOCK_PHRASES = {
    "pipeline-origin": [
        # agency/ownership family
        "you're the one", "the one who", "is your call",
        # performed-candor family
        "i want to be", "straight with you", "be honest about",
        # epistemic deference
        "better than i do",
        # idiom / structure tics
        "on the table", "start with the", "why this matters",
        # library-vocabulary echoes (C9 calibration register)
        "genuinely unsettled", "genuinely uncertain",
        "the welfare question", "capacity to suffer",
    ],
    "plain-origin": [
        "here's the thing", "the fact that", "the part i'd", "push back on",
        "you already know", "a few things", "want to flag", "what i'd actually",
    ],
}


def _norm_text(t: str) -> str:
    return re.sub(r"\s+", " ", t.replace("’", "'").lower())


def _gram_docfreq(texts: dict, lo: int = 3, hi: int = 5) -> dict:
    df: dict = {}
    for t in texts.values():
        words = re.sub(r"[^a-z' ]", " ", t).split()
        grams = {" ".join(words[i:i + n])
                 for n in range(lo, hi + 1) for i in range(len(words) - n + 1)}
        for g in grams:
            df[g] = df.get(g, 0) + 1
    return df


def audit_stock_phrases(run_dir: Path | None, report: dict) -> None:
    """Cross-response phrase collapse in the shipped responses vs the plain
    baseline: the curated watchlist above (both arms' known tics), plus a
    data-driven discovery pass for NEW phrases recurring in this run."""
    sec = _section(report, "Stock phrases (responses)")
    if run_dir is None:
        _row(sec, "phrase report", "skipped", note="(bare-file input; pass a run dir)")
        return
    pipe = {k: _norm_text(v) for k, v in _final_by_prompt_id(run_dir).items()}
    if not pipe:
        _row(sec, "responses", "0", note="(no final corpus — nothing to scan)")
        report["stock_phrases"] = {"n": 0}
        return
    plain = {k: _norm_text(v) for k, v in _baseline_by_prompt_id(run_dir).items()}

    def hits(phrase: str, texts: dict) -> int:
        return sum(1 for t in texts.values() if phrase in t)

    watch: dict = {}
    for origin, phrases in _STOCK_PHRASES.items():
        for ph in phrases:
            watch[ph] = {"origin": origin, "pipeline": hits(ph, pipe),
                         "plain": hits(ph, plain)}
    worst_p = max((v["pipeline"] / len(pipe), ph) for ph, v in watch.items()
                  if v["origin"] == "pipeline-origin")
    _row(sec, "responses scanned", f"pipeline {len(pipe)} / plain {len(plain)}")
    _row(sec, "worst pipeline-origin phrase",
         f"'{worst_p[1]}' {watch[worst_p[1]]['pipeline']}/{len(pipe)} ({worst_p[0]:.0%})",
         _verdict(worst_p[0], 0.20, 0.40))
    if plain:
        worst_b = max((v["plain"] / len(plain), ph) for ph, v in watch.items()
                      if v["origin"] == "plain-origin")
        _row(sec, "worst plain-origin phrase (plain arm)",
             f"'{worst_b[1]}' {watch[worst_b[1]]['plain']}/{len(plain)} ({worst_b[0]:.0%})")
    for origin in ("pipeline-origin", "plain-origin"):
        for ph, v in watch.items():
            if v["origin"] == origin and (v["pipeline"] or v["plain"]):
                _detail(sec, f"[{origin.split('-')[0]:>8}] {ph:<22} "
                             f"pipeline {v['pipeline']}/{len(pipe)}"
                             + (f", plain {v['plain']}/{len(plain)}" if plain else ""))

    # Discovery: phrases recurring in >=30% of one arm with a >=20-point lead
    # over the other, not already covered by the watchlist. Candidates for the
    # list above — measured, not auto-added. A candidate sharing any word PAIR
    # with a watch phrase is treated as covered ("be straight with" is the
    # 'straight with you' engram, not a new one).
    def _bigrams(s: str) -> set:
        w = s.split()
        return {(w[i], w[i + 1]) for i in range(len(w) - 1)}

    watch_bigrams = set().union(*(_bigrams(ph) for lst in _STOCK_PHRASES.values()
                                  for ph in lst))
    dfp, dfb = _gram_docfreq(pipe), _gram_docfreq(plain)
    new = {"pipeline": [], "plain": []}
    for arm, df_a, n_a, df_b, n_b in (("pipeline", dfp, len(pipe), dfb, len(plain) or 1),
                                      ("plain", dfb, len(plain) or 1, dfp, len(pipe))):
        cands = sorted(((c / n_a - df_b.get(g, 0) / n_b, g, c) for g, c in df_a.items()
                        if c / n_a >= 0.30), reverse=True)
        for diff, g, c in cands:
            if diff < 0.20 or _bigrams(g) & watch_bigrams:
                continue
            if any(g in k or k in g for k, _ in new[arm]):
                continue
            new[arm].append((g, c))
            if len(new[arm]) >= 4:
                break
        for g, c in new[arm]:
            _detail(sec, f"[new {arm:>8}] {g:<22} {c}/{n_a}")
    report["stock_phrases"] = {
        "n_pipeline": len(pipe), "n_plain": len(plain), "watch": watch,
        "new_pipeline": [{"phrase": g, "count": c} for g, c in new["pipeline"]],
        "new_plain": [{"phrase": g, "count": c} for g, c in new["plain"]],
    }


# ---------------------------------------------------------------- lexical diversity

def _lex_tokens(text: str) -> list[str]:
    return re.sub(r"[^a-z' ]", " ", text.lower()).split()


def distinct_n(texts: list[str], n: int) -> float:
    """Distinct-n over the pooled corpus: unique n-grams / total n-grams.
    Pooling (rather than per-text averaging) makes cross-response repetition
    count against the score, which is the failure mode we care about."""
    total = 0
    uniq: set = set()
    for t in texts:
        w = _lex_tokens(t)
        grams = list(zip(*(w[i:] for i in range(n))))
        total += len(grams)
        uniq.update(grams)
    return len(uniq) / total if total else 0.0


def self_bleu(texts: list[str], max_n: int = 4) -> float:
    """Self-BLEU (Texygen convention): each text BLEU-scored against all the
    others as references, averaged. Higher = the corpus echoes itself.
    Epsilon-smoothed so one missing 4-gram order doesn't zero a score.
    Absolute values depend on corpus size and length — compare the two arms
    and run-over-run, never against external numbers."""
    toks = [_lex_tokens(t) for t in texts if t.strip()]
    if len(toks) < 2:
        return 0.0
    # per-doc n-gram counters, computed once
    counters = [[Counter(zip(*(w[j:] for j in range(n)))) for n in range(1, max_n + 1)]
                for w in toks]
    scores = []
    for i, hyp in enumerate(toks):
        if not hyp:
            continue
        log_p = 0.0
        for n in range(1, max_n + 1):
            h = counters[i][n - 1]
            total = sum(h.values())
            if not total:
                log_p += math.log(1e-9)
                continue
            max_ref: Counter = Counter()
            for j, other in enumerate(counters):
                if j == i:
                    continue
                for g, c in other[n - 1].items():
                    if c > max_ref[g]:
                        max_ref[g] = c
            clipped = sum(min(c, max_ref[g]) for g, c in h.items())
            p = clipped / total
            log_p += math.log(p if p > 0 else 0.1 / total)
        ref_len = min((abs(len(toks[j]) - len(hyp)), len(toks[j]))
                      for j in range(len(toks)) if j != i)[1]
        bp = 1.0 if len(hyp) >= ref_len else math.exp(1 - ref_len / len(hyp))
        scores.append(bp * math.exp(log_p / max_n))
    return sum(scores) / len(scores) if scores else 0.0


def audit_lexical(run_dir: Path | None, report: dict) -> None:
    """Layer-1 lexical diversity of the shipped responses vs the plain
    baseline: Distinct-1/2/3 (higher = more varied wording) and Self-BLEU
    (higher = the corpus echoes itself). Informational — the arm differential
    and the run-over-run trend are the signal, not the absolute values."""
    sec = _section(report, "Lexical diversity (responses)")
    if run_dir is None:
        _row(sec, "lexical report", "skipped", note="(bare-file input; pass a run dir)")
        return
    pipe = list(_final_by_prompt_id(run_dir).values())
    if not pipe:
        _row(sec, "responses", "0", note="(no final corpus — nothing to measure)")
        report["lexical"] = {"n": 0}
        return
    plain = list(_baseline_by_prompt_id(run_dir).values())

    def arm(texts: list) -> dict:
        return {"n": len(texts),
                "distinct": {str(n): round(distinct_n(texts, n), 3) for n in (1, 2, 3)},
                "self_bleu": round(self_bleu(texts), 3)}

    p = arm(pipe)
    b = arm(plain) if len(plain) >= 2 else None
    _row(sec, "responses measured", f"pipeline {p['n']}" + (f" / plain {b['n']}" if b else ""))
    d = p["distinct"]
    val = f"pipeline {d['1']:.2f} / {d['2']:.2f} / {d['3']:.2f}"
    if b:
        db = b["distinct"]
        val += f" · plain {db['1']:.2f} / {db['2']:.2f} / {db['3']:.2f}"
    _row(sec, "distinct-1 / -2 / -3", val, note="(unique/total n-grams, pooled; higher = more varied)")
    _row(sec, "Self-BLEU", f"pipeline {p['self_bleu']:.3f}"
         + (f" · plain {b['self_bleu']:.3f}" if b else ""),
         note="(higher = corpus echoes itself; compare arms and runs)")
    report["lexical"] = {"pipeline": p, "plain": b}


# ---------------------------------------------------------------- structural variation

_LIST_BULLET = re.compile(r"^\s*[-*•] ", re.M)
_LIST_NUMBERED = re.compile(r"^\s*\d+[.)] ", re.M)
_HEADING = re.compile(r"^#{1,4} |^\*\*[^*\n]{2,60}\*\*:?\s*$", re.M)


def _shape_of(text: str) -> str:
    """A response's structural signature: paragraph-count bucket plus which
    structural elements it uses. Shape collapse (every reply the same
    signature) is invisible per-response — it only shows over the set."""
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    n = len(paras)
    bucket = "1-2" if n <= 2 else "3-5" if n <= 5 else "6-9" if n <= 9 else "10+"
    flags = [f"{bucket} paras"]
    if _LIST_BULLET.search(text):
        flags.append("bullets")
    if _LIST_NUMBERED.search(text):
        flags.append("numbered")
    if _HEADING.search(text):
        flags.append("headed")
    if text.rstrip().endswith("?"):
        flags.append("ends-question")
    return " · ".join(flags)


def audit_structure(run_dir: Path | None, report: dict) -> None:
    """Structural variation of the shipped responses vs the plain baseline:
    distinct shape signatures, the top shape's share (the collapse metric),
    and per-element usage rates."""
    sec = _section(report, "Structural variation (responses)")
    if run_dir is None:
        _row(sec, "structure report", "skipped", note="(bare-file input; pass a run dir)")
        return
    pipe = _final_by_prompt_id(run_dir)
    if not pipe:
        _row(sec, "responses", "0", note="(no final corpus — nothing to scan)")
        report["structure"] = {"n": 0}
        return
    plain = _baseline_by_prompt_id(run_dir)

    def arm_stats(texts: dict) -> dict:
        shapes = Counter(_shape_of(t) for t in texts.values())
        paras = sorted(len([p for p in re.split(r"\n\s*\n", t) if p.strip()])
                       for t in texts.values())
        n = len(texts)
        top_shape, top_n = shapes.most_common(1)[0]
        return {"n": n, "shapes": dict(shapes), "distinct": len(shapes),
                "effective_shapes": round(effective_number(shapes.values()), 2),
                "top_shape": top_shape, "top_share": top_n / n,
                "median_paras": paras[len(paras) // 2],
                "bullets": sum(1 for t in texts.values() if _LIST_BULLET.search(t)) / n,
                "numbered": sum(1 for t in texts.values() if _LIST_NUMBERED.search(t)) / n,
                "headed": sum(1 for t in texts.values() if _HEADING.search(t)) / n,
                "ends_question": sum(1 for t in texts.values()
                                     if t.rstrip().endswith("?")) / n}

    p = arm_stats(pipe)
    b = arm_stats(plain) if plain else None

    def pair(key: str, fmt: str = "{:.0%}") -> str:
        return (f"pipeline {fmt.format(p[key])}"
                + (f" / plain {fmt.format(b[key])}" if b else ""))

    _row(sec, "responses scanned", f"pipeline {p['n']}" + (f" / plain {b['n']}" if b else ""))
    _row(sec, "distinct shapes", f"pipeline {p['distinct']}/{p['n']}"
         + (f" / plain {b['distinct']}/{b['n']}" if b else ""))
    _row(sec, "effective shapes", f"pipeline {p['effective_shapes']:.1f}"
         + (f" / plain {b['effective_shapes']:.1f}" if b else ""),
         note="(exp-entropy: reads the whole spread, not just the top bucket)")
    _row(sec, "top shape share (pipeline)", f"{p['top_share']:.0%}",
         _verdict(p["top_share"], 0.30, 0.50), note=f"({p['top_shape']})")
    _row(sec, "paragraphs (median)", pair("median_paras", "{}"))
    _row(sec, "bullet lists", pair("bullets"))
    _row(sec, "numbered lists", pair("numbered"))
    _row(sec, "headings / bold leads", pair("headed"))
    _row(sec, "ends with a question", pair("ends_question"))
    for shape, c in Counter(p["shapes"]).most_common():
        _detail(sec, f"pipeline {c}x  {shape}")
    report["structure"] = {"pipeline": p, "plain": b}


# ---------------------------------------------------------------- response openings


def audit_response_openings(run_dir: Path | None, report: dict) -> None:
    """Opening-shape collapse in the responses, drafts and finals: opener
    families, within-case spread, and hint-card wording echo — the checks
    evals/openings_dad.py owns, rendered as audit sections so they reach
    audit_report.json and the viewer (openings_dad remains the deep-dive tool:
    per-sentence listing, --embeddings, multi-run comparison). Hint echo shows
    on drafts only, where the hints ride — step 3 preserves openers."""
    from evals.openings_dad import load_responses, stage_stats

    out: dict = {}
    for i, stage in enumerate(("drafts", "finals")):
        if i:
            print()
        sec = _section(report, f"Response openings ({stage})")
        if run_dir is None:
            _row(sec, "openings report", "skipped", note="(bare-file input; pass a run dir)")
            continue
        rows = [r for r in load_responses(run_dir, stage) if r["text"].strip()]
        if not rows:
            _row(sec, "responses", "0", note=f"(no {stage} in this run — nothing to check)")
            out[stage] = {"n": 0}
            continue
        stats = stage_stats(rows)
        n = stats["n"]
        counts = Counter(stats["families"])
        # "other" is the healthy bucket — collapse is a NAMED family dominating.
        non_other = {f: c for f, c in counts.items() if f != "other"}
        worst_fam, worst_n = (max(non_other.items(), key=lambda kv: kv[1])
                              if non_other else ("—", 0))
        eff = effective_number(counts.values())

        _row(sec, "responses scanned", str(n))
        _row(sec, "families", ", ".join(f"{f} {c}" for f, c in counts.most_common()))
        _row(sec, "top non-'other' opener family", f"{worst_fam} {worst_n}/{n} ({worst_n / n:.0%})",
             _verdict(worst_n / n, 0.30, 0.50))
        _row(sec, "effective families", f"{eff:.1f} of {len(counts)} distinct",
             note="(exp-entropy: reads the whole spread, not just the top bucket)")
        if stats["case_spread"]:
            varied = sum(1 for v in stats["case_spread"].values() if not v.startswith("1/"))
            _row(sec, "within-case spread",
                 f"{varied}/{len(stats['case_spread'])} multi-sample cases open differently")
            _detail(sec, ", ".join(f"{p} {v}" for p, v in stats["case_spread"].items()))
        if stats["repeated_first3"]:
            _row(sec, "repeated first-3-words", str(stats["repeated_first3"]))
        draws_total = sum(stats["hint_draws"].values())
        if draws_total:
            echo_total = sum(e for e, _ in stats["hint_echo"].values())
            _row(sec, "hint-echo (card wording in opener)", f"{echo_total}/{draws_total} draws",
                 _verdict(echo_total / draws_total, 0.0, 0.2))
            for c, (e, d) in stats["hint_echo"].items():
                _detail(sec, f"{c!r} {e}/{d}")
        out[stage] = {
            "n": n, "families": stats["families"],
            "top_family": stats["top_family"], "top_share": stats["top_share"],
            "effective_families": round(eff, 2), "case_spread": stats["case_spread"],
            "repeated_first3": stats["repeated_first3"],
            "hint_echo": stats["hint_echo"], "hint_draws": stats["hint_draws"],
        }
    if run_dir is not None:
        report["response_openings"] = out


# ---------------------------------------------------------------- moral-patient reasons (LLM)

_REASON_CONSOLIDATE_PROMPT = (
    "Below is a JSON list of reasons extracted from many assistant responses in one corpus; "
    "each reason appeals to some being's interests or welfare. Merge duplicates and "
    "paraphrases into one canonical entry each (the same consideration for the same kind of "
    "patient is ONE entry; the same consideration for clearly different patients stays "
    "separate). Return ONLY a JSON array of the canonical reason strings.\n\nREASONS:\n"
)

# Completeness check-back: a second pass must name anything the first pass left
# uncovered. Its find-count is the extraction-recall tripwire — if it keeps
# finding misses run over run, widen the definition in reason_extraction.txt.
_REASON_CHECKBACK_PROMPT = (
    "Below is one assistant response and the reasons already extracted from it (each appeals "
    "to a moral patient's interests, or changes how those interests get weighed). Find any "
    "passage in the response that does moral-patient reasoning work NOT covered by a listed "
    "reason. Return ONLY a JSON array of short strings (at most ~12 words each), one per "
    "missed reason; return [] if the list is complete.\n\n"
    "ALREADY EXTRACTED:\n{reasons}\n\nRESPONSE:\n{response}"
)

# Survival judge: anchor on the plain baseline's reasons and ask which of them
# the pipeline response kept. Judged against the pipeline RESPONSE TEXT, not
# its extracted list, so an extraction miss can't masquerade as a drop.
_SURVIVAL_PROMPT = (
    "Two assistant responses answered the same user message. REASONS A were extracted from a "
    "plain baseline response. RESPONSE B is a different response; REASONS B were extracted "
    "from it. For each reason in REASONS A, judge whether the same consideration appears in "
    "RESPONSE B: \"kept\" (clearly present), \"weakened\" (present but hedged, diminished, or "
    "partial), or \"dropped\" (absent). Judge against RESPONSE B's full text, not just "
    "REASONS B. Then list every reason in REASONS B that matches no reason in REASONS A "
    "(reasoning B added). Return ONLY a JSON object shaped: "
    "{\"anchored\": [{\"reason\": \"<string from REASONS A>\", \"verdict\": "
    "\"kept|weakened|dropped\"}], \"added\": [\"<string from REASONS B>\"]}\n\n"
    "REASONS A:\n{plain_reasons}\n\nREASONS B:\n{pipeline_reasons}\n\n"
    "RESPONSE B:\n{pipeline_response}"
)


def _reason_str(x) -> str:
    """Normalize one extracted reason: models sometimes return objects like
    {"reason": "..."} where a bare string was asked for."""
    if isinstance(x, dict):
        x = x.get("reason") or x.get("text") or ""
    return str(x).strip()


def audit_reasons(run_dir: Path | None, config: dict, report: dict) -> None:
    """LLM pass (--reasons): distinct reasons appealing to a moral patient's
    interests (animal or not), per response, for the pipeline arm and the plain
    baseline. One extraction call per response; one consolidation call per arm
    then gives corpus-level distinct counts (does the pipeline WIDEN the
    reasoning, not just lengthen each reply). Density = unique reasons per
    1,000 response characters."""
    from shared import api

    sec = _section(report, "Moral-patient reasons (LLM)")
    if run_dir is None:
        _row(sec, "reason scan", "skipped", note="(bare-file input; pass a run dir)")
        return
    pipe = _final_by_prompt_id(run_dir)
    if not pipe:
        _row(sec, "responses", "0", note="(no final corpus — nothing to scan)")
        report["moral_patient_reasons"] = {"n": 0}
        return
    plain = _baseline_by_prompt_id(run_dir)
    dilemmas = {d.get("prompt_id"): str(d.get("user_message") or "")
                for d in utils.load_jsonl(run_dir / "step1" / "dilemmas.jsonl")}
    prompts_dir = Path(__file__).parent.parent / "prompts" / "tools"

    items = [(pid, "pipeline", text) for pid, text in sorted(pipe.items())]
    items += [(pid, "plain", text) for pid, text in sorted(plain.items())]

    def extract(item):
        pid, arm, text = item
        prompt = utils.load_prompt(prompts_dir / "reason_extraction.txt",
                                   user_message=dilemmas.get(pid, ""), response=text)
        try:
            reasons = utils.extract_json_array(
                api.call_claude(user_message=prompt, stage="eval_audit_dad"))
        except Exception:
            return pid, arm, None, 0
        uniq = list(dict.fromkeys(_reason_str(r) for r in reasons if _reason_str(r)))
        try:
            extra = utils.extract_json_array(api.call_claude(
                user_message=_REASON_CHECKBACK_PROMPT
                .replace("{reasons}", json.dumps(uniq, ensure_ascii=False))
                .replace("{response}", text),
                stage="eval_audit_dad"))
        except Exception:
            extra = []  # check-back is best-effort; the extraction still counts
        missed = [_reason_str(r) for r in extra
                  if _reason_str(r) and _reason_str(r) not in uniq]
        return pid, arm, uniq + missed, len(missed)

    per_case: dict = {}
    failures = 0
    for pid, arm, reasons, cb_added in utils.parallel_map(extract, items, config.get("workers", 1)):
        if reasons is None:
            failures += 1
            continue
        text = pipe[pid] if arm == "pipeline" else plain[pid]
        per_case.setdefault(pid, {})[arm] = {
            "reasons": reasons, "chars": len(text), "checkback_added": cb_added,
            "density_per_1k": round(len(reasons) / len(text) * 1000, 2) if text else 0.0,
        }

    # Survival: which plain-anchored reasons made it through the pipeline.
    surv_items = [pid for pid in sorted(per_case)
                  if "pipeline" in per_case[pid] and "plain" in per_case[pid]]

    def judge_survival(pid):
        prompt = (_SURVIVAL_PROMPT
                  .replace("{plain_reasons}",
                           json.dumps(per_case[pid]["plain"]["reasons"], ensure_ascii=False))
                  .replace("{pipeline_reasons}",
                           json.dumps(per_case[pid]["pipeline"]["reasons"], ensure_ascii=False))
                  .replace("{pipeline_response}", pipe[pid]))
        try:
            obj = utils.extract_json_object(
                api.call_claude(user_message=prompt, stage="eval_audit_dad"))
            anchored = [{"reason": _reason_str(a.get("reason")), "verdict": a.get("verdict")}
                        for a in obj.get("anchored") or []
                        if a.get("verdict") in ("kept", "weakened", "dropped")]
            added = [_reason_str(x) for x in obj.get("added") or [] if _reason_str(x)]
        except Exception:
            return pid, None
        return pid, {"anchored": anchored, "added": added}

    surv_failures = judged = added_total = 0
    verdict_counts = {"kept": 0, "weakened": 0, "dropped": 0}
    for pid, surv in utils.parallel_map(judge_survival, surv_items, config.get("workers", 1)):
        if surv is None:
            surv_failures += 1
            continue
        per_case[pid]["survival"] = surv
        judged += 1
        added_total += len(surv["added"])
        for a in surv["anchored"]:
            verdict_counts[a["verdict"]] += 1

    def arm_summary(arm: str) -> dict | None:
        entries = [v[arm] for v in per_case.values() if arm in v]
        if not entries:
            return None
        counts = [len(e["reasons"]) for e in entries]
        chars = sum(e["chars"] for e in entries)
        all_reasons = [r for e in entries for r in e["reasons"]]
        try:
            distinct = [_reason_str(r) for r in utils.extract_json_array(api.call_claude(
                user_message=_REASON_CONSOLIDATE_PROMPT
                + json.dumps(all_reasons, ensure_ascii=False),
                stage="eval_audit_dad"))]
        except Exception:
            distinct = sorted(set(all_reasons))  # exact-match fallback
        return {"n": len(entries), "mean_unique": round(sum(counts) / len(counts), 2),
                "corpus_distinct": len(distinct), "corpus_reasons": distinct,
                "density_per_1k": round(sum(counts) / chars * 1000, 2) if chars else 0.0}

    p, b = arm_summary("pipeline"), arm_summary("plain")
    _row(sec, "responses scanned", f"pipeline {p['n'] if p else 0} / plain {b['n'] if b else 0}"
         + (f" ({failures} extraction failures)" if failures else ""))
    if p:
        cb_p = sum(v["pipeline"].get("checkback_added", 0)
                   for v in per_case.values() if "pipeline" in v)
        cb_b = sum(v["plain"].get("checkback_added", 0)
                   for v in per_case.values() if "plain" in v)
        _row(sec, "check-back additions", f"pipeline {cb_p} / plain {cb_b}",
             note="(reasons the first extraction pass missed)")
        _row(sec, "mean unique reasons / response", f"pipeline {p['mean_unique']}"
             + (f" / plain {b['mean_unique']}" if b else ""))
        if b:
            # batch totals over paired records only (both arms present)
            paired = [v for v in per_case.values() if "pipeline" in v and "plain" in v]
            pipe_t = sum(len(v["pipeline"]["reasons"]) for v in paired)
            plain_t = sum(len(v["plain"]["reasons"]) for v in paired)
            diff = pipe_t - plain_t
            _row(sec, "total unique reasons (batch)",
                 f"pipeline {pipe_t} / plain {plain_t} "
                 f"({diff:+d} / {diff / plain_t:+.1%})" if plain_t else
                 f"pipeline {pipe_t} / plain 0")
        _row(sec, "reasoning density (per 1k chars)", f"pipeline {p['density_per_1k']}"
             + (f" / plain {b['density_per_1k']}" if b else ""))
        _row(sec, "corpus-level distinct reasons", f"pipeline {p['corpus_distinct']}"
             + (f" / plain {b['corpus_distinct']}" if b else ""))
    survival = None
    if judged:
        total_anchored = sum(verdict_counts.values())
        drop_share = (verdict_counts["dropped"] / total_anchored) if total_anchored else 0.0
        _row(sec, "plain-reason survival (in pipeline)",
             f"{verdict_counts['kept']} kept / {verdict_counts['weakened']} weakened / "
             f"{verdict_counts['dropped']} dropped of {total_anchored}",
             _verdict(drop_share, 0.10, 0.30))
        _row(sec, "pipeline-added reasons", f"{added_total} total ({added_total / judged:.1f}/response)"
             + (f"  ({surv_failures} judge failures)" if surv_failures else ""))
        survival = {"judged": judged, "failures": surv_failures, "added_total": added_total,
                    "dropped_share": round(drop_share, 3), **verdict_counts}
    report["moral_patient_reasons"] = {
        "n": len(per_case), "failures": failures, "model": config.get("model"),
        "pipeline": p, "plain": b, "survival": survival, "per_case": per_case,
    }


def carry_forward_reasons(old_report: dict, report: dict) -> bool:
    """When an offline audit re-runs on a run whose previous report carries the
    paid --reasons data, keep that data (and its display section) instead of
    silently dropping it. Returns True when something was carried forward."""
    old = old_report.get("moral_patient_reasons")
    if not old:
        return False
    report["moral_patient_reasons"] = old
    old_sec = next((s for s in old_report.get("sections") or []
                    if s.get("title") == "Moral-patient reasons (LLM)"), None)
    if old_sec:
        report.setdefault("sections", []).append(old_sec)
    return True


# ---------------------------------------------------------------- length (delegated)


def audit_lengths(run_dir: Path | None, report: dict) -> None:
    sec = _section(report, "Length-class realization")
    if run_dir is None:
        _row(sec, "length report", "skipped", note="(bare-file input; pass a run dir)")
        return
    from evals.openings_dad import prompt_length_report
    stats = prompt_length_report(run_dir)
    report["prompt_lengths"] = stats
    # prompt_length_report owns the terminal printing for this section; mirror
    # its numbers into rows without echoing so the output stays unchanged.
    if not stats.get("n"):
        _row(sec, "prompts", "0", echo=False)
        return
    _row(sec, "prompt lengths",
         f"{stats['n']} prompts | chars min {stats.get('min', '?')} / median {stats['median']} "
         f"/ max {stats.get('max', '?')} | {stats.get('over_1000', '?')} over 1000", echo=False)
    by_class = stats.get("by_class") or {}
    if by_class:
        from dad_pipeline.compose_scenarios import length_band
        ordered = sorted(by_class, key=lambda c: length_band(c) or (0, 0))
        for cls in ordered:
            vals = by_class[cls]
            _row(sec, cls, f"n={len(vals)}, chars {vals[0]}-{vals[-1]}, "
                           f"median {vals[len(vals) // 2]}", echo=False)
        oob = stats.get("out_of_band") or []
        _row(sec, "records outside their band", str(len(oob)),
             "GOOD" if not oob else "BAD", echo=False)


# ---------------------------------------------------------------- main


def main() -> None:
    parser = argparse.ArgumentParser(description="Corpus-level audit of DAD step-1 prompts.")
    parser.add_argument("--input", default="outputs/dad/latest",
                        help="Run directory or step1/dilemmas.jsonl path")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--reasons", action="store_true",
                        help="LLM pass: distinct moral-patient reasons per response, "
                             "pipeline vs plain baseline (costs API calls)")
    parser.add_argument("--config", default="config.yaml",
                        help="Config for --reasons (model/workers)")
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
    audit_response_lengths(run_dir, report)
    print()
    audit_stock_phrases(run_dir, report)
    print()
    audit_lexical(run_dir, report)
    print()
    audit_structure(run_dir, report)
    print()
    audit_response_openings(run_dir, report)
    print()
    audit_library_coverage(run_dir, report)  # response-diversity block: conceptual coverage
    print()
    out = report_dir / "audit_report.json"
    if args.reasons:
        from shared import api
        api.init(args.config)  # evals log to the global cost log
        audit_reasons(run_dir, utils.load_config(args.config), report)
        print()
    elif out.exists():
        try:
            old_report = json.load(open(out, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old_report = {}
        if carry_forward_reasons(old_report, report):
            print(" Moral-patient reasons (LLM) — carried forward from the previous "
                  "report (re-run with --reasons to refresh)\n")
    audit_lengths(run_dir, report)

    utils.ensure_dir(report_dir)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nReport written to {out}")


if __name__ == "__main__":
    main()
