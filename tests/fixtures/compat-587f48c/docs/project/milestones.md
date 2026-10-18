# Milestones

<!--
Format rules (checked automatically):
- One "## M<n> · <name>" section per milestone. IDs are never renumbered or deleted; a dropped
  milestone keeps its section with "Status: dropped" and a reason.
- Status is one of: planned, building, gate, changes, accepted, dropped. Who sets it: the builder sets
  building and gate; the gate report sets changes; only an owner acceptance recorded in decisions.md
  allows accepted. Release is tracked in the Readiness line.
- Every milestone has a Promise, a numbered Demo ending, a Carries line (the intent.md done examples
  it carries, or "none"), a Mechanisms line (the intent.md mechanism cards it exercises, or "none"), at
  least one done example (M<n>.D<k>), and a Readiness line. Checkpoints are M<n>.C<k>.
- Every I-Dn in intent.md is carried by at least one milestone or named as a non-goal.
- Wiring rows carry a status: built, validated, wired, proven, or parked. At the gate every row is
  proven or parked.
- An accepted milestone's contract (Promise, Carries, Demo ending, Done examples) is hashed in its
  acceptance entry in decisions.md; it changes only with a "Superseded: D-<nnn>" line naming the
  owner's ruling.
- A parked item names its purpose, a re-enable condition, and the milestone that owns it.
- "later", "v2", "future", "TBD" are not states. Something is in a milestone, a named non-goal with a
  reason, or blocked by a named contract.
-->

## M1 · Add and show
Status: gate
Promise: A person adds an item and sees it.
Carries: I-D1
Mechanisms: Store

Demo ending:
1. Run the add command with milk → it prints 1. milk

In scope:
- add and show

Named non-goals:
- sync (reason: one device)

Parked:
- none

Done examples:
- M1.D1 When milk is added, it prints. Example: add milk → "1. milk"

Checkpoints:
- none

Interfaces: none

Steal: none

Wiring:
| Component | Producer / trigger | Consumer | Visible effect | Failure state | Test | Status |
|---|---|---|---|---|---|---|
| add command | the command line | the store | the printed list | an error line | test_app.py | proven |

AI evals: none

Readiness: built [x] · gate-passed [ ] · accepted [ ] · released [ ] · live-verified [ ]
Real-use needs: none


## M2 · Remove an item
Status: planned
Promise: A person removes an item.
Carries: none
Mechanisms: none

Demo ending:
1. Run the remove command with milk → the list is empty

In scope:
- remove

Named non-goals:
- undo (reason: one step is enough)

Parked:
- none

Done examples:
- M2.D1 When milk is removed, the list is empty. Example: remove milk → "(empty)"

Checkpoints:
- none

Interfaces: none

Steal: none

AI evals: none

Readiness: built [ ] · gate-passed [ ] · accepted [ ] · released [ ] · live-verified [ ]
Real-use needs: none
