# Project workflow choice

Before any coding workflow, read `project_policy.py status <project> --json` from the shared scripts.
The explicit project choice takes precedence over adoption, owner locks, saved state, handoffs, campaigns,
venture overlays and a conductor's dispatch. No choice means OFF. Only the owner's explicit on/off
instruction changes it: they type `/pipeline on` or `/pipeline off` (which runs `project_policy.py`); invoking
another skill never enables management.

When OFF, perform the user's requested work with their existing documents, design, code and tests.
Do not require adoption, plan conversion, a cold read, lock playback, intent verification, record repair,
writer claims, milestone acceptance, inbox processing or recovery bookkeeping before doing that work.
Old records can supply context but do not bind the workflow. Ask only about a concrete ambiguity that
changes the implementation. Do not route to a formal step, maintain the formal journal, or chain via
next auto at the end. Research, diagnosis, planning, explanation and independent reviews are still usable
when requested. Report an independent review as a review, never as formal gate or owner acceptance.

When ON, the skill's formal rules and evidence requirements apply unchanged. At a meaningful stop and
before starting a checker or another step, re-read the choice. If it changed, stop the formal chain and
continue the user's ordinary task without imposing a new gate. The choice is independent of the build
record and is never a missing ruling or an intent amendment.

## Venture projects

A project with a `truth/` folder is a venture project. When ON, read
`~/.claude/skills/_shared/references/venture-mode.md` before the skill's first step (before changing
anything, starting a round, recording an acceptance, writing or receiving a packet, or deploying). If it is
missing, stop with BLOCKED: this is a venture project and its rules are not installed.

## End

When ON, every formal step records itself when it ends: each run of a skill, and inside a longer run every
stop (a /dev freeze, question to the owner, blocker, or finished campaign step; each /gate round report and
acceptance; each /handoff packet written or received):

`python3 ~/.claude/skills/_shared/scripts/project_status.py record <project> --skill <name> [--arg <what it ran on>] --outcome "<one line>"`

It appends the journal (`docs/project/journal.md`), rewrites the Last step in `state.md`, and prints the
Next line: what comes next, who takes it, and why. The report closes with that line. Under `/next auto`, a
builder step is taken right away. When OFF, `record` writes nothing.
