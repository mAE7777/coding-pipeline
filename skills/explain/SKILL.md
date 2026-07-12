---
name: explain
description: "Explain what was built (a slice, the whole product, or current status) in a chosen audience register: engineer, founder, investor, or user. Use this skill when the user says /explain, 'explain this', 'what did we build', 'explain for an investor/founder/user/engineer', 'write release notes', 'write an investor update', or wants the build described without reading code. Re-derives the explanation per audience rather than reskinning one summary; keeps code hidden. Modes: engineer | founder | investor | user."
argument-hint: "[engineer | founder | investor | user] [slice | product | status]"
---

# explain — Explain the Build in the Right Register

> EXECUTABLE WORKFLOW. The code stays hidden; this is how the user understands what was built.
> Each mode is RE-DERIVED from the build state at a different altitude, never a reskinned summary.

## Mode + scope detection
Parse the argument for the audience mode (engineer / founder / investor / user) and the scope (a
slice, the whole product, or current status). If the audience is not given, infer it from "who
reads this and what will they decide," or ask one question. **Never silently default to engineer**
(the curse-of-knowledge trap). Default for this user: founder or user register for "what got
built," engineer on request, investor for updates.

## Workflow

### Stage 1 — Gather build state (don't dump code)
Read `intent-anchor.md` (goal, DoD, persona), `slices.md` (what's done), the latest `/loyal` and
`/qa` results and their collected **evidence** (real traces, screenshots), and `CHANGELOG.md`.
This is the source you re-derive from. Do not read or surface raw code unless engineer mode needs
a specific snippet.

### Stage 2 — Load the mode template
Load `references/modes.md` for the chosen mode's template, altitude, lead-with, omit-list, and
lint rules.

### Stage 3 — Re-derive at the mode's altitude
Engineer = the machinery; founder = customer outcome + the decision needed; investor = business
signal + the ask; user = "you can now …". Do NOT translate the engineer summary into the other
modes; re-derive each from intent + behavior + evidence. Three modes deliberately throw the code
internals away.

### Stage 4 — Lint the render
Check the render against the mode's rules: fail a user/founder/investor render that leaks engineer
jargon (endpoint, schema, refactor, latency); fail an investor render missing a metric or an ask;
fail a user render whose headline is a feature name instead of a benefit. Fix before showing.

### Stage 5 — Output (grounded, never fabricated)
Ground every claim in the evidence already collected (a screenshot, a behavior trace). If a mode
needs data you do not have (e.g. investor metrics), say what is missing rather than inventing it.

### Success: a single-register explanation, re-derived at the right altitude, lint-clean, grounded in real evidence.
### Failure: required data for the mode is missing. Say so; do not fabricate.

## Guardrails
- One register per output; never blur (Diátaxis).
- Never fabricate metrics or outcomes; ground in collected evidence.
- Code stays hidden unless engineer mode explicitly needs a snippet.

## Ecosystem
- **Reads**: `intent-anchor.md`, `slices.md`, `/loyal` and `/qa` results + evidence, `CHANGELOG.md`.
- **Loads**: `references/modes.md`.
- **Used by**: `/deploy` (user-mode changelog), on-demand recaps during the loop and after the
  final slice, and investor updates.
