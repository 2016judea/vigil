"""The continuity lens -- "where was I?"

Answers the 22 times in 33 days of measured usage that some version of *where
were we* was typed at the start of a session.

The design constraint is the one that kills this kind of feature: a log becomes
a list. So a row has to be *earned* by a verifiable fact, never by a guess:

  * uncommitted files            -- git says so
  * commits not yet pushed       -- git says so
  * the last thing each of you said -- the transcript says so, verbatim

Nothing here infers intent or summarises. There is no hallucination surface,
because nothing is being generated. That is deliberate: a continuity view you
cannot trust is worse than none, because you would act on it.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from .engine import PROJECTS, _git_root, _last_texts, _tail_lines, workspace_roots

# how far back a repo stays interesting without a commit or a live session
WINDOW_DAYS = 10
# transcripts older than this are not read at all -- bounds the whole scan
SCAN_DAYS = 14


def _git(repo: Path, *args: str) -> str:
    """Trailing newlines only. A full .strip() eats the leading space of the
    first `status --porcelain` line (" M path"), which silently shifts the
    filename slice by one character -- on the first file only."""
    try:
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, timeout=10).stdout.rstrip("\n")
    except Exception:
        return ""


def _repo_state(repo: Path) -> dict:
    dirty = [l for l in _git(repo, "status", "--porcelain").splitlines() if l.strip()]
    ahead = _git(repo, "rev-list", "--count", "@{u}..HEAD").strip()
    log = _git(repo, "log", "-5", "--format=%ct\t%cr\t%s")
    commits = []
    for line in log.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            commits.append({"at": int(parts[0]), "ago": parts[1], "subject": parts[2][:110]})
    return {
        "branch": _git(repo, "branch", "--show-current").strip(),
        "dirty": len(dirty),
        # the actual filenames matter -- "19 dirty" tells you nothing about what
        "dirty_files": [l[3:] for l in dirty[:6]],
        "unpushed": int(ahead) if ahead.isdigit() else 0,
        "commits": commits,
        "last_commit_at": commits[0]["at"] if commits else 0,
    }


def _recent_transcripts(days: int) -> list[Path]:
    cutoff = time.time() - days * 86400
    out = []
    for p in PROJECTS.glob("*/*.jsonl"):
        try:
            if p.stat().st_mtime >= cutoff:
                out.append(p)
        except OSError:
            continue
    return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)


def _attribute(rows: list[dict]) -> str | None:
    """Which repo this transcript was actually writing to. Same rule as the
    engine: the git root written to, never the launch cwd."""
    counts: dict[str, int] = {}
    for d in rows:
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
                counts[str(root)] = counts.get(str(root), 0) + 1
    return max(counts, key=counts.get) if counts else None


def report(live_repos: set[str] | None = None) -> dict:
    live_repos = live_repos or set()
    now = time.time()

    # last exchange per repo, from the most recent transcript that touched it
    seen: dict[str, dict] = {}
    for path in _recent_transcripts(SCAN_DAYS):
        rows = _tail_lines(path)          # tail only -- bounds a 1GB corpus
        if not rows:
            continue
        repo = _attribute(rows)
        if not repo or repo in seen:
            continue                       # first hit wins; files are newest-first
        you, claude = _last_texts(rows)
        title = ""
        for d in reversed(rows):
            if d.get("type") == "ai-title" and d.get("aiTitle"):
                title = d["aiTitle"]
                break
        seen[repo] = {
            "at": path.stat().st_mtime,
            "title": title,
            "you": " ".join(you.split())[:280],
            "claude": " ".join(claude.split())[:320],
        }

    # every repo worth a row: recently spoken to, or holding uncommitted work.
    # `seen` is already absolute git roots earned from transcripts, so a repo
    # living outside every root still gets a row if it was actually worked in.
    candidates = set(seen)
    for root in workspace_roots():
        for p in root.glob("*"):
            if (p / ".git").is_dir():
                candidates.add(str(p))

    repos = []
    for r in candidates:
        repo = Path(r)
        if not (repo / ".git").exists():
            continue
        g = _repo_state(repo)
        last = seen.get(r, {})
        touched = max(last.get("at", 0), g["last_commit_at"])
        stale = (now - touched) > WINDOW_DAYS * 86400

        # the rule that stops this becoming a list of every repo you own
        earns_a_row = bool(g["dirty"] or g["unpushed"] or repo.name in live_repos or not stale)
        if not earns_a_row:
            continue

        loops = []
        if g["dirty"]:
            loops.append(f"{g['dirty']} uncommitted file{'s' if g['dirty'] != 1 else ''}")
        if g["unpushed"]:
            loops.append(f"{g['unpushed']} commit{'s' if g['unpushed'] != 1 else ''} not pushed")

        repos.append({
            "repo": repo.name,
            "path": str(repo),
            "branch": g["branch"],
            "live": repo.name in live_repos,
            "touched": touched,
            "quiet_s": round(now - touched, 1) if touched else None,
            "open_loops": loops,
            "dirty_files": g["dirty_files"],
            "commits": g["commits"][:3],
            "title": last.get("title", ""),
            "you": last.get("you", ""),
            "claude": last.get("claude", ""),
        })

    repos.sort(key=lambda r: r["touched"], reverse=True)

    loose = [r for r in repos if r["open_loops"]]
    if not repos:
        headline = "Nothing recent to pick up."
    elif loose:
        n = sum(len(r["open_loops"]) for r in loose)
        where = loose[0]["repo"]
        headline = (f"{n} loose end{'s' if n != 1 else ''}, "
                    f"{'mostly ' if len(loose) > 1 else ''}in {where}.")
    else:
        headline = f"Everything is committed. Last worked in {repos[0]['repo']}."

    return {"at": now, "headline": headline, "repos": repos}


if __name__ == "__main__":
    print(json.dumps(report(), indent=2))
