# Milestones

## M1 · Record and total
Status: accepted
Promise: A person records expenses by day and category and sees one category's total; an unreadable file is reported, never lost.
Carries: I-D1, I-D2
Mechanisms: Totals

Demo ending:
1. In an empty folder run `python3 -m tally total food` -> "Total food: 0.00"
2. Run add food 5, add travel 40, add food 7.5, then total food -> "Total food: 12.50"
3. Run export -> CSV with a header and three lines
4. Write "{broken" into expenses.json and run add food 1 -> an error naming the file, exit 2, the file still holds "{broken"

Done examples:
- M1.D1 When food and travel expenses exist, total food sums only food. Example: see demo step 2
- M1.D2 If the file is unreadable, the tool refuses and keeps it. Example: see demo step 4
- M1.D3 When export runs, every expense prints as a CSV line. Example: see demo step 3

Interfaces: none

Wiring:
| Component | Producer / trigger | Consumer | Visible effect | Failure state | Test | Status |
|---|---|---|---|---|---|---|
| add command | the command line | the data file | "added ..." | error on unreadable file or bad input | tests/test_tally.py | proven |
| total command | the command line | the data file | "Total <category>: <n>" | error on unreadable file | tests/test_tally.py | proven |
| export command | the command line | the data file | CSV on stdout | error on unreadable file | tests/test_tally.py | proven |

Readiness: built [x] · gate-passed [x] · accepted [x] · released [ ] · live-verified [ ]

## M2 · Import a bank statement
Status: gate
Promise: A person brings a bank's CSV statement in, and each spending line becomes an expense in the category their rules give it, once, however often the statement is imported.
Carries: I-D3
Mechanisms: Totals

Demo ending:
1. In an empty folder write rules.txt holding the lines `coffee -> food`, `freshmart -> food`, `shell -> travel`, `transit -> travel`, `rent -> rent`; run `python3 -m tally import <project>/tests/statements/northbank-2026-09.csv` -> "imported 4 expense(s) from the northbank statement (0 already recorded, 1 income line(s) skipped)"
2. Run export -> four lines: 2026-09-02 food 3.50, 2026-09-05 travel 61.20, 2026-09-12 food 48.75, 2026-09-20 food 3.50
3. Run the same import again -> "imported 0 expense(s) ... (4 already recorded, ...)", and export is unchanged
4. Import tests/statements/riverside-2026-09.csv and tests/statements/mono-2026-09.csv -> export adds 2026-09-01 rent 1,250.00, 2026-09-18 uncategorized 89.90, 2026-09-04 travel 2.90, 2026-09-11 uncategorized 11.50
5. Import a Northbank statement whose third line has the date 31/09/2026 -> "error: ... line 3: ..." exit 2, export unchanged

In scope:
- the import command for Northbank, Riverside Credit Union, and Mono CSV statements
- rules.txt: `<text> -> <category>`, first match wins, otherwise uncategorized

Named non-goals:
- other banks (reason: the owner uses only these three)
- editing rules from the command line (reason: a text file is enough)

Parked:
- none

Done examples:
- M2.D1 When a statement from any of the three banks is imported, each spending line becomes one expense with its day, its amount, and its rule's category (uncategorized when no rule matches), and income lines are left out. Example: see demo steps 1, 2 and 4
- M2.D2 When the same statement is imported twice, the second import records nothing. Example: see demo step 3
- M2.D3 If a line of the statement cannot be read, nothing is recorded and the error names the line. Example: see demo step 5

Checkpoints:
- none

Interfaces: none

Steal: none

Wiring:
| Component | Producer / trigger | Consumer | Visible effect | Failure state | Test | Status |
|---|---|---|---|---|---|---|
| import command | the command line, tally/cli.py | the data file, through tally/importer.py | "imported N expense(s) ..." | error naming the statement line; nothing recorded | tests/test_import.py | proven |

AI evals: none

Readiness: built [x] · gate-passed [ ] · accepted [ ] · released [ ] · live-verified [ ]
Real-use needs: none

## M3 · Monthly report
Status: planned
Promise: A person sees what each category cost in each month.
