---
name: dev
description: "Build one milestone, or an owner-authorized campaign of milestones, as one sustained run against the locked plan: restate the understanding and have it read cold, record the baseline, build the load-bearing mechanism first with checkpoints, wire as you go, keep state.md current, then freeze the candidate and start the gate. /dev resume continues after a break, a compaction, or a switch from another tool. Use once /plan has locked the intent."
argument-hint: "[M<k> | M<k>-M<n> | resume | freeze]"
hooks:
  Stop:
    - hooks:
        - type: command
          command: "python3 $HOME/.claude/skills/dev/scripts/milestone-continue.py"
---

# /dev

Deliver what the user asked for, at the scope they intended. Interpret ambiguity the way a careful
colleague would: make routine judgment calls yourself, and check in only when different readings would lead
to materially different work. If you conclude the ask is mistaken or a better approach exists, say so in a
sentence and keep going with the task as asked - don't quietly narrow, widen, or transform it. Finish the
whole task, not just the easy part of it - only report completion when it's fully done. If you genuinely
can't complete something, do the rest and state plainly what's missing and why. Stop short of actions or
changes that are clearly beyond what the user's ask implies.
(The user here is the owner; the task is the milestone or campaign.)

Load-bearing rules:
- The load-bearing mechanism first, built for real. Final quality: there is no later pass that makes it real.
- The moment a placeholder, mock, sample, canned output, or other stand-in on the product path looks needed,
  stop and ask the owner before writing it. Their consent, in their own words, becomes a decision entry with
  the `[placeholder-consent: <path or part> <what> owner <date>]` token paired with a named non-goal or a
  contract-blocked entry, proven with `rulings.py record`. You never write a consent the owner did not give.
- Fail loudly at boundaries. No catch-and-continue with an invented default, no fallback for a case that
  cannot happen; a fallback exists only as a designed, listed, labeled, visible behavior.
- Tests are written with the code and never weakened: no raised timeouts, skipped tests, or removed
  assertions to get green.
- Wire as you go: when a wiring row moves (built, validated, wired, proven), update its status in
  `milestones.md`. Code outside this milestone is parked unreachable with its re-enable condition.
- Write through: a decision is written when it is made (`[proposed]` unless the owner decided it); `state.md`
  at every checkpoint and meaningful completion. Before reporting progress, audit each claim against a tool
  result from this session; only report work you can point to evidence for, and say plainly what is not yet
  verified.
- No build-record IDs (I-D3, L-01, M1.D2) and no intent prose in product code or comments: the blind copy
  fails on them, and they are not product text.
- A new dependency, interface change, migration, or external effect needs a decision entry; if it changes
  the milestone contract, it needs the owner's ruling.

Scripts: `~/.claude/skills/_shared/scripts/`. Heavy commands go through the machine lock (the guard hook
tells you the exact wrapped command); dev servers run through `heavy.py serve` in the background.

## Start: /dev M<k>
1. `record_check.py`: anything but `complete` means `/plan adopt` first, unless the owner ruled otherwise.
   `intent_lock.py verify` must pass. The milestone is planned or changes; earlier milestones are accepted,
   or covered by a campaign authorization.
2. Read the intent, brief, the milestone contract, interfaces, `AGENTS.md`, and the stack pack named in
   `docs/project/gate.md`. When the project has a `truth/` folder, read
   `~/.claude/skills/_shared/references/venture-mode.md` (BLOCKED if it is missing).
3. `baseline.py record <project> M<k>` (once per milestone).
4. `state.md`: the Writer line is claimed for this session by the continuity hook at your first edit (check
   that it names this session: `claude session <id>` or `codex session <id>`), Milestone `M<k> · phase: building`,
   Baseline, the Understanding (the promise and must-not-lose items in your own words), and the Open task
   list. Set the milestone's Status to building.
5. Understanding check: `run_isolated.py cold-reader --dir auto --out .evidence/dev --project <project>
   --render --milestone M<k> --inputs understanding --` in the background. Fix every material divergence in
   your Understanding before code; one the files cannot settle is a question for the owner. Show the owner
   the one-line understanding and keep going.

## Build
Work the Open list in the order the contract needs, hard part first. At each checkpoint run its check,
record the result under Done with the evidence path, and do not build dependents on a failed checkpoint.
For your own look at a UI, use `playwright-cli` (headless, token-lean; snapshots land in `.playwright-cli/`,
which the fingerprint ignores; the browser lock is taken for you and released by `playwright-cli close`) and
build to the design intent in `intent.md`; high-stakes design goes through `/taste-design` or `/atelier`
first. Background work (a build, a server, an agent) is listed under In flight while it runs.
Subagents: none by default. A read-only explorer for a genuinely wide unknown; parallel builders (at most
two worktrees) only when the owner asks, each given the absolute path of this checkout's build record. A
large mechanical change runs through a saved workflow, never a batch that spawns many agents at once.

## Stops
Input that arrives mid-build (a suggestion, someone's opinion, an idea the owner floats without deciding) goes
into the inbox (`inbox.py add`, see `/inbox`) and the build goes on; it is weighed at a stop, or at once when it
says the current work is wrong. The owner's own instruction is a ruling, not an inbox item.
Stop for: a stand-in, a material intent fork, a contract change, an irreversible or credentialed action, or
a blocker only the owner can clear. Every stop first writes a Blockers row (what, who can clear it, what
unblocks it). A question to the owner ends your message with the question. Never end a turn on a plan, a
promise, or an offer while work is still owed; the stop hook holds the turn while Open items remain.

## Freeze: /dev freeze (or when the Open list is done)
Every Open item done with evidence; every wiring row proven or parked; servers stopped and leases released
(`heavy.py release --owner <session>`); `state.md` Candidate set to `fingerprint.py <project>` and phase
`gate`; the milestone's Status `gate`. Then start the gate in the background:
`python3 ~/.claude/skills/_shared/scripts/gate_run.py <project> --milestone M<k>` and continue with `/gate`
when it reports.

## Resume: /dev resume
Read `state.md`, `docs/project/handoffs/latest.md`, and what the session-start note said changed. When the
note reports work after the last handoff (another session or tool that stopped without updating the record,
for example when its usage limit ran out), fold that work in before building on it:
1. Every decision or instruction in the owner's messages the note quotes goes into the record: a decision entry
   in their words, proven with the `rulings.py record ... --session <the id the note gives>` it names; open
   items into state.md. Ask the owner only where two readings of their words would build different things.
2. The files changed since the note may hold a half-finished edit: read the diff, run the test command, and
   either finish the edit to its evident purpose (the other session's last message says what it was doing) or
   revert it, recording which in state.md.
3. Update state.md (Done with evidence, Open, Next step), mark evidence for changed files STALE, keep the
   baseline, restate the Understanding, and continue.
The continuity hook records you as the writer on your first edit. If the other tool is still open in this
checkout, the note says so: ask the owner to close it, since two writers in one checkout conflict.

## Campaign: /dev M<k>-M<n>
Only with the owner's authorization, recorded as a decision in their words. Follow `references/campaign.md`.

## End
Every stop (a freeze, a question to the owner, a blocker, a finished campaign step) ends with `python3 ~/.claude/skills/_shared/scripts/project_status.py record <project> --skill dev --arg M<k> --outcome "<one line>"` (the journal and the Last step in state.md), and the report closes with the Next line it prints: what comes next, who takes it, and why. Under `/next auto`, a builder step is taken right away.
