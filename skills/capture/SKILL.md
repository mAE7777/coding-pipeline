---
name: capture
description: "Keep idea conversations whole until the owner decides to build: ChatGPT chats (export file or pasted text, voice-mode transcripts included), voice recordings, notes, and existing documents are stored verbatim with numbered turns, then organized into a dossier (problems, vision, story, product, users, implementation ideas, research questions, decisions, rejected ideas, open tensions) where every point cites the turns it came from and the owner's own words are kept apart from the assistant's suggestions. Re-importing a chat that grew adds only the new turns. Checked by script (every owner turn covered, every quote verbatim) and by an isolated fidelity reader. Use for /capture, 'save this chat', 'keep this conversation', and before /plan when ideas came from conversations."
argument-hint: "add <file> [--chat <title or id>] | status | check | prompt"
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

## add <file>
1. Import: `capture.py add <project> <file> [--chat <title or id>]`. Kinds are detected (a `.json` ChatGPT
   export, pasted chat text with "You said:" and "ChatGPT said:" markers, a Markdown or text document, an
   audio recording). For an export with many chats, `capture.py list <file>` shows them. How to get a chat out
   of ChatGPT without loss is in `references/chatgpt.md`. A second import of the same chat adds only its new
   turns. Audio is transcribed locally with whisper through the heavy lock; its turns are labeled as
   machine-transcribed.
2. Organize: read the new turns in full (in `docs/project/sources/SRC-<n>-*/transcript.md`) and update
   `docs/project/sources/dossier.md` in the grammar in `references/dossier.md`: new units for new points,
   `superseded by` for changed positions, open questions, tensions, and the no-content turns (greetings,
   "go on").
3. Check: `capture.py check <project>`; fix every FAIL in the dossier (never in the transcript).
4. Fidelity: the isolated reader compares the dossier with the transcripts. In the background:
   `run_isolated.py cold-reader --dir auto --out .evidence/capture --project <project> --render --mode fidelity
   --docs docs/project/sources/<SRC folder>/transcript.md --`, one `--docs` per source changed. Fix every
   material item it names, then check again.
5. Tell the owner, plainly: what the new material added, what changed position, the open questions and
   tensions, and whether it looks ready to plan. Offer nothing they did not ask about.

## status
`docs/project/sources/index.md`, the unit counts by category and status, the open questions, and the last
check and fidelity results.

## check
Steps 3 and 4 on the current dossier.

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
