# intent-anchor.md template

The anchor is the frozen original intent. Everything in Check Mode diffs against it. It is written
once at t=0 and never silently edited. Its whole job is to NOT co-drift with the build, so that
when the human's memory of "what I wanted" has quietly moved, the anchor still tells the truth.

`/plan` fills this with the interrogated, example-grounded, explicitly-confirmed content (see
`plan/references/interrogation.md`). Run standalone, `/loyal freeze` captures the core fields and
notes the rest as TODO for `/plan`.

Write this to the project root as `intent-anchor.md`:

```markdown
# Intent Anchor

- Frozen: <ISO date>
- Hash: <short hash of Goal + Definition of done>

## Goal
<one sentence: what this is, for the person who will use it>

## Definition of done (EARS + a grounding example each)
Each behavior is one EARS statement plus one concrete example with real data.
1. When <trigger>, the system shall <response>.
   - e.g. <real input → real observable result>
2. While <state>, the system shall <response>.
   - e.g. <real input → real observable result>
3. If <bad condition>, then the system shall <response>.
   - e.g. <real input → real observable result>
<3 to 6 total. Behavior, not implementation. EARS keywords: When=event, While=state,
Where=optional feature, If/Then=unwanted path, shall=mandatory & testable.>

## Load-bearing behavior
<the single behavior that, if wrong, makes the whole thing pointless>

## Persona
<who uses this, at what level of expertise; sets the evaluator's altitude>

## Design intent (UI projects only)
<overall feel; reference products/screenshots; brand / color / dark-or-light; the one screen that
matters most. Omit for non-UI projects.>

## Resolved details
<the answers to the hidden-details questions that applied: states, concurrency, auth, data
lifecycle, integration failure modes, etc. One line each. Omit dimensions that don't apply.>

## Assumptions Index
<every inference / default / unconfirmed reading, surfaced for sign-off. Each line is
[ASSUMPTION] <what was assumed and why>. The user signs off this whole list at the CONFIRM gate.>
```

## Rules

- **Behavior, not implementation.** "When the user clicks export, the system shall produce a PDF
  of their notes" is a behavior. "Uses the pdfkit library" is not. If a line names a function,
  file, library, or framework, rewrite it.
- **EARS + example, not prose.** Each definition-of-done line is a testable EARS statement with a
  concrete grounding example. Prose like "it should handle errors gracefully" is not freezable;
  rewrite it as `If <specific error>, then the system shall <specific response>` with an example.
- **One load-bearing behavior.** Not three. Force the choice. The forcing is the value: it makes
  the headline of every later report obvious.
- **Nothing material is assumed silently.** Every inference lives in the Assumptions Index and is
  confirmed at the gate. An assumption baked into a DoD line instead of surfaced here is a
  process violation.
- **The evaluator never sees this file.** Check Mode passes the isolated evaluator only the Goal,
  the Persona, and the project's build/run commands (which leak no intent); the DoD, examples, and
  resolved details are the harness's private diff target, so the evaluator must rediscover
  behaviors rather than confirm a list. qa, by contrast, DOES see the EARS DoD + examples (it
  checks correctness against the stated requirements).
- **The hash is a tamper check**, not security. It exists so a later "no drift" result cannot be
  quietly manufactured by editing the anchor. If intent genuinely changed, append a dated
  `## Re-freeze` section below the original and note in the ledger that the drift baseline reset.
  Never delete the original.
- **If the user cannot fill Goal and Load-bearing behavior, stop.** A build whose intent cannot be
  stated cannot be checked for drift, and pretending otherwise produces a sensor that measures
  nothing.
