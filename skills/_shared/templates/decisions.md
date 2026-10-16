# Decisions

<!--
Append-only. Written at the moment a decision is made, not at the end of a session. A superseded
decision stays; the new one names it.

An entry the owner decided carries "[owner <date>]" followed by the owner's own words in quotes: a whole
sentence they typed, or their whole message, never a fragment (a cut can drop a "no"). Each such entry also
has a local proof that the quoted words were typed by the owner, and an owner entry without one fails the
checks. The builder never writes "[owner ...]" on its own judgment; it writes "[proposed]" and asks.

Fixed forms:
  Acceptance:  "Accept M<k> · contract <hash> · fingerprint <fingerprint> · review reviews/M<k>.md"
  Stand-in:    "[placeholder-consent: <path or part> <what stands in> owner <date>] pairs: named non-goal
               (<reason>) | contract-blocked @<entry>"
  Test change: "[test-change: <path>]", in an owner-ruled entry only: the one way a test deleted, skipped,
               or loosened since the milestone began passes the gate
  Lock:        "Lock intent · hash <hash>"

A material decision (costly to reverse, or one other work builds on) also carries, after Why:
  Invariants: <what must stay true whichever option wins>
  Verified facts: <each with its source>
  Unverified assumptions: <each, with how it will be checked>
  Options: <each with its cost and risk; in place of Alternatives>
  Revalidate: <the evidence this decision makes STALE>
  Reversal plan: <how it would be undone>
  Review when: <the condition or date that reopens it>
-->

## D-001 · <date> · <title>
Decision: <what was decided>
Why: <the reason>
Alternatives: <what else was considered>
Source: [owner <date>] "<the owner's words>" | [proposed]
Affects: <IDs: C-xx, L-xx, M<k>, interfaces>
Supersedes: <D-xxx or none>
