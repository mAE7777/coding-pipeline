# State

<!--
The compaction and handoff anchor. Rewritten at every checkpoint and meaningful completion.
Read by milestone-continue.py (Writer, Milestone, Campaign, Open, In flight, Blockers), handoff_check.py
(Open), and the reload gate. Local-only: kept out of commits through .git/info/exclude.
The wiring table lives in milestones.md, not here.
-->

Updated: <UTC timestamp>

## Writer
claude session <id>    (or: codex session <id>; one writer per checkout; /dev resume and /handoff
receive rewrite this line)

## Milestone
M<k> · phase: <building | checkpoint M<k>.C<n> | gate | fixing | idle>

## Campaign
none    (or: M1-M3 · D-<nnn>, the owner's authorization to chain milestones without waiting)

## Baseline
<fingerprint recorded when the milestone started; the file list is in .evidence/baseline-M<k>.txt>

## Candidate
<fingerprint at the freeze, or "not frozen">

## Understanding
<the milestone promise and the must-not-lose items, restated in the builder's own words>

## Done
- <item> · evidence: <path under .evidence/>

## Open
- [ ] <task>

## In flight
none    (background builds, servers, agents, or external effects still running; the stop check lets a
turn end while this is not "none")

## Failures
none

## Blockers
none    (what · who can clear it · what unblocks it; written before every stop)

## Next step
<the exact next action>

## Last step
<skill and what it ran on · UTC time · session · outcome; written by project_status.py record at the end of
every step, with the full history in docs/project/journal.md>
