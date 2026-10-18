# Intent

Status: frozen

## Goal
Keep a record of expenses, typed in or imported from the bank, and see what each category costs.

## Identity and promise
The expense notebook that never loses a line.

## Who
Persona (blind): an adult comfortable with a terminal.
Someone who logs spending by category, and at the end of the month brings in what the bank recorded instead of typing it.

## Load-bearing behavior
A category's total is the sum of that category's expenses, and nothing recorded or imported is ever lost or counted twice.

## Done examples
- I-D1 When expenses in two categories exist, the total of one category is the sum of only its expenses. Example: add food 5, add travel 40, add food 7.5 -> "Total food: 12.50"
- I-D2 If the data file is unreadable, the tool says so, exits non-zero, and leaves the file untouched. Example: expenses.json holds "{broken" -> "error: cannot read expenses.json ..." exit 2, file unchanged
- I-D3 When a bank statement is imported, each of its spending lines becomes one expense, categorized by the person's rules. Example: a statement with four purchases and one salary payment -> four expenses, "imported 4 expense(s) ... 1 income line(s) skipped"

## Mechanism cards
### Totals
Purpose: a category's cost at a glance.
Observable guarantee: a total changes only with that category's entries.
Rejected imitation: one grand total over every expense, shown under the category's name.
Discriminating probe: two categories with different amounts; each total must differ.

## Must not lose
- L-01 A file that cannot be read is never overwritten · check: corrupt the file, run add and import, the file is unchanged
- L-02 Every amount shows as it was entered or exported by the bank, to the cent · check: import a statement with 1.250,00 and 89,90, then export shows 1,250.00 and 89.90
- L-03 Every spending line of an imported statement is recorded exactly once: none dropped, none doubled · check: import a statement, then compare its spending lines with the expenses recorded, one each

## Design intent
none

## Assumptions
- A-01 one person, one folder · signed 2026-09-20
- A-02 the statements come from Northbank, Riverside Credit Union, and Mono, as their CSV exports · signed 2026-09-29

## Re-freeze log
