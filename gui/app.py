#!/usr/bin/env python3
"""
Prompt Studio — a tiny local web app for viewing, editing, and running the
pipeline prompts without touching the Python scripts underneath.

Run it:   python gui/app.py
Then open: http://localhost:8765  (it tries to open your browser automatically)

It serves a single-page UI (gui/index.html) and a small JSON API. Nothing
leaves your machine: prompts are read/written under prompts/, generated text is
written under outputs/gui_runs/, and your API key (if you use API mode) is
stored only in the local .env file.
"""

import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent.parent          # repo root
GUI = ROOT / "gui"
RUNS_DIR = ROOT / "outputs" / "gui_runs"
RUNS_LOG = RUNS_DIR / "runs.jsonl"
ENV_PATH = ROOT / ".env"
PORT = int(os.environ.get("PROMPT_STUDIO_PORT", "8765"))

# ---------- helpers ----------

def _safe(rel: str) -> Path:
    """Resolve a repo-relative path and refuse anything outside the repo."""
    p = (ROOT / rel).resolve()
    if not str(p).startswith(str(ROOT)):
        raise ValueError("path escapes repo root")
    return p

# Read endpoints may only reach these subtrees, and never a dotfile (e.g. .env).
ALLOWED_READ_PREFIXES = ("prompts/", "outputs/", "constitution/")

def _safe_read(rel: str) -> Path:
    rel = (rel or "").strip()
    if any(part.startswith(".") for part in Path(rel).parts):
        raise ValueError("path not readable")
    if not rel.startswith(ALLOWED_READ_PREFIXES):
        raise ValueError("path not readable")
    return _safe(rel)

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _load_env_key() -> str:
    # Prefer a real environment variable; otherwise read .env directly.
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"].strip()
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""

def _save_env_key(key: str) -> None:
    lines = []
    found = False
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY"):
                lines.append(f"ANTHROPIC_API_KEY={key}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"ANTHROPIC_API_KEY={key}")
    ENV_PATH.write_text("\n".join(lines) + "\n")

def _model() -> str:
    cfg = ROOT / "config.yaml"
    if cfg.exists():
        for line in cfg.read_text().splitlines():
            if line.strip().startswith("model:"):
                return line.split(":", 1)[1].strip()
    return "claude-sonnet-4-6"

def _compose(template: str, variables: dict) -> str:
    """Substitute {name} placeholders. Unknown placeholders are left intact."""
    def repl(m):
        k = m.group(1)
        return str(variables[k]) if k in variables else m.group(0)
    return re.sub(r"\{(\w+)\}", repl, template)

# ---------- run backends ----------

def _run_api(system: str, user: str) -> tuple[str, str]:
    """Return (output, error). Uses the Anthropic API + stored key."""
    key = _load_env_key()
    if not key:
        return "", "No API key saved. Add one in Settings, or use Claude Code CLI mode."
    try:
        import anthropic
    except ImportError:
        return "", "The 'anthropic' package isn't installed (pip install -r requirements.txt)."
    try:
        client = anthropic.Anthropic(api_key=key, max_retries=0)
        msg = client.messages.create(
            model=_model(),
            max_tokens=4000,
            system=system or "",
            messages=[{"role": "user", "content": user}],
        )
        return "".join(getattr(b, "text", "") for b in msg.content), ""
    except Exception as e:  # surface billing/auth/etc. plainly
        return "", f"{type(e).__name__}: {e}"

def _run_cli(system: str, user: str) -> tuple[str, str]:
    """Return (output, error). Shells out to the Claude Code CLI (`claude -p`)."""
    prompt = (system + "\n\n" + user).strip() if system else user
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True, text=True, timeout=600,
        )
    except FileNotFoundError:
        return "", "Claude Code CLI not found. Install it, or switch to API mode."
    except subprocess.TimeoutExpired:
        return "", "Claude Code CLI timed out (10 min)."
    if proc.returncode != 0:
        return "", (proc.stderr or "claude exited non-zero").strip()
    return proc.stdout.strip(), ""

