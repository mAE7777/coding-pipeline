---
name: handoff
description: "Hand work over without losing anything: between sessions, between Claude Code and Codex, or to an outside reviewer (a ChatGPT chat, a colleague). Switching tools needs no command (the continuity hooks keep docs/project/handoffs/latest.md current and brief the next session); use this to write a checked packet on purpose, render a paste-ready prompt for another model with its limits and hand-back, run the receiving intake explicitly, or check a packet. Modes: write [to: session | codex | claude | chatgpt | reviewer], receive [packet], check [packet]."
argument-hint: "write [to: codex | claude | chatgpt | reviewer | session] | receive [packet] | check [packet]"
---

# /handoff

Load-bearing rules:
- Pass references and fingerprints, never a paraphrase: the receiver reads the same files and proves it by
  restating and reconciling before acting.
- Nothing is lost: every active constraint, must-not-lose item, open item, parked item, and open or logged
  gate finding is carried, and `handoff_check.py` must pass before a packet goes anywhere.
- One writer per checkout. A receiver becomes the writer only when it starts changing files.
- Send outside this machine only what may leave it (see Privacy).
- Venture projects: when the project has a `truth/` folder, read
  `~/.claude/skills/_shared/references/venture-mode.md` before writing or receiving a packet; if it is missing, stop with BLOCKED (this is a
  venture project and its rules are not installed).

Scripts: `~/.claude/skills/_shared/scripts/`.

## write [to: ...]
1. `python3 continuity.py packet <project>` (the tool and session are read from the environment) writes
   `docs/project/handoffs/latest.md` from `state.md`, the record, and the live fingerprint. Before that, make
   sure `state.md` is true right now (Done with evidence, Open, In flight, Blockers, Next step).
2. `handoff_check.py docs/project/handoffs/latest.md --project <project>` must pass; fix `state.md` and
   re-run until it does.
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
3. Resolve or record each discrepancy (a Blockers row for any that needs the owner), then continue with the
   packet's next step; the continuity hook records you as the writer on your first edit.

## check [packet]
`handoff_check.py` on the packet, and the cold reader when the packet will be read by someone without this
project's context.

## Privacy
A prompt for a chat model outside this machine (ChatGPT, a colleague) carries no secrets, credentials, `.env`
values, customer data, or private documents the owner has not cleared. When unsure, say what you would send
and ask. Codex and Claude Code sessions on this machine read the files directly and need no copy.

## End
Every packet written or received ends with `python3 ~/.claude/skills/_shared/scripts/project_status.py record <project> --skill handoff --outcome "<one line>"` (the journal and the Last step in state.md), and the report closes with the Next line it prints: what comes next, who takes it, and why. Under `/next auto`, a builder step is taken right away.
