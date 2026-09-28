# Brief: shared grocery list

## Goal
Two people in one household keep one grocery list on their own phones.

## Constraints
| ID | Rule | Reason | Source | Status |
|---|---|---|---|---|
| C-01 | The app works fully offline; no edit ever waits on the network | subway commutes | [owner 2026-09-20] | active |
| C-02 | Every edit is confirmed by the server before it is shown as saved | avoid lost edits | [owner 2026-09-21] | active |

## Done examples
- I-D1 When one person adds an item, the other person sees it quickly.
- I-D2 When a person deletes the list, the list is removed.
- I-D3 If both people edit the same item, the right version wins.

## Milestones
- M1: adding and seeing items on both phones.
- M2: the rest.