def _do_run(body: dict) -> dict:
    prompt_path = body.get("promptPath", "")
    template = _safe(prompt_path).read_text() if prompt_path else body.get("promptText", "")
    variables = body.get("variables", {}) or {}
    system = body.get("system", "") or ""
    mode = body.get("mode", "cli")
    composed = _compose(template, variables)
    output, error = (_run_api if mode == "api" else _run_cli)(system, composed)
    rec = {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f"),
        "timestamp": _now(),
        "pipeline": body.get("pipeline", ""),
        "stage": body.get("stage", ""),
        "stage_name": body.get("stageName", ""),
        "promptPath": prompt_path,
        "mode": mode,
        "variables": variables,
        "system": system,
        "composed_prompt": composed,
        "output": output,
        "error": error,
    }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RUNS_LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec

def _read_jsonl(rel: str) -> list:
    p = _safe_read(rel)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out

# ---------- git / pull-request integration ----------
# Non-technical users edit prompts, bundle related edits into commits on a
# working branch (never the protected main), then open a PR upstream.
import shutil

GIT_PROTECTED = {"main", "master"}
BRANCH_RE = re.compile(r"^(?!-)[A-Za-z0-9._/][A-Za-z0-9._/-]{0,79}$")
UPSTREAM = "Mycelium-tools/alignment-data-pipeline"   # PR target repo
# Never let git/gh hang waiting for a credential prompt; fail fast instead.
_GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
_GIT_LOCK = threading.Lock()   # serialize HEAD-mutating ops across threads

def _have(tool: str) -> bool:
    return shutil.which(tool) is not None

def _run(cmd: list, timeout: int = 180, strip: bool = True):
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                       timeout=timeout, env=_GIT_ENV)
    out = p.stdout.strip() if strip else p.stdout
    return p.returncode, out, p.stderr.strip()

def _git(*args, timeout: int = 180, strip: bool = True):
    return _run(["git", *args], timeout=timeout, strip=strip)

def _gh(*args, timeout: int = 180):
    return _run(["gh", *args], timeout=timeout)

def _branch_name() -> str:
    # symbolic-ref gives the branch name; it fails on a detached HEAD (-> "" = detached)
    code, out, _ = _git("symbolic-ref", "--quiet", "--short", "HEAD")
    return out if code == 0 else ""

def _changed() -> list:
    # --untracked-files=all lists untracked files individually (not a collapsed dir);
    # -z + DO NOT strip (the leading space in codes like " M" is meaningful).
    code, out, _ = _git("status", "--porcelain", "--untracked-files=all", "-z", strip=False)
    files = []
    if code == 0 and out:
        toks = [t for t in out.split("\0") if t]
        i = 0
        while i < len(toks):
            tok = toks[i]
            if len(tok) < 4 or tok[2] != " ":
                i += 1
                continue
            xy, path = tok[:2], tok[3:]
            if xy and xy[0] in ("R", "C"):   # rename/copy: next token is the old path — consume it
                i += 1
            files.append({"path": path, "code": xy, "untracked": xy == "??"})
            i += 1
    return files

def _ahead_of_main() -> int:
    code, out, _ = _git("rev-list", "--count", "main..HEAD")
    try:
        return int(out) if code == 0 else 0
    except ValueError:
        return 0

def _branch_commits() -> list:
    if _branch_name() in GIT_PROTECTED:
        return []
    code, out, _ = _git("log", "--oneline", "--no-decorate", "-n", "50", "main..HEAD")
    rows = []
    if code == 0 and out:
        for line in out.splitlines():
            sha, _, subj = line.partition(" ")
            rows.append({"sha": sha, "subject": subj})
    return rows

def _gh_user() -> str:
    if not _have("gh"):
        return ""
    code, out, _ = _gh("api", "user", "--jq", ".login")
    return out if code == 0 else ""

def _status_dict() -> dict:
    branch = _branch_name()
    push_perm = None
    if _have("gh"):
        code, out, _ = _gh("api", f"repos/{UPSTREAM}", "--jq", ".permissions.push")
        if code == 0:
            push_perm = (out == "true")
    code, origin, _ = _git("remote", "get-url", "origin")
    return {
        "branch": branch,
        "detached": branch == "",
        "protected": (branch in GIT_PROTECTED) or (branch == ""),
        "files": _changed(),
        "branchCommits": _branch_commits(),
        "aheadOfMain": _ahead_of_main(),
        "ghAvailable": _have("gh"),
        "ghUser": _gh_user(),
        "pushPermOrigin": push_perm,
        "origin": origin if code == 0 else "",
        "upstream": UPSTREAM,
    }

