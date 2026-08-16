"""Engine tests. The two-sample delta is the whole trick, so it gets the most
coverage: a pending tool_use means BLOCKED only once the transcript is frozen.
"""
import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vigil.engine import Engine, _pending_tool_uses, _last_texts, FROZEN_AFTER

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

def check(name, got, want):
    ok = got == want
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   got={got!r} want={want!r}" if not ok else ""))
    return ok

def main():
    import tempfile
    d = Path(tempfile.mkdtemp())
    results = []

    results.append(check("pending tool_use detected",
                         _pending_tool_uses(rows_with_pending_edit()), ["Edit"]))
    results.append(check("answered tool_use is not pending",
                         _pending_tool_uses(rows_answered()), []))

    you, ai = _last_texts([
        {"type": "user", "message": {"content": "ship it"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},
    ])
    results.append(check("last user text", you, "ship it"))
    results.append(check("last assistant text", ai, "done"))

    you2, _ = _last_texts([{"type": "user", "isMeta": True, "message": {"content": "hook noise"}}])
    results.append(check("isMeta user rows ignored", you2, ""))

    # --- the delta, which is the actual thing worth testing ---
    e = Engine()
    f = write(d / "s1.jsonl", rows_with_pending_edit())
    rows = rows_with_pending_edit()

    state, _, _ = e.classify("s1", f, rows, time.time())
    results.append(check("fresh pending call reads as working, NOT blocked", state, "working"))

    # transcript grew -> unambiguously working, even with a pending call
    write(f, rows_with_pending_edit() + [{"type": "assistant", "message": {"content": []}}])
    state, _, _ = e.classify("s1", f, rows, time.time())
    results.append(check("growing transcript is working", state, "working"))

    # frozen past the window with a pending call -> blocked
    e2 = Engine()
    f2 = write(d / "s2.jsonl", rows_with_pending_edit())
    now = time.time()
    e2.classify("s2", f2, rows, now)
    e2._frozen_since["s2"] = now - (FROZEN_AFTER + 5)
    state, pend, _ = e2.classify("s2", f2, rows, now + 1)
    results.append(check("frozen + pending reads as blocked", state, "blocked"))
    results.append(check("blocked reports which tool", pend, ["Edit"]))

    # frozen with nothing pending -> his turn, and the lamp must stay dark
    e3 = Engine()
    f3 = write(d / "s3.jsonl", rows_answered())
    now = time.time()
    e3.classify("s3", f3, rows_answered(), now)
    e3._frozen_since["s3"] = now - (FROZEN_AFTER + 5)
    state, _, _ = e3.classify("s3", f3, rows_answered(), now + 1)
    results.append(check("frozen + nothing pending is 'yours', not an alarm", state, "yours"))

    print()
    print(f"  {sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1

if __name__ == "__main__":
    raise SystemExit(main())
