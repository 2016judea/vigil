"""Models-lens tests. `parse` is the load-bearing piece: a family it splits
wrongly either misses a real successor or invents one, and both failures look
authoritative on the terminal. Everything else in the lens is plumbing.

No network here -- the catalog is passed in. Plain `test_*` functions: pytest
collects them, and `python3 tests/test_models.py` runs them without pytest.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vigil.models import PIN, parse


def test_dotted_and_dashed_versions_agree():
    # the catalog writes versions dotted; this machine writes them dashed. If
    # these two do not land in the same family, every anthropic pin reads current.
    assert parse("anthropic/claude-sonnet-4.6") == parse("claude-sonnet-4-6")


def test_flash_lite_is_its_own_family():
    # a variant word after the version is part of the family, not the version --
    # otherwise flash-lite is offered flash's successor and the price is wrong
    assert parse("google/gemini-3.5-flash-lite") == ("gemini|flash-lite", (3, 5))
    assert parse("google/gemini-3.7-flash") == ("gemini|flash", (3, 7))


def test_release_datestamp_is_not_a_version():
    # absorbing it would make claude-haiku-4-5-20251001 sort above every real haiku
    assert parse("claude-haiku-4-5-20251001") == ("claude-haiku|", (4, 5))


def test_preview_matches_its_ga_twin():
    assert parse("gemini-3-pro-image-preview") == parse("google/gemini-3-pro-image")


def test_variant_suffix_survives():
    assert parse("anthropic/claude-opus-4.8-fast") == ("claude-opus|fast", (4, 8))


def test_single_component_version_parses():
    assert parse("claude-opus-5") == ("claude-opus|", (5,))


def test_ordering():
    assert parse("claude-sonnet-5")[1] > parse("claude-sonnet-4-6")[1]
    assert parse("gemini-3.7-flash")[1] > parse("gemini-3.5-flash")[1]


def test_unversioned_id_yields_nothing():
    assert parse("anthropic/claude-code") is None


def test_pin_regex_stops_before_prose_punctuation():
    # "we pin claude-opus-5." counted "claude-opus-5." as a second, unparseable pin
    assert PIN.findall("we pin claude-opus-5. Also claude-sonnet-4-5, and gemini-3.5-flash-lite.") == \
        ["claude-opus-5", "claude-sonnet-4-5", "gemini-3.5-flash-lite"]
    assert PIN.findall('"model": "claude-haiku-4-5-20251001"') == ["claude-haiku-4-5-20251001"]


def main() -> int:
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("  PASS  " + name)
            except Exception as exc:
                fails += 1
                print(f"  FAIL  {name}   {type(exc).__name__}: {exc}")
    print(f"\n  {len([n for n in globals() if n.startswith('test_')]) - fails} passed, {fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