def _diff(path: str) -> str:
    if path not in {f["path"] for f in _changed()}:
        raise ValueError("not a changed file")
    code, out, _ = _git("diff", "HEAD", "--", path)
    if out.strip():
        return out
    # untracked file: show it as all-added vs an empty file
    _, out, _ = _git("diff", "--no-index", "--", os.devnull, path)
    return out

def _make_branch(name: str) -> dict:
    name = (name or "").strip()
    if not BRANCH_RE.match(name) or name in GIT_PROTECTED:
        raise ValueError("Please use a simple branch name (letters, numbers, dashes, slashes) and not 'main'.")
    existed = _git("rev-parse", "--verify", "--quiet", name)[0] == 0
    code, _, err = (_git("switch", name) if existed else _git("switch", "-c", name))
    if code != 0:
        raise RuntimeError(err or "could not switch branch")
    st = _status_dict()
    st["switchedToExisting"] = existed
    return st

def _commit(message: str, files: list) -> dict:
    branch = _branch_name()
    if not branch or branch in GIT_PROTECTED:
        raise ValueError("You're not on a working branch yet (main is protected). Create a working branch first.")
    if not (message or "").strip():
        raise ValueError("A commit message is required.")
    valid = {f["path"] for f in _changed()}
    sel = [p for p in (files or []) if p in valid]
    if not sel:
        raise ValueError("None of the selected files have changes to commit.")
    code, _, err = _git("add", "--", *sel)
    if code != 0:
        raise RuntimeError(err or "git add failed")
    # pathspec on commit scopes the commit to exactly these files (a clean bundle)
    code, out, err = _git("commit", "-m", message, "--", *sel)
    if code != 0:
        raise RuntimeError(err or "git commit failed")
    return {"ok": True, "committed": sel, "summary": out.splitlines()[0] if out else "", "status": _status_dict()}

def _manual(branch: str, head: str = "", pushed: bool = True) -> dict:
    head = head or branch
    if pushed:
        return {
            "compareUrl": f"https://github.com/{UPSTREAM}/compare/main...{head}?expand=1",
            "pushHint": f"Your branch is pushed — open the compare link to finish the PR to {UPSTREAM} (base: main).",
        }
    return {
        "compareUrl": f"https://github.com/{UPSTREAM}",
        "pushHint": f"Push your branch (git push -u origin {branch}, or to your own fork), then open a PR to {UPSTREAM} (base: main).",
    }

def _submit(title: str, body: str) -> dict:
    branch = _branch_name()
    if not branch or branch in GIT_PROTECTED:
        raise ValueError("Switch to your working branch before submitting.")
    if not (title or "").strip():
        raise ValueError("A pull-request title is required.")
    if _ahead_of_main() == 0:
        raise ValueError("No commits to submit yet. Commit at least one bundle first.")

    def net(fn, *a):
        # turn a slow/hung network call into a normal failure so we can still offer a manual link
        try:
            return fn(*a)
        except subprocess.TimeoutExpired:
            return (124, "", "timed out (network slow, or it was waiting for credentials)")

    steps = []
    head = branch
    # 1) try pushing straight to origin (works only if you have write access)
    code, out, err = net(_git, "push", "-u", "origin", branch)
    steps.append({"step": "push to origin", "ok": code == 0, "detail": (err or out)[:300]})
    if code != 0:
        # 2) no write access → fork and push to the fork
        if not _have("gh"):
            return {"ok": False, "needsManual": True, "steps": steps, "manual": _manual(branch, pushed=False)}
        user = _gh_user()
        c, out, err = net(_gh, "repo", "fork", UPSTREAM, "--remote", "--remote-name", "fork", "--clone=false")
        steps.append({"step": "create your fork", "ok": c == 0, "detail": (err or out)[:300]})
        c, out, err = net(_git, "push", "-u", "fork", branch)
        steps.append({"step": "push to your fork", "ok": c == 0, "detail": (err or out)[:300]})
        if c != 0:
            return {"ok": False, "needsManual": True, "steps": steps, "manual": _manual(branch, f"{user}:{branch}", pushed=False)}
        head = f"{user}:{branch}"
    # 3) open the PR
    if not _have("gh"):
        return {"ok": False, "needsManual": True, "steps": steps, "manual": _manual(branch, head, pushed=True)}
    c, out, err = net(_gh, "pr", "create", "--repo", UPSTREAM, "--base", "main",
                      "--head", head, "--title", title, "--body", body or "")
    steps.append({"step": "open pull request", "ok": c == 0, "detail": (err or out)[:300]})
    if c == 0:
        url = next((ln for ln in out.splitlines() if ln.startswith("http")), out.strip())
        return {"ok": True, "prUrl": url, "head": head, "steps": steps}
    return {"ok": False, "needsManual": True, "steps": steps, "manual": _manual(branch, head, pushed=True)}

