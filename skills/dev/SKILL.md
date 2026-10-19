---
name: dev
description: "Build one milestone, or an owner-authorized campaign of milestones, as one sustained run against the locked plan: understanding read cold, the load-bearing mechanism first, wired as it goes, then the candidate frozen for the gate. /dev M<k>, /dev M<k>-M<n>, /dev resume (after a break, a compaction, or a switch from another tool), /dev freeze. Use once /plan has locked the intent."
argument-hint: "[M<k> | M<k>-M<n> | resume | freeze]"
hooks:
  Stop:
    - hooks:
        - type: command
          command: "python3 $HOME/.claude/skills/dev/scripts/milestone-continue.py"
---

**Workflow choice, first.** Run `python3 ~/.claude/skills/_shared/scripts/project_policy.py status <project> --json`. OFF or no choice: when the status names the fast workflow, use its matching /<name>-fast skill if it lists one; otherwise do the requested work directly from the existing documents, code, and tests, with no formal step, record, or End chain. ON: the rules below apply; recheck the choice before each next step. Only the owner's explicit on or off, through /pipeline, changes it. Contract: `~/.claude/skills/_shared/references/project-control.md`.

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
- Enough context before code: read every file the milestone touches in full, with its callers and consumers,
  and run what you can; when the record, the code, or a result leaves you unsure, gather more (read, run,
  `/scout`, ask) before writing. Never cut reading, research, or analysis to save turns; economy means not
  repeating work, never knowing less.
- The load-bearing mechanism first, built for real. Final quality: there is no later pass that makes it real.
  A card with a design file (`docs/project/research/design-<card>.md`, from the architect arena) is built to
  that sketch; a departure from it is a decision entry first.
- The moment a placeholder, mock, sample, canned output, or other stand-in on the product path looks needed,
  stop and ask the owner before writing it. Their consent, in their own words, goes in through
  `decisions.py add --source-owner` with the `[placeholder-consent: <path or part> <what> owner <date>]` token
  paired with a named non-goal or a contract-blocked entry. You never write a consent the owner did not give.
- Fail loudly at boundaries. No catch-and-continue with an invented default, no fallback for a case that
  cannot happen; a fallback exists only as a designed, listed, labeled, visible behavior.
- Tests are written with the code and never weakened: no raised timeouts, skipped tests, or removed
  assertions to get green. The gate's `test-tamper` check fails a deleted test, a new skip, only, or
  expected-failure marker, or a raised timeout since the baseline, unless the owner ruled
  `[test-change: <path>]` in decisions.md, and only warns when assertions fall, so that part is yours; the
  gate also warns on a file pushed past 1,000 lines and on slop in outbound text (`gate_checks.py`).
- Wire as you go: when a wiring row moves (built, validated, wired, proven), update its status in
  `milestones.md`. Code outside this milestone is parked unreachable with its re-enable condition.
- Write through: a decision when it is made, through `decisions.py add` (`--proposed` unless the owner
  decided it); `state.md` at every checkpoint and meaningful completion. Before reporting progress, audit each
  claim against a tool result from this session, and say plainly what is not yet verified.
- No build-record IDs (I-D3, L-01, M1.D2) and no intent prose in product code or comments: they are not
  product text, and `gate_copies.py` fails the blind copy on them.
- A new dependency, interface change, migration, or external effect needs a decision entry; if it changes
  the milestone contract, it needs the owner's ruling.

Venture projects (a `truth/` folder): read `~/.claude/skills/_shared/references/venture-mode.md` first; if it is missing, stop BLOCKED.

Scripts: `~/.claude/skills/_shared/scripts/`. `<session>` is this session's ID, as on `state.md`'s Writer line.

