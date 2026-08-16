# VIGIL — the instrument

**A vigil is defined by nothing happening.** That is the product.

grounded: 2026-08-16 — built from 351 real sessions / 33 days of Aidan's own
Claude Code exhaust, mined in the session that wrote this spec.

---

## The thesis

Brick & Mortar turns a city's public exhaust into a spatial model an AI reasons
over. VIGIL is the same move pointed inward: **it turns Aidan's own Claude
exhaust into a model of how he works**, and puts one instrument on top of it.

The fleet already exists. It is not made of subagents — it is made of terminal
tabs. Measured over 33 days:

| | |
|---|---|
| Real sessions | **351** (10.6/day, 5 repos) |
| Time with ≥2 sessions live | **48%** |
| Time with ≥2 *different repos* live | **34%**, peak 5 |
| Median session | 16 min, 3 typed turns, 43 tool calls |
| Sessions >6h / >24h | 42 / 11 |
| Sessions that used a subagent | 47 of 351 |
| Sessions running >1 subagent at once | **2. Ever.** |
| Skill calls to skills that no longer exist | **~210** |
| Hooks configured | **0** |

He is a dispatcher — 14 tool calls per instruction typed — running a real fleet
on human attention alone.

## What it is not

Not a kanban. Not a session list. Claude Code already ships **Agent View**
(`claude agents`), and every third-party tool — Conductor, Crystal, Claude Squad,
Vibe Kanban, Nimbalyst — is a re-implementation of it. They manage *processes*.
None of them know anything about him.

## The one rule

> Design the resting state first, because it is the state.

Most of the time the reading is **clear**. Every competitor treats that as the
empty case — grey text, nothing to see. It is the screen he will look at ninety
percent of the time, so it gets the most care.

*(Back-reference: the Ive critique in this session — hierarchy is "removing those
things that are all vying for your attention," not removing things. See
`~/.claude/skills/jony-ive/corpus/2008-00-00-objectified-interview.md`.)*

## The guardrail, which is not optional

The reduction lives in **what is shown at rest**, never in **what can be found**.
Contrast stays high in both themes; every action stays labelled and reachable.
Ive's own record — iOS 7, Button Shapes — is the reason this is written down.
Aidan's attention-poor axiom in `~/.claude/CLAUDE.md` outranks the persona.

---

## Architecture

    ~/.claude/projects/**/*.jsonl   ─┐
    claude agents --json            ─┼──▶  daemon  ──▶  /api/state (JSON + SSE)
    ~/.claude/skills, project skills─┘                        │
                                                    ┌─────────┴─────────┐
                                                 the Face          vigil CLI
                                              (127.0.0.1:7717)     (terminal)

One substrate, one daemon, two thin surfaces. Python 3 stdlib only — no
dependencies to rot, no install friction.

### State machine (verified against live processes, 2026-08-16)

`claude agents --json` gives liveness only — pid, cwd, sessionId, startedAt. It
does **not** give status. Status is derived here:

| State | Test | Lights the lamp |
|---|---|---|
| `working` | transcript grew between two polls | no |
| `blocked` | alive, transcript frozen ≥20s, **and** an unanswered `tool_use` at the tail | **yes** |
| `yours` | alive, frozen, no unanswered `tool_use` — Claude finished its turn | no |
| `resting` | alive, frozen >30 min | no |
| `gone` | no live pid | no (off-rail) |

**The two-sample delta is load-bearing.** A pending `tool_use` alone means either
"blocked on a permission prompt" *or* "mid-tool-call right now." Session
`b6db10f8` was caught as a live false positive while writing this spec — it had
an unanswered `Edit` and was simply working. Only the frozen-ness separates them.

**Only `blocked` lights the lamp.** `yours` is most sessions most of the time; if
it alarmed, the resting state would never exist and the instrument would be a
list again.

### Reading hierarchy

1. any `blocked` → **alarm.** The question in his own words + one action.
2. else any `yours` → quiet reading, no lamp: "Three answers waiting."
3. else → **"Nothing needs you."**

### Naming and attribution

- **Session name** comes from the `ai-title` transcript entry (`"Review Jony
  Ive's feedback"`), not from `claude agents --json`'s `name` (`"bricks-e8"`).
  Take the **last** `ai-title` in the file — it is re-emitted as the session
  drifts.
- **Repo** is the git root most often *written to* (from `Edit`/`Write`
  `file_path` params), **not** the launch `cwd`. Several sessions launched in
  `bricks` were pushing to `writing-topology`; keying on `cwd` mislabels the rail.

### The rail

Each live session is one mark. **Position = time since it last spoke** (log
scale, 0–60 min across the rail). **Brightness = whether it is moving.** Labels
stagger to a second row when they would collide. Every mark is a real button
with a real accessible label.

This is the part no competitor has, and it is not decoration: a status list sorts
by state and throws the time axis away, and time is the actual dimension of this
fleet — 42 sessions over six hours, 11 over a day.

---

## Lenses

The Face is the first lens over the substrate. Two more, chosen with it:

- **Rot** — skills invoked in transcripts vs. skills present on disk. Currently
  ~210 invocations of skills that no longer exist (`gemini-web-search` 53×,
  `mobile-qa` 42×, `copy-voice` 22×). This is tenet 9 failing in the direction
  nobody watches: not a stale skill, a *silently missing* one.
- **Continuity** — what was decided, what is still open, per repo. Answers the 22
  times in 33 days he typed some version of *where were we*.

## Substrate preservation

`cleanupPeriodDays` was unset → a 30-day sweep. First token **2026-04-04**;
oldest surviving transcript **2026-07-15**. **~102 days were already permanently
gone** before this project started.

- `cleanupPeriodDays` → 36500 (set 2026-08-16)
- `~/.claude-archive/transcripts/` — mirror outside the sweep path

There is no year of data. The model is built on 33 days and deepens from here.
Saying so is the honest version.

## Non-goals

- Not a replacement for Agent View — VIGIL reads alongside it.
- Not orchestration. It does not spawn, route, or supervise agents. The data says
  he does not run subagent fleets; he runs session fleets.
- No cloud, no telemetry, no network egress. The corpus never leaves the machine
  — same separation as the bricks substrate.
