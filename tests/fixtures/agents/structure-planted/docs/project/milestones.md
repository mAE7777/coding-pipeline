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

## M2 · Monthly report
Status: gate
Promise: A person sees what each category cost in each month, oldest month first.
Carries: I-D3
Mechanisms: Totals

Demo ending:
1. In an empty folder run `python3 -m tally report` -> "no expenses yet"
2. Run add food 5 --on 2026-09-03, add travel 40 --on 2026-09-10, add food 7.50 --on 2026-09-20, add food 3 --on 2026-10-01, then report -> three lines: "2026-09 food 12.50", "2026-09 travel 40.00", "2026-10 food 3.00"
3. Run add rent 1250 --on 2026-10-01, then report -> the last line is "2026-10 rent 1,250.00"
4. Write "{broken" into expenses.json and run report -> an error naming the file, exit 2, the file still holds "{broken"

In scope:
- the report command

Named non-goals:
- budgets (reason: M3)
- months with no expenses (reason: the owner wants only months that have spending)

Parked:
- none

Done examples:
- M2.D1 When expenses fall in two months, report shows each month's total per category, oldest month first and categories in alphabetical order within a month. Example: see demo step 2
- M2.D2 When a month's total reaches a thousand, report shows it the way the tool shows every amount. Example: see demo step 3
- M2.D3 If the file is unreadable, report refuses and keeps it. Example: see demo step 4

Checkpoints:
- none

Interfaces: none

Steal: none

Wiring:
| Component | Producer / trigger | Consumer | Visible effect | Failure state | Test | Status |
|---|---|---|---|---|---|---|
| report command | the command line | the data file | one line per month and category | error on unreadable file | tests/test_report.py | proven |

AI evals: none

Readiness: built [x] · gate-passed [ ] · accepted [ ] · released [ ] · live-verified [ ]
Real-use needs: none

## M3 · Budgets
Status: planned
Promise: A person sets a monthly budget for a category and sees when a month goes over it.
