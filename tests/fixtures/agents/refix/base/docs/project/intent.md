# Intent

Status: frozen

## Goal
Keep a record of expenses and see what each category costs, with a CSV copy and a file per month for the records, each reading back exactly as recorded.

## Identity and promise
The expense notebook that never loses a line.

## Who
Persona (blind): an adult comfortable with a terminal.
Someone who logs spending by category, checks a category's total, and keeps each month's expenses as a CSV file.

## Load-bearing behavior
A category's total is the sum of that category's expenses, every CSV the tool writes reads back as what was recorded, and nothing already recorded is ever lost.

## Done examples
- I-D1 When expenses in two categories exist, the total of one category is the sum of only its expenses. Example: add food 5, add travel 40, add food 7.5 -> "Total food: 12.50"
- I-D2 If the data file is unreadable, the tool says so, exits non-zero, and leaves the file untouched. Example: expenses.json holds "{broken" -> "error: cannot read expenses.json ..." exit 2, file unchanged
- I-D3 When a month is archived, its file holds a header line and one CSV line per expense of that month, and reads back as those expenses. Example: food 5 on 2026-09-03 and food 3 on 2026-10-01, archive 2026-09 -> archive/2026-09.csv holds "day,category,amount" and "2026-09-03,food,5.00"

## Mechanism cards
### Totals
Purpose: a category's cost at a glance.
Observable guarantee: a total changes only with that category's entries.
Rejected imitation: one grand total over every expense, shown under the category's name.
Discriminating probe: two categories with different amounts; each total must differ.

## Must not lose
- L-01 A file that cannot be read is never overwritten · check: corrupt the file, run add, the file is unchanged
- L-02 What a CSV holds is what was recorded: every category and amount reads back unchanged · check: export and archive categories holding a comma, a quote, and a line break, then read them with a CSV reader

## Design intent
none

## Assumptions
- A-01 one person, one folder · signed 2026-09-20

## Re-freeze log
