# <Project name>

<!--
The project map for any coding agent or new contributor. Short: what is where, how to run things, the
conventions that are not obvious from the code. CLAUDE.md holds one line: @AGENTS.md
Local-only by default (local_only.py keeps it out of commits), since the session section names the
pipeline's tools; gate keys live in docs/project/gate.md. Everything else in plain developer language.
-->

## Map
- <folder> · <what lives there>

## Commands
<!-- one labeled line each, plain: checkers and the demo run exactly these, and the gate takes the machine lock for them -->
install: <command>
build: <command>
test: <command>
run: <command>
demo: <command that starts the product the way the demo ending needs, or the same as run>

### Running them in a session
When the pipeline manages this project, run a heavy command (install, build, test, typecheck) through the
machine lock with bounded output, so the guard never has to deny it first:
`python3 ~/.claude/skills/_shared/scripts/heavy.py run --owner <session> --tail 60 -- <command>`.
It prints the exit code, the failing lines, and the last 60 lines; the full log stays in `.evidence/logs/`.
Run a server (run, demo) in the background:
`python3 ~/.claude/skills/_shared/scripts/heavy.py serve --owner <session> -- <command>`.
`<session>` is this session's ID.

## Conventions
- <the non-obvious rules: naming, error handling, where state lives, what never to import>

## Working agreement
<!-- coding-pipeline-policy:v1 -->
The coding-pipeline working agreement below applies only when this project's
`.coding-pipeline.json` explicitly sets `managed` to `true` (shared by Git worktrees).
Otherwise follow the user's current request and existing project documents directly;
adoption, owner lock, record maintenance, handoff intake and milestone stop rules
are not prerequisites. Pipeline skills may be used as independent tools without
enabling the workflow. This choice also applies after resume or compaction.

- The plan, decisions, and current state live in docs/project/. Start by reading docs/project/state.md and
  docs/project/handoffs/latest.md; they say who worked last, what is open, and the next step. Then run
  `python3 ~/.claude/skills/_shared/scripts/continuity.py recover .`: it prints work another session did after
  that note (the owner's words there, verbatim), which goes into the record before you build on it.
- One writer at a time in this checkout. When you start changing files, you are the writer: your name
  goes on the Writer line of state.md.
- Keep state.md current as you go (Done with evidence, Open, In flight, Blockers, Next step), and write a
  decision into docs/project/decisions.md when it is made, not at the end.
- docs/project/intent.md is locked; only the owner changes what it says.
- Suggestions, proposed changes, and new ideas from anyone go into docs/project/inbox.md (`python3 ~/.claude/skills/_shared/scripts/inbox.py add`),
  not straight into the work; each leaves the inbox only with a decision in docs/project/decisions.md.
- Long builds and test suites run one at a time on this machine; the local wrapper makes them wait their turn.

When compacting, keep the current milestone ID, the open checklist, files modified, failing checks, and
any decision not yet written to docs/project/decisions.md (write it first).
