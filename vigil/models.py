"""The models lens -- "what have I pinned that has been superseded?"

`rot` watches one direction: you reach for a skill that is no longer there.
This is the mirror. A pinned model id does not rot loudly -- it keeps working,
at the old price, on the old capability, for as long as the vendor keeps the
endpoint alive. Nothing anywhere says a newer sibling shipped.

Two facts, joined:

  * what this machine pins  -- grepped out of tracked source, never guessed
  * what exists             -- openrouter.ai/api/v1/models, free and keyless

A row is earned the same way every VIGIL row is: a file on disk says you pin
`gemini-3.5-flash`, and the catalog says `gemini-3.7-flash` shipped later. No
recommendation is inferred beyond that. Whether the newer one is *better* is
not a thing either source knows, so this lens does not claim it -- it reports
that a successor exists, when, and what it costs.

EGRESS: this is the one part of VIGIL that talks to the network, and it does so
only when invoked from the CLI. The daemon never calls it, so the "no egress"
property of the running process is unchanged.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .engine import workspace_roots

CATALOG = "https://openrouter.ai/api/v1/models"
CACHE = Path.home() / "Library" / "Caches" / "vigil" / "openrouter.json"
MAX_AGE = 6 * 3600

# Only ids shaped like a real versioned model. A bare vendor word matches far
# too much English prose -- "claude-archive", "gpt-ads" and "gemini-app" all
# turned up in a first pass over the same corpus, and a lens that cries wolf
# gets ignored.
PIN = re.compile(
    r"\b((?:claude-(?:opus|sonnet|haiku|fable)|gemini|gpt)-\d[a-zA-Z0-9._-]*)"
)

# extensions worth grepping; everything else is data, prose or binary
SUFFIX = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".sh", ".yml", ".yaml", ".toml", ".env", ".md"}

DATESTAMP = re.compile(r"^\d{8}$")
VERSION = re.compile(r"^\d+(?:\.\d+)*$")
DROP = {"preview", "exp", "latest", "experimental"}


def parse(model_id: str) -> tuple[str, tuple[int, ...]] | None:
    """`anthropic/claude-sonnet-4.6` -> ("claude-sonnet|", (4, 6)).

    The family is everything that is not the version -- the words before it and
    any variant words after it -- so `gemini-3.7-flash` and `gemini-3.5-flash`
    share a family while `gemini-3.5-flash-lite` gets its own. Version digits
    may be dotted (`4.8`, the catalog) or dashed (`4-6`, how this machine
    writes them), which is why trailing digit tokens are absorbed.
    """
    name = model_id.split("/")[-1]
    tokens = [t for t in name.split("-") if t]
    tokens = [t for t in tokens if not DATESTAMP.match(t) and t.lower() not in DROP]

    at = next((i for i, t in enumerate(tokens) if VERSION.match(t)), None)
    if at is None:
        return None

    ver: list[int] = []
    for part in tokens[at].split("."):
        ver.append(int(part))
    end = at + 1
    while end < len(tokens) and tokens[end].isdigit():
        ver.append(int(tokens[end]))
        end += 1

    return "-".join(tokens[:at]) + "|" + "-".join(tokens[end:]), tuple(ver)


def catalog(refresh: bool = False) -> dict:
    """The catalog, cached. Cheap on the wire but not free on latency, and the
    cache is also what makes "new since I last looked" answerable at all."""
    if not refresh and CACHE.is_file():
        try:
            held = json.loads(CACHE.read_text())
            if time.time() - held.get("fetched_at", 0) < MAX_AGE:
                return held
        except (ValueError, OSError):
            pass
    try:
        req = urllib.request.Request(CATALOG, headers={"User-Agent": "vigil/1"})
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read())["data"]
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        if CACHE.is_file():                    # stale beats nothing, but say so
            held = json.loads(CACHE.read_text())
            held["stale"] = str(e)
            return held
        return {"fetched_at": 0, "models": [], "error": str(e)}

    fresh = {
        "fetched_at": time.time(),
        "models": [
            {
                "id": m["id"],
                "created": m.get("created", 0),
                "prompt": m.get("pricing", {}).get("prompt"),
                "context": m.get("context_length"),
            }
            for m in data
            if ":" not in m["id"]              # :batch / :free are billing modes
        ],
    }
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(fresh))
    except OSError:
        pass
    return fresh


def pins() -> dict[str, list[str]]:
    """Every versioned model id this machine hard-codes, and where.

    Tracked files only, via `git ls-files` -- it is fast, it honours the
    ignores, and it keeps the walk out of `data/cache`, which on this machine
    is gigabytes of substrate that could never contain a model id anyway.
    """
    found: dict[str, set[str]] = {}
    seen_repos: set[Path] = set()

    roots = list(workspace_roots()) + [Path.home() / ".claude"]
    for root in roots:
        if not root.is_dir():
            continue
        repos = [root] if (root / ".git").is_dir() else [p for p in root.glob("*") if p.is_dir()]
        for repo in repos:
            repo = repo.resolve()
            if repo in seen_repos:
                continue
            seen_repos.add(repo)
            if (repo / ".git").is_dir():
                try:
                    out = subprocess.run(
                        ["git", "-C", str(repo), "ls-files", "-z"],
                        capture_output=True, timeout=20,
                    ).stdout.decode(errors="replace")
                    files = [repo / f for f in out.split("\0") if f]
                except (OSError, subprocess.SubprocessError):
                    continue
            elif repo == (Path.home() / ".claude").resolve():
                files = [p for p in repo.glob("*/**/*") if p.is_file()]
            else:
                continue

            for f in files:
                if f.suffix not in SUFFIX:
                    continue
                try:
                    if f.stat().st_size > 2_000_000:
                        continue
                    text = f.read_text(errors="replace")
                except OSError:
                    continue
                for hit in PIN.findall(text):
                    found.setdefault(hit, set()).add(str(f).replace(str(Path.home()), "~"))

    return {k: sorted(v) for k, v in sorted(found.items())}


def report(refresh: bool = False) -> dict:
    cat = catalog(refresh)
    live = cat.get("models", [])

    families: dict[str, list[dict]] = {}
    for m in live:
        p = parse(m["id"])
        if not p:
            continue
        fam, ver = p
        families.setdefault(fam, []).append({**m, "ver": ver})

    mine = pins()
    superseded = []
    for pin, where in mine.items():
        p = parse(pin)
        if not p:
            continue
        fam, ver = p
        newer = [c for c in families.get(fam, []) if c["ver"] > ver]
        if not newer:
            continue
        best = max(newer, key=lambda c: (c["ver"], c["created"]))
        code = [f for f in where if not f.endswith(".md")]
        superseded.append({
            "pin": pin,
            "newest": best["id"],
            "shipped": time.strftime("%Y-%m-%d", time.localtime(best["created"])),
            "price": best["prompt"],
            "context": best["context"],
            "behind": len({tuple(c["ver"]) for c in newer}),
            "refs": len(where),
            "code_refs": len(code),
            "files": where,
        })
    superseded.sort(key=lambda s: (-s["code_refs"], -s["refs"], s["pin"]))

    return {
        "fetched": time.strftime("%Y-%m-%d %H:%M", time.localtime(cat.get("fetched_at", 0))),
        "catalog": len(live),
        "pins": len(mine),
        "superseded": superseded,
        "stale": cat.get("stale"),
        "error": cat.get("error"),
    }


if __name__ == "__main__":
    print(json.dumps(report(), indent=2))
