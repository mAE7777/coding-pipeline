---
name: evolve
description: "The pipeline's own improvement loop, started by the owner in any session that used the pipeline. /evolve harvests the session (every failure, block, inconclusive or stuck step, the owner's pushback, and the friction a script cannot see, with what the session did about each, even a stopgap) into incidents in a private ledger; then /evolve run proves each problem with a reproduction that fails on the current pipeline, designs the fix against the session's own workaround, and keeps a change only when a rule fixed in advance says the pipeline got better (the reproduction flips, no benchmark gets worse, measured by the same instrument in the same environment) and an isolated reviewer finds the cause removed and nothing weakened. Every problem, measurement, and decision stays on record, so the pipeline only ever moves forward. Use for /evolve, 'improve the pipeline from this session', 'log these pipeline problems', 'what went wrong with the pipeline'."
argument-hint: "[run [INC-nnnn ...] | status]"
---

# /evolve

Every session that uses the pipeline finds out something about it: a check that stopped the wrong thing, a
step that looped, an instruction two readings could take differently, a stopgap that got the work through.
Without this loop those lessons stay in one transcript. With it, each becomes an incident, is proven real,
and is fixed only in a way that measurably improves the pipeline and cannot quietly make anything else worse.

Load-bearing rules:
- **No fix without a reproduction.** A problem is real when a suite fails on the current pipeline because of
  it. Until then it is a report, kept and counted, never acted on.
- **The judge is fixed before the change.** `evolve.py compare` decides BETTER, SAME, WORSE, or INCOMPARABLE
  by the rule in its own documentation; run it from the installed copy
  (`~/.claude/skills/_shared/scripts/evolve.py`), which is the pipeline before the change, never from the
  branch being judged. A change to the judge itself (evolve.py, the change reviewer, the fixtures'
  expectations) is a rule change: the owner rules on it and the old judge measures it.
