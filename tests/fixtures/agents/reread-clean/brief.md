# Brief: book loans

## Goal
One person keeps track of the books they lend to friends.

## Constraints
| ID | Rule | Reason | Source | Status |
|---|---|---|---|---|
| C-01 | All data stays in one local file, loans.json | no accounts, no server | [owner 2026-10-03] | active |
| C-02 | Only the Python standard library | no install step | [owner 2026-10-03] | active |

## Done examples
- I-D1 When a book is lent, `python3 loans.py lend "Dune" Sam` records it with today's date and prints `lent Dune to Sam, due 2026-10-17` (on 2026-10-03).
- I-D2 When a loan is past its due date (14 days after the loan, unless `--due YYYY-MM-DD` was given when lending), `python3 loans.py list` marks it OVERDUE.
- I-D3 When a book comes back, `python3 loans.py return "Dune"` prints `Dune is back from Sam`, and `python3 loans.py list` no longer shows it.

## Named non-goals
- Syncing loans to the borrower's phone (reason: one person, one computer; see C-01)

## Milestones
### M1 · Lend and list
Promise: a person records the books they lend and sees which loans are overdue.
Carries: I-D1, I-D2, I-D3
Demo ending:
1. `python3 loans.py lend "Dune" Sam` -> `lent Dune to Sam, due <today plus 14 days>`
2. `python3 loans.py lend "Emma" Ana --due 2026-01-01`, then `python3 loans.py list` -> both loans listed, Emma marked OVERDUE
3. `python3 loans.py return "Dune"` -> `Dune is back from Sam`; then `python3 loans.py list` -> only Emma
Named non-goals: lending to more than one borrower at once (reason: not asked for)
