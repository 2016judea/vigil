"""VIGIL state engine.

Derives fleet state from two sources:
  * `claude agents --json`      -> liveness only (pid, cwd, sessionId, startedAt)
  * ~/.claude/projects/**.jsonl -> everything else, by tailing the transcript

The load-bearing detail is in `classify`: an unanswered tool_use at the tail means
EITHER "blocked on a permission prompt" OR "mid-tool-call right now". Only a
two-sample delta separates them. See SPEC.md.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

HOME = Path.home()
PROJECTS = HOME / ".claude" / "projects"

# the conventional places a checkout sits, one level below home.
#
# `Documents` and `Downloads` are deliberately absent. They are TCC-protected,
# and a launchd agent has no grant and no way to prompt -- so merely globbing
# one BLOCKS FOREVER instead of raising, which no try/except can catch. Adding
# `Documents` here hung /api/continuity permanently; the lens never answered.
# `Desktop` is protected too, but it is where the daemon was already reading
# from and it is granted; anything else goes in VIGIL_ROOTS explicitly.
_DEFAULT_ROOTS = ("Desktop", "code", "src", "dev", "repos", "projects", "work")

# how much of a transcript tail to parse; bounded so a 50MB session stays cheap
TAIL_BYTES = 512 * 1024

# a frozen transcript is only "blocked" once it has been still this long. below
# this, a pending tool_use is just a call in flight.
FROZEN_AFTER = 20.0
# past this, an alive-but-silent session has been parked rather than abandoned
RESTING_AFTER = 30 * 60.0
# repo attribution needs a full scan, so re-derive it on a slow clock
REPO_RECHECK = 300.0

# candidate locations for the CLI, which is not on PATH under the VS Code extension
_CLI_CANDIDATES = [
    HOME / ".local/bin/claude",
    Path("/opt/homebrew/bin/claude"),
    Path("/usr/local/bin/claude"),
]


def workspace_roots() -> list[Path]:
    """Directories that *contain* repos, one level down. `VIGIL_ROOTS` overrides
    (colon-separated), otherwise the conventional locations that exist.

    A single hardcoded root is the wrong failure: the continuity and rot lenses
    would return *fewer rows* on a machine laid out differently rather than an
    error, and a thin reading is indistinguishable from a quiet one.
    """
    env = os.environ.get("VIGIL_ROOTS", "").strip()
    if env:
        return [Path(p).expanduser() for p in env.split(":") if p.strip()]
    return [HOME / n for n in _DEFAULT_ROOTS if (HOME / n).is_dir()]


def claude_binary() -> str | None:
    """Locate the claude CLI. The VS Code extension ships its own and does not
    put it on PATH, so glob the extensions directory as a fallback."""
    for p in _CLI_CANDIDATES:
        if p.exists():
            return str(p)
    ext = sorted((HOME / ".vscode" / "extensions").glob("anthropic.claude-code-*/resources/native-binary/claude"))
    return str(ext[-1]) if ext else None


def live_sessions() -> list[dict]:
    """Live Claude processes. Liveness only -- this call carries no status."""
    exe = claude_binary()
    if not exe:
        return []
    try:
        out = subprocess.run(
            [exe, "agents", "--json"], capture_output=True, text=True, timeout=20
        ).stdout
        return json.loads(out) if out.strip().startswith("[") else []
    except Exception:
        return []


def _tail_lines(path: Path, nbytes: int = TAIL_BYTES) -> list[dict]:
    """Parse the last `nbytes` of a JSONL transcript, dropping the leading
    partial line."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > nbytes:
                fh.seek(size - nbytes)
                fh.readline()  # discard the partial line we landed inside
            raw = fh.read()
    except OSError:
        return []
    rows = []
    for line in raw.split(b"\n"):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _pending_calls(rows: list[dict]) -> list[dict]:
    """tool_use blocks issued but never answered, within the parsed window."""
    issued: dict[str, dict] = {}
    answered: set[str] = set()
    for d in rows:
        if d.get("type") == "assistant":
            for b in d.get("message", {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    issued[b.get("id")] = b
        elif d.get("type") == "user":
            c = d.get("message", {}).get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        answered.add(b.get("tool_use_id"))
    return [b for tid, b in issued.items() if tid not in answered]


def _pending_tool_uses(rows: list[dict]) -> list[str]:
    return [b.get("name", "?") for b in _pending_calls(rows)]


def _asked(rows: list[dict]) -> str:
    """What the blocked session is actually asking.

    The last assistant *text* is usually a paragraph of preamble; the real
    question lives in the tool input. Prefer it -- the alarm should carry the
    question, not the run-up to it.
    """
    for b in _pending_calls(rows):
        inp = b.get("input") or {}
        name = b.get("name")
        if name == "AskUserQuestion":
            qs = inp.get("questions") or []
            if qs and isinstance(qs[0], dict) and qs[0].get("question"):
                return str(qs[0]["question"])
        if name == "ExitPlanMode":
            return "Approve the plan?"
        if name in ("Edit", "Write", "NotebookEdit"):
            fp = inp.get("file_path")
            if fp:
                return f"Permission to write {Path(fp).name}"
        if name == "Bash":
            cmd = str(inp.get("command", ""))[:120]
            if cmd:
                return f"Permission to run: {cmd}"
    return ""


def _last_texts(rows: list[dict]) -> tuple[str, str]:
    """(last thing you typed, last thing Claude said) within the window."""
    user_txt = asst_txt = ""
    for d in rows:
        if d.get("type") == "assistant":
            for b in d.get("message", {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip():
                    asst_txt = b["text"].strip()
        elif d.get("type") == "user" and not d.get("isMeta") and d.get("toolUseResult") is None:
            c = d.get("message", {}).get("content")
            s = c if isinstance(c, str) else "".join(
                b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"
            ) if isinstance(c, list) else ""
            s = s.strip()
            if s and not s.startswith("<") and "system-reminder" not in s[:200]:
                user_txt = s
    return user_txt, asst_txt


def _git_root(p: Path) -> Path | None:
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    return None


class Engine:
    """Holds the previous sample so state can be a delta, not a snapshot."""

    def __init__(self) -> None:
        self._prev: dict[str, tuple[int, float]] = {}   # sid -> (size, sampled_at)
        self._frozen_since: dict[str, float] = {}       # sid -> when it stopped growing
        self._title: dict[str, str] = {}                # sid -> ai-title (cached)
        self._repo: dict[str, tuple[str, float]] = {}   # sid -> (repo, computed_at)

    # -- naming ----------------------------------------------------------
    def title_for(self, sid: str, path: Path, rows: list[dict]) -> str:
        """Prefer the LAST ai-title -- it is re-emitted as a session drifts."""
        for d in reversed(rows):
            if d.get("type") == "ai-title" and d.get("aiTitle"):
                self._title[sid] = d["aiTitle"]
                return d["aiTitle"]
        if sid in self._title:
            return self._title[sid]
        found = ""
        try:
            with path.open(errors="replace") as fh:
                for line in fh:
                    if '"ai-title"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    if d.get("aiTitle"):
                        found = d["aiTitle"]
            self._title[sid] = found
        except OSError:
            pass
        return found

    # -- attribution -----------------------------------------------------
    def repo_for(self, sid: str, path: Path, cwd: str) -> str:
        """The git root most often WRITTEN to -- not the launch cwd. A session
        launched in one repo routinely ends up writing to a sibling."""
        # a long session can migrate repos mid-flight, so this cannot be cached
        # forever -- but a full scan is expensive, so recompute on a slow clock
        hit = self._repo.get(sid)
        if hit and (time.time() - hit[1]) < REPO_RECHECK:
            return hit[0]
        counts: dict[str, int] = {}
        try:
            with path.open(errors="replace") as fh:
                for line in fh:
                    if '"file_path"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    if d.get("type") != "assistant":
                        continue
                    for b in d.get("message", {}).get("content") or []:
                        if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                            continue
                        if b.get("name") not in ("Edit", "Write", "NotebookEdit"):
                            continue
                        fp = (b.get("input") or {}).get("file_path")
                        if not fp:
                            continue
                        root = _git_root(Path(fp))
                        if root:
                            counts[root.name] = counts.get(root.name, 0) + 1
        except OSError:
            pass
        repo = max(counts, key=counts.get) if counts else Path(cwd).name
        self._repo[sid] = (repo, time.time())
        return repo

    # -- the state machine -----------------------------------------------
    def classify(self, sid: str, path: Path, rows: list[dict], now: float):
        """Returns (state, pending_tools, seconds_since_it_last_spoke).

        `rows` is the already-parsed tail, so a poll reads each transcript once.
        """
        try:
            st = path.stat()
        except OSError:
            return "gone", [], 0.0

        size, mtime = st.st_size, st.st_mtime
        prev = self._prev.get(sid)
        self._prev[sid] = (size, now)

        # grew since the last poll -> unambiguously working
        if prev is not None and size != prev[0]:
            self._frozen_since.pop(sid, None)
            return "working", [], max(0.0, now - mtime)

        # not growing. on first sight, mtime is an honest freeze start.
        still_for = now - self._frozen_since.setdefault(sid, mtime)

        # a call in flight looks identical to a permission prompt until the
        # transcript has been still a while. this window is the whole trick.
        if still_for < FROZEN_AFTER:
            return "working", [], still_for

        pending = _pending_tool_uses(rows)
        if pending:
            return "blocked", pending, still_for
        if still_for > RESTING_AFTER:
            return "resting", [], still_for
        return "yours", [], still_for

    # -- the whole picture -----------------------------------------------
    def snapshot(self) -> dict:
        now = time.time()
        alive = live_sessions()
        by_sid = {a["sessionId"]: a for a in alive if a.get("sessionId")}

        index: dict[str, Path] = {}
        for p in PROJECTS.glob("*/*.jsonl"):
            index[p.stem] = p

        sessions = []
        for sid, meta in by_sid.items():
            path = index.get(sid)
            if not path:
                continue
            rows = _tail_lines(path)  # parsed once, shared by every consumer below
            said_you, said_ai = _last_texts(rows)
            state, pending, quiet = self.classify(sid, path, rows, now)
            sessions.append({
                "id": sid[:8],
                "sessionId": sid,
                "pid": meta.get("pid"),
                "repo": self.repo_for(sid, path, meta.get("cwd", "")),
                "cwd": meta.get("cwd", ""),
                # a young session has no ai-title yet; your own words beat the
                # cwd name, which reads as a wrong repo next to `repo` above
                "title": (self.title_for(sid, path, rows)
                          or (" ".join(said_you.split())[:60] if said_you else "")
                          or f"untitled · {sid[:8]}"),
                "state": state,
                "pending": pending,
                "quiet_s": round(quiet, 1),
                "age_s": round(now - (meta.get("startedAt", now * 1000) / 1000), 1),
                "asked": _asked(rows) if state == "blocked" else "",
                "you": said_you[:400],
                "claude": said_ai[:600],
            })

        sessions.sort(key=lambda s: s["quiet_s"])
        blocked = [s for s in sessions if s["state"] == "blocked"]
        yours = [s for s in sessions if s["state"] == "yours"]

        # the reading hierarchy -- only `blocked` lights the lamp
        if blocked:
            lamp, headline = True, f"{blocked[0]['repo']} is waiting on you."
        elif yours:
            n = len(yours)
            lamp = False
            headline = "One answer is waiting." if n == 1 else f"{n} answers are waiting."
        else:
            lamp, headline = False, "Nothing needs you."

        return {
            "at": now,
            "lamp": lamp,
            "headline": headline,
            "focus": blocked[0] if blocked else (yours[0] if yours else None),
            "sessions": sessions,
            "repos": sorted({s["repo"] for s in sessions}),
        }
