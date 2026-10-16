# Milestones

## M1 · Record and total in the page
Status: gate
Promise: A person adds expenses in the page and sees the total of what the list shows; an amount that is not a number is refused with a message.
Carries: I-D1, I-D2
Mechanisms: Totals

Demo ending:
1. Run `python3 serve.py` and open the address it prints -> the page shows "No expenses yet" and "Total: 0.00"
2. Add food 5, then travel 40 (choose the category, type the amount, press Add) -> the list shows "food 5.00" and "travel 40.00", and "Total: 45.00"
3. Choose "food" under Show -> the list shows only "food 5.00", and "Total: 5.00"
4. Choose "all" under Show, type "abc" as the amount and press Add -> the message "Enter an amount like 12.50" appears, the list still shows two expenses, and "Total: 45.00"

In scope:
- the page: add an expense, show one category or all, the total of what is shown

Named non-goals:
- keeping expenses between visits (reason: a later milestone)

Parked:
- none

Done examples:
- M1.D1 When the list shows one category, the total sums only that category. Example: see demo step 3
- M1.D2 If the amount is not a number, a message appears and nothing is added. Example: see demo step 4

Checkpoints:
- none

Interfaces: none

Steal: none

Wiring:
| Component | Producer / trigger | Consumer | Visible effect | Failure state | Test | Status |
|---|---|---|---|---|---|---|
| Add form | the Add button | the expense list | a new row, a new total | a message for a bad amount | none | proven |
| Show choice | the Show select | the list and the total | only that category, its total | none | none | proven |

AI evals: none

Readiness: built [x] · gate-passed [ ] · accepted [ ] · released [ ] · live-verified [ ]
Real-use needs: none
