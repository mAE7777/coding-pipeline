# Milestones

## M1 · Record and total
Status: gate
Promise: A person records expenses and sees one category's total; an unreadable file is reported, never lost.
Carries: I-D1, I-D2
Mechanisms: Totals

Demo ending:
1. In an empty folder run `python3 app.py total food` → "Total food: 0.00"
2. Run add food 5, add travel 40, add food 7.5, then total food → "Total food: 12.50"
3. Run export → CSV with a header and three lines
4. Write "{broken" into expenses.json and run add food 1 → an error naming the file, exit 2, the file still holds "{broken"

In scope:
- add, total, export

Named non-goals:
- budgets (reason: not asked for)

Parked:
- none

Done examples:
- M1.D1 When food and travel expenses exist, total food sums only food. Example: see demo step 2
- M1.D2 If the file is unreadable, the tool refuses and keeps it. Example: see demo step 4
- M1.D3 When export runs, every expense prints as a CSV line. Example: see demo step 3

Checkpoints:
- none

Interfaces: none

Steal: none

Wiring:
| Component | Producer / trigger | Consumer | Visible effect | Failure state | Test | Status |
|---|---|---|---|---|---|---|
| add command | the command line | the data file | "added ..." | error on unreadable file | tests/test_app.py | proven |
| total command | the command line | the data file | "Total <category>: <n>" | error on unreadable file | none | proven |
| export command | the command line | the data file | CSV on stdout | error on unreadable file | none | proven |

AI evals: none

Readiness: built [x] · gate-passed [ ] · accepted [ ] · released [ ] · live-verified [ ]
Real-use needs: none
