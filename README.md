# Coding Pipeline

Skills, checker agents, hooks, and scripts for building software with Claude Code, with Codex alongside. The
models plan, build, and test their own work well, so the pipeline does not script that work. It guards the
places where agent-built software still goes wrong:

- a familiar imitation built in place of what was meant;
- scope quietly narrowed or widened;
- failures hidden behind fallbacks;
- parts built but never wired in;
- work called done too early;
- decisions lost when context is compacted or work moves between sessions and tools.

The principles are in [`skills/_shared/references/pipeline-constitution.md`](skills/_shared/references/pipeline-constitution.md).

## This pipeline or the fast one

This repository is the full workflow. It suits a project that needs a locked intent, gated milestones, and a
record that outlasts any one session. For tools, scripts, prototypes, small apps, and everyday changes, use
[coding-pipeline-fast](https://github.com/mAE7777/coding-pipeline-fast): one plan file, one concentrated
verification, fewer tokens. Both can be installed together. The full workflow runs only in a project you turn
on. In every other project, a full skill that has a fast counterpart points to it when fast is installed.

## Turn the workflow on or off for a project

A project is OFF until you type `/pipeline on` (Codex: `$pipeline on`). `/pipeline off` turns it off at once.
`/pipeline status` shows the choice and what is installed. Each command takes an optional project folder. The model never runs
`/pipeline` by itself, and no skill, old record, or finished adoption turns a project on.

The choice lives in `.coding-pipeline.json`, outside the build record:

```json
{"version": 1, "managed": false}
```

A missing, unreadable, or invalid file means OFF. Git worktrees share the main checkout's choice, and a nested
repository has its own. From a shell: `python3 ~/.claude/skills/_shared/scripts/project_policy.py off <project>`.

While a project is OFF, the skills still work as tools on its existing documents, design, and code. Old locks,
handoff notes, and unfinished adoptions are never prerequisites. The hooks, the formal checker runs, and the
journal stay out of the way, and a formal run in progress stops when it sees the switch. When a project is
ON, every gate and owner-acceptance rule applies.

When the choice changes, an `AGENTS.md` working agreement that an older version of the pipeline generated gets
the new workflow-choice paragraph. Any other `AGENTS.md` is left alone.

## How work flows

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

Work is cut into milestones. A milestone is a product state a person can use end to end, with a demo that
proves it. Verification happens only at the joints: the intent lock, the builder's restated understanding, a
few load-bearing checkpoints, the milestone gate, and irreversible actions. It never runs as a ritual inside
the build.

## Skills

| Command | What it does |
|---|---|
| `/next` | Says where the project stands and what comes next, then does it. `auto` keeps going until the owner must decide; `status` only reports. |
| `/capture` | Turns chats, recordings, notes, and documents (a file or a folder) into a dossier that cites every point and keeps the owner's words apart from an assistant's. One isolated reader drafts it and another audits it against the sources, within a spending cap the owner sets. |
| `/scout` | Settles an unknown with graded evidence: a question, a map of the code, a spike, or a chat model's answer checked against sources. |
| `/plan` | Writes the build record and locks the intent with the owner. `adopt` takes over a project without a record, `amend` changes the intent by the owner's ruling, `convert` migrates older formats. |
| `/dev` | Builds one milestone, or a run the owner authorized, in one sustained run. `resume` continues after a break or a tool switch; `freeze` hands the milestone to the gate. |
| `/gate` | Accepts or rejects a milestone through isolated checkers and a computed verdict. `accept` records the owner's acceptance. |
| `/loyal` | Checks during a build whether what exists is still the thing that was meant. |
| `/fix` | Makes a targeted change outside a milestone, starting from a reproduction. |
| `/handoff` | Hands work to another session, another tool, or an outside reviewer. |
| `/inbox` | Holds other people's opinions, proposals, and ideas in their own words until they are weighed against the locked intent, then records what was adopted or rejected and why. The gate fails when an item disappears. |
| `/deploy` | Ships after a plain-words confirmation of each irreversible action, then checks the live product. |
| `/explain` | Explains what exists to an engineer, a founder, an investor, or a user. |
| `/polish` | An optional outside-in pass before real users see the product. |
| `/evolve` | Improves the pipeline from real use. It collects failures and friction from sessions, reproduces each one, and keeps a change only when the reproduction flips, nothing measured gets worse, and an isolated reviewer finds the cause removed. |
| `/code-craft` | Code-craft methods from pstack, read on demand: `review`, `architect`, `blast-radius`, `unslop`, `verify-skill`, and `pr <open \| check \| babysit \| ship>`. It works in OFF projects too. |
| `/pipeline` | Turns the workflow on or off for a project, shows its status, and updates the installed pipeline (`update`). |

`/pipeline`, `/evolve`, and `/polish` run only when you type them. Their `disable-model-invocation` setting
keeps them out of the model's skill list.

## Checkers

Each checker runs as a separate headless process in a prepared copy of the project, under the operating
system's sandbox. A script renders its inputs from files, and no checker sees the builder's conversation.

| Agent | Catches |
|---|---|
| `code-verifier` | A build that passes its own tests while its core mechanism is a familiar imitation, or its failure paths quietly degrade. Structural damage, logged unless it is one of four presumptive blockers. In a focused round, whether the open findings are fixed. It also runs the demo from a clean start. |
| `loyal-evaluator` | A product that works but is no longer the thing that was meant. It describes the product and guesses its purpose before it is told the goal. |
| `gate-judge` | A verdict that grades the builder's story instead of the evidence. |
| `cold-reader` | A document clear to its author that still admits several builds, a restatement that shifted the promise, or a summary that lost or bent its source. |
| `claim-verifier` | A research claim that rests on one reprinted, misread, or outdated source. |
| `change-reviewer` | A change to the pipeline that turns its reproduction green while the cause survives, loosens a check, hides a failure, or skips the owner's ruling. |

The routing table, `skills/_shared/models.json`, sets each checker's model and effort, per mode where the
modes judge different things (`python3 ~/.claude/skills/_shared/scripts/models.py list` shows it). A route
changes only after the measurements in [`docs/model-routing.md`](docs/model-routing.md) pass and the owner
approves. `spend.py report` shows what each milestone, round, and checker cost, in tokens and dollars.

## The build record

`AGENTS.md` is the map every agent reads: labeled commands, conventions, and the working agreement. Beside it,
`docs/project/` holds:

- committed: `intent.md` (locked and hashed), `milestones.md`, `interfaces.md`, `decisions.md`, `fix-log.md`,
  and `inbox.md`;
- local only: `brief.md`, `state.md`, `gate.md`, handoff notes, gate reviews, research, captured sources, and
  evidence.

The templates are in `skills/_shared/templates/`.

## Guarantees enforced in code

- **Isolation.** A checker gets no user settings, plugins, or MCP servers, and only the tools it needs. Its
  reads are fenced to its copy and the toolchains, its writes to the copy and caches, and its network to
  localhost. A Codex-family checker also reaches HTTPS, because its own model call runs inside the fence. Every
  round plants a canary in the real project, and a checker that reads it fails the round.
- **The owner's words.** Only messages the owner typed count. Agent reports and harness notices that arrive in
  the user role never count as a ruling.
- **Owner rulings.** The intent lock, a milestone acceptance, and consent to a stand-in quote the owner. A script
  proves each quote is a whole sentence (or the whole message) the owner typed, so a cut quote cannot drop a
  "no". An acceptance names the exact candidate that passed its gate, and a release ships only that candidate.
- **Nothing silent.** Every non-success has a name (FAIL, NOT_RUN, BLOCKED, INCONCLUSIVE, STALE, and others).
  Missing inputs are named, and the verdict is recomputed from the evidence.
- **Tests stay honest.** `gate.sh` fails a deleted test, a test moved out of the runner's collection, a new
  skip, only, or expected-failure marker, and a raised timeout, unless the owner ruled the change. Fewer
  assertions is a warning.
- **Handoffs.** The handoff note is rewritten at every stop and checked for anything dropped. A new session in
  either tool is told who worked last, what changed since, and what is next.
- **Compaction.** After a compaction, edits wait until the state files are read again.
- **Machine load.** A kernel lock lets one heavy job (a build, a test suite, a browser, a simulator) run at a
  time on the machine. Subagent concurrency and depth are capped.

## Techniques and references

- **The craft layer** (`skills/code-craft/`) is pstack 0.15.25 from
  [cursor/plugins](https://github.com/cursor/plugins), vendored under its MIT license (`LICENSE-pstack`,
  provenance in `UPSTREAM.json`). `/code-craft` opens a method directly, and pipeline steps open the same files
  when their trigger fires. `index.md` says where the pipeline's rules win. The skill is named `code-craft`,
  not `craft`, so installing it never replaces a `/craft` skill you already have.
- **The agent-product reference** (`skills/_shared/references/agent-product/`) compresses the AI Engineering
  Handbook's controls for a product that runs agents or causes outside effects (payments, messages, bookings,
  publishing). `/plan` reads it at intake for such a product. [`docs/handbook-adoption.md`](docs/handbook-adoption.md)
  records which handbook chapters apply and why.

