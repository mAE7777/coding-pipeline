---
name: loyal
description: "Standalone intent-fidelity check: did we build what was meant? An isolated evaluator never told the goal reconstructs what the product does from real runs; an isolated judge diffs that against the locked intent (drift, missing, extra, a right name doing the wrong job). Works mid-build on the live tree. Modes: check [M<k>] (default), vigilance (a planted discrepancy, manual only), status (the intent ledger)."
argument-hint: "[check [M<k>] | vigilance | status]"
---

**Workflow choice, first.** Run `python3 ~/.claude/skills/_shared/scripts/project_policy.py status <project> --json`. OFF or no choice: when the status names the fast workflow, use its matching /<name>-fast skill if it lists one; otherwise do the requested work directly from the existing documents, code, and tests, with no formal step, record, or End chain. ON: the rules below apply; recheck the choice before each next step. Only the owner's explicit on or off, through /pipeline, changes it. Contract: `~/.claude/skills/_shared/references/project-control.md`.

# /loyal

The failure this exists for: a product that works but is no longer the thing that was meant, and a report
that becomes one more approve button.

Load-bearing rules:
- The evaluator and the judge run isolated, by script (the charter's law 3); this session only starts the
  check and renders the result.
- A finding is fixed in the product, or the owner changes the intent through `/plan amend`; never the intent to
  make a check pass.
- Venture projects (a `truth/` folder): read `~/.claude/skills/_shared/references/venture-mode.md` first; if it is missing, stop BLOCKED.

## check [M<k>]
1. `intent_lock.py verify docs/project/intent.md` must pass (a missing lock means `/plan` first). M<k> is the
   milestone in progress (from `state.md`) unless named.
2. In the background: `python3 ~/.claude/skills/_shared/scripts/gate_run.py <project> --milestone M<k>
   --intent-only` (its usage says what runs: the blind copy of the live tree, the evaluator's three passes, the
   judge, and a line in `docs/project/reviews/intent-ledger.md`).
3. Read `.evidence/loyal/M<k>/r<n>/verdict.json` and the judge's result, and render the report in
   `references/delta-report-format.md`: the load-bearing verdict first, the goal next to the evaluator's purpose
   guess, then only the items that are not HOLDS, one line each in behavior language; a clean check is one line,
   with no finding invented to look thorough. INCONCLUSIVE is reported with its reason (the verdict file names
   the checker and what it could not ground).

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

## End
`python3 ~/.claude/skills/_shared/scripts/project_status.py record <project> --skill loyal --arg M<k> --outcome "<one line>"`, then close the report with the Next line it prints (`project-control.md`, End).
