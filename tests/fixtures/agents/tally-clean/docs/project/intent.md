# Intent

Status: draft

## Goal
Keep a running record of expenses and see what one category costs.

## Identity and promise
The expense notebook that never loses a line.

## Who
Persona (blind): an adult comfortable with a terminal.
Someone who logs spending by category and checks a category's total at the end of the week.

## Load-bearing behavior
A category's total is the sum of that category's expenses, and nothing already recorded is ever lost.

## Done examples
- I-D1 When expenses in two categories exist, the total of one category is the sum of only its expenses. Example: add food 5, add travel 40, add food 7.5 → "Total food: 12.50"
- I-D2 If the data file is unreadable, the tool says so, exits non-zero, and leaves the file untouched. Example: expenses.json holds "{broken" → "error: cannot read expenses.json ..." exit 2, file unchanged

## Mechanism cards
### Totals
Purpose: a category's cost at a glance.
Observable guarantee: the total changes only with that category's entries.
Rejected imitation: one grand total over every expense, shown under the category's name.
Discriminating probe: two categories with different amounts; each total must differ.

## Must not lose
- L-01 A file that cannot be read is never overwritten · check: corrupt the file, run add, the file is unchanged
- L-02 No invented expenses appear · check: on a fresh folder, total food is 0.00

## Design intent
none

## Assumptions
- A-01 one person, one folder · signed 2026-09-27

## Re-freeze log