## Install

```
python3 install.py plan          # list every action, change nothing
python3 install.py apply         # install into ~/.claude, archive retired pieces, write the manifest,
                                 # and update Codex's copies when a Codex package is installed
python3 settings_patch.py        # show the hook registrations; --apply writes them (with a backup)
python3 codex_hooks_patch.py     # the same for Codex, which asks you to trust new hooks once
python3 install.py check         # prove the installed files match this repository, with no shadow copies
```

`apply` installs the skills in `~/.claude/skills/`, the shared scripts, templates, references, and routing table
in `~/.claude/skills/_shared/`, the checkers in `~/.claude/agents/`, and the hooks in `~/.claude/hooks/`. Its
manifest, `~/.claude/.pipeline-install.json`, records each installed file's hash. `apply` stops at a file you
edited under `~/.claude` and names it. It never touches your routing override (`~/.claude/.pipeline-models.json`)
or your shadow-run records (`~/.claude/.pipeline-shadow.jsonl`).

A local `private/` folder, if present, is installed over the same paths (the owner's standing requirements and
private rules) with its own tests, which the self-test runs. It is never published.

Requirements: macOS (the sandbox and copy-on-write clones), Python 3.9 or later, Claude Code 2.1.283 or later,
Playwright for Python with Chromium (the checkers' browser), and `playwright-cli` (the builder's browser).
`install.py check` fails when one is missing. Optional: the Codex CLI (the second model family for code review)
and whisper (audio capture).

