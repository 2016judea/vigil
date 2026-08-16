"""python3 -m vigil            -> run the daemon (serves the Face)
python3 -m vigil status        -> one-shot terminal reading
python3 -m vigil watch         -> live terminal reading
python3 -m vigil rot           -> skills reached for that no longer exist
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

from .engine import Engine
from .server import HOST, PORT, serve

DIM, BOLD, AMBER, RESET = "\033[2m", "\033[1m", "\033[38;5;214m", "\033[0m"


def human(s: float) -> str:
    if s < 60:
        return f"{s:.0f}s"
    if s < 3600:
        return f"{s/60:.0f}m"
    if s < 86400:
        return f"{s/3600:.1f}h".replace(".0h", "h")
    return f"{s/86400:.0f}d"


def _fetch() -> dict | None:
    """Prefer the running daemon; fall back to a direct read so `status` works
    even when nothing is serving."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/state", timeout=3) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def render(st: dict) -> str:
    lines: list[str] = []
    lamp = f"{AMBER}◉ NEEDS YOU{RESET}" if st["lamp"] else f"{DIM}○ clear{RESET}"
    lines.append("")
    lines.append(f"  {lamp}")
    lines.append("")
    lines.append(f"  {BOLD}{st['headline']}{RESET}")

    f = st.get("focus")
    if st["lamp"] and f:
        # the question, not the run-up to it -- same rule as the Face
        ask = f.get("asked") or f.get("claude") or ""
        if ask:
            q = " ".join(ask.split())[:150]
            lines.append(f"  {DIM}│{RESET} {q}")
        pend = ", ".join(f.get("pending") or [])
        lines.append(f"  {DIM}{f['repo']} · {f['title']} — waiting {human(f['quiet_s'])}"
                     + (f" on {pend}" if pend else "") + RESET)
    lines.append("")

    for s in st["sessions"]:
        dot = {"blocked": f"{AMBER}◉{RESET}", "working": "●"}.get(s["state"], f"{DIM}○{RESET}")
        title = (s["title"] or "")[:44]
        repo = s["repo"][:18]          # long repo names must not shift the columns
        lines.append(f"  {dot} {repo:<18} {title:<46} {DIM}{human(s['quiet_s']):>5}  {s['state']}{RESET}")
    if not st["sessions"]:
        lines.append(f"  {DIM}Nothing is running.{RESET}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"

    if cmd == "serve":
        return serve()

    if cmd == "rot":
        from .rot import report
        r = report()
        print()
        print(f"  {BOLD}{r['lost_calls']} calls went to skills that no longer exist.{RESET}")
        print(f"  {DIM}{r['invocations']} skill calls across {r['distinct']} names; "
              f"{r['on_disk']} skills on disk.{RESET}")
        print()
        for m in r["missing"][:20]:
            print(f"  {AMBER}gone{RESET}  {m['skill']:<34} {DIM}{m['calls']:>4} calls{RESET}")
        if not r["missing"]:
            print(f"  {DIM}Nothing reached for is missing.{RESET}")
        print()
        return

    if cmd in ("status", "watch"):
        st = _fetch()
        if st is None:
            # no daemon: read the fleet directly, but say the vigil is not kept
            eng = Engine()
            eng.snapshot()          # prime the delta
            time.sleep(1.0)
            st = eng.snapshot()
            print(f"{DIM}  (daemon not running — one-shot read){RESET}")
        if cmd == "status":
            print(render(st))
            return
        try:
            while True:
                st = _fetch()
                if st is None:
                    print(f"\033[2J\033[H{DIM}  vigil daemon is not running.{RESET}")
                else:
                    print(f"\033[2J\033[H{render(st)}")
                time.sleep(3)
        except KeyboardInterrupt:
            print()
        return

    print(__doc__)


if __name__ == "__main__":
    main()
