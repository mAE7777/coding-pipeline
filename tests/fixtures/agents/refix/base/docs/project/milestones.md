# Milestones

## M1 · Record, total, export, and archive
Status: changes
Promise: A person records expenses by day and category, sees one category's total, prints every expense as CSV, and archives a month to a CSV file; an unreadable file is reported, never lost.
Carries: I-D1, I-D2, I-D3
Mechanisms: Totals

Demo ending:
1. In an empty folder run `python3 -m tally total food` -> "Total food: 0.00"
2. Run add food 5 --on 2026-09-03, add travel 40 --on 2026-09-10, add food 7.5 --on 2026-09-20, then total food -> "Total food: 12.50"
3. Run export -> "day,category,amount" and three lines, in the order recorded
4. Run add food 3 --on 2026-10-01, then archive 2026-09 -> "archived 3 expense(s) to archive/2026-09.csv"; the file holds the header and the three September lines
5. Write "{broken" into expenses.json and run add food 1 -> an error naming the file, exit 2, the file still holds "{broken"

In scope:
- add, total, export, archive

Named non-goals:
- budgets (reason: not asked for)
- escaping spreadsheet formulas in the CSV (reason: the owner reads the files as text, and a CSV must read back exactly as recorded)

Parked:
- none

Done examples:
- M1.D1 When food and travel expenses exist, total food sums only food. Example: see demo step 2
- M1.D2 When export runs, it prints the header and every expense as a CSV line that reads back as recorded. Example: see demo step 3
- M1.D3 When a month is archived, its file holds the header and that month's expenses only. Example: see demo step 4
- M1.D4 If the file is unreadable, every command refuses and keeps it. Example: see demo step 5

Checkpoints:
- none

Interfaces: none

Steal: none

Wiring:
| Component | Producer / trigger | Consumer | Visible effect | Failure state | Test | Status |
|---|---|---|---|---|---|---|
| add command | the command line | the data file | "added ..." | error on unreadable file or bad input | tests/test_tally.py | proven |
| total command | the command line | the data file | "Total <category>: <n>" | error on unreadable file | tests/test_tally.py | proven |
| export command | the command line | the data file | CSV on stdout | error on unreadable file | tests/test_tally.py | proven |
| archive command | the command line | the data file, the archive folder | "archived N expense(s) to ..." and the file | error on unreadable file or bad month | tests/test_tally.py | proven |

AI evals: none

Readiness: built [x] · gate-passed [ ] · accepted [ ] · released [ ] · live-verified [ ]
Real-use needs: none

## M2 · Monthly report
Status: planned
Promise: A person sees what each category cost in each month.