## How the work runs
- **Order.** Subtract dead weight and lay the scaffold the later steps stand on; then the load-bearing
  mechanism and the riskiest unknown; then the rest, wiring as you go. Logged findings, polish, and ideas
  outside the contract wait for their slot (the next milestone's Open list or the inbox).
- **Verification ladder.** Each edit: only the typecheck hook (once per turn, when typed files changed). A
  checkpoint: its own `check:` command and the tests of the modules touched, not the full suite or an
  isolated checker. The freeze: nothing extra; the gate's deterministic layer runs first and stops a failing
  round cheaply.
- **Heavy commands** go through the machine lock (the guard hook denies them otherwise):
  `python3 ~/.claude/skills/_shared/scripts/heavy.py run --owner <session> --tail 60 -- <cmd>` prints the exit
  code, the failing lines, and the tail; the full log stays in `.evidence/logs/`. Dev servers run through
  `heavy.py serve` in the background.
- **Two fixes, one premise.** When `heavy.py` prints that a failure has survived 2 fixes, write down the
  premise both fixes shared and test it before a third fix
  (`~/.claude/skills/code-craft/principles/principle-attack-the-premise.md`). Record each refuted approach, with
  its evidence, under Eliminated approaches in `state.md`, so a resumed session does not retry it.
- **Economy.** Quiet flags; do not re-read a file you just wrote; do not re-run a check that passed and whose
  inputs did not change.
- **After a compaction**, `python3 ~/.claude/skills/_shared/scripts/reentry_digest.py <project>` is the
  re-read (the reload gate accepts it); the full files stay one lookup away.

## Start: /dev M<k>
1. `record_check.py`: anything but `complete` means `/plan adopt` first, unless the owner ruled otherwise.
   `intent_lock.py verify` must pass. The milestone is planned or changes; earlier milestones are accepted,
   or covered by a campaign authorization.
2. Read the intent, brief, the milestone contract, interfaces, `AGENTS.md`, the stack pack named in
   `docs/project/gate.md`, and `~/.claude/skills/code-craft/index.md` (once per milestone session; its triggers
   say when a principle or method leaf is read).
3. `baseline.py record <project> M<k>` (it refuses a second baseline: a milestone starts once).
4. `state.md`: the Writer line is claimed for this session by the continuity hook at your first edit (check
   that it names this session: `claude session <id>` or `codex session <id>`), Milestone `M<k> · phase: building`,
   Baseline, the Understanding (the promise and must-not-lose items in your own words), and the Open task
   list. Set the milestone's Status to building.
5. Understanding check: `run_isolated.py cold-reader --dir auto --out .evidence/dev --project <project>
   --render --milestone M<k> --inputs understanding --` in the background. Fix every material divergence in
   your Understanding before code; one the files cannot settle is a question for the owner. Show the owner
   the one-line understanding and keep going.

## Build
Work the Open list in the order above. At each checkpoint run its check, record the result under Done with
the evidence path, and do not build dependents on a failed checkpoint.
For your own look at a UI, use `playwright-cli` (snapshots land in `.playwright-cli/`, which the fingerprint
ignores; the browser lock is taken for you and released by `playwright-cli close`) and build to the design
intent in `intent.md`. Every user interface meets `~/.claude/skills/gate/references/interface-baseline.md`
whatever its style (hidden from the user never means hidden from the log, and every failure with a
consequence shows obviously); before the freeze, run its clarity pass and tell the owner what you removed,
tucked away, or merged. High-stakes design (the design intent says so, or the owner asks):
`references/high-stakes-design.md`.
Own checks: a project-local verification skill, generated once with `~/.claude/skills/code-craft/verify/`
(`/code-craft verify-skill`) and kept in `docs/project/verify/`: local-only, builder-only, never in a checker pack.
Background work (a build, a server, an agent) is listed under In flight while it runs.
Subagents: none by default. A read-only explorer for a genuinely wide unknown, briefed with
`~/.claude/skills/code-craft/brief.md` (the task contract and the result package); parallel builders (at most two
worktrees) only when the owner asks, each given the absolute path of this checkout's build record. A large
mechanical change runs through a saved workflow, never a batch that spawns many agents at once. What the
builder believes about the product (the verification skill, feature maps, explanations) never enters a
checker's pack: a checker that read it would no longer check independently.

## Stops
Input that arrives mid-build goes into the inbox (`inbox.py add`; `/inbox` says when it is weighed) and the
build goes on. The owner's own instruction is a ruling, not an inbox item.
Stop for: a stand-in, a material intent fork, a contract change, an irreversible or credentialed action, or
a blocker only the owner can clear. Every stop first writes a Blockers row (what, who can clear it, what
unblocks it). A question to the owner ends your message with the question. Never end a turn on a plan, a
promise, or an offer while work is still owed; the stop hook (`milestone-continue.py`) holds the turn while
Open items remain. Every stop (a freeze, a question, a blocker, a finished campaign step) ends with the End
record.

## Freeze: /dev freeze (or when the Open list is done)
Every Open item done with evidence; every wiring row proven or parked; servers stopped and leases released
(`heavy.py release --owner <session>`); `state.md` Candidate set to `fingerprint.py <project>` and phase
`gate`; the milestone's Status `gate` (`gate_run.py` refuses a round on any other Status but `accepted`, a
re-gate after a hotfix, and `milestone_lint.py` applies its at-gate rules to Status `gate`). Then start
`python3 ~/.claude/skills/_shared/scripts/gate_run.py <project> --milestone M<k>` in the background and
continue with `/gate` when it reports.

## Resume: /dev resume
Read `state.md`, `docs/project/handoffs/latest.md`, and what the session-start note said changed. When the
note reports work after the last handoff (another session or tool that stopped without updating the record,
for example when its usage limit ran out), fold that work in before building on it:
1. Every decision or instruction in the owner's messages the note quotes goes into the record:
   `decisions.py add` with `--source-owner "<their words>" --session <the session the note names>`; open
   items into state.md. Ask the owner only where two readings of their words would build different things.
2. The files changed since the note may hold a half-finished edit: read the diff, run the test command, and
   either finish the edit to its evident purpose (the other session's last message says what it was doing) or
   revert it, recording which in state.md.
3. Update state.md (Done with evidence, Open, Next step), mark evidence for changed files STALE, keep the
   baseline, restate the Understanding, and continue.
If the note says the other tool is still open in this checkout, ask the owner to close it: one writer per
checkout.

## Campaign: /dev M<k>-M<n>
Only with the owner's authorization, recorded as a decision in their words. Follow `references/campaign.md`.

## End
`python3 ~/.claude/skills/_shared/scripts/project_status.py record <project> --skill dev --arg M<k> --outcome "<one line>"`, then close the report with the Next line it prints (`project-control.md`, End).
