"""Shared utilities: JSONL I/O, checkpointing, prompt loading, run scoping."""

import json
import os
import random
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, UTC

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


def extract_json(text: str):
    """Parse the JSON value in a model response, tolerating surrounding chatter.

    Models occasionally wrap their JSON in markdown fences or add prose before
    or after it ("Here are the subtypes: [...] Let me know if..."), which bare
    json.loads rejects ("Extra data" / "Expecting value") — crashing a paid run
    on an otherwise usable response. This tries a full parse from every `[`/`{`
    in the text and returns the longest value that parses, so a short bracketed
    aside in the preamble can't shadow the real payload.

    Raises json.JSONDecodeError when no complete JSON value is present — and
    also when the payload itself is broken: truncated by max_tokens, or
    malformed mid-array (missing/trailing comma, both common LLM slip-ups).
    A broken container usually contains smaller values that do parse, and
    salvaging such a fragment would feed the caller a wrong-shaped result
    (a dict where a list was expected, with elements silently dropped)
    instead of a clean parse error. The unifying signal: a failed parse
    whose consumed region fully contains a successfully parsed candidate is
    a real payload that broke partway — candidates inside or after it are
    its fragments and are disqualified, while a complete value found before
    it (a genuine payload followed by broken chatter) is still returned.

    strict=False: literal control characters inside string values (raw
    newlines/tabs) are tolerated — the way prose-heavy JSON at temperature 1.0
    most often goes invalid, and the historical cause of silently empty scopes.
    """
    decoder = json.JSONDecoder(strict=False)
    candidates = []  # (start, end, value)
    failures = []  # (start, position where the parse gave up)
    for match in re.finditer(r"[\[{]", text):
        try:
            value, end = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError as err:
            failures.append((match.start(), err.pos))
            continue
        candidates.append((match.start(), end, value))

    broken = [q for q, p in failures
              if any(q < s and e <= p for s, e, _ in candidates)]
    eligible = [c for c in candidates
                if not any(c[0] > q for q in broken)]
    if eligible:
        return max(eligible, key=lambda c: c[1] - c[0])[2]
    if broken:
        raise json.JSONDecodeError(
            "JSON container is malformed or truncated", text, min(broken)
        )
    raise json.JSONDecodeError("no JSON value found in response", text, 0)


def load_prompt(path: str | Path, **kwargs) -> str:
    text = Path(path).read_text()
    if kwargs:
        text = text.format(**kwargs)
    return text


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def sample_language(distribution: dict[str, float], rng: random.Random | None = None) -> str:
    chooser = rng or random
    languages = list(distribution.keys())
    weights = list(distribution.values())
    return chooser.choices(languages, weights=weights, k=1)[0]


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
    """Point parent/latest at run_dir. Symlinks on Windows need Developer Mode
    or elevation (WinError 1314), so fall back to a directory junction (no
    privilege required), and failing that warn and continue — the pointer is a
    convenience; resolve_run_dir orders runs by directory name, not this link."""
    link = parent / "latest"
    # lexists also catches broken symlinks and junctions, which exists() misses.
    if os.path.lexists(link):
        link.unlink()
    try:
        link.symlink_to(run_dir.relative_to(parent), target_is_directory=True)
    except OSError:
        try:
            # Junction targets must be absolute; mklink is a cmd builtin.
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(run_dir.resolve())],
                check=True, capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError):
            print(
                f"  WARNING: could not update the {link} pointer (no symlink "
                "privilege, junction fallback failed); runs are unaffected.",
                file=sys.stderr,
            )


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


def warn_if_backend_changed(run_dir: str | Path, live_config: dict) -> None:
    """On --resume, warn if the live config's `backend` differs from the one the
    run started with (recorded in run_manifest.json).

    Switching mid-run is allowed — flipping to `api` after hitting the
    claude_code usage limit is the documented recovery — but it mixes generation
    semantics and cost accounting within one run, so surface it rather than
    letting it happen silently.
    """
    manifest_path = Path(run_dir) / "run_manifest.json"
    if not manifest_path.is_file():
        return
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return
    started = (manifest.get("config") or {}).get("backend", "api")
    current = live_config.get("backend", "api")
    if started != current:
        print(
            f"  WARNING: this run started on backend {started!r} but config.yaml now says "
            f"{current!r}. Resuming will finish it under a different backend (mixed generation "
            "semantics and cost accounting in one run). Each cost_log.jsonl row is tagged with "
            "its backend.",
            file=sys.stderr,
        )


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
            self._data["last_updated"] = datetime.now(UTC).isoformat()
            ensure_dir(self.path.parent)
            with open(self.path, "w") as f:
                json.dump(self._data, f)

    @property
    def done_count(self) -> int:
        return len(self._completed)
