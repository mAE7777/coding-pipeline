# Cutting milestones

Loaded by `/plan` when writing `docs/project/milestones.md`. A milestone is a complete product state a real
person can use end to end, proven by a demo they can watch, built as one sustained run, verified at its
gate, accepted by the owner. The format is in the template; `milestone_lint.py` enforces it.

## Laws
- **A demo, not a list.** Each milestone ends with a numbered demo: steps a viewer watches, each with an
  observable result. If you cannot write the demo, the milestone is not a milestone.
- **Rings, not layers.** Each milestone adds a capability ring on top of real earlier ones; a later
  milestone never makes an earlier one real. No "backend milestone" then "frontend milestone".
- **The hard part first.** M1 carries the load-bearing mechanism, built for real. A product that
  integrates many parts starts with a walking skeleton through every layer with the hard mechanism real
  inside it.
- **First consumer.** Cross-cutting obligations (security, consent, deletion and export, languages,
  accessibility, observability) ship with the first milestone that needs them, never in a later
  hardening milestone.
- **Carried examples.** Each milestone names the product-level done examples (I-Dn) it carries and the
  mechanism cards it exercises; together the milestones carry every I-Dn, or an example is a named non-goal
  with a reason. The gate scores a milestone on what it carries plus every must-not-lose item.
- **One sustained run.** One builder can hold the contract and finish it in one run. A small tool is one
  milestone; a product is usually two to five.
- **No "later".** Everything is in a milestone, a named non-goal with a reason, or blocked by a named
  contract. Parked code is unreachable and names its purpose, its re-enable condition, and the milestone
  that owns it.

## Checkpoints (0 to 3 per milestone)
A checkpoint marks a load-bearing boundary where later work depends on something being right: a schema
every screen reads, a sync protocol, an auth boundary. Each has one targeted, mostly deterministic check
run before dependents are built (`M1.C1 storage schema · why here: every screen reads it · check: pytest
tests/test_store.py`). The builder's ordinary task list lives in `state.md` and is never gated.

## The wiring table
One row per component the milestone introduces: producer or trigger, consumer, visible effect, failure
state, test, status (built, validated, wired, proven, parked). At the gate every row is proven or parked,
and the gate compares the table with the code's routes, events, and model calls: anything one-sided is
UNWIRED (built, unreachable), UNCONSUMED (produced, nothing uses it), or PHANTOM (a visible state or claim
with no producing cause).

## AI evals
When a promise depends on model output quality, the milestone declares an eval: a development set the
builder may see, a holdout it never sees (its path goes in `gate.md` under "Holdout", outside the
project), a strong baseline, scoring by constructed truth or blind comparison, and thresholds fixed before
results. Unit tests never certify semantic quality. Without live model access the eval is NOT_RUN and the
milestone can be built but not called ready for real use.

## Readiness
`built · gate-passed · accepted · released · live-verified`, plus the real-world evidence the milestone
still needs ("real-use needs"). These are different words for different facts: never collapse them.

## The cut, shown to the owner
The recommended cut and the strongest alternative, each with what the person can do after each milestone,
how it is built, and why that order. The owner picks or corrects at the lock.
