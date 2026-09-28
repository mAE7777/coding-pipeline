# Handoff prompts

Short, pointing at files by absolute path, stating authority and limits. Fill the brackets; remove none of
the lines.

## To Codex (same machine)
Codex reads `AGENTS.md` at the start, and its session-start hook briefs it from the handoff note, so
opening Codex in the project is enough. When the owner wants to say it explicitly:

    Continue the work in <absolute project path>. Read docs/project/handoffs/latest.md and
    docs/project/state.md first, restate the milestone promise and the must-not-lose items, reconcile any
    file the note lists as changed, then continue with its next step. Keep state.md current as you go and
    record decisions in docs/project/decisions.md when you make them. Stop and ask before any stand-in on
    the product path, contract change, or irreversible action. When done, freeze with `$dev freeze`.

Differences to state when they matter: Codex has no `/dev` stop hook (it runs until its own turn ends, so
the note asks it to finish its Open list), and its checks run under Codex's own sandbox rules.

## To Claude Code (same machine)
Opening Claude Code in the project is enough; the session-start hook briefs it. Explicitly: `/dev resume`.

## To a new session of the same tool
`/dev resume` (or `$dev resume` in Codex).

## To a ChatGPT chat or a colleague (a reviewer with no access to this machine)
Attach `docs/project/handoffs/latest.md` and the files the question needs (never secrets or `.env`), then:

    You are reviewing work in progress on <one-line product description>. The attached handoff note is the
    authoritative state; the attached files are the plan it refers to. Question: <the exact question>.
    Answer only from the attachments and sources you cite; if something is not in them, say so instead of
    guessing. Save your answer as a Markdown document the owner can drop into
    docs/project/research/<slug>.<reviewer>.md: the answer first, then each claim with its source.

The reply comes back through `/scout ingest docs/project/research/<slug>.<reviewer>.md`, never pasted into the
plan directly.
