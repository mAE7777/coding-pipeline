# Intent

<!--
What must be true for the person who uses this. Locked with the owner and hashed (intent_lock.py). After
the lock the text above "Re-freeze log" is never edited; a change is a re-freeze entry at the bottom,
made only with the owner's ruling. Written in plain product language: no framework, library, file, or
function names.
-->

Status: draft

## Goal
<one sentence: what this is, for the person who will use it>

## Identity and promise
<what it IS in the user's head, one sentence>
Before: <the user's situation without it>
After: <the user's situation with it>

## Who
Persona (blind): <skill level and the surface they use, with no purpose or domain words; this line is the
only part of this file an evaluator that must guess the purpose may see>
<the fuller persona: situation, needs, context>

## Load-bearing behavior
<the one behavior that, if wrong, makes the whole thing pointless>

## Done examples
<!-- product-level; each is one testable statement plus one concrete example with real data -->
- I-D1 When <trigger>, <observable result>. Example: <real input> → <real output>
- I-D2 If <failure>, the user sees <honest state>. Example: <real input> → <real output>

## Mechanism cards
<!-- one per load-bearing mechanism; the rejected imitation is what a builder drifts into -->
### <mechanism name>
Purpose: <why it exists for the user>
Observable guarantee: <what a user or test can see that proves it works>
Rejected imitation: <the familiar, easier version that looks similar but is NOT acceptable, and why>
Discriminating probe: <an input pair or scenario whose result differs between the real mechanism and the imitation>

## Must not lose
<!-- each item ends with how it is checked, or why it cannot be checked in code -->
- L-01 <property, boundary, or red line> · check: <probe, test, or inspection>
- L-02 <property> · not code-checkable (<reason; the owner checks it at acceptance>)

## Languages and appearance
<!-- copied from the owner's standing requirements file when one exists (otherwise asked at intake);
     changed only by owner ruling, with the decision ID -->
Languages: <every language user-facing output supports>
Appearance: <light, dark, or both>

## Design intent
<UI only: feel, references, the one screen that matters most, named patterns to avoid>

## Assumptions
- A-01 <what was assumed and why> · signed <date>

## Re-freeze log
<!--
One entry per owner-ruled change, appended; the text above is never edited after the lock.
  ### RF-1 · <date> · D-<nnn>
  Supersedes I-D2 with I-D2a: <new statement>. Example: <...>
  Adds I-D5: <statement>. Example: <...>
  Drops L-03 (reason: <...>)
  Invalidates: <milestones and evidence this makes STALE>
-->
