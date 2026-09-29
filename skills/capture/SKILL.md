---
name: capture
description: "Keep and understand everything a project's ideas and knowledge live in: ChatGPT chats (export or pasted, voice included), voice recordings, notes, documents (Markdown, text, PDF, Word, OpenDocument, RTF, HTML, EPUB), and records and logs, one file or a whole folder at once. All of it is stored verbatim in numbered units; an isolated reader that never saw anyone's summary drafts the dossier from them (every load-bearing point with its verbatim quote, who said it, and whether it still stands, the owner's words apart from an assistant's suggestions), and a second isolated reader audits the dossier against the sources for anything dropped, bent, or misattributed, again until an audit finds nothing material. Details that decide nothing stay one lookup away in the verbatim sources. Spend is measured and kept within the owner's budget. Checked by script (every owner turn and document section accounted for; every quote verbatim; every source extracted and cleared by an audit). Use for /capture, 'save this chat', 'read these documents or logs', 'understand this folder', and before /plan or /plan adopt."
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
Every load-bearing point is read, drafted, and checked; nothing that could change a decision is skimmed. What is
not paid for is a detail that decides nothing (a field list, a format, an example): it stays in the verbatim
source, one lookup away. The reading is done by isolated readers, whose spend is bounded and measured; there are
no helper agents here.

0. **Budget**: `python3 ~/.claude/skills/_shared/scripts/spend.py start <project> --phase capture` (unless a phase,
   such as an adoption, is already active). After the import, `spend.py estimate <project>`: above the target
   (5 percent of the week), tell the owner before reading, with what a smaller plan would leave unread, and let
   them choose. After every step, `spend.py status <project>`: over the target, tell the owner at the next stop;
   over the cap (10 percent), the runner refuses new reads, so stop and report what is done, what remains, and
   what it would cost; only the owner raises the cap (`spend.py raise`, their words). `spend.py stop` at the end.
1. **Import**: `capture.py add <project> <file or folder> [--chat <title or id>]`. Kinds are detected: a ChatGPT
   export (`capture.py list <file>` shows its chats), pasted chat text, documents (Markdown and text; PDF by
   page; Word, OpenDocument, RTF, HTML, EPUB converted, the converter recorded), logs and records (windows of
   200 lines), audio (whisper, through the heavy lock, labeled machine-transcribed). A folder is walked whole;
   `docs/project/sources/import-ledger.md` records every file and what became of it. A file that could not be
   read is named there with the reason (a scanned PDF needs OCR): tell the owner, never pass over it. A log over
   200 KB is registered with a script summary (time range, error lines), not read window by window. A second
   import of a chat that grew adds only its new turns; an unchanged file is not imported again. How to get a
   chat out of ChatGPT without loss is in `references/chatgpt.md`.
2. **Draft**: in the background, one extraction per portion: `run_isolated.py cold-reader --dir auto --out
   .evidence/capture/extract-<n> --project <project> --render --mode extract --docs
   docs/project/sources/<SRC folder>/transcript.md --`, one `--docs` per source in the portion (a portion is
   what one reader takes in fully, up to about 150 thousand tokens; at most three runs at once). The reader lists
   every load-bearing point in the dossier's own shape; `capture.py draft <project> <its result.md>` turns them
   into units (quotes checked against the turns, attribution and status kept, turns with nothing load-bearing
   listed as read) and puts any point it could not verify in `sources/rounds/` to settle. Each source is
   extracted once.
3. **Edit** `docs/project/sources/dossier.md` (grammar in `references/dossier.md`): merge the same point drafted
   from two portions, link changed positions (`superseded by`, both kept), confirm every `owner-agreed` rests on
   the owner's agreeing words, and write Where it stands, Open questions, and Tensions. Read a source yourself
   where a unit is unclear or two units conflict; that is the reading this step pays for. A dossier you wrote
   yourself first (a short chat) is checked with `capture.py reconcile` against the extraction instead.
4. **Audit, until an audit finds nothing material**: one fidelity read per portion, which sees the transcripts and
   only the units citing them: `run_isolated.py cold-reader --dir auto --out .evidence/capture/audit-<n> --project
   <project> --render --mode fidelity --docs <transcript> ... --`, then `capture.py audit <project> <its
   result.md>`. Settle every material row in `sources/audits/` (`fixed S-<nnn> (<what changed>)`, `not an issue
   (<why>)`, `owner (<the question>)`); minor rows are listed and fixed when it costs little. A portion whose audit
   found something material is audited again with `--previous <that result.md>`; the others are done.
   `capture.py check` passes when every source is extracted and its latest audit found nothing material.
5. **Tell the owner**, plainly: what the material says, what the reading cost (`spend.py status`), what changed position, the open questions and tensions
   (the rounds' owner rows among them), any file that could not be read and what would fix it, and whether it
   looks ready to plan. Offer nothing they did not ask about.

## status
`docs/project/sources/index.md`, the unit counts by category and status, the open questions, and the last
check and fidelity results.

## check
`capture.py check`, then the draft (step 2) for any source not yet extracted and the audits (step 4) for any
source not yet cleared, on the current dossier.

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
