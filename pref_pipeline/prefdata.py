"""Data access for the preference rating app. No Streamlit imports — testable standalone.

A rating stores the rater's choice both as the blinded side ("left"/"right",
plus "tie"/"both_bad") and deblinded to the underlying arm ("a"/"b"). The
training-ready export final/preferences.jsonl contains one chosen/rejected
record per decisive rating and is rebuilt after every rating.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import utils

RUNS_ROOT = Path(__file__).parent.parent / "outputs" / "pref" / "runs"

CHOICES = ("left", "right", "tie", "both_bad")


def list_runs(runs_root: Path = RUNS_ROOT) -> list[Path]:
    """Pref runs that have pairs to rate, newest first."""
    if not runs_root.is_dir():
        return []
    return [
        d for d in sorted(runs_root.iterdir(), reverse=True)
        if (d / "pairs" / "pairs.jsonl").exists()
    ]


def load_pairs(run_dir: Path) -> list[dict]:
    return utils.load_jsonl(run_dir / "pairs" / "pairs.jsonl")


def load_ratings(run_dir: Path) -> list[dict]:
    return utils.load_jsonl(run_dir / "ratings" / "ratings.jsonl")


def pending_pairs(pairs: list[dict], ratings: list[dict], rater: str) -> list[dict]:
    """Pairs this rater has not rated yet, in generation order."""
    rated = {r["pair_id"] for r in ratings if r.get("rater") == rater}
    return [p for p in pairs if p["pair_id"] not in rated]


def sides(pair: dict) -> tuple[str, str]:
    """(left_arm, right_arm) for blinded display."""
    left = pair.get("left_arm", "a")
    return left, ("b" if left == "a" else "a")


def record_rating(run_dir: Path, pair: dict, rater: str, choice: str, note: str = "") -> dict:
    """Persist one rating (choice: left/right/tie/both_bad) and rebuild the export."""
    if choice not in CHOICES:
        raise ValueError(f"choice must be one of {CHOICES}, got {choice!r}")
    left, right = sides(pair)
    rating = {
        "pair_id": pair["pair_id"],
        "rater": rater,
        "choice": choice,
        "chosen_arm": {"left": left, "right": right}.get(choice),
        "left_arm": left,
        "note": note.strip(),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    utils.append_jsonl(rating, run_dir / "ratings" / "ratings.jsonl")
    rebuild_preferences(run_dir)
    return rating


def rebuild_preferences(run_dir: Path) -> int:
    """Rebuild final/preferences.jsonl from all decisive ratings (ties and
    both_bad carry no chosen/rejected signal and are skipped).

    NOTE: this emits one record per decisive rating with no aggregation across
    raters. If two raters disagree on a pair, the file will contain two
    contradictory chosen/rejected records for the same prompt. That is fine for
    A/B spec analysis (the intended use), but the file must NOT be fed to
    preference training verbatim without a majority-vote / dedup pass first.
    """
    pairs = {p["pair_id"]: p for p in load_pairs(run_dir)}
    records = []
    for r in load_ratings(run_dir):
        pair = pairs.get(r["pair_id"])
        arm = r.get("chosen_arm")
        if not pair or arm not in ("a", "b"):
            continue
        other = "b" if arm == "a" else "a"
        records.append({
            "pair_id": pair["pair_id"],
            "prompt_id": pair["prompt_id"],
            "user_message": pair["user_message"],
            "chosen": pair[f"response_{arm}"],
            "rejected": pair[f"response_{other}"],
            "chosen_arm": arm,
            "chosen_arm_name": pair["arm_names"][arm],
            "rejected_arm_name": pair["arm_names"][other],
            "rater": r["rater"],
            "note": r.get("note", ""),
        })
    utils.save_jsonl(records, run_dir / "final" / "preferences.jsonl")
    return len(records)


def arm_win_counts(pairs: list[dict], ratings: list[dict]) -> dict[str, int]:
    """Choices per arm name (plus tie/both_bad), across all raters."""
    by_id = {p["pair_id"]: p for p in pairs}
    counts: dict[str, int] = {}
    for r in ratings:
        pair = by_id.get(r["pair_id"])
        if not pair:
            continue
        arm = r.get("chosen_arm")
        key = pair["arm_names"][arm] if arm in ("a", "b") else r["choice"]
        counts[key] = counts.get(key, 0) + 1
    return counts
