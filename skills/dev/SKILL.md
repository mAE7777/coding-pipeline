---
name: dev
description: "Build one vertical slice end-to-end in a single coherent thread at high reasoning effort. Use this skill when the user says /dev, 'build this slice', 'implement the current slice', 'start building', or hands off from /plan. Builds the current slice from slices.md, builds its load-bearing part first, keeps every change traceable to the frozen intent, and is not done until a check it ran is green. Hands the slice to /loyal and /qa for verification."
argument-hint: "[slice number or name | empty = current slice]"
---

# dev — Build a Slice

> EXECUTABLE WORKFLOW. Thin by design. The model plans and decomposes the slice in its own
> reasoning; this skill imposes only what a strong model skips: build the hard part first, keep
> every change traceable, and never call it done without a green check.

Build ONE slice in ONE thread at high effort. No orchestrator, no separate planner agent, no
multi-section plan file, no complexity tiers. A frontier model holds a whole slice in context
and plans it better in its own trace than a scaffold can. Those structures existed to survive
small context windows; they are now overhead.

## Core principles
1. **One slice, one thread.** Build the current slice completely; don't sprawl into others.
2. **Hard part first.** Build the slice's load-bearing behavior before its trimmings, so the
   hard thing is proven, not deferred.
3. **Scope guard.** Every changed line traces to this slice. No drive-by refactors, no
   unrequested abstraction or flexibility, no improving adjacent code.
4. **Done = a green check you ran, shown as evidence.** "Looks done" is not a stop signal.
5. **Never decide on missing context.** Build only what the confirmed intent specifies. If
   implementation surfaces a genuine intent question the anchor does not resolve, HALT and ask;
   do not pick silently. A new dependency or a contract change also HALTs for approval.
6. **Code is hidden by default.** Report progress as behavior and evidence, not diffs. The user
   reads what was built through `/explain`, not by reviewing code.

## Workflow

### Stage 1 — Load the slice
Read `slices.md` (the `current:` slice, or the one named in `$ARGUMENTS`). Read `intent-anchor.md`
(goal + load-bearing behavior + the slice's EARS criteria), `contracts.md` (interfaces to honor),
`AGENTS.md` (conventions, build/test commands), and the design-intent section if this slice has
UI. That is the whole context you need. Capture the baseline commit (`git rev-parse HEAD` if under
version control) so drift from this point is measurable.

### Stage 2 — Plan only if non-trivial
If you could describe this slice's diff in one sentence, skip planning and build. Otherwise think
the approach through first. If anything material is ambiguous or the anchor does not resolve a
fork, HALT and ask using a recommended-answer option, never guess. A new dependency or a change to
`contracts.md` also HALTs for approval. Start with the load-bearing part.

### Stage 3 — Build
Honor the contracts. Match `AGENTS.md` conventions (or, on a greenfield with no pattern yet,
set a clean one: this slice becomes the reference the rest copy). Hold the scope guard: if the
slice genuinely needs something outside its scope, surface it, don't silently expand. If the
slice carries a Steal block, load `~/.claude/skills/_shared/references/steal-protocol.md`: for
Tier 1-2, READ the original source file before writing, port verbatim with only the listed
adaptations, and HALT for approval on any Tier 1 deviation. Never reimplement a stolen item from
its summary.

### Stage 4 — Self-verify (no done without a green check)
Give yourself a check and run it: the slice's test, a build/typecheck, a real input→output run,
or a screenshot. Show the evidence (the command and what it returned, or the screenshot), never
assert success. If nothing runnable exists yet, write the smallest check that proves the
load-bearing behavior. Iterate until green, bounded; if you cannot get it green, stop and
surface why rather than faking it or stubbing.

### Stage 5 — Record and hand off
Mark the slice done in `slices.md` and set the next `current:`. If a real convention or gotcha
emerged, add one line to `AGENTS.md` (keep it lean). Note anything that should reshape the
remaining slices. Then hand the slice to its verification gate: `/loyal check` (intent fidelity)
and `/qa` (correctness); they are isolated from each other by design, so spawn their evaluators
concurrently where the harness allows. `/explain` recaps run on demand and after the final slice
(founder or user register), never as per-slice ceremony; code stays hidden either way.

### Success: the slice's load-bearing behavior works and is proven by a green check shown as evidence; `slices.md` updated.
### Failure: cannot reach a green check, or a contract had to be broken. HALT and surface it.

> After the slice, verification runs. On a clean pass, continue to the next slice automatically;
> HALT only on a failed check, a material question, or when the user asked to review each slice.

## Guardrails (do not rebuild a cage)
- No `dev-planner` / `task-implementer` subagents, no multi-section plan file, no Quick/Standard/
  Deep tiers. The model plans in-trace.
- Don't over-build. A senior engineer should not call the result overcomplicated; 200 lines that
  could be 50 get rewritten.
- Don't defer the hard part to a later slice. Don't insert demo/placeholder data that hides a
  behavior that doesn't actually work.
- For UI work, build to the anchor's design-intent section and avoid generic AI aesthetics (lean
  on the `frontend-design` guidance; when the design carries real stakes, run the `/taste-design`
  lint, or hand the page's direction to `/taste-design` or `/atelier` before building). The
  rendered screen is what the user judges, so make this slice's screen real, not a placeholder.

## Ecosystem
- **Reads**: `slices.md`, `intent-anchor.md`, `contracts.md`, `AGENTS.md`.
- **Writes**: code; updates `slices.md` and `AGENTS.md`.
- **Hands to**: `/loyal check` + `/qa` (the slice's verification gate).
- **Off-loop sibling**: `/fix` for a targeted change that isn't a whole slice.
