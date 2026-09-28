# Intent

Status: draft

## Goal
Two flatmates see who owes whom after sharing costs. CANARY-INTENT-4417

## Identity and promise
Settling up without an argument.

## Who
Persona (blind): an adult comfortable with a terminal.
Two people splitting rent, groceries, and utilities.

## Load-bearing behavior
After any set of shared expenses, the tool states one transfer that settles everything.

## Done examples
- I-D1 When A pays 30 for both and B pays 10 for both, the tool says B owes A 10. Example: add A 30, add B 10 → "B owes A 10.00"

## Mechanism cards
### Settle
Purpose: one clear transfer.
Observable guarantee: the transfer equals half the difference of what each paid.
Rejected imitation: listing totals and leaving the arithmetic to the people.
Discriminating probe: unequal payments; the stated transfer must be half the difference.

## Must not lose
- L-01 Deleting an expense says whether it can be restored · check: read the delete help, delete, try to restore

## Re-freeze log
