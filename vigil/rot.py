"""The rot lens.

Tenet 9 says a stale skill is worse than a missing one. There is a second
failure it does not name and nobody watches: a skill that is *silently gone*
while still being reached for. Over 33 days that happened ~210 times.

This lens reads the archive, counts what was invoked, and subtracts what is
still on disk.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

HOME = Path.home()

# every place a skill can live
SKILL_DIRS = [
    HOME / ".claude" / "skills",
    *[p / ".claude" / "skills" for p in (HOME / "Desktop").glob("*") if p.is_dir()],
]
PLUGIN_GLOB = HOME / ".claude" / "plugins" / "cache"

# shipped with the CLI rather than present on disk -- counting these as missing
# would cry wolf on every run and train him to ignore the lens
BUILTIN = {
    "artifact-design", "artifact-diagramming", "artifact-capabilities", "dataviz",
    "claude-api", "update-config", "keybindings-help", "code-review", "simplify",
    "fewer-permission-prompts", "loop", "schedule", "run", "init", "security-review",
}


def on_disk() -> set[str]:
    have: set[str] = set(BUILTIN)
    for d in SKILL_DIRS:
        if d.is_dir():
            have |= {p.name for p in d.iterdir() if p.is_dir()}
    if PLUGIN_GLOB.is_dir():
        for p in PLUGIN_GLOB.glob("**/skills/*"):
            if p.is_dir():
                have.add(p.name)
    return have


def invoked(roots: list[Path]) -> Counter:
    """Count Skill tool_use calls across every transcript we still hold."""
    counts: Counter = Counter()
    seen_files = set()
    for root in roots:
        if not root.is_dir():
            continue
        for f in root.glob("**/*.jsonl"):
            key = f.name
            if key in seen_files:      # archive mirrors live; do not double count
                continue
            seen_files.add(key)
            try:
                with f.open(errors="replace") as fh:
                    for line in fh:
                        if '"Skill"' not in line:
                            continue
                        try:
                            d = json.loads(line)
                        except Exception:
                            continue
                        if d.get("type") != "assistant":
                            continue
                        for b in d.get("message", {}).get("content") or []:
                            if (isinstance(b, dict) and b.get("type") == "tool_use"
                                    and b.get("name") == "Skill"):
                                name = (b.get("input") or {}).get("skill")
                                if name:
                                    counts[name] += 1
            except OSError:
                continue
    return counts


def report() -> dict:
    have = on_disk()
    used = invoked([HOME / ".claude-archive" / "transcripts", HOME / ".claude" / "projects"])
    missing = []
    for name, n in used.most_common():
        base = name.split(":")[-1]
        if base in have or name in have:
            continue
        if name.startswith("superpowers:"):   # plugin-provided, resolved at runtime
            continue
        missing.append({"skill": name, "calls": n})
    return {
        "invocations": sum(used.values()),
        "distinct": len(used),
        "on_disk": len(have),
        "missing": missing,
        "lost_calls": sum(m["calls"] for m in missing),
    }


if __name__ == "__main__":
    print(json.dumps(report(), indent=2))
