# Milestones

## M1 · Import and total
Status: building
Promise: A person imports their bank's CSV or OFX export and sees one category's total; nothing imported is lost or counted twice.
Carries: I-D1, I-D2
Mechanisms: Durable record

Demo ending:
1. In an empty folder run `python3 tally.py import march.csv` -> "imported 3 expenses"
2. Run `python3 tally.py import march.ofx` -> "imported 3 expenses"
3. Run `python3 tally.py total food` -> the sum of the food rows of both files
4. Run `python3 tally.py import march.csv` again -> "imported 0 expenses (3 already recorded)"

In scope:
- import (CSV and OFX), total

Named non-goals:
- editing an imported expense (reason: a later milestone)

Parked:
- none

Done examples:
- M1.D1 When march.csv is imported, each of its rows becomes one expense. Example: see demo step 1
- M1.D2 When march.ofx is imported, each of its transactions becomes one expense. Example: see demo step 2
- M1.D3 When the same file is imported again, nothing is added. Example: see demo step 4
- M1.D4 When an import says "imported N expenses", those expenses are already saved in expenses.json. Example: stop the process right after the message of demo step 1; expenses.json holds the 3 rows

Checkpoints:
- none

Interfaces: none

Steal: none

Wiring:
| Component | Producer / trigger | Consumer | Visible effect | Failure state | Test | Status |
|---|---|---|---|---|---|---|
| import command | the command line | expenses.json | "imported N expenses" | error on an unreadable file | planned | planned |
| total command | the command line | expenses.json | "Total <category>: <n>" | error on an unreadable file | planned | planned |

AI evals: none

Readiness: built [ ] · gate-passed [ ] · accepted [ ] · released [ ] · live-verified [ ]
Real-use needs: none
