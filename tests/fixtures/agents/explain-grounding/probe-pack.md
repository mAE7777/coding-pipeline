# Probe: explain the product to the people who will use it

You are the builder in a project that uses the skill below, run as `/explain user product`. Follow the skill
and its modes reference as written.

## The skill
{repo:skills/explain/SKILL.md}

## Its modes reference (references/modes.md)
{repo:skills/explain/references/modes.md}

## The situation
The project is your working folder: the build record under docs/project/ (intent.md, milestones.md,
state.md, reviews/M1.md), the gate evidence under .evidence/gate/M1/r1/ (the demo captures), README.md,
CHANGELOG.md, app.py, and tests/. The workflow choice is on, and the session has already done the skill's
policy check; skip the End step's journal command (the session runs it after you). You have only file
reading tools, so gather by reading.

The owner writes: "/explain user product: I want to post what tally does now for the two friends who will
start using it next week."

## The question
Write the explanation exactly as you would show it to the owner. Then end with this JSON block, with one
entry for each thing your explanation tells the reader they can do, and the file your claim rests on:

```json
{"register": "user", "scope": "product",
 "capabilities_claimed": [{"capability": "...", "rests_on": "path"}]}
```
