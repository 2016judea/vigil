# vigil

**An instrument for a fleet of Claude Code sessions. Its normal reading is *clear*.**

    python3 -m vigil            # daemon + the Face at http://127.0.0.1:7717
    python3 -m vigil status     # one-shot terminal reading
    python3 -m vigil watch      # live terminal reading
    python3 -m vigil rot        # skills reached for that no longer exist

Python 3 standard library only. Localhost only. Nothing leaves the machine.

## Why it exists

The fleet was already real and completely unmanaged. Across 33 days of actual
usage: **351 sessions, 10.6 a day, 5 repos, 48% of the time with two or more
live, peak five.** Not subagents — *terminal tabs*. Only 2 sessions ever ran
more than one subagent at once.

Claude Code ships **Agent View** (`claude agents`) and every third-party tool
re-implements it. They manage processes. None of them know anything about you.

See [SPEC.md](SPEC.md) for the full argument and the state machine.

## The one rule

> Design the resting state first, because it is the state.

Most of the time nothing needs you. That is the screen you look at ninety
percent of the time, so it gets the most care — not a grey empty state.

**Only `blocked` lights the lamp.** A session that finished its turn is not an
alarm; if it were, the resting state would never exist and this would be a list
again.

## What it reads

| Source | Gives |
|---|---|
| `claude agents --json` | liveness only — pid, cwd, sessionId |
| `~/.claude/projects/**.jsonl` | state, the question, names, attribution |

Two details that are easy to get wrong, and were:

- **A pending `tool_use` is ambiguous.** It means "blocked on a prompt" *or*
  "mid-call right now". Only a two-sample delta separates them. A live session
  was caught as a false positive while this was being written.
- **`cwd` lies.** Sessions launched in `bricks` routinely write to
  `writing-topology` or `literature-mutations`. Attribution keys on the git root
  actually *written to*.

## Tests

    python3 tests/test_engine.py

The two-sample delta gets the most coverage, because it is the whole trick.
