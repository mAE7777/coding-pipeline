# Handoff

<!--
Written by /handoff write, checked by handoff_check.py before it is sent, read by /handoff receive.
Every section is required. "none" is allowed where there is genuinely nothing, never "TBD".
Stored under docs/project/handoffs/ (local-only).
-->

From: <session or model>
To: <new session | codex | claude | reviewer>
Written: <UTC timestamp>

## Authority
May: <what the receiver is authorized to do>
May not: <irreversible actions, scope changes, and anything else it must stop for>

## Read list
- docs/project/intent.md · sha256 <hash>
- docs/project/brief.md · sha256 <hash>
- docs/project/milestones.md · sha256 <hash>
- docs/project/state.md · sha256 <hash>

## Candidate
<fingerprint from fingerprint.py>

## Done
- <item> · evidence: <path>

## Open
- [ ] <every open item from state.md>

## In flight
<running processes, background agents, external effects sent but not confirmed; or none>

## Blockers
<what · owner · unblock condition; or none>

## Failures
<known failing checks and counterexamples that must stay covered; or none>

## Carried forward
<!-- at a milestone boundary: every parked item, known limit, and logged (non-blocking) gate finding,
     each with its ID; handoff_check.py compares this with milestones.md and reviews/M<k>.findings.json -->
- <ID> <what> · from: <M<k> parked | gate finding | known limit>

## Constraint IDs
<every active constraint ID from brief.md, e.g. C-01, C-02>

## Must-not-lose IDs
<every ID from intent.md "Must not lose", e.g. L-01, L-02>

## Next step
<the exact next action>

## Hand back
<what the receiver returns, where, and when to stop>
