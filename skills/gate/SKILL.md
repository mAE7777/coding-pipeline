---
name: gate
description: "Accept or reject one frozen milestone: runs the round in the background (deterministic checks, isolated code review, blind intent reconstruction, demo, judge), computes the verdict from the evidence, drives the fix loop, and brings the owner a one-screen summary. /gate M<k> runs it; /gate accept M<k> records the owner's acceptance in their words; /gate status reports. Use after /dev freezes a milestone, and on M0 during adoption."
argument-hint: "M<k> | accept M<k> | status"
---

**Workflow choice, first.** Run `python3 ~/.claude/skills/_shared/scripts/project_policy.py status <project> --json`. OFF or no choice: do the requested work directly from the existing documents, code, and tests, with no formal step, record, or End chain. ON: the rules below apply; recheck the choice before each next step. Only the owner's explicit on or off, through /pipeline, changes it. Contract: `~/.claude/skills/_shared/references/project-control.md`.

# /gate

Load-bearing rules:
- The builder never grades its own work: every judgment runs in an isolated process in a prepared copy, and
  this session only starts the round, reads what it produced, fixes, and reports.
- `gate_report.py` computes the verdict from the evidence. The judge's own verdict is an input; a mismatch
  is reported, never smoothed over.
- Nothing silent: every check has a status, and NOT_RUN and SKIP carry their reason (`gate_report.py` lists
  them). A model or provider switch, a served model other than the one asked for, and an escalated retry are
  exceptions in the summary (each checker's `summary.json` records them).
- One round per project at a time, always in the background (`gate_run.py` refuses a second).

Venture projects (a `truth/` folder): read `~/.claude/skills/_shared/references/venture-mode.md` first; if it is missing, stop BLOCKED.

Scripts: `~/.claude/skills/_shared/scripts/`.

## Run a round: /gate M<k>
1. The milestone is frozen (`/dev freeze`): `gate_run.py` refuses a tree that differs from `state.md`'s
   Candidate, and a server started from the project blocks the round.
2. Start `python3 gate_run.py <project> --milestone M<k>` with the Bash tool's background option, then wait
   for its completion notice (progress is in `.evidence/gate/M<k>/r<n>/progress.log`). Its usage text gives
   the order; a deterministic FAIL ends the round before any checker runs. A checker that ends ERROR or
   INCONCLUSIVE is re-run once, on `models.json`'s escalate model and effort when its route asked for less.
3. Read `.evidence/gate/M<k>/r<n>/verdict.json` and the round appended to `docs/project/reviews/M<k>.md`.

## What a round runs
- **Scope.** Round 1 is full. `gate_run.py` decides each later round with `regate_scope.py decide` (the
  reasons are in the round's `scope.json`). A round is focused only when all of these hold, measured over the
  whole change since the last full round:
  - every changed file is named in a finding that blocked since then (its `files`), or in a fix-log entry
    since the acceptance (a hotfix), or is a test file;
  - the change is under about 150 lines, every changed file readable as text;
  - no changed file is intent-bearing (gate.md's Intent-bearing paths), a dependency manifest, a lockfile,
    a migration, or build or CI configuration.
  Otherwise the round is full. The final milestone's build rounds are always full (a hotfix round after its
  acceptance may be focused). `gate_run.py --full` forces a full round that replays every earlier milestone's
  demo ending; a round that did, or a focused hotfix round after an acceptance that did, is release ready
  (`release_ready` in `verdict.json`, which /deploy requires).
- **A focused round** runs the full deterministic layer, the code-verifier re-verifying every finding that
  blocked since the last full round (each one's `fixed_when`, so an undone fix is caught) on the delta, the
  demo, and the judge. The blind evaluator's result is carried from the last full round, labeled CARRIED
  with the fingerprint it ran on.
- **The deterministic layer** (`layer1.json`) runs gate.sh, the record checks, the labeled typecheck, lint,
  build, and test suite, every runnable earlier and current checkpoint check, checks that the wiring-row and
  contract test paths exist, and fails when a command changed the review copy. The reviewer reads
  `layer1.json`, does not run those again, and runs what it lists under "Not run by the gate" (the wiring and
  contract tests among them).
- **gate.sh's change checks** (`gate_checks.py`, against the milestone's baseline): `test-tamper` FAILs a
  deleted test, a new skip, only, or expected-failure marker, or a raised timeout, unless the owner ruled
  `[test-change: <path>]` in decisions.md; `file-growth` WARNs on a code file pushed past 1,000 lines;
  `prose-lint` WARNs on slop in outbound text and commit messages.
- A shadow set in `~/.claude/.pipeline-models.json` runs beside the real checker and never counts.

## What the verdict means
- **ACCEPT-READY**: write the owner summary (below) and ask for acceptance. In a campaign, record the
  verdict and start the next milestone; acceptance is batched at the end.
- **CHANGES**: the fix loop. Each blocking finding names its loop-back point and what shows it fixed:
  a contained defect goes to `/fix`, work inside the contract goes back to `/dev`. Then freeze again and run
  the next round. The judge keeps each finding's ID across rounds, and `gate_report.py` turns a finding
  still blocking in a second round into BLOCKED, for the owner. An intent finding goes to `/plan amend` with
  the owner, never to an edit of the intent (`intent_lock.py verify` fails one).
- **BLOCKED**: something only the owner can settle. Write the Blockers row and ask, plainly.
- **INCONCLUSIVE**: a checker could not ground itself even after its re-run, or the judge's verdict did not
  follow from its findings. Say which and why (the summary files name it), remove the cause, run again.
- **Logged findings**, under any verdict, never start a round: they go to the next milestone's Open list or
  `/polish`.

## The owner summary
One screen, in plain words, readable without any earlier context, exceptions first: the verdict; what
failed, what was skipped and why, what needs a ruling; the intent diff in words (what holds, what drifted);
exceptions such as a model switch or a CARRIED result; each checker's model and effort (set by
`models.json`); how to see the demo (the captures under `.evidence/gate/M<k>/r<n>/captures/`, and the command
to try it yourself); the readiness line. IDs appear only in parentheses after their plain meaning.

## Acceptance: /gate accept M<k>
Only when the owner says so, in their words (a whole sentence, never a cut):
`python3 decisions.py add <project> --title "Accept M<k>" --body "Accept M<k> · contract <milestone_lint.py --contract-hash M<k>> · fingerprint <candidate> · review reviews/M<k>.md" --source-owner "<their words>"`.
Keep that body exactly: `milestone_lint.py` and `pr_watch.py land-check` parse it. Set the milestone's Status
to accepted and tick accepted in its Readiness line; `milestone_lint.py` must pass. A rejection sets the
Status to changes, and the evidence of later milestones built on it is STALE. In a venture project the
private overlay says what to copy into `truth/`.

## The final milestone
Its round is always full, and `render_pack.py` adds the whole-product checks (wiring against every
milestone's table, document consistency, docs and changelog, accessibility and performance,
`simplified-stand-in`). Venture projects add helm's exit checks from the overlay.

## Status: /gate status
The latest round per milestone from `docs/project/reviews/`, the open findings from the ledgers, and
whether a round is running (`.evidence/gate/round.running`).

## The protocols the checkers use
`references/interface-baseline.md` (every user interface: the floor under any style, and the clarity pass),
`references/ui-ux-validation-protocol.md` (web UI), `references/native-ui-validation-protocol.md` (native),
`references/game-qa-protocol.md` (games), `references/regression-and-coverage-strategy.md`. The
code-verifier reads the one that fits; they also help when writing a milestone's demo ending.

## End
`python3 ~/.claude/skills/_shared/scripts/project_status.py record <project> --skill gate --arg M<k> --outcome "<one line>"`, then close the report with the Next line it prints (`project-control.md`, End).
