"""Shared utilities: JSONL I/O, checkpointing, prompt loading, run scoping."""

import json
import os
import random
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime

import yaml


def parallel_map(fn, items: list, workers: int):
    """Map fn over items with a thread pool, yielding results in input order.

    fn must be side-effect free (API call + parsing only): because results come
    back in input order, callers can zip() them with items and keep all file
    writes and checkpoint marks on their own thread. If a call ultimately fails,
    the exception surfaces here; items already yielded are safely checkpointed
    and --resume picks up the rest.
    """
    if workers <= 1 or len(items) <= 1:
        yield from map(fn, items)
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        yield from pool.map(fn, items)


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_jsonl(data: list[dict], path: str | Path, append: bool = False) -> None:
    p = Path(path)
    ensure_dir(p.parent)
    mode = "a" if append else "w"
    with open(p, mode) as f:
        for record in data:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_jsonl(record: dict, path: str | Path) -> None:
    p = Path(path)
    ensure_dir(p.parent)
    with open(p, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    records = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_prompt(path: str | Path, **kwargs) -> str:
    text = Path(path).read_text()
    if kwargs:
        text = text.format(**kwargs)
    return text


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def sample_language(distribution: dict[str, float]) -> str:
    languages = list(distribution.keys())
    weights = list(distribution.values())
    return random.choices(languages, weights=weights, k=1)[0]


def new_run_id(label: str) -> str:
    """Mint a run ID: timestamp (to the minute) + sanitized label suffix."""
    safe_label = re.sub(r"[^a-zA-Z0-9_-]", "-", label.strip())
    return f"{datetime.now().strftime('%Y-%m-%d_%H-%M')}_{safe_label}"


def _git_status() -> tuple[str | None, bool, list[str]]:
    """Return (short_commit, dirty, dirty_files) for the repo, or (None, False, []) outside git."""
    cwd = Path(__file__).parent
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True, cwd=cwd,
        ).stdout.strip()
        porcelain = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, check=True, cwd=cwd,
        ).stdout
        dirty_files = [line[3:].strip() for line in porcelain.splitlines() if line.strip()]
        return commit, bool(dirty_files), dirty_files
    except Exception:
        return None, False, []


def _update_latest_symlink(parent: Path, run_dir: Path) -> None:
    link = parent / "latest"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(run_dir.relative_to(parent), target_is_directory=True)


def create_run_dir(
    runs_root: str | Path,
    label: str,
    config: dict,
    snapshot_dirs: dict[str, Path] | None = None,
) -> Path:
    """Create a new run directory with a manifest, and point the `latest` symlink at it.

    snapshot_dirs maps name -> source directory; each is copied into
    run_dir/inputs/<name> so the run stays reproducible even after the
    source files (prompt templates, constitution) change.
    """
    runs_root = Path(runs_root)
    run_id = new_run_id(label)
    run_dir = runs_root / run_id
    suffix = 2
    while run_dir.exists():
        run_dir = runs_root / f"{run_id}-{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True)

    if snapshot_dirs:
        for name, src in snapshot_dirs.items():
            shutil.copytree(src, run_dir / "inputs" / name)

    commit, dirty, dirty_files = _git_status()
    manifest = {
        "manifest_version": 2,
        "run_id": run_dir.name,
        "label": label,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "git_commit": commit,
        "git_dirty": dirty,
        "git_dirty_files": dirty_files,
        "inputs_snapshot": bool(snapshot_dirs),
        "model": config.get("model"),
        "config": config,
    }
    with open(run_dir / "run_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    _update_latest_symlink(runs_root.parent, run_dir)
    return run_dir


def resolve_constitution_dir(prompts_dir: str | Path) -> Path | None:
    """If prompts_dir is a run's input snapshot (.../inputs/prompts), return the
    sibling inputs/constitution dir; otherwise None (callers fall back to the
    repo's live constitution/)."""
    prompts_dir = Path(prompts_dir)
    if prompts_dir.name == "prompts" and prompts_dir.parent.name == "inputs":
        candidate = prompts_dir.parent / "constitution"
        if candidate.is_dir():
            return candidate
    return None


def resolve_run_dir(runs_root: str | Path, run_id: str | None = None) -> Path:
    """Find an existing run directory: by ID if given, otherwise the most recent."""
    runs_root = Path(runs_root)
    if run_id:
        run_dir = runs_root / run_id
        if not run_dir.is_dir():
            raise SystemExit(f"Run '{run_id}' not found under {runs_root}")
        return run_dir
    runs = sorted(d for d in runs_root.iterdir() if d.is_dir()) if runs_root.is_dir() else []
    if not runs:
        raise SystemExit(f"No runs found under {runs_root} — nothing to resume.")
    return runs[-1]


class Checkpoint:
    """Persist a set of completed IDs to disk so runs can be resumed."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._data: dict = {"completed": [], "last_updated": None}
        if self.path.exists():
            with open(self.path) as f:
                self._data = json.load(f)
        self._completed: set = set(self._data.get("completed", []))

    def is_done(self, id_: str | int) -> bool:
        return str(id_) in self._completed

    def mark_done(self, id_: str | int) -> None:
        key = str(id_)
        if key not in self._completed:
            self._completed.add(key)
            self._data["completed"] = list(self._completed)
            self._data["last_updated"] = datetime.utcnow().isoformat()
            ensure_dir(self.path.parent)
            with open(self.path, "w") as f:
                json.dump(self._data, f)

    @property
    def done_count(self) -> int:
        return len(self._completed)
