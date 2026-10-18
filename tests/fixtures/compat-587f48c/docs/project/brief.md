# Brief

<!--
Everything the builder needs to act well that is not the frozen intent. Living: entries are superseded
in place (status column) rather than deleted, and every change of a constraint has a decisions.md entry.
Source labels: [owner <date>] · [research <ref> <grade>] · [environment <date>] · [proposed].
An unlabeled constraint does not bind.
-->

## Goal and why now
One list the owner trusts, so chores stop being forgotten.

## Expectations
- Quality bar: final quality; there is no later pass that makes it real
- What good looks like: a plain list that never loses or reorders an item
- Standing requirements: none
- Non-functional: macOS and Linux

## Constraints
| ID | Rule | Reason | Source | Scope | Change trigger | Status |
|---|---|---|---|---|---|---|
| C-01 | standard library only | nothing to install | [proposed] | all code | a feature that needs a package | active |

## Starting state
<!-- dated, evidenced facts; perishable -->
- an empty folder · checked 2026-10-12 · evidence: ls

## Context index
- docs/project/intent.md · what must be true

## Factors
- none

## Unknowns
- none

## Stop rules
- Ask the owner when: a scope change or a new dependency
- Never without the owner: deleting the list file
