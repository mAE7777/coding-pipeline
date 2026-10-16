# Intent

Status: draft

## Goal
Bring a household's bank transactions into one expense record and see what one category costs.

## Identity and promise
The expense record you fill from your bank's own export, without retyping a line.

## Who
Persona (blind): an adult comfortable with a terminal who downloads bank statements.
Someone who imports each month's bank export and checks a category's total.

## Load-bearing behavior
Every transaction in a bank export becomes exactly one expense, kept safely, and a category's total counts only that category.

## Done examples
- I-D1 When a bank export in CSV or OFX is imported, every transaction becomes one expense. Example: import march.csv (3 rows) -> "imported 3 expenses"; import march.ofx (3 transactions) -> "imported 3 expenses"
- I-D2 When expenses in two categories exist, the total of one category sums only its expenses. Example: food 5, travel 40, food 7.5 -> "Total food: 12.50"

## Mechanism cards
### Durable record
Purpose: nothing imported is ever lost.
Observable guarantee: an import is persisted to expenses.json before "imported N expenses" is printed; a process killed right after the message has lost nothing.
Rejected imitation: expenses held in a cache and written out later (at exit, in the background, or every few imports).
Discriminating probe: import, kill the process right after the message, then read expenses.json: the new rows are there.

## Must not lose
- L-01 An unreadable expenses file is never overwritten · check: corrupt the file, run import, the file is unchanged
- L-02 A transaction already imported is never imported twice · check: import the same file twice, the second import adds 0

## Design intent
none

## Assumptions
- A-01 one person, one folder · signed 2026-10-02

## Re-freeze log
