# Pipeline charter

The principles behind the coding pipeline: `/next`, `/capture`, `/scout`, `/plan`, `/dev`, `/gate`, `/loyal`,
`/fix`, `/handoff`, `/inbox`, `/deploy`, `/explain`, `/polish`, `/evolve`. Written for frontier agents (Claude Opus 5.5 and
GPT-6 Astra class), in Claude Code and in Codex. Each skill carries its own rules; this file is the reason
they are shaped the way they are, and the tie-breaker when a situation is not covered.

## Why the pipeline looks like this
Current models plan, decompose, write tests, and check their own work well, and they sustain multi-hour
runs. Scripting those steps now makes results worse: step choreography, verification rituals, and
pressure language are the patterns vendors tell you to delete. What still goes wrong is judgment:
drifting toward a familiar imitation of what was meant, quietly narrowing or widening scope, hiding
failure behind a fallback, leaving built parts unwired, claiming "done" early, and losing decisions across
compaction, handoffs, and switches between tools. The pipeline controls those failure points and nothing
else. A rule earns its place only if a strong model does measurably worse without it, and anything a script
can enforce is enforced by a script or a hook rather than asked for in prose.

## The six laws
1. **Brief, don't script.** Give the situation (goal, users, expectations, constraints with their reasons,
   the verified starting state, context, trade-offs, unknowns, when to stop) and the finish line.
2. **Milestones are the unit of truth.** A milestone is a complete product state a real person can use end to
   end, with a demo that proves it; built as one sustained run, verified at its gate, accepted by the owner.
   The builder's own task list lives inside it and is never gated.
3. **Prove at the joints, isolated by process where not knowing is the point.** The joints: the intent lock,
   the builder's restated understanding, load-bearing checkpoints, the milestone gate, irreversible actions.
   Self-checking during the build is the model's own loop and is never instructed or delegated. Independent
   checks run as separate processes in prepared copies under an OS sandbox, with inputs rendered by script
   from files, so isolation never depends on prompt text or on the builder's wording.
4. **Nothing silent.** Every non-success has a name and a count; every built part is wired and proven, or
   parked and unreachable; every fact carries its source and date; evidence from another fingerprint is STALE.
5. **Enough context, within the owner's budget.** Every load-bearing point is read and checked; a detail that
   decides nothing stays one lookup away in the verbatim sources rather than being read again and again. Every
   loop (audits, cold reads, the fix loop) ends when a pass finds nothing material, never at a count; a count
   only changes the method or asks the owner. Spend is measured per phase (`spend.py`): capture and adoption
   stay within 5 percent of the week and stop at 10 until the owner raises it, told plainly what a smaller plan
   would leave unread. Economy also means never paying twice for the same work.
6. **Disk is truth, context is cache.** Decisions, state, and evidence are written when they happen; the
   owner's instructions count once written down, in their own words, proven against the transcript;
   handoffs pass references and fingerprints; after a compaction, writes wait until the state files are read.

## The flow
Ideas from conversations are kept whole by `/capture` until the owner decides to build. `/plan` turns an
idea, a dossier, or an existing project (`/plan adopt`) into the build record and locks the intent with the
owner. `/dev` builds one milestone; `/gate` accepts or rejects it through isolated checkers; the owner
accepts it by watching the demo. Input that arrives while building (other people's opinions, proposed
changes, new ideas) waits in the inbox, verbatim, until `/inbox` weighs it and the owner rules; it enters the
record only through a decision. `/scout` answers real unknowns, `/fix` makes targeted changes, `/handoff`
moves work between sessions and tools on purpose (switching tools is automatic), `/deploy` ships, `/explain`
tells any audience what exists, `/polish` scrutinizes a product from outside. The owner never has to know which
step comes next: `project_status.py` computes it from the record, every skill ends by recording its step and
naming the next one, and `/next` (or `/next auto`, which chains steps until the owner must decide) takes it.
The pipeline improves from its own use: `/evolve` turns what went wrong in a session into incidents, and
changes the pipeline only when a reproduction proves the problem and a rule fixed before the change,
applied to both sides measured alike, says the result is better.

## The build record
`AGENTS.md` (the map: labeled commands, conventions, a working agreement both tools read) plus
`docs/project/`: `intent.md` (locked and hashed; changed only by an owner-ruled re-freeze), `milestones.md`,
`interfaces.md`, `decisions.md` (append-only), `fix-log.md`, `inbox.md` (all committed); `brief.md`, `state.md`,
`gate.md`, `handoffs/`, `reviews/`, `research/`, `sources/`, `.evidence/`, and by default `AGENTS.md` and
`CLAUDE.md` (local-only, through git's local exclude file written by `local_only.py`, never `.gitignore`). One concern, one file: new input goes into the right file with its
source, the old entry marked superseded. Templates are in `_shared/templates/`.

Authority when sources disagree: the owner's latest instruction once written down, then `intent.md`, then
active constraints, then the milestone contract, then `interfaces.md`, then code and tests (facts about the
tree, not proof of intent). A conflict is reported, never settled by picking the convenient side.

## Statuses
Checks: PASS · FAIL · WARN · SKIP (does not apply, with the reason) · NOT_RUN (could not run, with the
reason) · BLOCKED (owner and unblock condition) · INCONCLUSIVE (the checker could not ground itself) ·
STALE · QUARANTINED (a flaky test, with owner, reason, expiry). Behavior: HOLDS · FAILS · UNGROUNDED. Intent
diff: HOLDS · DRIFT · MISSING · EXTRA · ORPHAN · INACCURATE (the right name with a changed causal role).
Wiring: UNWIRED · UNCONSUMED · PHANTOM. Gate: ACCEPT-READY · CHANGES · BLOCKED · INCONCLUSIVE. Milestone:
planned · building · gate · changes · accepted · dropped. Readiness: built · gate-passed · accepted ·
released · live-verified, five different facts. A report shows counts; one green word never covers a NOT_RUN.

## Human gates
The owner is asked only where their judgment cannot be replaced: the intent lock; any stand-in on the product
path; milestone acceptance (watching the demo); each irreversible or credentialed action; a material fork the
documents do not settle; a finding that survived two fix rounds; a real change of scope; a change of intent;
declining or reshaping someone's input.
Routine choices are made and logged.

## Resources
Model thinking is remote and costs tokens; builds, tests, servers, browsers, and simulators are local and cost
heat. Per session at most 3 agent contexts at once (subagents plus isolated runs), at most 5 subagents at
once, nesting depth 2; workflows run at most 3 agents at once. Machine-wide at most 1 heavy job, through the
kernel lock and leases in `_shared/scripts/heavy.py`, enforced by a hook. Subagents are for isolation or for
large independent work that would flood the context, never for double-checking one's own work, and not
in capture or adoption, where reading is the builder's or an isolated run's so its cost stays bounded and measured.

## Writing the skills
Each SKILL.md stays under about 200 lines with its load-bearing rules first, states outcomes and
constraints with their reasons, keeps curated knowledge in references loaded on demand, and names the one
failure each checker exists to catch. Owner-facing text decodes on its own: plain meaning first, any ID only
in parentheses after it.

## Output that leaves the machine
Commits, READMEs, changelogs, and shipped text read as written by a human developer: no AI or tooling
traces, no skill or agent names, and no spaced em-dashes. Committed planning files use neutral labels
(`[owner <date>]`, `[proposed]`, `[research <ref> <grade>]`, `[environment <date>]`); files that name models
and tools stay local.
