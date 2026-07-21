#!/usr/bin/env python3
"""Review queue for DAD phrase-tic candidates.

The audit (evals/audit_dad.py) writes candidate phrases to
<run>/audit/tic_candidates.jsonl every run — phrases rare in general English yet
over-represented in the corpus, not already promoted or dismissed. This tool
aggregates those across committed runs (recurrence = how many runs a phrase
shows up in) and lets a reviewer promote or dismiss them, editing the curated
lists in evals/tics.yaml.

NON-INTERACTIVE by design: it prints candidates or mutates the YAML in one shot,
so the decision happens in chat (through Claude Code) rather than at a TTY.

    python evals/review_tics.py list                       # pending candidates, most-recurrent first
    python evals/review_tics.py list --arm prompt --min-runs 2
    python evals/review_tics.py promote "gut check" --origin pipeline-origin --family performed-candor
    python evals/review_tics.py ignore "and honestly" --reason "common English filler"
"""
import argparse
import json
from pathlib import Path

import yaml

TICS = Path(__file__).parent / "tics.yaml"
RUNS_ROOT = Path(__file__).parent.parent / "outputs" / "dad" / "runs"


def load_watch_ignore(path: Path = TICS) -> tuple[dict, set]:
    """(watch: origin -> [phrases], ignore: set) from the YAML; empties if absent."""
    if not path.exists():
        return {}, set()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _phrases(entries) -> list:
        return [e["phrase"] if isinstance(e, dict) else e for e in (entries or [])]

    watch = {origin: _phrases(ents) for origin, ents in (data.get("watch") or {}).items()}
    return watch, set(_phrases(data.get("ignore")))


def _excluded(watch: dict, ignore: set) -> set:
    return ignore | {p for phrases in watch.values() for p in phrases}


def _covered(phrase: str, excluded: set) -> bool:
    return phrase in excluded or any(phrase in e or e in phrase for e in excluded)


