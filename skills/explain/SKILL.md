---
name: explain
description: "Explain what was built, a milestone, the whole product, or the current status, in one audience register: engineer, founder, investor, or user, re-derived for that reader rather than reskinned. Also renders a milestone's demo script for the owner and a gate result as a standalone one-screen summary. Grounded only in the build record and collected evidence; the code stays out of sight. Use for /explain, 'what did we build', 'explain this for an investor', 'release notes', 'walk me through the demo'."
argument-hint: "[engineer | founder | investor | user] [M<k> | product | status | demo M<k> | gate M<k>]"
---

# /explain

Load-bearing rules:
- One register per output, re-derived from intent, behavior, and evidence at that reader's altitude; never a
  translated engineer summary.
- Every claim rests on evidence already collected (a demo capture, a gate result, a trace). Data a register
  needs and does not have (an investor metric) is named as missing, never invented.
- When a narrative lock exists (a venture project's `truth/narrative-lock.md`), identity and promise come
  first, rendered from it at the reader's scope.
- Standalone: a reader with none of this project's context understands every sentence; an ID appears only in
  parentheses after its plain meaning.

## Steps
1. Pick the register from the argument, or from who reads it and what they will decide; ask once if that is
   unclear. Never default to engineer.
2. Gather: `docs/project/intent.md`, `milestones.md` (what is accepted, gate-passed, built), the latest
   rounds in `docs/project/reviews/`, the demo captures in `.evidence/gate/`, and the changelog. Read code only
   when engineer mode needs a specific snippet.
3. Render with the mode's template, altitude, lead, omissions, and lint rules in `references/modes.md`; lint
   the render against them and fix it before showing.

## demo M<k>
The milestone's demo ending as a script the owner can follow or record: each step, what to do, what they
will see (with the capture from the latest gate round beside it), and the one thing the step proves, in the
user's register.

## gate M<k>
The latest gate round as the one-screen owner summary: the verdict, exceptions first (what failed, what
was skipped and why, what needs a ruling), what held and what drifted in words, how to see the demo, and the
readiness line.