Tests: `bash tests/pipeline-selftest.sh` runs every script and hook suite and the static checks.
`python3 tests/agent_fixtures.py` runs each checker against projects with planted defects and clean controls,
three times each, on its route's setting (`--model` and `--effort` measure another).

## Update

Type `/pipeline update` in any session. It does four things:

1. It pulls the repository that `~/.claude` was installed from, fast-forward only. A diverged branch is reported,
   never merged, and a failed fetch goes on with the local commits.
2. It runs `install.py apply` and `settings_patch.py --apply`.
3. It proves the result with `install.py check`.
4. It reports the revisions before and after, the commits between them, and the skills, agents, hooks, and
   shared files that changed.

It refuses while the repository has uncommitted changes, or untracked files under `skills/`, `agents/`, or
`hooks/`, and while a gate or checker run is in progress. Nothing pulls or installs in the background.

When coding-pipeline-fast is installed, the same command updates it after the pipeline: it runs fast's
`install.py update`, which follows the same rules, and reports on its own `fast:` lines. One part's refusal never
stops the other. A fast install made before fast had `update` needs `python3 install.py apply` once in the fast
repository.

An open session keeps the skill text it already read. Scripts, hook scripts, and checker agents run the new
version at their next call. Two hooks tell you what is stale:

- At session start, you hear when the repository holds commits that are not installed.
- At the first prompt after an update, each open session is told once which skills changed. Re-read the
  SKILL.md of the skill in use, or invoke the skill again.

Codex has no such hooks: after an update, start a new Codex session.

On a machine whose installed copy predates `/pipeline update`, run `python3 install.py apply` and
`python3 settings_patch.py --apply` once from the repository.
