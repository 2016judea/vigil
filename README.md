# vigil

**An instrument for a fleet of Claude Code sessions. Its normal reading is *clear*.**

## Install

    ./mac/install.sh          # app + LaunchAgent + `vigil` on PATH
    ./mac/install.sh --uninstall

That gives you three surfaces over one daemon:

| | |
|---|---|
| **Menu bar** | `/Applications/Vigil.app` — a hollow dot at rest, a filled amber dot when a session is blocked. Click for the reading. |
| **The Face** | <http://127.0.0.1:7717> — the full instrument, phone-readable |
| **Terminal** | `vigil status` · `vigil watch` · `vigil where` · `vigil rot` |

The daemon runs under launchd: one instance, restarted if it dies, started at
login. Python 3 standard library only. Localhost only. Nothing leaves the machine.

### Where it looks for your repos

The continuity and rot lenses need to know where checkouts live. By default they
look one level below `$HOME` in `Desktop`, `code`, `src`, `dev`, `repos`,
`projects` and `work` — whichever exist. Override it at install time:

    VIGIL_ROOTS=~/code:~/work/clients ./mac/install.sh

It has to reach **the daemon**, which is what reads the repos — so `install.sh`
bakes it into the LaunchAgent. Exporting it in your own shell does nothing once
the daemon is up, because `vigil where` just asks the daemon.

Continuity also picks up any repo your transcripts show you actually writing to,
whether or not it sits under a root.

If you keep repos in `~/Documents` or `~/Downloads`, name them in `VIGIL_ROOTS`
and grant the app Full Disk Access — those two are TCC-protected, and an
ungranted launchd agent **hangs** on them rather than failing (see the traps
below). The daemon runs as a LaunchAgent, so this is not hypothetical.

### App identity

The app and its LaunchAgent are identified by `local.vigil`, which deliberately
claims no domain. macOS files privacy grants, launchd jobs and Launch Services
registration under that string, so if you sign or distribute the app, use one you
own:

    VIGIL_BUNDLE_ID=dev.example.vigil ./mac/install.sh

Renaming is safe to do later. `install.sh` boots out and deletes **any**
LaunchAgent that runs this daemon, whatever it was previously labelled, before
installing the new one — otherwise two pollers would race for port 7717. The
grant that lets the daemon read your repos is attached to the Python binary, not
to the bundle id, so it survives a rename.

### What the port serves

`http://127.0.0.1:7717` binds to loopback and requires no auth, which is the
right trade for a personal instrument but worth stating plainly: `/api/state`
returns **the last thing you typed** (400 chars) and the last thing Claude said
(600 chars) per live session, and `/api/continuity` returns your branch names and
uncommitted filenames. Anything that can reach your loopback interface can read
that. There is no egress, no telemetry, and nothing is written outside
`~/Library/Logs` and `/tmp`.

## The three lenses

One substrate, three questions:

- **Who needs me** — the fleet. Only a session that literally cannot proceed
  lights the lamp.
- **Where was I** — `vigil where`, or "Where was I" on the Face. Per repo:
  uncommitted files, commits not pushed, and the last thing each of you said.
  **Every row is earned by a verifiable fact — git or a transcript, never a
  guess.** Nothing is summarised or inferred, so there is no hallucination
  surface. A continuity view you cannot trust is worse than none, because you
  would act on it.
- **What is rotting** — `vigil rot`. Skills still being reached for that no
  longer exist on disk.

## Logs

    tail -f ~/Library/Logs/Vigil.log     # the menu bar app
    tail -f /tmp/vigil-daemon.log        # the daemon (launchd writes here)

The app logs launches, reopens, daemon reachability and every lamp transition --
not every poll, so the file stays readable.

## The macOS traps this hit, so you do not have to

- **A TCC-protected directory does not fail, it stalls.** Globbing `~/Documents`
  from the launchd agent left `/api/continuity` unanswered past 25 seconds — no
  error, no exception, just a lens that never returned. The access was waiting on
  an authorization decision a launchd agent cannot ask a human for; the grant
  turned up in the TCC database *during* the hang. `try`/`except` cannot catch a
  block. This is why `Documents` and `Downloads` are not in the default roots
  above — reaching into a protected directory has to be opt-in.
- **`~/Desktop` is TCC-protected.** Terminal has been granted access, so
  `python3 -m vigil` works by hand — but a launchd agent has no grant and no way
  to prompt, so the interpreter **blocks forever in startup**, before it can even
  load `encodings`. The symptom is a process that is alive, silent, and not
  listening. `install.sh` therefore stages the Python package into
  `~/Library/Application Support/Vigil` and points the LaunchAgent's
  `WorkingDirectory` and `PYTHONPATH` there — outside every protected directory,
  and outside the signed bundle (see the last trap).
- **`HTTPServer.server_bind()` calls `socket.getfqdn()`** — a reverse-DNS lookup
  that is instant in a shell and can stall under launchd. `_Server` overrides it.
- **`contentTintColor` does nothing on a menu bar button.** macOS forces template
  images monochrome, so the amber alarm is drawn as real pixels.
- **Nothing may be written inside a signed `.app`.** Python dropped
  `__pycache__/*.pyc` into the bundle on first run, broke the seal
  (`a sealed resource is missing or invalid`) and the app stopped launching from
  Finder. The bundle is now immutable; the package lives in Application Support.
- **A menu bar app gives no feedback when launched**, and none at all when
  launched while already running. Vigil opens its own menu on launch and on
  reopen, so the click visibly does something.

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
- **`cwd` lies.** A session launched in one repo routinely ends up writing to a
  sibling. Attribution keys on the git root actually *written to*.

## Tests

    python3 tests/test_engine.py

The two-sample delta gets the most coverage, because it is the whole trick.
