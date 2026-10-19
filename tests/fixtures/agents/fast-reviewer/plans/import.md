# tally

## Goal
Keep a record of expenses, typed in or imported from the bank, and see what each category costs.

## Done when
- [ ] With rules.txt holding the lines `coffee -> food`, `freshmart -> food`, `shell -> travel`, `transit -> travel`, and `rent -> rent`, `python3 -m tally import tests/statements/northbank-2026-09.csv` prints "imported 4 expense(s) from the northbank statement (0 already recorded, 1 income line(s) skipped)", and `export` then shows 2026-09-02 food 3.50, 2026-09-05 travel 61.20, 2026-09-12 food 48.75, and 2026-09-20 food 3.50
- [ ] Importing the same statement again records nothing: "imported 0 expense(s) ... (4 already recorded, ...)", and export is unchanged
- [ ] Riverside Credit Union and Mono statements import too: after tests/statements/riverside-2026-09.csv and tests/statements/mono-2026-09.csv, export adds 2026-09-01 rent 1,250.00, 2026-09-18 uncategorized 89.90, 2026-09-04 travel 2.90, and 2026-09-11 uncategorized 11.50
- [ ] Every spending line of an imported statement is recorded exactly once: none dropped, none doubled
- [ ] A statement line that cannot be read (a date of 31/09/2026) records nothing, and the error names the line and exits 2

## Not doing
- other banks (the owner uses only these three)
- editing rules from the command line (a text file is enough)

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

## Notes
<!-- one line each, dated: decisions, research answers (source + date), the owner's rulings -->

## Progress
Started at: <commit>
Verified at: none

## Next
- /gate-fast

## Open
<!-- leftovers after verification, small known issues -->
