# Intent

Status: frozen

## Goal
Keep a record of expenses and see what each category costs, overall and month by month.

## Identity and promise
The expense notebook that never loses a line.

## Who
Persona (blind): an adult comfortable with a terminal.
Someone who logs spending by category and looks back at it at the end of each month.

## Load-bearing behavior
A category's total is the sum of that category's expenses, in every view, and nothing already recorded is ever lost.

## Done examples
- I-D1 When expenses in two categories exist, the total of one category is the sum of only its expenses. Example: add food 5, add travel 40, add food 7.5 -> "Total food: 12.50"
- I-D2 If the data file is unreadable, the tool says so, exits non-zero, and leaves the file untouched. Example: expenses.json holds "{broken" -> "error: cannot read expenses.json ..." exit 2, file unchanged
- I-D3 When expenses fall in two months, the monthly report shows what each category cost in each month, oldest month first. Example: food 5 on 2026-09-03, travel 40 on 2026-09-10, food 7.50 on 2026-09-20, food 3 on 2026-10-01 -> "2026-09 food 12.50", "2026-09 travel 40.00", "2026-10 food 3.00"

## Mechanism cards
### Totals
Purpose: a category's cost at a glance.
Observable guarantee: a total changes only with that category's entries.
Rejected imitation: one grand total over every expense, shown under the category's name.
Discriminating probe: two categories with different amounts; each total must differ.

## Must not lose
- L-01 A file that cannot be read is never overwritten · check: corrupt the file, run add, the file is unchanged
- L-02 Every amount shows as it was entered, to the cent, in every view · check: add 1,250 and 0.99, then total, export, and report show 1,250.00 and 0.99

## Design intent
none

## Assumptions
- A-01 one person, one folder · signed 2026-09-20

## Re-freeze log
