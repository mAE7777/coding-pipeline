# Intent

<!--
What must be true for the person who uses this. Locked with the owner and hashed. After
the lock the text above "Re-freeze log" is never edited; a change is a re-freeze entry at the bottom,
made only with the owner's ruling. Written in plain product language: no framework, library, file, or
function names.
-->

Locked by the owner 2026-10-18 · hash 0a667d0486298123 · ruling D-001 · re-freezes 0
## Goal
Keep one short to-do list in a terminal.

## Identity and promise
A list you can trust.
Before: chores are kept in mind and forgotten.
After: every chore is written down and shown in order.

## Who
Persona (blind): an adult comfortable with a command line.
Someone who keeps a few chores in mind.

## Load-bearing behavior
Adding an item shows it at once.

## Done examples
<!-- product-level; each is one testable statement plus one concrete example with real data -->
- I-D1 When an item is added, it is printed back. Example: add milk → "1. milk"

## Mechanism cards
<!-- one per load-bearing mechanism; the rejected imitation is what a builder drifts into -->
### Store
Purpose: items survive.
Observable guarantee: the item is printed.
Rejected imitation: a constant list.
Discriminating probe: add two different items.

## Must not lose
<!-- each item ends with how it is checked, or why it cannot be checked in code -->
- L-01 Items are never reordered · check: add a then b, see a before b

## Languages and appearance
<!-- copied from the owner's standing requirements file when one exists (otherwise asked at intake);
     changed only by owner ruling, with the decision ID -->
Languages: English
Appearance: the terminal's own

## Design intent
none

## Assumptions
- A-01 one user · signed 2026-10-12

## Re-freeze log
<!--
One entry per owner-ruled change, appended; the text above is never edited after the lock.
  ### RF-1 · <date> · D-<nnn>
  Supersedes I-D2 with I-D2a: <new statement>. Example: <...>
  Adds I-D5: <statement>. Example: <...>
  Drops L-03 (reason: <...>)
  Invalidates: <milestones and evidence this makes STALE>
-->
