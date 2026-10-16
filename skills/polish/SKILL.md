---
name: polish
description: "Optional outside-in scrutiny of a finished product before real users or investors see it, through the users, market, investor, or expert lens, or all: finds what would make it fail or fall flat, with evidence, and routes real defects to /fix or a milestone. Typed by the owner; not part of the build loop, and skipped for a CLI, a library, or a personal tool."
argument-hint: "[users | market | investor | expert | all]"
disable-model-invocation: true
---

**Workflow choice, first.** Run `python3 ~/.claude/skills/_shared/scripts/project_policy.py status <project> --json`. OFF or no choice: do the requested work directly from the existing documents, code, and tests, with no formal step, record, or End chain. ON: the rules below apply; recheck the choice before each next step. Only the owner's explicit on or off, through /pipeline, changes it. Contract: `~/.claude/skills/_shared/references/project-control.md`.

# /polish

Judgment over volume: a few real, specific findings beat a quota of manufactured ones. This is product
scrutiny, not code review: correctness, wiring, and intent fidelity belong to the gate.

## Steps
1. **Frame**: what the product is, who it is for, the bar it must clear (`docs/project/intent.md`, the README,
   a venture project's narrative lock). Choose the lenses that apply and skip the rest.
2. **One instrument per lens**, run one at a time:
   - real users: the `user-persona-tester` agent drives the product in a browser as several realistic people;
   - market: the `market-mapper` agent, with current sources and dates;
   - skeptical investor: the `investor-stress-tester` agent;
   - domain expert: the `devils-advocate` agent on the product's central claim.
   Each gets the product (how to run it, or the live URL), the intent's goal and persona, and nothing about
   how it was built.
3. **Synthesize**: what would actually stop a user or a deal, with its evidence, against what is nice to have;
   what the product does well, stated plainly (a venture project classifies findings through `/strategist`).
   Real defects go to `/fix` or into a milestone; a finding that questions the intent goes to the owner, never
   quietly into the plan. Write `docs/project/research/polish-<date>.md`.

## End
`python3 ~/.claude/skills/_shared/scripts/project_status.py record <project> --skill polish --outcome "<one line>"`, then close the report with the Next line it prints (`project-control.md`, End).
