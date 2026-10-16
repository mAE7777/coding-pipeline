---
name: next
description: "The front door: where the project stands and what comes next, computed from its record, then done. /next takes the next step or asks the owner the one question that is theirs; /next auto keeps going until the owner must decide (lock, acceptance, stand-in consent, inbox ruling, irreversible action, blocker); /next status only reports. Use for /next, 'what now', 'continue', 'keep going', 'where are we', and when the owner names no step."
argument-hint: "[auto | status]"
---

**Workflow choice, first.** Run `python3 ~/.claude/skills/_shared/scripts/project_policy.py status <project> --json`. OFF or no choice: do the requested work directly from the existing documents, code, and tests, with no formal step, record, or End chain. ON: the rules below apply; recheck the choice before each next step. Only the owner's explicit on or off, through /pipeline, changes it. Contract: `~/.claude/skills/_shared/references/project-control.md`.

# /next

The owner should never have to know which step comes next or remember where the work stopped. The record
knows: `python3 ~/.claude/skills/_shared/scripts/project_status.py <project>` computes, from the files alone,
the state and the ordered next steps, each marked builder (do it now), owner (only they can decide), or wait
(something is running).

## /next status
Run it and tell the owner in plain words, in their language: what the project is, which milestone it is on and
how far along, what the last step was, anything waiting in the inbox or blocked, and the next step with who
takes it and why. Nothing else happens.

## /next
1. Run the status and give the owner the short version (two or three lines: where it stands, what is next).
2. When the first step is the builder's, take it now: follow that skill (`/dev M2`, `/gate M1`, `/inbox review`,
   `/plan adopt`, and so on) exactly as if the owner had typed it. When it is the owner's, ask the one question
   it names, in plain words, with what the options mean, and stop. When it is wait, say what is running and
   continue when it reports.
3. When the step is done, its skill's End records it and prints the new next step; report that and stop.

## /next auto
The same, but after each builder step, run the status again and take the next builder step, until the first
owner step, a wait (continue when the running work reports), or a failure the step's own loop cannot clear.
When the status says the last 3 steps repeated without changing the record, that is an owner step: say what
is looping and what was tried. Then stop with a plain summary: every step taken with its outcome, where the
project stands, and the owner's question. It never takes an owner step on the owner's behalf, never treats an
earlier approval as covering a new decision, and never skips a skill's own checks to go faster. The owner
can stop it at any time; the record is current after every step, so `/next` picks up exactly there.

## Sessions
Work inside one phase (a milestone's build through its gate, a plan up to its lock, a batch of capture rounds)
stays in one session: its working knowledge is not worth rebuilding. A step marked "best begun in a new session"
opens a new phase (the next milestone, the first build after the lock): the record carries everything, and the
last phase's detours and rejected options stay behind. Under `/next`, tell the owner and let them choose; under
`/next auto`, keep going unless this session is already long (much of its context used), and then stop at that
step with the suggestion. Never start another session yourself. In the new session the owner types `/next`.

## Rules
- The status script is the authority on what comes next. When it and your own reading disagree (the record
  looks wrong, a note is stale), fix the record first (state.md, a stale In flight line, a missing decision),
  then run it again; never act on the disagreement silently.
- Every step ends with `project_status.py record`, which prints the next step (`project-control.md`, End).
- In Codex, the skills are `$next`, `$dev`, and so on; everything else is the same.
