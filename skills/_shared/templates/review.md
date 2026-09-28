# Review of M<k>

<!--
docs/project/reviews/M<k>.md, local-only. gate_report.py appends one block per gate round (never
overwritten) and keeps reviews/M<k>.findings.json, the findings ledger with each finding's rounds.
The builder may add the owner summary below a round; it never edits a script-written block.
-->

## Round <n> · <UTC timestamp> · fingerprint <fingerprint>
Verdict: <ACCEPT-READY | CHANGES | BLOCKED | INCONCLUSIVE> (computed; judge said <verdict>)
Deterministic layer: <PASS | FAIL> · <counts>
Checkers: code-verifier <status> · loyal-evaluator <status> · demo <status> · gate-judge <status>
Intent diff: <HOLDS n · DRIFT n · MISSING n · EXTRA n · ORPHAN n · INACCURATE n>
Blocking: <finding IDs with one line each and the loop-back point>
Logged: <finding IDs>
Not run: <what could not run and why>
Evidence: .evidence/gate/M<k>/r<n>/

### Owner summary
<one screen, exceptions first: what failed, what was skipped, what needs a ruling, how to see the demo>
