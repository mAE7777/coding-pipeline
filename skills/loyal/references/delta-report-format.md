# Delta report format (Check Mode Stage 3)

The report is the product. Its job is to let a busy, non-engineer builder judge intent fidelity in
one glance and either move on or feed back a correction. Every formatting rule below exists to
fight approval fatigue, which is the way this whole loop dies.

## Hard rules

1. **Headline first.** The first line is the load-bearing behavior verdict. Nothing precedes it.
2. **Goal vs reconstruction, side by side.** Two lines: the frozen goal, and the evaluator's
   purpose guess. If they read as the same product, good. If they read as different products, that
   is the drift, even when every individual behavior "works".
3. **Show only what is not HOLDS.** List DRIFT, MISSING, EXTRA, ORPHAN. One line each, behavior
   language, zero code. Do not list the behaviors that hold; a clean item does not need the eye.
4. **No findings theater.** If nothing drifted, the body is one line: "No drift from intent this
   milestone." Do not invent soft findings to look thorough. Manufactured findings are what teach
   the eye to skim, and a skimming eye misses the real one next time.
5. **Traces collapsed.** The grounding trace for each item is available on `inspect`, not shown by
   default. The glance stays a glance.
6. **One screen.** If the delta does not fit one screen, the milestone was too big; say so and
   suggest splitting the next one, rather than emitting a wall.

## Shape

```
LOAD-BEARING: <HOLDS | DRIFT | MISSING> — <the behavior, in one clause>

Goal (frozen): <one line>
Built (reconstructed): <evaluator purpose guess, one line>

Drift from intent:
  DRIFT    <behavior> now <what it actually does> (wanted: <what intent said>)
  MISSING  <DoD behavior that is not present>
  EXTRA    <behavior nobody asked for>
  ORPHAN   <behavior that fits no purpose>

[accept]  [correct <n>]  [inspect <n>]  [ask <n>]
```

## Verdict labels

- **HOLDS**: present, grounded, matches intent. Not listed in the body.
- **DRIFT**: present but does something other than intent. The core signal.
- **MISSING**: a definition-of-done behavior is absent.
- **EXTRA**: a behavior exists that no intent statement called for (the led-by-the-nose signal).
- **ORPHAN**: an unexplained behavior from the evaluator (drift or rot, route rot to the gate).

## When vigilance is active

If this pass carries a planted discrepancy (Vigilance Mode), one of the listed items is
deliberately false. Render it exactly like a real item, with no tell. After the user responds,
reveal whether they caught it and log the result. Do not skip the reveal; the point is the human
seeing their own miss, which is the only thing that resets a skimming habit.
