---
name: scout
description: "Optional pre-build research for a genuine unknown: a feasibility question, a real technology choice, or mapping an unfamiliar codebase. Use this skill when the user says /scout, 'research options', 'is this feasible', 'what should I use for', 'evaluate approaches', or 'map this codebase' BEFORE framing a build. Skip it when there is no real unknown. Produces a short discovery note that feeds /plan."
argument-hint: "<question | topic | codebase path>"
---

# scout — Research a Real Unknown (optional, thin)

> EXECUTABLE WORKFLOW. Only run when there is a genuine unknown. If the build has no real research
> question, skip straight to /plan.

Answers "is this feasible / what should we use / how does this code work" so `/plan` can freeze
intent on solid ground. Thin: no tier matrix, no forced investigation taxonomy, no mandatory
bilingual brief, no required comparison-table format.

## When to use vs skip
Use when a feasibility risk decides whether to build at all, a real technology choice has
non-obvious trade-offs, or you must understand an unfamiliar/brownfield codebase first. Skip when
you already know the approach (most small, CLI, or interest projects). Say "no real unknown, go
straight to /plan" rather than manufacturing research.

## Workflow

### Stage 1 — Name the real question and the riskiest assumption
State, in a line or two, the decision this research must resolve and the single assumption that,
if false, kills the approach. That assumption gets the most scrutiny.

### Stage 2 — Investigate
Research the options, feasibility, or codebase with the right tools (web search and fetch, reading
the code, a research subagent for unlimited-scope questions, doc-fetching tools). When the
unknown is an existing codebase, load `references/brownfield-analysis-guide.md` for a mapping
strategy. Verify load-bearing claims against a primary source; a single blog is weak evidence. Run a deliberate
disconfirming search for your leading option (look for why it fails) to counter confirmation bias.

### Stage 3 — Decide and surface trade-offs
Recommend an option with its real trade-offs and an honest confidence level. Where two options are
genuinely close, say so rather than forcing a false winner. Flag anything still unverified.

### Stage 4 — Thin deliverable
Write a short `discovery/discovery-<slug>.md`: the question, the riskiest assumption and how it
resolved, the recommendation and trade-offs, open unknowns, and any constraints `/plan` should
freeze around. Length matches the stakes.

### Success: the real question is answered with primary-source-grounded evidence and an honest confidence level.
### Failure: the riskiest assumption could not be resolved. Say so; that itself is the finding.

## Guardrails
- Don't research what you already know. Don't pad a brief to look thorough.
- Don't default to a fixed stack; derive the choice from the project's nature.

## Ecosystem
- **Reads**: the codebase (brownfield), the web.
- **Spawns (optional)**: a research subagent for unlimited-scope research.
- **Hands to**: `/plan` (freeze intent and contracts on the resolved ground).
