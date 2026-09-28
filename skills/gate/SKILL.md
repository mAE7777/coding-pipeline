---
name: gate
description: "Accept or reject one frozen milestone. Runs the whole round in the background (copies of the candidate, the deterministic checks, the isolated code review preferring the other model family, the blind two-pass intent reconstruction, the isolated demo run, the isolated judge), computes the verdict from the evidence, drives the fix loop, and brings the owner a one-screen summary. /gate accept M<k> records the owner's acceptance in their own words. Use after /dev freezes a milestone, and on M0 during adoption."
argument-hint: "M<k> | accept M<k> | status"
---

# /gate

Load-bearing rules:
- The builder never grades its own work. Every judgment runs in an isolated process in a prepared copy; this
  session only starts the round, reads what it produced, fixes, and reports.
- The verdict is computed by `gate_report.py` from the evidence; the judge's own verdict is an input, and a
  mismatch is reported, never smoothed over.
- Nothing silent: every check has a status; NOT_RUN and SKIP carry their reason; a model or provider switch
  (for example Codex unavailable, Claude used) is an exception in the summary.
- One round per project at a time, always in the background: it lasts longer than one shell call.
- Venture projects: when the project has a `truth/` folder, read
  `~/.claude/skills/_shared/references/venture-mode.md` before starting a round or recording an acceptance; if it is missing, stop with BLOCKED (this is a
  venture project and its rules are not installed).

Scripts: `~/.claude/skills/_shared/scripts/`.

## Run a round: /gate M<k>
1. The milestone is frozen: `state.md` Candidate equals `fingerprint.py <project>` (`/dev freeze` does this).
   The project's own servers are stopped (a server started from the project blocks the round).
2. Start it: `python3 gate_run.py <project> --milestone M<k>` with the Bash tool's background option, then
   wait for its completion notice (progress is in `.evidence/gate/M<k>/r<n>/progress.log`). In order it
   makes the review, demo, and blind copies; runs the deterministic layer (gate.sh, milestone_lint,
   intent_lock verify, rulings, the test suite, the project's own gate command and design lint); a
   deterministic FAIL ends the round there. Then the code-verifier on the review copy, the loyal-evaluator
   on the blind copy (pass 1 without the goal, pass 2 with it), the demo in the untouched demo copy, the
   gate-judge on copies of every result, and the report. A checker that ends ERROR or INCONCLUSIVE is re-run
   once. The copies are deleted at the end.
3. Read `.evidence/gate/M<k>/r<n>/verdict.json` and the round appended to `docs/project/reviews/M<k>.md`.

## What the verdict means
- **ACCEPT-READY**: write the owner summary (below) and ask for acceptance. In a campaign, record the
  verdict and start the next milestone; acceptance is batched at the end.
- **CHANGES**: the fix loop. Each blocking finding names its loop-back point and what shows it fixed:
  a contained defect goes to `/fix`, work inside the contract goes back to `/dev`. Then freeze again and run
  the next round; the judge keeps each finding's ID across rounds, and a finding still blocking in a second
  round turns the verdict BLOCKED, for the owner to decide. An intent finding is never fixed by editing
  the intent: that is `/plan amend` with the owner.
- **BLOCKED**: something only the owner can settle. Write the Blockers row and ask, plainly.
- **INCONCLUSIVE**: a checker could not ground itself even after its re-run, or the judge's verdict did not
  follow from its findings. Say which and why (the summary files name it), remove the cause, run again.

## The owner summary
One screen, in plain words, readable without any earlier context, exceptions first: the verdict; what
failed, what was skipped and why, what needs a ruling; the intent diff in words (what holds, what drifted);
exceptions such as a model switch; how to see the demo (the captures under
`.evidence/gate/M<k>/r<n>/captures/`, and the command to try it yourself); the readiness line. IDs appear only
in parentheses after their plain meaning.

## Acceptance: /gate accept M<k>
Only when the owner says so, in their words. Add a decision entry `D-<nnn> · <date> · Accept M<k>` whose body
is `Accept M<k> · contract <milestone_lint.py --contract-hash M<k>> · fingerprint <candidate> · review
reviews/M<k>.md` and `Source: [owner <date>] "<their words>"` (a whole sentence, never a cut); run `rulings.py record <project> --id D-<nnn>
--quote "<their words>"`; set the milestone's Status to accepted and tick accepted in its Readiness line;
`milestone_lint.py` must pass. A rejection sets the Status to changes, and the evidence of later milestones
built on it is STALE. In a venture project the private overlay says what to copy into `truth/`.

## The final milestone
Its gate adds whole-product checks, run by the code-verifier with an extra pack section and read by the
judge: the full wiring inventory against every milestone's table, a consistency pass across the documents
(terms, entities in interfaces with no intent, milestones with no carried examples), docs and changelog
current, accessibility and performance where they apply, and nothing load-bearing shipped as a simplified
stand-in of its mechanism without a live consent (the check named `simplified-stand-in`). Venture projects
add helm's exit checks from the overlay.

## Status: /gate status
The latest round per milestone from `docs/project/reviews/`, the open findings from the ledgers, and
whether a round is running (`.evidence/gate/M<k>.running`).

## The protocols the checkers use
`references/interface-baseline.md` (every user interface: the floor under any style, and the clarity pass),
`references/ui-ux-validation-protocol.md` (web UI), `references/native-ui-validation-protocol.md` (native),
`references/game-qa-protocol.md` (games), `references/regression-and-coverage-strategy.md`. The
code-verifier reads the one that fits; they also help when writing a milestone's demo ending.

## End
Every round report and every acceptance ends with `python3 ~/.claude/skills/_shared/scripts/project_status.py record <project> --skill gate --arg M<k> --outcome "<one line>"` (the journal and the Last step in state.md), and the report closes with the Next line it prints: what comes next, who takes it, and why. Under `/next auto`, a builder step is taken right away.
