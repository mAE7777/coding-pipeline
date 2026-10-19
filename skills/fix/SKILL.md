---
name: fix
description: "Make a targeted change outside a milestone's build run: a bug, a blocking gate finding (an ID such as M2-F03), a production hotfix, a flaky test, a small tweak. Reproduction first, the smallest change, a regression test, an entry in the fix log; redirects to /plan amend or a milestone when it grows past a fix. Use for /fix, 'fix this', 'patch', or a finding the gate sent back."
argument-hint: "<the problem, or a gate finding ID such as M2-F03>"
---

**Workflow choice, first.** Run `python3 ~/.claude/skills/_shared/scripts/project_policy.py status <project> --json`. OFF or no choice: when the status names the fast workflow, use its matching /<name>-fast skill if it lists one; otherwise do the requested work directly from the existing documents, code, and tests, with no formal step, record, or End chain. ON: the rules below apply; recheck the choice before each next step. Only the owner's explicit on or off, through /pipeline, changes it. Contract: `~/.claude/skills/_shared/references/project-control.md`.

# /fix

Load-bearing rules:
- Reproduce before changing anything: a real failing trace (command and output), or for a gate finding its
  quoted evidence reproduced in this tree. No reproduction, no fix: say what you tried.
- The smallest change that fixes it. Every changed line traces to this fix; no adjacent refactor, no new
  scope. `/dev`'s load-bearing rules apply (no unconsented stand-in, loud failure, tests never weakened).
- The reproduction becomes a regression test that fails before the change and passes after.
- Two failed fixes that share one premise: write the premise down and test it before a third (`heavy.py`
  prints when a failure has survived 2 fixes). Three failed attempts: stop and report what was tried and what
  you learned, as a Blockers row.
- A fix that turns into a new capability, a contract change, or many files is not a fix: stop and route it
  to `/plan amend` (intent changes) or into a milestone.

Venture projects (a `truth/` folder): read `~/.claude/skills/_shared/references/venture-mode.md` first; if it is missing, stop BLOCKED.

When `record_check.py` does not report `complete`, a fix still goes ahead when the owner asked for it; the
fix log is created, and the missing record is named in your report (adoption is `/plan adopt`).

## Steps
The method is `~/.claude/skills/code-craft/methods/bug-fix.md`, read after `~/.claude/skills/code-craft/index.md`,
whose overrides win. A fix in shared code also gets `~/.claude/skills/code-craft/review/blast-radius.md`.
1. **Classify** the origin: code, plan (the contract was wrong), interface, environment, or test. A plan or
   interface origin means the fix also needs a decision entry (`decisions.py add`), and possibly the owner.
2. **Reproduce.** When the cause is not obvious after reproducing, match the symptom in
   `references/root-cause-catalogs.md`.
3. **Change** the smallest thing. Heavy commands run as
   `python3 ~/.claude/skills/_shared/scripts/heavy.py run --owner <session> --tail 60 -- <cmd>` (`<session>`
   is this session's ID; the full log stays in `.evidence/logs/`).
4. **Prove it**: the regression test (rule 3); every checkpoint the change touches re-run (their
   checks are in `milestones.md`); the blast-radius proof for shared code; for a diff of a few files, the
   bundled `/code-review` gives a cheap fresh look.
5. **Log** in `docs/project/fix-log.md` (template in `~/.claude/skills/_shared/templates/fix-log.md`):
   symptom, origin, reproduction and its test, the change, checks re-run with evidence paths, attempts. The
   Change line names every file the fix touched: `regate_scope.py` reads it to allow a focused re-gate.
6. **Hand back.** For a gate finding: say which finding is fixed and what shows it (its `fixed_when`), freeze
   again (`/dev freeze`), and run `/gate`. `regate_scope.py` decides the next round: focused when the change
   stays inside the findings' files, is under about 150 lines, and touches nothing intent-bearing; otherwise
   full. For a hotfix after acceptance: set `state.md` Candidate to `fingerprint.py <project>` and leave the
   Status `accepted` (never `/dev freeze`, which reopens the milestone), run `/gate M<k>` again (a focused
   hotfix round when every changed file is on a fix-log entry's Change line or is a test, under about 150
   lines, nothing intent-bearing; otherwise full), then the owner's `/gate accept M<k>` of the new candidate,
   then `/deploy`; the fix joins the next milestone's regression demo.

## Flaky tests
Never skip a flaky test silently or raise its timeout to hide it. Find the cause (shared state, timing,
order, network). If it cannot be fixed now, quarantine it explicitly: the fix log's Quarantined line (owner,
reason, expiry), and a marker in the test itself so the runner reports it as QUARANTINED, not passing. That
marker is a skip, so the gate's `test-tamper` check fails it unless the owner ruled `[test-change: <path>]`
in decisions.md.

## End
`python3 ~/.claude/skills/_shared/scripts/project_status.py record <project> --skill fix --outcome "<one line>"`, then close the report with the Next line it prints (`project-control.md`, End).
