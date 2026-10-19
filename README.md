# Coding Pipeline

A set of skills, checker agents, hooks, and scripts for building software with coding agents (Claude Code,
and Codex alongside it). It is written for current frontier models, which plan, test, and check their own
work well and can run for hours. So it does not script the work. It controls the places where agent-built
software still goes wrong: drifting toward a familiar imitation of what was meant, quietly narrowing or
widening scope, hiding failures behind fallbacks, leaving built parts unwired, calling things done too early,
and losing decisions when context is compacted or work moves between sessions and tools.

The principles are in [`skills/_shared/references/pipeline-constitution.md`](skills/_shared/references/pipeline-constitution.md).

## Choose whether a project is managed

Projects default to **OFF**, including projects with old or partially adopted records. Use `/pipeline on`
(Codex: `$pipeline on`) to enable the formal workflow, `/pipeline off` to disable it immediately, or
`/pipeline status` to inspect the choice. Each command accepts an optional project folder. Type the command:
the model does not start `/pipeline` itself. No adoption or owner ruling is needed to change the choice.

The choice is stored outside the build record in `.coding-pipeline.json`:

```json
{"version": 1, "managed": false}
```

OFF persists across sessions, compaction and Claude/Codex. Existing documents and design remain usable
directly. Old locks, handoffs, missing record files and unfinished adoption never become prerequisites.
Skills remain available as independent tools. The pipeline's automatic hooks, formal checker runners and
continuation stop applying; an in-flight formal run stops when it observes the change. ON preserves the
original gates and owner acceptance rules. Invoking a skill or finding old files never enables management.

Git worktrees share the main checkout's choice. Nested repositories have their own choice. The controller
also conditions recognizable older generated `AGENTS.md` agreements without removing project conventions.
Existing managed projects must explicitly turn ON after this update. A missing, unreadable or invalid selection
is treated as OFF; it cannot silently revive a workflow.

Direct CLI: `python3 ~/.claude/skills/_shared/scripts/project_policy.py off /path/to/project`.

## How work flows

The formal flow below applies when the project is ON.

```
 conversations, voice notes ──/capture──> dossier ──┐
 an existing codebase ────────────/plan adopt───────┤
 an idea ────────────────────────────/plan──────────┴──> intent locked with the owner
                                                              │
    /dev M1  (one sustained run: understanding checked, hard part first, wired as it goes)
      │ freeze
    /gate M1 (copies → deterministic checks → review → blind reconstruction → demo → judge)
      ├─ CHANGES      → /fix or /dev, then the next round
      └─ ACCEPT-READY → the owner watches the demo and accepts → /dev M2 ...
```

Work is cut into **milestones**: complete product states a person can use end to end, each with a demo
that proves it. Verification happens only at the joints (the intent lock, the builder's restated
understanding, a few load-bearing checkpoints, the milestone gate, and irreversible actions), never as a
ritual inside the build.

## Skills

| Command | What it does |
|---|---|
| `/next` | The front door: where the project stands and what comes next, computed from the record, then does it; `auto` keeps going step after step and stops only where the owner must decide; `status` only reports. Every skill ends by recording its step in a journal and naming the next one |
| `/capture` | Keeps and understands what a project's ideas and knowledge live in (ChatGPT chats, voice recordings, notes, documents in Markdown, PDF, Word, and similar formats, records and logs; a file or a whole folder), verbatim in numbered units, organized into a dossier that cites every point and keeps the owner's words apart from an assistant's; an isolated reader drafts it from the sources (every load-bearing point, quoted), a second audits it against them until an audit finds nothing material, and the spend stays within the owner's budget (5 percent of the week, stopping at 10 until the owner raises it) |
| `/scout` | Turns a real unknown into graded evidence: ask, map, spike, or offload to a chat model and verify what comes back |
| `/plan` | Writes the build record and locks the intent with the owner; `adopt` takes over a project that has no record; `amend` changes intent by ruling; `convert` migrates older formats |
| `/dev` | Builds one milestone (or an authorized run of several) as one sustained run; `resume` after a break or a switch of tools; `freeze` hands it to the gate |
| `/gate` | Accepts or rejects a milestone through isolated checkers and a computed verdict; `accept` records the owner's acceptance |
| `/loyal` | Checks mid-build whether what was built is still the thing that was meant |
| `/fix` | Makes a targeted change outside a milestone, reproduction first |
| `/handoff` | Hands work over on purpose, to another session, another tool, or an outside reviewer |
| `/inbox` | Keeps other people's opinions, proposed changes, and new ideas in their own words until they are weighed: each is checked against the locked intent and earlier decisions, researched where it rests on a claim, adopted whole, in part, reshaped, placed in a milestone, or rejected (by the owner unless it is a whole adoption inside the current contract), written where it belongs, and cleared with a decision entry; the gate fails on any item that vanished |
| `/deploy` | Ships behind a plain-English confirmation of each irreversible action, then verifies the live product |
| `/explain` | Explains what exists to an engineer, founder, investor, or user |
| `/polish` | Optional outside-in scrutiny before real users see it |
| `/evolve` | Improves the pipeline itself from real use: in any session that used it, harvests every failure, block, stuck step, and piece of friction with what the session did about it into a private ledger; then proves each problem with a reproduction, weighs the fix against the session's own workaround, and keeps a change only when a rule fixed in advance says the pipeline got better (the reproduction flips, nothing measured gets worse, both sides measured alike) and an isolated reviewer finds the cause removed and nothing weakened |
| `/craft` | Code craft vendored from pstack and read on demand: `review` (a read-only review of the current diff), `architect`, `blast-radius`, `unslop`, `verify-skill`, and `pr <open \| check \| babysit \| ship>`; usable on projects where the pipeline is OFF. Pipeline steps open the same files when their trigger fires |

