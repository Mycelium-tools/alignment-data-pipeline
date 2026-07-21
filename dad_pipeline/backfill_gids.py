"""Backfill stable response/plain/example gids onto historical DAD runs.

The registry gained three kinds after scenario/prompt (see id_registry.py):
response_gid (R-####, step-2 draft responses), plain_gid (C-####, baseline
control responses), example_gid (E-####, finished user/assistant pairs). This
script labels the runs that predate them, walking `outputs/dad/runs/` in
directory-name (chronological) order and starting from the first run that
carries S-/P- gids — so the new numbering timeline matches the registry's
scenario/prompt history. Pre-registry runs are left untouched.

Content-keyed and idempotent: records that already carry a gid are skipped,
and re-running assigns nothing new. Run it any time with:

    python dad_pipeline/backfill_gids.py [--runs-root outputs/dad/runs] [--dry-run]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import utils
from dad_pipeline.id_registry import IdRegistry, example_fingerprint, response_fingerprint


def _insert_after(rec: dict, after_key: str, key: str, value) -> dict:
    """The record with `key: value` placed right after `after_key` (or
    appended), so backfilled files read like pipeline-written ones."""
    out = {}
    for k, v in rec.items():
        out[k] = v
        if k == after_key:
            out[key] = value
    if key not in out:
        out[key] = value
    return out


def _label_file(path: Path, label_record, dry_run: bool) -> int:
    """Apply `label_record` (returns a new record or None for no change) to
    every record in a jsonl file; rewrite the file only if anything changed.
    Returns the number of newly labeled records."""
    if not path.exists():
        return 0
    records = utils.load_jsonl(path)
    changed = 0
    out = []
    for rec in records:
        new = label_record(rec)
        out.append(new if new is not None else rec)
        changed += new is not None
    if changed and not dry_run:
        utils.save_jsonl(out, path)
    return changed


def backfill_run(run_dir: Path, registry: IdRegistry, dry_run: bool = False) -> dict:
    """Label one run's step2/baseline/step3/final files. Returns per-file
    counts of newly labeled records (empty dict for a pre-gid-era run)."""
    dilemmas = utils.load_jsonl(run_dir / "step1" / "dilemmas.jsonl")
    if not any(d.get("prompt_gid") or d.get("scenario_gid") for d in dilemmas):
        return {}  # pre-registry run: outside the labeling window

    counts = {}

    def responses(rec):
        if rec.get("response_gid") or not rec.get("assistant_response"):
            return None
        gid = registry.gid("response", response_fingerprint(rec["assistant_response"]))
        return _insert_after(rec, "response_id", "response_gid", gid)

    counts["step2/responses.jsonl"] = _label_file(
        run_dir / "step2" / "responses.jsonl", responses, dry_run)

    def plain(rec):
        if rec.get("plain_gid") or not rec.get("baseline_response"):
            return None
        gid = registry.gid("plain", response_fingerprint(rec["baseline_response"]))
        return _insert_after(rec, "prompt_id", "plain_gid", gid)

    counts["baseline/baseline_responses.jsonl"] = _label_file(
        run_dir / "baseline" / "baseline_responses.jsonl", plain, dry_run)

    # Rewrites carry the step-2 draft verbatim, so the response fingerprint
    # resolves to the same R-#### with no join needed.
    gids_by_record_id = {}

    def rewrites(rec):
        example = None
        if rec.get("user_message") and rec.get("rewritten_response"):
            example = registry.gid("example", example_fingerprint(
                rec["user_message"], rec["rewritten_response"]))
        response = (registry.gid("response", response_fingerprint(rec["draft_response"]))
                    if rec.get("draft_response") else None)
        if rec.get("record_id"):
            gids_by_record_id[rec["record_id"]] = (example, response)
        if rec.get("example_gid") or rec.get("response_gid"):
            return None
        new = _insert_after(rec, "record_id", "example_gid", example)
        return _insert_after(new, "response_id", "response_gid", response)

    counts["step3/rewrites.jsonl"] = _label_file(
        run_dir / "step3" / "rewrites.jsonl", rewrites, dry_run)

    def final(rec):
        if rec.get("example_gid"):
            return None
        example, response = gids_by_record_id.get(rec.get("record_id"), (None, None))
        if example is None and len(rec.get("messages") or []) > 1:
            example = registry.gid("example", example_fingerprint(
                rec["messages"][0].get("content", ""), rec["messages"][1].get("content", "")))
        if example is None and response is None:
            return None
        new = _insert_after(rec, "record_id", "example_gid", example)
        return _insert_after(new, "example_gid", "response_gid", response)

    counts["final/dad_corpus.jsonl"] = _label_file(
        run_dir / "final" / "dad_corpus.jsonl", final, dry_run)

    return {k: v for k, v in counts.items() if v}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--runs-root", default="outputs/dad/runs",
                        help="the DAD runs directory (default: outputs/dad/runs)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be labeled without writing anything")
    args = parser.parse_args()

    runs_root = Path(args.runs_root)
    registry = IdRegistry(runs_root.parent / "id_registry.json")

    labeled_any = False
    for run_dir in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        counts = backfill_run(run_dir, registry, dry_run=args.dry_run)
        if counts:
            labeled_any = True
            detail = ", ".join(f"{k} +{v}" for k, v in counts.items())
            print(f"{run_dir.name}: {detail}")
    if not args.dry_run and labeled_any:
        registry.save()
        print(f"Registry updated: {registry.path}")
    elif not labeled_any:
        print("Nothing to label — all gid-era runs already carry response/plain/example gids.")


if __name__ == "__main__":
    main()