# ---------- HTTP handler ----------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, payload, ctype="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def _guard(self) -> bool:
        # Require a custom header the UI always sends. A cross-origin page can't set it
        # without a CORS preflight this server never answers, which blocks drive-by
        # (CSRF) calls to the /api endpoints. Same-origin UI requests pass through.
        if self.headers.get("X-Prompt-Studio") != "1":
            return False
        origin = self.headers.get("Origin")
        if origin and not (origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:")):
            return False
        return True

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path.startswith("/api/") and not self._guard():
            return self._send(403, {"error": "forbidden — open the app at the printed http://localhost URL"})
        try:
            if u.path in ("/", "/index.html"):
                return self._send(200, (GUI / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/pipeline":
                return self._send(200, json.loads((GUI / "pipeline.json").read_text()))
            if u.path == "/api/prompt":
                rel = q.get("path", [""])[0]
                return self._send(200, {"path": rel, "text": _safe_read(rel).read_text()})
            if u.path == "/api/file":
                rel = q.get("path", [""])[0]
                p = _safe_read(rel)
                return self._send(200, {"path": rel, "text": p.read_text() if p.exists() else ""})
            if u.path == "/api/records":
                return self._send(200, {"records": _read_jsonl(q.get("file", [""])[0])})
            if u.path == "/api/runs":
                return self._send(200, {"runs": list(reversed(_read_jsonl("outputs/gui_runs/runs.jsonl")))})
            if u.path == "/api/key":
                return self._send(200, {"hasKey": bool(_load_env_key())})
            if u.path == "/api/git/status":
                return self._send(200, _status_dict())
            if u.path == "/api/git/diff":
                p = q.get("path", [""])[0]
                return self._send(200, {"path": p, "diff": _diff(p)})
            return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(400, {"error": str(e)})

    def do_PUT(self):
        try:
            if not self._guard():
                return self._send(403, {"error": "forbidden"})
            b = self._body()
            if self.path == "/api/prompt":
                rel = b["path"]
                if not rel.startswith("prompts/"):
                    raise ValueError("only files under prompts/ are editable")
                _safe(rel).write_text(b["text"])
                return self._send(200, {"ok": True, "path": rel})
            if self.path == "/api/key":
                _save_env_key(b["key"].strip())
                return self._send(200, {"ok": True, "hasKey": True})
            return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(400, {"error": str(e)})

    def do_POST(self):
        try:
            if not self._guard():
                return self._send(403, {"error": "forbidden"})
            if self.path == "/api/run":
                return self._send(200, _do_run(self._body()))
            # serialize the HEAD-mutating git ops so two tabs can't interleave
            if self.path == "/api/git/branch":
                with _GIT_LOCK:
                    return self._send(200, _make_branch(self._body().get("name", "")))
            if self.path == "/api/git/commit":
                b = self._body()
                with _GIT_LOCK:
                    return self._send(200, _commit(b.get("message", ""), b.get("files", [])))
            if self.path == "/api/git/submit":
                b = self._body()
                with _GIT_LOCK:
                    return self._send(200, _submit(b.get("title", ""), b.get("body", "")))
            return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(400, {"error": str(e)})


def main():
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    server, port = None, PORT
    for candidate in range(PORT, PORT + 20):   # if a copy is already running, use the next free port
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    if server is None:
        print(f"\n  Couldn't find a free port near {PORT}. Close any other copies and try again.\n")
        sys.exit(1)
    url = f"http://localhost:{port}"
    print(f"\n  Prompt Studio is running.\n\n    Open this in your browser:   {url}\n\n"
          f"  Leave this window open while you use it. Press Ctrl-C here to stop.\n")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped. You can close this window.")
        sys.exit(0)


if __name__ == "__main__":
    main()