`/pipeline`, `/evolve`, and `/polish` run only when you type them: they are left out of the model's skill listing
(`disable-model-invocation`), so the model never starts them on its own or from another skill.

## Checkers

Each runs as a separate headless process in a prepared copy of the project, under the operating system's
sandbox, with its inputs rendered by a script from files. None sees the builder's conversation. Each run's
model and effort come from the routing table, `skills/_shared/models.json` (`models.py list` shows them), by
route: the checker, and its mode where the modes judge different things (the code-verifier's review, re-verify,
and demo; the cold-reader's documents, re-read, understanding, extraction, fidelity, and re-audit). The agent
file sets neither, and each run gets only its own mode's part of it. Every route runs today's setting until a
change to it passes the measurements in [`docs/model-routing.md`](docs/model-routing.md) (pooled fixtures,
cost, shadow runs beside real rounds) and the owner approves it. `spend.py report` shows what each milestone,
round, and checker cost.

| Agent | Catches |
|---|---|
| `code-verifier` | a build that passes its own tests while the core mechanism is a familiar imitation, or failure paths quietly degrade; structural damage, logged unless it is one of four presumptive blockers; in a focused round, whether the open findings are fixed; also runs the demo from a clean start |
| `loyal-evaluator` | a product that works but is no longer the thing that was meant: it describes what the product does and guesses its purpose before it is told the goal |
| `gate-judge` | a verdict that grades the builder's story instead of the evidence |
| `cold-reader` | a document clear to its author that admits several builds; a restatement that shifted the promise; a summary that lost or bent its source |
| `claim-verifier` | a research claim resting on one reprinted, misread, or outdated source |
| `change-reviewer` | a change to the pipeline that turns its reproduction green while the cause survives, loosens a check, hides a failure, or is labeled a fix to skip the owner's ruling |

## The build record

`AGENTS.md` (the map: labeled commands, conventions, a working agreement every agent reads) plus
`docs/project/`: `intent.md` (locked and hashed), `milestones.md`, `interfaces.md`, `decisions.md`,
`fix-log.md`, `inbox.md` (input waiting to be weighed), and local-only working files (`brief.md`, `state.md`, `gate.md`, handoff notes, gate reviews,
research, captured sources, evidence). Templates are in `skills/_shared/templates/`.

## Guarantees enforced in code

- **Isolation.** Checkers run with no user settings, no plugins or MCP servers, only the tools they need,
  reads fenced to their own copy and toolchains, writes fenced to the copy and caches, network limited to
  localhost (a Codex-family checker also reaches HTTPS, because its own model call runs inside the same fence),
  and a canary planted in the real project for every round: a checker that reads it fails the round.
- **Owner's words.** Only messages the owner typed count: agent reports and harness notices that arrive in
  the user role are never taken as the owner's ruling, and a quoted ruling must equal the words recorded.
- **Owner rulings.** The intent lock, milestone acceptance, and any consent to a stand-in quote the owner's
  own words, and a script proves those words are a whole sentence (or the whole message) the owner typed, so a
  cut quote cannot drop a "no". An acceptance names the
  exact candidate that passed its gate, and a release ships only that candidate.
- **Nothing silent.** Every non-success has a name (FAIL, NOT_RUN, BLOCKED, INCONCLUSIVE, STALE, and the rest),
  missing inputs are named, and the verdict is recomputed from the evidence.
- **Handoffs.** A handoff note is rewritten at every stop and checked for anything dropped; a new session in
  either tool is told who worked last, what changed since, and what is next.
- **Compaction.** After a compaction, edits wait until the state files have been read again.
- **Machine load.** One heavy job (build, test suite, browser, simulator) runs at a time on the machine, through
  a kernel lock; subagent concurrency and depth are capped.

## Install

```
python3 install.py plan          # every action, nothing changed
python3 install.py apply         # install into ~/.claude, archive retired pieces, write a manifest,
                                 # and bring Codex's copies up to date when a Codex package is installed
python3 settings_patch.py        # show the hook registrations; add --apply to write them (with a backup)
python3 codex_hooks_patch.py     # the same for Codex; Codex asks you to trust new hooks once
python3 install.py check         # prove the installed files match this repository, with no shadow copies
```

`apply` puts the skills (the craft layer included) in `~/.claude/skills/`; the shared scripts, templates,
references, and the routing table (`models.json`) in `~/.claude/skills/_shared/`; the checkers in
`~/.claude/agents/`; and the hooks in `~/.claude/hooks/`. Its manifest, `~/.claude/.pipeline-install.json`, records
every installed file's hash, and the routing table's on its own. Your personal routing override
(`~/.claude/.pipeline-models.json`) and shadow-run records (`~/.claude/.pipeline-shadow.jsonl`) are never touched.

Tests: `bash tests/pipeline-selftest.sh` runs every script and hook suite and the static checks.
`python3 tests/agent_fixtures.py` runs each checker against planted-defect and clean projects, three times each,
on its route's setting (`--model` and `--effort` measure another).

Requirements: macOS (the sandbox and copy-on-write clones), Python 3.9+, Claude Code 2.1.283 or later,
Playwright for Python with Chromium (the checkers' browser), and `playwright-cli` (the builder's browser);
`install.py check` fails when one is missing. Optional: Codex CLI (the other model family for code review),
whisper (audio capture).

A local `private/` folder, if present, is installed over the same paths (the owner's standing requirements
and any private rules) and carries its own tests, which the self-test runs; it is never published.

## Updating the pipeline

Type `/pipeline update` in any session. It pulls the repository `~/.claude` was installed from (fast-forward
only: a diverged branch is reported, never merged; a failed fetch goes on with the local commits), runs
`install.py apply` and `settings_patch.py --apply`, proves the result with `install.py check`, and reports the
revisions before and after, the commits between them, and which skills, agents, hooks, and shared files
changed. It refuses while the repository has uncommitted changes or untracked files under `skills/`, `agents/`,
or `hooks/` (an edit in progress is never installed half-done) and while a gate or checker run is in progress.
`/pipeline status` shows what is installed and what the repository holds. Nothing pulls or installs in the
background.

When the fast workflow (mAE7777/coding-pipeline-fast) is installed, `/pipeline update` updates it too: after the
pipeline's own part, it runs `install.py update` in the repository fast's manifest
(`~/.claude/.pipeline-fast-install.json`) names, which refuses, pulls, and installs by the same rules, and reports
it on its own `fast:` lines. One part's refusal never stops the other; the command exits 1 when either was
refused or failed. A fast install made before fast's `update` existed records no repository: run
`python3 install.py apply` once in the fast repository. `/pipeline status` and the two notices below cover fast
as well.

What a running session keeps: Claude Code gives the next invocation of a skill its changed SKILL.md, but a skill
already invoked stays in the conversation as the text it read then, and its frontmatter hooks stay as they were
registered at that invocation. Scripts, hook scripts, and checker agents are read from `~/.claude` at each call,
so they run the new version at once. Two hooks close the gap. At session start, a session is told when the
repository holds commits not installed yet. At the first prompt after an update, every open session is told,
once, that the skill text it read is out of date: re-read the SKILL.md of the skill in use and the references
the next step relies on, or invoke the skill again (which also registers its new hooks); the changed skills are
named (the notice speaks of the fast skills when only fast changed). Claude Code's settings watcher usually picks
up new hook registrations in open sessions; a restart does when it does not. Codex sessions get neither notice,
since Codex has no such hook: after an update, start a new Codex session or re-read the skill in use.

Once, on a machine whose installed copy predates this: run `python3 install.py apply` and
`python3 settings_patch.py --apply` from the repository. From then on `/pipeline update` does both.
