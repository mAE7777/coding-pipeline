# tally

## Goal
Keep a record of expenses and see what each category costs, overall and month by month.

## Done when
- [ ] In an empty folder, `python3 -m tally report` prints "no expenses yet"
- [ ] After `add food 5 --on 2026-09-03`, `add travel 40 --on 2026-09-10`, `add food 7.50 --on 2026-09-20`, and `add food 3 --on 2026-10-01`, `python3 -m tally report` prints "2026-09 food 12.50", "2026-09 travel 40.00", "2026-10 food 3.00": oldest month first, categories in alphabetical order within a month
- [ ] After `add rent 1250 --on 2026-10-01`, the last line of `report` is "2026-10 rent 1,250.00": amounts show the way the tool shows every amount
- [ ] When expenses.json cannot be read, `report` prints an error naming the file, exits 2, and leaves the file as it was

## Not doing
- budgets (they come next)
- months with no expenses (the owner wants only months that have spending)

## Commands
- run: python3 -m tally
- test: python3 -m unittest discover -s tests
- build:
- deploy:

## Map
- tally/cli.py: the command line
- tally/ledger.py: the expenses recorded, and their totals
- tally/store.py: the data file (expenses.json)
- tally/money.py: amounts: parsed, kept in cents, shown (only money.py turns cents into text)
- tally/dates.py: days

## Notes
<!-- one line each, dated: decisions, research answers (source + date), the owner's rulings -->

## Progress
Started at: <commit>
Verified at: none

## Next
- /gate-fast

## Open
<!-- leftovers after verification, small known issues -->
