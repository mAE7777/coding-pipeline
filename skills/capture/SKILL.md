---
name: capture
description: "Keep and understand a project's sources: ChatGPT chats (exported or pasted), voice recordings, notes, documents (Markdown, text, PDF, Word, OpenDocument, RTF, HTML, EPUB), records and logs, a file or a whole folder, kept verbatim in a cited, audited dossier. Modes: add <file or folder>, status, check, prompt. Use for /capture, 'save this chat', 'read these documents or logs', 'understand this folder', and before /plan or /plan adopt."
argument-hint: "add <file or folder> | status | check | prompt"
---

**Workflow choice, first.** Run `python3 ~/.claude/skills/_shared/scripts/project_policy.py status <project> --json`. OFF or no choice: when the status names the fast workflow, use its matching /<name>-fast skill if it lists one; otherwise do the requested work directly from the existing documents, code, and tests, with no formal step, record, or End chain. ON: the rules below apply; recheck the choice before each next step. Only the owner's explicit on or off, through /pipeline, changes it. Contract: `~/.claude/skills/_shared/references/project-control.md`.

# /capture

The failure this exists for: an idea discussed over many rounds loses its nuance on the way into a plan.
A hedge becomes a decision, a suggestion the owner never took up becomes "the owner wants", an earlier
position survives a later change of mind, or a point simply disappears.

Load-bearing rules (`capture.py check` fails each breach it can see):
- The verbatim transcript is the only truth: stored exactly as received, never edited, and everything else
  points into it by turn number.
- The owner's words and the assistant's suggestions stay apart. Every point about the owner's view quotes the
  owner's words verbatim, with the turn; a suggestion becomes the owner's view only when a later owner turn
  agrees, quoted.
- Nothing is deleted: a changed position marks the old unit `superseded by S-<nnn>`, and both stay.
- Capture does not decide the workflow. The dossier feeds `/plan`, helm, or nothing yet, as the owner chooses.
- Venture projects (a `truth/` folder): read `~/.claude/skills/_shared/references/venture-mode.md` first; if it is missing, stop BLOCKED.

Scripts: `~/.claude/skills/_shared/scripts/capture.py`. The project folder is the current project, or for
an idea with no folder yet a new folder named for the idea beside the owner's other projects (the standing
requirements file, `~/.claude/skills/_shared/references/owner-standing.md`, says where; otherwise ask); it
becomes the project if the idea goes ahead.

## add <file or folder>
Every load-bearing point is read, drafted, and checked; a detail that decides nothing stays in the verbatim
source, one lookup away (the charter's law 5). Isolated readers do the reading, so its spend is bounded and
measured; there are no helper agents here.

0. **Budget**: `python3 ~/.claude/skills/_shared/scripts/spend.py start <project> --phase capture` (unless a phase,
   such as an adoption, is already active). After the import, `spend.py estimate <project>`: above the target
   (5 percent of the week), tell the owner before reading, with what a smaller plan would leave unread, and let
   them choose. After every step, `spend.py status <project>`: over the target, tell the owner at the next stop;
   over the cap (10 percent), the runner refuses new reads, so stop and report what is done, what remains, and
   what it would cost; only the owner raises the cap (`spend.py raise`, their words). `spend.py stop` at the end.
1. **Import**: `capture.py add <project> <file or folder> [--chat <title or id>]`. Its usage lists the kinds it
   detects, how a folder walk is recorded in `docs/project/sources/import-ledger.md`, and what a second import
   adds. A file it could not read is named there with the reason (a scanned PDF needs OCR): tell the owner,
   never pass over it. How to get a chat out of ChatGPT without loss is in `references/chatgpt.md`.
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
4. **Audit, until an audit finds nothing material**: one fidelity read per portion: `run_isolated.py
   cold-reader --dir auto --out .evidence/capture/audit-<n> --project <project> --render --mode fidelity --docs
   <transcript> ... --`, then `capture.py audit <project> <its result.md>`. Settle every material row in
   `sources/audits/` (`fixed S-<nnn> (<what changed>)`, `not an issue (<why>)`, `owner (<the question>)`);
   minor rows are fixed when it costs little. A portion whose audit found something material is audited again
   with `--previous <that result.md>`. From the third audit on, a portion's audit reads only what the one
   before flagged: `--docs` only the transcripts its material rows cite, with `--previous`; a point those
   cannot settle goes to the owner as an `owner (...)` row (a count changes the method, never ends the loop).
   `capture.py check` says what is left.
5. **Tell the owner**, plainly: what the material says, what the reading cost (`spend.py status`), what changed
   position, the open questions and tensions (the rounds' owner rows among them), any file that could not be
   read and what would fix it, and whether it looks ready to plan. Offer nothing they did not ask about.

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
`/plan` takes the dossier from there ("From a capture dossier"). After the lock, a captured conversation does
not reach the plan directly: each new idea, proposed change, or opinion in it becomes an inbox item citing its
turns (`inbox.py add <project> --from <who> --kind <kind> --source "SRC-<n> T<a>-T<b>"`), weighed by `/inbox
review`; a decision the owner states outright is a ruling and goes through `/plan amend`. In a venture project
each source is also registered in helm's source ledger (the private overlay says how).

## End
`python3 ~/.claude/skills/_shared/scripts/project_status.py record <project> --skill capture --outcome "<one line>"`, then close the report with the Next line it prints (`project-control.md`, End).
