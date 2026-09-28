# Milestones

<!--
Format rules (checked by milestone_lint.py):
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

## M1 · <name>
Status: planned
Promise: <what a person can now do, in their words>
Carries: <I-D1, I-D2 from intent.md, or none>
Mechanisms: <mechanism card names from intent.md, or none>

Demo ending:
1. <step the viewer watches> → <observable result>
2. <step> → <result>

In scope:
- <capability>

Named non-goals:
- <thing> (reason: <one clause>)

Parked:
- none

Done examples:
- M1.D1 When <trigger>, <observable result>. Example: <real input> → <real output>
- M1.D2 If <failure>, the user sees <honest state>. Example: <real input> → <real output>

Checkpoints:
- M1.C1 <boundary> · why here: <what depends on it> · check: `<command or probe>`

Interfaces: <introduced or changed, with anchors into interfaces.md>

Steal: none

Wiring:
| Component | Producer / trigger | Consumer | Visible effect | Failure state | Test | Status |
|---|---|---|---|---|---|---|
| <component> | <what triggers it> | <what uses it> | <what the user sees> | <what the user sees when it fails> | <test path> | built |

AI evals: none

Readiness: built [ ] · gate-passed [ ] · accepted [ ] · released [ ] · live-verified [ ]
Real-use needs: <real-world evidence required beyond the gate, or "none">

<!--
When an upstream idea anchor exists, the file ends with its closure: every anchor item in one of three
states. A product with blueprint parts adds "Parts: [P1] [P3]" under each milestone's Mechanisms line.

## Idea-anchor closure
| Item | What it is | Where it lives |
|---|---|---|
| K1 | <anchor item> | IN-MILESTONE @M1 |
| K2 | <anchor item> | named non-goal (<reason>) |
| K3 | <anchor item> | contract-blocked @<decision or contract entry> |
-->
