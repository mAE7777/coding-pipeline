# tally

## Goal
Keep a running record of expenses and see what one category costs, in "the expense notebook that never loses a line"

## Done when
- [ ] In an empty folder, `python3 app.py total food` prints "Total food: 0.00"
- [ ] After `python3 app.py add food 5`, `add travel 40`, and `add food 7.5`, `python3 app.py total food` prints "Total food: 12.50"
- [ ] `python3 app.py export` prints every expense as CSV: a header, then one line per expense
- [ ] When expenses.json cannot be read (it holds "{broken"), `python3 app.py add food 1` prints an error naming the file, exits 2, and leaves the file as it was

## Not doing
- budgets (not asked for)

## Commands
- run: python3 app.py
- test: python3 -m unittest discover -s tests
- build:
- deploy:

## Notes
<!-- one line each, dated: decisions, research answers (source + date), the owner's rulings -->

## Progress
Started at: <commit>
Verified at: none

## Next
- /gate-fast

## Open
<!-- leftovers after verification, small known issues -->
