# Fix log

<!--
Append-only record of changes made outside a milestone. One entry per fix, written when the fix lands.
A fix that grows past its scope becomes a milestone or a plan amendment instead.
-->

## F-001 · <date> · <short title>
Symptom: <what the user or a check saw, with the exact output>
Origin: <where the defect came from: code, plan, interface, environment, test>
Reproduction: <command or steps; now a regression test at <path>>
Change: <files touched and why this is the smallest change that fixes it>
Checks re-run: <checkpoints and tests re-run, with exit codes and evidence paths>
Attempts: <1 | 2 | 3; three failed attempts stop the fix and go to the owner>
Quarantined: none    (or: <test> · owner <who> · reason <why> · expires <date>)
