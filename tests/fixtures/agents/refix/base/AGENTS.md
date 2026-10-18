# tally

## Map
- tally/cli.py · the command line
- tally/store.py · the data file (expenses.json)
- tally/money.py · amounts: parsed, kept in cents, shown
- tally/export.py · expenses as CSV
- tally/archive.py · one CSV file per month

## Commands
test: python3 -m unittest discover -s tests
run: python3 -m tally
demo: python3 -m tally

## Conventions
Plain standard library only. Amounts are whole cents everywhere.
