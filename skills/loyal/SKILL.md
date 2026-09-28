---
name: loyal
description: "Standalone intent-fidelity check: did we build what was meant? An isolated evaluator that was never told the goal reconstructs what the product actually does from real runs, guesses its purpose, and only then sees the goal; an isolated judge diffs that against the locked intent (drift, missing, extra, orphan, and a feature with the right name doing the wrong job). Works mid-build on the live tree. Modes: check (default), vigilance (a planted discrepancy to test the reader's attention, manual only), status (the intent ledger). The same evaluator runs inside every /gate round; the intent itself is locked by /plan."
argument-hint: "[check [M<k>] | vigilance | status]"
---

# /loyal

The failure this exists for: a product that works but is no longer the thing that was meant, and a report
that becomes one more approve button.

Load-bearing rules:
- The evaluator never sees the goal before it has described what the product does; the diff is judged in a
  separate isolated process. This session only starts the check and renders the result.
- The report shows only what is not HOLDS. No finding is invented to look thorough: a clean check is one line.
- The intent is changed only by `/plan amend` with the owner, never to make a check pass.
- Venture projects: when the project has a `truth/` folder, read
  `~/.claude/skills/_shared/references/venture-mode.md` before a check; if it is missing, stop with BLOCKED (this is a
  venture project and its rules are not installed).

## check [M<k>]
1. `intent_lock.py verify docs/project/intent.md` must pass (a missing lock means `/plan` first). M<k> is the
   milestone in progress (from `state.md`) unless named.
2. In the background: `python3 ~/.claude/skills/_shared/scripts/gate_run.py <project> --milestone M<k>
   --intent-only`. It copies the live tree (no freeze needed), strips everything that states intent from the
   blind copy, runs the evaluator (pass 1 without the goal, pass 2 with it) and the judge, and logs the result
   in `docs/project/reviews/intent-ledger.md`.
3. Read `.evidence/loyal/M<k>/r<n>/verdict.json` and the judge's result, and render the report in
   `references/delta-report-format.md`: the load-bearing verdict first, the goal next to the evaluator's purpose
   guess, then only the items that are not HOLDS, one line each in behavior language. INCONCLUSIVE is reported
   with its reason (the verdict file names the checker and what it could not ground).

## vigilance (manual only)
Runs only when the owner invokes it. Before showing a check report, pick one real item and falsify it
plausibly (a HOLDS turned into a DRIFT, or a swapped purpose guess), and write the plant first to
`docs/project/reviews/intent-ledger.md` under `## Vigilance` (the item, the true verdict, `outcome: pending`).
Show the report with no tell. After the owner responds, read the block back, set `outcome: caught` or
`missed`, and reveal the plant either way. A pending block left by an interrupted session is resolved and
revealed before anything else.

## status
The intent ledger's recent checks, the vigilance record (caught and missed), and the open intent findings
in `docs/project/reviews/*.findings.json`.
