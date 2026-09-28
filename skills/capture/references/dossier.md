# The dossier grammar

`docs/project/sources/dossier.md`. `capture.py check` parses it; keep to the shapes below exactly.

```
# Dossier: <working title>
Status: exploring | ready to plan | planned | parked (<reason>)
Sources: SRC-1 (ChatGPT, "<chat title>", 48 turns) · SRC-2 (voice note, 12 turns)

## Where it stands
<one paragraph: the current best understanding, the latest positions, pointing at unit IDs>

## Units
- S-001 · problem · owner · current · SRC-1 T003, T017
  <the point, in plain words, as faithful as a paraphrase can be>
  > "<the owner's exact words>" (SRC-1 T003)
- S-002 · product · owner-agreed · current · SRC-1 T021-T022
  <an assistant proposal the owner then agreed to>
  > "<the owner's words agreeing>" (SRC-1 T022)
- S-003 · implementation · assistant · not taken up · SRC-1 T024
  <an assistant suggestion the owner never took up>
- S-004 · vision · owner · superseded by S-019 · SRC-1 T005
  <an earlier position, kept>
  > "<the owner's words then>" (SRC-1 T005)

## Open questions
- Q-1 <a question the conversations left open> · from S-007 · research | owner decision

## Tensions
- <two positions that pull against each other, with both unit IDs, and whether the owner resolved it>

## No-content turns
SRC-1 T001, T009
```

Fields of a unit line, in order, separated by " · ":
- ID: `S-<nnn>`, never reused or renumbered.
- Category: problem, vision, narrative, product, user, implementation, research, constraint, decision,
  rejected, term, other.
- Attribution: `owner` (the owner said it), `owner-agreed` (the assistant proposed it and a later owner turn
  agreed), `assistant` (the assistant's, not endorsed), `document` (from an imported document), `transcribed`
  (the owner's words through machine transcription).
- Status: `current`, `open` (undecided), `not taken up`, `rejected`, `superseded by S-<nnn>`.
- References: `SRC-<n> T<nnn>`, ranges `T012-T015`, lists `T003, T017`, several sources separated by "; ",
  branch turns `B1-T002`.

Quotes (`> "..." (SRC-n Tnnn)`) must be verbatim from the cited turn. `owner`, `owner-agreed`, and
`transcribed` units need at least one quote from an owner turn. A hedge stays a hedge ("maybe", "not sure",
"could"): write the unit as open, never as a decision. Every owner turn on a main line is cited by some unit or
listed under No-content turns.
