# Milestones

## M1 · Record, total, and report
Status: gate
Promise: A person records expenses, sees one category's total on screen or as JSON, and saves a CSV report; an unreadable file is reported, never lost.
Carries: I-D1, I-D2
Mechanisms: Totals

Demo ending:
1. In an empty folder run `python3 app.py total food` -> "Total food: 0.00"
2. Run add food 5, add travel 40, add food 7.5, then total food -> "Total food: 12.50"
3. Run `python3 app.py export --out report.csv` -> report.csv exists and holds a header and three lines
4. Run `python3 app.py total food --json` -> prints {"category": "food", "total": 12.5}
5. Write "{broken" into expenses.json and run add food 1 -> an error naming the file, exit 2, the file still holds "{broken"

In scope:
- add, total (on screen and as JSON), export (to the screen or to a file)

Named non-goals:
- budgets (reason: not asked for)

Parked:
- none

Done examples:
- M1.D1 When food and travel expenses exist, total food sums only food. Example: see demo step 2
- M1.D2 If the file is unreadable, the tool refuses and keeps it. Example: see demo step 5
- M1.D3 When export runs with --out, the file holds every expense as a CSV line. Example: see demo step 3
- M1.D4 When total runs with --json, it prints the category and its total as JSON. Example: see demo step 4

Checkpoints:
- none

Interfaces: none

Steal: none

Wiring:
| Component | Producer / trigger | Consumer | Visible effect | Failure state | Test | Status |
|---|---|---|---|---|---|---|
| add command | the command line | the data file | "added ..." | error on unreadable file | tests/test_app.py | proven |
| total command | the command line | the data file | "Total <category>: <n>" or JSON | error on unreadable file | tests/test_app.py | proven |
| export command | the command line | the data file | CSV on stdout or in the --out file | error on unreadable file | tests/test_app.py | proven |

AI evals: none

Readiness: built [x] · gate-passed [ ] · accepted [ ] · released [ ] · live-verified [ ]
Real-use needs: none
