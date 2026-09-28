---
name: capture
description: "Keep and understand everything a project's ideas and knowledge live in: ChatGPT chats (export or pasted, voice included), voice recordings, notes, documents (Markdown, text, PDF, Word, OpenDocument, RTF, HTML, EPUB), and records and logs, one file or a whole folder at once. All of it is stored verbatim in numbered units and organized into a dossier where every point cites the units it came from and the owner's words stay apart from an assistant's suggestions. It reads in rounds until nothing is missed: after each organizing pass an isolated reader that never sees the dossier lists every point in the sources, a script diffs that list against the dossier, and every difference is settled; the rounds end only when one finds nothing missed, and an isolated fidelity reader then checks for distortion. Checked by script (every owner turn, document section, and log window accounted for; every quote verbatim; every source read by an independent extraction). Use for /capture, 'save this chat', 'read these documents or logs', 'understand this folder', and before /plan or /plan adopt."
argument-hint: "add <file or folder> | status | check | prompt"
---

# /capture

The failure this exists for: an idea discussed over many rounds loses its nuance on the way into a plan.
A hedge becomes a decision, a suggestion the owner never took up becomes "the owner wants", an earlier
position survives a later change of mind, or a point simply disappears.

Load-bearing rules:
- The verbatim transcript is the only truth. It is stored exactly as received and never edited; everything
  else points into it by turn number.
- In the dossier, the owner's words and the assistant's suggestions are different things. A suggestion
  becomes the owner's view only when a later owner turn agrees, quoted.
- Every point about the owner's view quotes the owner's words, verbatim, with the turn.
- Nothing is deleted: a changed position marks the old unit `superseded by S-<nnn>`, and both stay.
- Capture does not decide the workflow. The dossier feeds `/plan`, helm, or nothing yet, as the owner chooses.
- Venture projects: when the project has a `truth/` folder, read
  `~/.claude/skills/_shared/references/venture-mode.md` before adding a source; if it is missing, stop with BLOCKED (this is a
  venture project and its rules are not installed).

Scripts: `~/.claude/skills/_shared/scripts/capture.py`. The project folder is the current project, or for
an idea with no folder yet a new folder named for the idea beside the owner's other projects (the standing
requirements file, `~/.claude/skills/_shared/references/owner-standing.md`, says where; otherwise ask); it
becomes the project if the idea goes ahead.

## add <file or folder>
Context comes before economy: every unit is read in full, and nothing is skimmed or cut to save a round. What
keeps the cost sane is never reading the same thing twice without a reason, not reading less.

1. **Import**: `capture.py add <project> <file or folder> [--chat <title or id>]`. Kinds are detected: a ChatGPT
   export (`capture.py list <file>` shows its chats), pasted chat text, documents (Markdown and text; PDF by
   page; Word, OpenDocument, RTF, HTML, EPUB converted, the converter recorded), logs and records (windows of
   200 lines), audio (whisper, through the heavy lock, labeled machine-transcribed). A folder is walked whole;
   `docs/project/sources/import-ledger.md` records every file and what became of it. A file that could not be
   read is named there with the reason (a scanned PDF needs OCR): tell the owner, never pass over it. A second
   import of a chat that grew adds only its new turns; an unchanged file is not imported again. How to get a
   chat out of ChatGPT without loss is in `references/chatgpt.md`.
2. **Organize**: read the new units in full (`docs/project/sources/SRC-<n>-*/transcript.md`) and update
   `docs/project/sources/dossier.md` in the grammar in `references/dossier.md`. Every owner turn, document
   section, and log window is carried by a unit or listed under "No-content turns" (read, nothing to keep);
   changed positions are marked `superseded by`, and both stay. For a large corpus, work in portions you can
   take in fully, writing each portion's units before the next.
3. **Rounds, until one finds nothing missed** (the dossier is checked against a reading that never saw it):
   a. Extraction: in the background, `run_isolated.py cold-reader --dir auto --out .evidence/capture/extract-<n>
      --project <project> --render --mode extract --docs docs/project/sources/<SRC folder>/transcript.md --`,
      one `--docs` per source in the portion. Size each portion so the reader can take all of it in (split a
      large corpus into several runs, at most three at once); the reader gets the sources only.
   b. `capture.py reconcile <project> .evidence/capture/extract-<n>/cold-reader.result.md` writes
      `sources/rounds/round-<n>.md` with every point the dossier does not carry.
   c. Settle every row: `added S-<nnn>` (a unit now carries it), `in S-<nnn> (<why the match missed it>)`,
      `not a point (<why>)`, or `owner (<the question>)` for what only the owner can settle.
   d. `capture.py check`. A source whose latest round added units gets another round (only the sources that are
      still yielding); a round that adds nothing ends the reading of that source. After three rounds that keep
      finding, change the method (smaller portions, a reader told what kind of point was being missed), never
      stop.
4. **Fidelity**: the isolated reader compares the dossier with the sources for distortion, misattribution, lost
   evolution, and tensions closed that the owner left open: `run_isolated.py cold-reader --dir auto --out
   .evidence/capture/fidelity --project <project> --render --mode fidelity --docs <transcript> --`. Fix every
   material item, then read again with `--previous .evidence/capture/fidelity/cold-reader.result.md` (and a new
   `--out`) until a read finds nothing material in what it was given.
5. **Tell the owner**, plainly: what the material says, what changed position, the open questions and tensions
   (the rounds' owner rows among them), any file that could not be read and what would fix it, and whether it
   looks ready to plan. Offer nothing they did not ask about.

## status
`docs/project/sources/index.md`, the unit counts by category and status, the open questions, and the last
check and fidelity results.

## check
`capture.py check`, then the rounds (step 3) for any source not yet read by an independent extraction or still
yielding, and the fidelity reads (step 4), on the current dossier.

## prompt
Print the optional ChatGPT project instructions from `references/chatgpt.md`, for the owner to paste once into
a ChatGPT Project so its replies keep the owner's words and its own suggestions apart.

## When the owner decides to build
`/plan` starts from the dossier: every live unit lands in the plan (`brief.md` `## Source closure`, checked by
`capture.py closure`). After the lock, a captured conversation does not reach the plan directly: each new
idea, proposed change, or opinion in it becomes an inbox item citing its turns (`inbox.py add <project> --from
<who> --kind <kind> --source "SRC-<n> T<a>-T<b>"`), weighed by `/inbox review`; a decision the owner states
outright is a ruling and goes through `/plan amend`. In a venture project each source is also registered in helm's source ledger (the private
overlay says how).

## End
Every run ends with `python3 ~/.claude/skills/_shared/scripts/project_status.py record <project> --skill capture --outcome "<one line>"` (the journal and the Last step in state.md), and the report closes with the Next line it prints: what comes next, who takes it, and why. Under `/next auto`, a builder step is taken right away.
