---
name: handoff
description: "Hand work over without losing anything: between sessions, between Claude Code and Codex, or to an outside reviewer (a ChatGPT chat, a colleague). Switching tools needs no command (hooks keep the handoff current); use this for a checked packet on purpose, a paste-ready prompt for another model, receiving one, or checking one. Modes: write [to: session | codex | claude | chatgpt | reviewer], receive [packet], check [packet]."
argument-hint: "write [to: codex | claude | chatgpt | reviewer | session] | receive [packet] | check [packet]"
---

**Workflow choice, first.** Run `python3 ~/.claude/skills/_shared/scripts/project_policy.py status <project> --json`. OFF or no choice: do the requested work directly from the existing documents, code, and tests, with no formal step, record, or End chain. ON: the rules below apply; recheck the choice before each next step. Only the owner's explicit on or off, through /pipeline, changes it. Contract: `~/.claude/skills/_shared/references/project-control.md`.

# /handoff

Load-bearing rules:
- A packet passes references and fingerprints, never a paraphrase, and loses nothing: `handoff_check.py`
  fails one that drops an active constraint, a must-not-lose item, an open or parked item, or an open or
  logged gate finding, and it must pass before a packet goes anywhere. The receiver restates and reconciles
  before acting.
- One writer per checkout. A receiver becomes the writer only when it starts changing files.
- A prompt for a chat model outside this machine (ChatGPT, a colleague) carries no secrets, credentials,
  `.env` values, customer data, or private documents the owner has not cleared. When unsure, say what you
  would send and ask. Codex and Claude Code sessions on this machine read the files directly and need no copy.

Venture projects (a `truth/` folder): read `~/.claude/skills/_shared/references/venture-mode.md` first; if it is missing, stop BLOCKED.

Scripts: `~/.claude/skills/_shared/scripts/`.

## write [to: ...]
1. Make `state.md` true right now (Done with evidence, Open, In flight, Blockers, Next step); then
   `python3 continuity.py packet <project>` (the tool and session are read from the environment) writes
   `docs/project/handoffs/latest.md` from it, the record, and the live fingerprint.
2. `handoff_check.py docs/project/handoffs/latest.md --project <project>`; on a FAIL, fix `state.md` and
   write the packet again.
3. For a packet that must survive later notes, copy it to `docs/project/handoffs/<UTC time>-<to>.md`.
4. Render the prompt for the receiver (`references/prompts.md` has one per target) and give it to the
   owner to paste, or, for a reviewer, the file to attach.
5. For a cold check that the packet decodes on its own: the documents cold reader on the packet
   (`run_isolated.py cold-reader --dir auto ... --render --docs docs/project/handoffs/latest.md --`), then fix
   what it could not resolve.

## receive [packet]
The session-start note already says who worked last and what changed; this is the full intake:
1. `handoff_check.py <packet> --project <project>`. A changed Candidate fingerprint means someone changed the
   tree after the note: list the changed files (the note's file list against the tree) and reconcile them
   before acting.
2. Read the read list, restate the milestone promise and the must-not-lose items in your own words, and list
   every discrepancy between the packet and the tree.
3. Resolve or record each discrepancy (a decision through `decisions.py add`; a Blockers row for any that
   needs the owner), then continue with the packet's next step; the continuity hook records you as the writer
   on your first edit.

## check [packet]
`handoff_check.py` on the packet, and the cold reader when the packet will be read by someone without this
project's context.

## End
`python3 ~/.claude/skills/_shared/scripts/project_status.py record <project> --skill handoff --outcome "<one line>"`, then close the report with the Next line it prints (`project-control.md`, End).