- **Fair measurement.** Both sides run the same suites, with the same instrument (the branch's `tests/`),
  in the same environment (the same Claude Code, Codex, Python, and checker models), with the same number
  of runs; every measurement is kept; a noisy result is measured again on both sides (`--again`), never on
  one side until it looks good.
- **Never weaker.** No test, fixture expectation, lint, gate rule, or checker instruction may accept more
  than before inside a fix. Removing a test counts as worse. A fix that trades a loud failure for a quiet one
  breaks the fourth law and is not a fix.
- **The session's workaround is an option.** What the session actually did is weighed like any other design,
  measured when it is a change to the pipeline, and the record says whether the chosen change adopts it,
  generalizes it, or replaces it and why.
- **Who decides.** A fix to a defect or a clearer document inside the pipeline's rules is the builder's. A
  new capability, a changed rule, a changed owner gate, anything that lets a checker decide differently, and
  anything that relaxes a check are the owner's rulings, in their words, proven with the transcript.
- **Private in, public out.** The ledger (`$HOME/.claude/pipeline-evolution/`, one for Claude Code and Codex)
  keeps project details and stays on this machine. What enters the repository (tests, fixtures, text) is synthetic and carries no project's
  content, names, or paths.

Script: `python3 ~/.claude/skills/_shared/scripts/evolve.py` (subcommands and every rule in its header).

## /evolve (harvest, in the session that had the trouble)
1. `evolve.py harvest [--project <dir>]` reads this session's whole transcript (compacted parts included)
   and writes `candidates.md`: each signal once, grouped by a signature, with its evidence. Known problems
   only get an occurrence added; a fixed problem seen again is flagged as a REGRESSION.
2. Judge every new candidate: a pipeline problem, something outside the pipeline (the environment, the
   project's own code, a choice that was right), or noise. Say which, with the reason.
3. Add what no script sees, from this session's own memory and record: an instruction that was unclear or
   read two ways, a step that did needless work, context that had to be rebuilt, a wrong turn later
   corrected, a place the owner had to explain what the pipeline should have known. These are incidents too,
   with the transcript place that shows them.
4. For each pipeline problem, `evolve.py similar "<signature or words>"` first. Same cause as an existing
   incident: add this occurrence and evidence to it (reopen it when it was fixed: `Status: reopened`). New:
   `evolve.py new-incident --title ... --kind ... --where ... --signature ... --harvest <dir> --candidate <n>`,
   then fill in the impact and what the session did, with evidence of whether it worked.
5. Skills outside the pipeline: record as `not-pipeline (<which skill or tool>)` and name them to the owner.
6. Report, then continue straight into run unless the owner said harvest only or this session is already
   long (the ledger carries everything; `/evolve run` resumes in any session).

## /evolve run [INC-nnnn ...] (in the pipeline repository)
The incidents named, or every open, confirmed, and reopened one (`evolve.py status` lists them, most
frequent first). Work through them one cause at a time.

1. **Group by cause.** Incidents with one root cause become one change; one incident with two causes is two.
   Read the code the incident points at before deciding.
2. **Reproduce**, cheapest faithful suite first: a unit test for a script or hook
   (`repro:test:tests/<file>.py::<Class>.<test>`); a checker or probe fixture for model behavior
   (`repro:fixtures:<name>`, a planted case the current checker or text gets wrong; a probe embeds the text
   under test with `{repo:<path>}`, see `tests/agent_fixtures.py`); a scenario only for a whole flow. It must
   fail for the incident's reason: a test that fails only because a name the fix adds is missing proves
   nothing. Record it in the incident's Reproduction section and set `Status: confirmed`. Not reproducible
   after real attempts: `Status: not-reproduced`, each attempt recorded; it stays counted and is retried
   when it recurs. Outside the pipeline after all: `environment (...)` or `not-pipeline (...)`.
3. **Open the change**: `evolve.py new-change --title ... --incidents ... --kind fix|doc|capability|rule-change`,
   then, from a clean main, `git switch -c evolve/chg-<nnnn> <Base>` in the repository, and commit the
   reproduction first.
4. **Design**: the root cause with file and line; at least two options with what, how, and why, the
   session's workaround among them (on its own branch and measured when it is a pipeline change); the choice
   and why it beats the others. For an owner kind, ask the owner now, in plain words with the options, and
   write their answer as `[owner <date>] "<their words>" · session <id>`.
5. **Build** the fix on the branch; the reproduction stays in the suite for good.
6. **Measure**: `evolve.py touchmap <Base> <branch>` names the suites the change can affect (selftest
   always; the checker fixtures for any checker text or runner change; a flow scenario when the change
   alters what that flow does). Write them with the reproduction into the record's `Suites:` line, then
   `evolve.py bench <Base> --suites "..." --instrument <branch>` and `evolve.py bench <branch> --suites "..."`,
   then `evolve.py compare <Base> <branch> --suites "..."`. A scenario is measured against the installed
   pipeline, so install the branch for its after-run and reinstall main if the change is not kept.
7. **Only BETTER goes on.** WORSE: fix what got worse or choose another option. SAME: the reproduction did not
   flip, so the fix is wrong or the reproduction is. INCOMPARABLE: measure what is missing, alike on both
   sides.
8. **Review**: `evolve.py review CHG-<nnnn>` runs the change reviewer (`change-reviewer`) in isolation on the
   branch. Its findings
   are addressed on the branch, then measured and reviewed again; the review covers the exact commit.
9. **Record**: `evolve.py record CHG-<nnnn>` refuses any missing proof; on success the incidents are fixed.
10. **Release**: fast-forward main to the branch, `python3 install.py apply`, the Codex sync that
    `install.py check` names when Codex's copies are behind, `python3 install.py check` until it passes, push,
    then `evolve.py check` (every fixed incident proven and merged). A commit message says what changed for a user of the pipeline, in plain words.

A change the owner orders directly, outside this loop, still closes its incidents on the record: `Status:
resolved (<commit> · <how it was verified>)`; `evolve.py check` requires the commit on main, and a harvest that
sees the problem again flags it as a regression like any fixed one.

## /evolve status
`evolve.py status` and `evolve.py check`: the ledger in plain words, what is open and how often it recurs,
what is proven and released, and anything the check refuses.

## Economy
The script reads the transcript, groups signals, adds known occurrences, and remembers measurements, so the
model reads only new candidates and never pays twice for the same benchmark (per commit, instrument, and
environment). Deduplicate before reproducing, reproduce with the cheapest faithful suite, batch incidents that
share a cause, run scenarios only when a flow changes, and review once per change. None of this cuts what
is examined: every candidate is judged, and every loop ends when it converges.

## Finish
Report to the owner in plain words, in their language: what the session revealed (counts: candidates,
incidents new and recurring, set aside and why), then for each change what was wrong, what the session had
done, what changed and why that option, the before and after numbers, and the reviewer's view; what is
waiting for the owner's ruling; what could not be reproduced. End with `evolve.py status`.
