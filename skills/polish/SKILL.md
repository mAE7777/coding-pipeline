---
name: polish
description: "Optional product scrutiny before a real launch: stress-test a finished build from the outside (real-user, market, skeptical-investor, domain-expert perspectives) to find what would make it fail or fall flat. Use this skill when the user says /polish, 'stress test the product', 'is this ready for the real world', 'pressure-test before launch', for a product or startup-track build. NOT part of the coding loop; skip it for a CLI, library, or interest project. Routes findings to /fix or /dev."
argument-hint: "[focus: users | market | investor | all]"
---

# polish — Optional Product Scrutiny

> EXECUTABLE WORKFLOW. Optional and orthogonal to the build loop. Run only when the thing is a
> product going to real users or investors. A code tool or interest project never needs this.

External pressure-testing: simulate the perspectives that decide whether a product survives
contact with the world, and surface concrete weaknesses. Judgment over volume: a few real,
specific findings beat a quota of manufactured ones.

## Workflow

### Stage 1 — Frame
What is this product, who is it for, what bar must it clear (read `intent-anchor.md`, the README,
any startup-track docs). Pick the lenses that apply (real users, market/competition, skeptical
investor, blunt domain expert). Skip the ones that don't.

### Stage 2 — Pressure-test per lens
For each chosen lens, simulate that perspective honestly and find the real weaknesses: where a
real user gets confused or churns, where the market position is weak or undifferentiated, where an
investor's hardest question has no good answer, where a domain expert sees a flaw. Use real
evidence (run the product, real market data via research) over opinion. Don't manufacture findings
to hit a count.

### Stage 3 — Synthesize and route
Collect findings by severity (what would actually kill it vs nice-to-have). Route real defects to
`/fix` or `/dev` (with a `/loyal check` if intent is touched). Surface the strategic ones (market,
investor) for the user's judgment. Write a short product-readiness note.

### Success: the real, ship-blocking weaknesses are named with evidence and routed.
### Failure: nothing concrete found (genuinely solid, or the lenses didn't fit). Say which.

## Guardrails
- No fixed persona fusion, no question quotas. Use the lenses that fit; find what's real.
- This is product scrutiny, not code review. Correctness is `/qa`; intent fidelity is `/loyal`.

## Ecosystem
- **Reads**: `intent-anchor.md`, README, startup-track docs; runs the product; researches the
  market.
- **Spawns (optional)**: `deep-researcher` / market research for real external data.
- **Routes to**: `/fix`, `/dev`. **Feeds**: the startup pipeline (`/launch`, `/scale`) if
  applicable.
