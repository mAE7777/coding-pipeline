# tally

## Goal
Keep a record of expenses and see each month whether a category stayed within its budget, in the owner's words "I set what food may cost a month, and the status tells me when a month went over"

## Done when
- [ ] `python3 -m tally budget food 100` sets food's budget to 100.00 a month, kept in budgets.json; setting it again replaces it
- [ ] `python3 -m tally status 2026-09` shows, for each budgeted category, what it cost in that month against its budget. Example: after `add food 5 --on 2026-09-03`, `add travel 40 --on 2026-09-10`, `add food 7.50 --on 2026-09-20`, `budget food 100`, and `budget travel 30`, `status 2026-09` prints "food 12.50 of 100.00" and "travel 40.00 of 30.00  over"
- [ ] A category whose spending in the month went over its budget is marked "over" in status
- [ ] When budgets.json cannot be read, `budget` and `status` print an error naming the file, exit 2, and leave the file as it was

## Not doing
- weekly or yearly budgets (the owner budgets by month)
- alerts beyond the status line (not asked for)

## Commands
- run: python3 -m tally
- test: python3 -m unittest discover -s tests
- build:
- deploy:

## Map
- tally/cli.py: the command line
- tally/ledger.py: the expenses recorded, and their totals
- tally/store.py: the data file (expenses.json)
- tally/money.py: amounts: parsed, kept in cents, shown
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
