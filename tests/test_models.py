"""Models-lens tests. `parse` is the load-bearing piece: a family it splits
wrongly either misses a real successor or invents one, and both failures look
authoritative on the terminal. Everything else in the lens is plumbing.

No network here -- the catalog is passed in.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vigil.models import parse


def check(name, got, want):
    ok = got == want
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   got={got!r} want={want!r}" if not ok else ""))
    return ok


def main() -> int:
    r = []

    # the catalog writes versions dotted; this machine writes them dashed. If
    # these two do not land in the same family, every anthropic pin reads current.
    r.append(check("dotted and dashed versions agree",
                   parse("anthropic/claude-sonnet-4.6"), parse("claude-sonnet-4-6")))

    # a variant word after the version is part of the family, not the version --
    # otherwise flash-lite is offered flash's successor and the price is wrong
    r.append(check("flash-lite is its own family",
                   parse("google/gemini-3.5-flash-lite"), ("gemini|flash-lite", (3, 5))))
    r.append(check("flash keeps its own family",
                   parse("google/gemini-3.7-flash"), ("gemini|flash", (3, 7))))

    # a release datestamp is not a version component; absorbing it would make
    # claude-haiku-4-5-20251001 sort above every real haiku
    r.append(check("release datestamp is not a version",
                   parse("claude-haiku-4-5-20251001"), ("claude-haiku|", (4, 5))))

    # preview and GA are the same model at the same version, so no supersede fires
    r.append(check("preview matches its GA twin",
                   parse("gemini-3-pro-image-preview"), parse("google/gemini-3-pro-image")))

    r.append(check("a variant suffix survives", parse("anthropic/claude-opus-4.8-fast"),
                   ("claude-opus|fast", (4, 8))))
    r.append(check("a single-component version parses",
                   parse("claude-opus-5"), ("claude-opus|", (5,))))

    # ordering is what the whole lens rests on
    r.append(check("5 is newer than 4.6",
                   parse("claude-sonnet-5")[1] > parse("claude-sonnet-4-6")[1], True))
    r.append(check("3.7 is newer than 3.5",
                   parse("gemini-3.7-flash")[1] > parse("gemini-3.5-flash")[1], True))
    r.append(check("an unversioned id yields nothing", parse("anthropic/claude-code"), None))

    print()
    print(f"  {sum(r)}/{len(r)} passed")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())
