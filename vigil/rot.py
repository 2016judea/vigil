"""The rot lens.

A stale skill is a known problem -- it goes on applying dead assumptions at full
confidence. The failure nobody watches is the other one: a skill that is
*silently gone* while still being reached for. Over 33 days of measured usage
that happened ~210 times, and nothing anywhere said so.

This lens reads the archive, counts what was invoked, and subtracts what is
still on disk.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .engine import workspace_roots

HOME = Path.home()
PLUGIN_GLOB = HOME / ".claude" / "plugins" / "cache"

# shipped with the CLI rather than present on disk -- counting these as missing
# would cry wolf on every run and train you to ignore the lens
BUILTIN = {
    "artifact-design", "artifact-diagramming", "artifact-capabilities", "dataviz",
    "claude-api", "update-config", "keybindings-help", "code-review", "simplify",
    "fewer-permission-prompts", "loop", "schedule", "run", "init", "security-review",
}


def skill_dirs() -> list[Path]:
    """Every place a skill can live: the global directory, plus the per-project
    `.claude/skills` of each repo. Resolved per call rather than frozen at
    import -- a project added after the daemon started would otherwise have all
    of its skills read as missing."""
    dirs = [HOME / ".claude" / "skills"]
    for root in workspace_roots():
        dirs += [p / ".claude" / "skills" for p in root.glob("*") if p.is_dir()]
    return dirs


def on_disk() -> set[str]:
    have: set[str] = set(BUILTIN)
    for d in skill_dirs():
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
