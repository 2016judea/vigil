"""Engine tests. The two-sample delta is the whole trick, so it gets the most
coverage: a pending tool_use means BLOCKED only once the transcript is frozen.

Plain `test_*` functions: pytest collects them, and `python3 tests/test_engine.py`
runs them without pytest (the CI job has only the standard library).
"""
import json, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vigil.engine import Engine, _pending_tool_uses, _last_texts, FROZEN_AFTER, RESTING_AFTER


def rows_with_pending_edit():
    return [
        {"type": "user", "message": {"content": "make the change"}},
        {"type": "assistant", "message": {"stop_reason": "tool_use", "content": [
            {"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/x/y.py"}}]}},
    ]


def rows_answered():
    r = rows_with_pending_edit()
    r.append({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1"}]}})
    return r


def write(tmp, rows):
    tmp.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return tmp


def _tmp(name, rows):
    return write(Path(tempfile.mkdtemp()) / name, rows)


def _frozen(rows, name="s", busy=False):
    """An engine that has watched this transcript sit still past FROZEN_AFTER."""
    e = Engine()
    f = _tmp(name + ".jsonl", rows)
    now = time.time()
    e.classify(name, f, rows, now, busy=busy)
    e._frozen_since[name] = now - (FROZEN_AFTER + 5)
    return e, f, now + 1


def test_pending_tool_use_detected():
    assert _pending_tool_uses(rows_with_pending_edit()) == ["Edit"]


def test_answered_tool_use_is_not_pending():
    assert _pending_tool_uses(rows_answered()) == []


def test_last_texts():
    you, ai = _last_texts([
        {"type": "user", "message": {"content": "ship it"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},
    ])
    assert (you, ai) == ("ship it", "done")


def test_is_meta_user_rows_ignored():
    you, _ = _last_texts([{"type": "user", "isMeta": True, "message": {"content": "hook noise"}}])
    assert you == ""


def test_fresh_pending_call_reads_as_working_not_blocked():
    e = Engine()
    rows = rows_with_pending_edit()
    f = _tmp("s1.jsonl", rows)
    state, _, _ = e.classify("s1", f, rows, time.time())
    assert state == "working"


def test_growing_transcript_is_working():
    e = Engine()
    rows = rows_with_pending_edit()
    f = _tmp("s1.jsonl", rows)
    e.classify("s1", f, rows, time.time())
    write(f, rows + [{"type": "assistant", "message": {"content": []}}])
    state, _, _ = e.classify("s1", f, rows, time.time())
    assert state == "working"


def test_frozen_plus_pending_reads_as_blocked_and_names_the_tool():
    e, f, later = _frozen(rows_with_pending_edit(), "s2")
    state, pend, _ = e.classify("s2", f, rows_with_pending_edit(), later)
    assert (state, pend) == ("blocked", ["Edit"])


def test_frozen_with_nothing_pending_is_yours_not_an_alarm():
    e, f, later = _frozen(rows_answered(), "s3")
    state, _, _ = e.classify("s3", f, rows_answered(), later)
    assert state == "yours"


def test_a_busy_session_with_nothing_pending_is_working_not_yours():
    # a parent session running a subagent writes nothing to its own transcript for
    # minutes; the CLI reports it busy, and the Face must not count it as an answer waiting
    e, f, later = _frozen(rows_answered(), "s4", busy=True)
    state, _, _ = e.classify("s4", f, rows_answered(), later, busy=True)
    assert state == "working"


def test_a_busy_session_with_a_pending_call_still_blocks():
    # busy is not a free pass: a permission prompt is a pending call on a still file
    e, f, later = _frozen(rows_with_pending_edit(), "s5", busy=True)
    state, pend, _ = e.classify("s5", f, rows_with_pending_edit(), later, busy=True)
    assert (state, pend) == ("blocked", ["Edit"])


def test_long_silent_idle_session_is_resting():
    e, f, later = _frozen(rows_answered(), "s6")
    e._frozen_since["s6"] = later - (RESTING_AFTER + 5)
    state, _, _ = e.classify("s6", f, rows_answered(), later)
    assert state == "resting"


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
