"""Stable, content-keyed global ids for scenarios and prompts.

The per-run ids — scenario_id (S-###) and prompt_id (AW-####) — reset every run
and are unique only within a run, so they can't identify "the same scenario/
prompt" across runs. This registry adds a *stable* id alongside them:
scenario_gid / prompt_gid, which counts up globally and is reused whenever the
same content appears again. That lets the compare viewer align the same
scenario or prompt across runs (e.g. reuse a scenario set, vary the prompt
templates, and compare). Additive — the per-run ids are untouched.

The registry is a git-tracked JSON file shared across runs (one id space); in
tests it lives under the tmp output root, so it never touches the real one.
"""

import hashlib
import json
from pathlib import Path


def _fingerprint(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]


def scenario_fingerprint(scenario: dict) -> str:
    """Hash of a scenario's categorical shape — everything but its own ids."""
    return _fingerprint({k: v for k, v in scenario.items()
                         if k not in ("scenario_id", "scenario_gid")})


def prompt_fingerprint(user_message: str) -> str:
    """Hash of the whitespace-normalized user message."""
    return _fingerprint(" ".join((user_message or "").split()))


class IdRegistry:
    """Maps a content fingerprint to a stable integer per kind ('scenario' /
    'prompt'). New content gets max+1; seen content keeps its number; numbers
    never reset across runs. Persisted as JSON."""

    KINDS = ("scenario", "prompt")

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: dict[str, dict[str, int]] = {k: {} for k in self.KINDS}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                loaded = {}
            if isinstance(loaded, dict):
                for kind in self.KINDS:
                    table = loaded.get(kind)
                    if isinstance(table, dict):
                        self._data[kind] = {str(k): int(v) for k, v in table.items()}

    def assign(self, kind: str, fingerprint: str) -> int:
        """Return the stable number for this content, allocating the next one
        (global max + 1) the first time it's seen."""
        table = self._data.setdefault(kind, {})
        if fingerprint not in table:
            table[fingerprint] = max(table.values(), default=0) + 1
        return table[fingerprint]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
