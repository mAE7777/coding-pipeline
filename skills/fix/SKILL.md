---
name: fix
description: "Make a targeted change outside a milestone's build run: a bug, a blocking gate finding, a production hotfix, a flaky test, a small tweak. Reproduce first, change the smallest thing that fixes it, turn the reproduction into a regression test, re-run what the change touches, log it in the fix log. Redirects to /plan amend or a milestone when the change grows past a fix. Use for /fix, 'fix this', 'patch', or a finding the gate sent back."
argument-hint: "<the problem, or a gate finding ID such as M2-F03>"
---

# /fix

Load-bearing rules:
- Reproduce before changing anything: a real failing trace (command and output), or for a gate finding its
  quoted evidence reproduced in this tree. No reproduction, no fix: say what you tried.
- The smallest change that fixes it. Every changed line traces to this fix; no adjacent refactor, no new
  scope. The same standing rules as `/dev` apply: loud failure at boundaries, no invented defaults, no
  stand-in on the product path without the owner's consent in their words, tests never weakened.
- The reproduction becomes a regression test that fails before the change and passes after.
- Three failed attempts: stop and report what was tried and what you learned, as a Blockers row.
- A fix that turns into a new capability, a contract change, or many files is not a fix: stop and route it
  to `/plan amend` (intent changes) or into a milestone.
- Venture projects: when the project has a `truth/` folder, read
  `~/.claude/skills/_shared/references/venture-mode.md` before changing anything; if it is missing, stop with BLOCKED (this is a
  venture project and its rules are not installed).

When `record_check.py` does not report `complete`, a fix still goes ahead when the owner asked for it; the
fix log is created, and the missing record is named in your report (adoption is `/plan adopt`).

## Steps
1. **Classify** the origin: code, plan (the contract was wrong), interface, environment, or test. A plan or
   interface origin means the fix also needs a decision entry, and possibly the owner.
2. **Reproduce.** When the cause is not obvious after reproducing, match the symptom in
   `references/root-cause-catalogs.md`.
3. **Change** the smallest thing; heavy commands go through the machine lock.
4. **Prove it**: the regression test red then green; every checkpoint the change touches re-run (their checks
   are in `milestones.md`); for a diff of a few files, the bundled `/code-review` gives a cheap fresh look.
5. **Log** in `docs/project/fix-log.md` (template in `~/.claude/skills/_shared/templates/fix-log.md`):
   symptom, origin, reproduction and its test, change, checks re-run with evidence paths, attempts.
6. **Hand back.** For a gate finding: say which finding is fixed and what shows it (its `fixed_when`); the
   milestone is frozen again and the next gate round runs (`/dev freeze`, then `/gate`). For a production
   hotfix: `/deploy` next, and the fix joins the next milestone's regression demo.

## Flaky tests
Never skip a flaky test silently or raise its timeout to hide it. Find the cause (shared state, timing,
order, network). If it cannot be fixed now, quarantine it explicitly: in the fix log, `Quarantined: <test> ·
owner <who> · reason <why> · expires <date>`, and mark it in the test itself so the runner reports it as
QUARANTINED, not passing.

## End
Every run ends with `python3 ~/.claude/skills/_shared/scripts/project_status.py record <project> --skill fix --outcome "<one line>"` (the journal and the Last step in state.md), and the report closes with the Next line it prints: what comes next, who takes it, and why. Under `/next auto`, a builder step is taken right away.
