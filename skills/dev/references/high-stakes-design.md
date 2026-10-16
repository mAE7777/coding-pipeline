# High-stakes design

Loaded by `/dev` when the design intent says the design is high-stakes, or the owner asks for it.

The look of a whole page or site goes through `/atelier`, its single entry, which drives `/taste-design`
itself; a single component, or a judgment of a screen that exists, goes to `/taste-design` directly. Hand
either one the design intent, the milestone contract, and
`~/.claude/skills/gate/references/interface-baseline.md` as constraints.

What comes back enters this project, not the design station: the treatment the owner approved is recorded
as a decision in their words (`decisions.py add --source-owner`), the built code is ported into the product
under this milestone, and it answers to the contract, the wiring table, and the clarity pass like any other
code. Their own verifiers and juries add to the gate; they never replace it.
