# tally

## Map
- tally/cli.py · the command line
- tally/ledger.py · the expenses recorded, and their totals
- tally/store.py · the data file (expenses.json)
- tally/money.py · amounts: parsed, kept in cents, shown
- tally/dates.py · days

## Commands
test: python3 -m unittest discover -s tests
run: python3 -m tally
demo: python3 -m tally

## Conventions
Plain standard library only. Amounts are whole cents everywhere; only money.py turns them into text.
