---
name: fix
description: "Make a targeted change that isn't a whole slice: a bug fix, a qa finding, a small tweak. Use this skill when the user says /fix, 'fix this', 'fix bug', 'patch this', 'address this qa finding', or wants a change scoped to a handful of files. Triage, change the smallest thing that works, verify with a real check shown as evidence, log it. Redirects to /plan and /dev if the change turns out to be a whole slice."
argument-hint: "<description of the fix or a qa finding reference>"
---

# fix — Targeted Change

> EXECUTABLE WORKFLOW. The off-loop quick path. The smallest change that works, proven by a real
> check.

For a change that is not a whole slice. If it grows into one (a new capability, a contract change,
many files), stop and redirect to `/plan` + `/dev`.

## Workflow

### Stage 1 — Triage
If it's a bug, reproduce it first (a real failing trace). If it's a qa finding, read it. If the
root cause isn't obvious after reproducing, load `references/root-cause-catalogs.md` and match the
symptom to a likely cause. Scope it: if this is actually a new capability or needs a contract
change, REDIRECT to `/plan` + `/dev` and stop.

### Stage 2 — Change
Make the smallest change that fixes it. Scope guard: every changed line traces to this fix; don't
refactor adjacent code or add unrequested scope.

### Stage 3 — Verify (evidence)
Run a real check that proves it's fixed (the reproduction now passes, the behavior works), shown
as command + output. For a bug, the reproduction trace going from red to green is the proof. Three
strikes: if three attempts don't fix it, stop and surface why rather than thrashing.

### Stage 4 — Log
Append a one-line entry to `fix-log.md` (what was wrong, what changed, the evidence). If the fix
touched a load-bearing behavior, suggest a `/loyal check`.

### Success: the problem is fixed, proven by a real check; `fix-log.md` updated.
### Failure: three attempts failed, or scope exceeded a targeted change (redirect).

## Ecosystem
- **Reads**: the qa finding / bug report, `contracts.md`, `AGENTS.md`.
- **Writes**: code; `fix-log.md`.
- **Redirects to**: `/plan` + `/dev` when the change is really a slice. Re-verified by `/qa` if
  non-trivial.
