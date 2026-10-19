# tally

## Goal
Keep a record of expenses and see what each category costs, with a CSV copy and a file per month for the records, each reading back exactly as recorded.

## Done when
- [ ] After `add food 5 --on 2026-09-03`, `add travel 40 --on 2026-09-10`, and `add food 7.5 --on 2026-09-20`, `python3 -m tally total food` prints "Total food: 12.50"
- [ ] `python3 -m tally export` prints "day,category,amount", then one line per expense in the order recorded, and every line reads back as recorded through a CSV reader (a category may hold a comma, a double quote, or a line break)
- [ ] After `add food 3 --on 2026-10-01`, `python3 -m tally archive 2026-09` prints "archived 3 expense(s) to archive/2026-09.csv", and that file holds the header and the three September expenses only
- [ ] An amount below zero is refused (exit 2) and nothing is recorded; zero is accepted
- [ ] When expenses.json cannot be read, every command (add, total, export, archive) prints an error naming the file, exits 2, and leaves the file as it was

## Not doing
- budgets (not asked for)
- escaping spreadsheet formulas in the CSV (the owner reads the files as text, and a CSV must read back exactly as recorded)

## Commands
- run: python3 -m tally
- test: python3 -m unittest discover -s tests
- build:
- deploy:

## Map
- tally/cli.py: the command line
- tally/store.py: the data file (expenses.json)
- tally/money.py: amounts: parsed, kept in cents, shown
- tally/export.py: expenses as CSV
- tally/archive.py: one CSV file per month

## Notes
- 2026-10-18: the last review found three problems, fixed in this change: a category holding a comma, a quote, or a line break broke the CSV; a negative amount was accepted; add overwrote an unreadable expenses.json

## Progress
Started at: <commit>
Verified at: none

## Next
- /gate-fast on the fixes

## Open
<!-- leftovers after verification, small known issues -->