def aggregate_candidates(runs_root: Path = RUNS_ROOT, tics_path: Path = TICS,
                         arm: str | None = None, min_runs: int = 1) -> list[dict]:
    """Candidates across all committed runs, minus anything now watched/ignored,
    aggregated per (phrase, arm): recurrence (# runs), peak z, peak prevalence."""
    watch, ignore = load_watch_ignore(tics_path)
    excluded = _excluded(watch, ignore)
    agg: dict = {}
    for f in sorted(Path(runs_root).glob("*/audit/tic_candidates.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if arm and r["arm"] != arm:
                continue
            phrase = r["phrase"]
            if _covered(phrase, excluded):
                continue
            a = agg.setdefault((phrase, r["arm"]), {
                "phrase": phrase, "arm": r["arm"], "runs": set(),
                "max_z": None, "max_prev": 0.0, "bg_zipf": r.get("bg_zipf"), "example": ""})
            a["runs"].add(r.get("run_id") or str(f.parent.parent.name))
            if r.get("z") is not None:
                a["max_z"] = r["z"] if a["max_z"] is None else max(a["max_z"], r["z"])
            if r.get("of"):
                a["max_prev"] = max(a["max_prev"], r["df"] / r["of"])
            if not a["example"] and r.get("example"):
                a["example"] = r["example"]
    rows = [{**v, "times_seen": len(v["runs"])} for v in agg.values()]
    rows = [r for r in rows if r["times_seen"] >= min_runs]
    rows.sort(key=lambda r: (-r["times_seen"], -(r["max_z"] or 0.0), -r["max_prev"]))
    return rows


def _duplicate_of(phrase: str, watch: dict, ignore: set) -> str | None:
    if phrase in ignore:
        return "ignore-list"
    for origin, phrases in watch.items():
        if phrase in phrases:
            return f"watch/{origin}"
    return None


def promote(phrase: str, origin: str, family: str | None = None,
            tics_path: Path = TICS) -> str:
    """Append a phrase to watch[origin] in the YAML (preserving comments)."""
    watch, ignore = load_watch_ignore(tics_path)
    dup = _duplicate_of(phrase, watch, ignore)
    if dup:
        return f"'{phrase}' is already in {dup}; nothing to do."
    entry = f'    - {{phrase: "{phrase}"' + (f", family: {family}" if family else "") + "}\n"
    header = f"  {origin}:"
    lines = tics_path.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.rstrip("\n") == header:
            lines.insert(i + 1, entry)
            break
    else:
        raise SystemExit(f"origin '{origin}' not found under 'watch:' in {tics_path}")
    tics_path.write_text("".join(lines), encoding="utf-8")
    return f"Promoted '{phrase}' -> watch/{origin}" + (f" (family {family})" if family else "")


def ignore_phrase(phrase: str, reason: str | None = None, tics_path: Path = TICS) -> str:
    """Append a phrase to the ignore-list in the YAML (preserving comments)."""
    watch, ignore = load_watch_ignore(tics_path)
    dup = _duplicate_of(phrase, watch, ignore)
    if dup:
        return f"'{phrase}' is already in {dup}; nothing to do."
    inline = f'{{phrase: "{phrase}"' + (f', reason: "{reason}"' if reason else "") + "}"
    text = tics_path.read_text(encoding="utf-8")
    if "ignore: []" in text:
        text = text.replace("ignore: []", f"ignore:\n  - {inline}")
    else:
        lines = text.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if line.rstrip("\n") == "ignore:":
                lines.insert(i + 1, f"  - {inline}\n")
                break
        else:
            raise SystemExit(f"no 'ignore:' key found in {tics_path}")
        text = "".join(lines)
    tics_path.write_text(text, encoding="utf-8")
    return f"Ignored '{phrase}'" + (f" ({reason})" if reason else "")


def _cmd_list(args) -> None:
    rows = aggregate_candidates(Path(args.runs_root), Path(args.tics),
                                arm=args.arm, min_runs=args.min_runs)[:args.limit]
    if not rows:
        print("No pending candidates. (Run the audit on a run, or loosen --min-runs.)")
        return
    print(f"{len(rows)} pending candidate(s) — most-recurrent first:\n")
    for r in rows:
        z = f"z {r['max_z']}" if r["max_z"] is not None else "z —"
        print(f"[{r['arm']:>8}] {r['phrase']!r}  seen in {r['times_seen']} run(s), "
              f"prev {r['max_prev']:.0%}, {z}, zipf {r['bg_zipf']}")
        if r["example"]:
            print(f"            e.g. {r['example']}")
    print('\nPromote: python evals/review_tics.py promote "<phrase>" '
          "--origin pipeline-origin --family <family>")
    print('Ignore:  python evals/review_tics.py ignore "<phrase>" --reason "<why>"')


def _cmd_promote(args) -> None:
    print(promote(args.phrase, args.origin, args.family, Path(args.tics)))


def _cmd_ignore(args) -> None:
    print(ignore_phrase(args.phrase, args.reason, Path(args.tics)))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd")

    pl = sub.add_parser("list", help="show pending candidates across committed runs")
    pl.add_argument("--runs-root", default=str(RUNS_ROOT))
    pl.add_argument("--tics", default=str(TICS))
    pl.add_argument("--arm", choices=["response", "prompt"], default=None)
    pl.add_argument("--min-runs", type=int, default=1)
    pl.add_argument("--limit", type=int, default=30)
    pl.set_defaults(func=_cmd_list)

    pp = sub.add_parser("promote", help="add a candidate to the watchlist")
    pp.add_argument("phrase")
    pp.add_argument("--origin", choices=["pipeline-origin", "plain-origin"],
                    default="pipeline-origin")
    pp.add_argument("--family", default=None)
    pp.add_argument("--tics", default=str(TICS))
    pp.set_defaults(func=_cmd_promote)

    pi = sub.add_parser("ignore", help="dismiss a candidate (never surfaced again)")
    pi.add_argument("phrase")
    pi.add_argument("--reason", default=None)
    pi.add_argument("--tics", default=str(TICS))
    pi.set_defaults(func=_cmd_ignore)
    return p


def main(argv: list | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):  # bare invocation -> default to `list`
        args = parser.parse_args(["list"])
    args.func(args)


if __name__ == "__main__":
    main()
