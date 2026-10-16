# Craft index

The pipeline constitution (`skills/_shared/references/pipeline-constitution.md`) and the active skill's human gates win every conflict with any file in this folder.

Read this file once per milestone or fix session. Open a leaf only when its trigger fires. Paths are relative to this folder.

## Where this pipeline's rules win

- **never-block-on-the-human** ("reversible actions proceed") covers only choices the human-gates list does not name. Those are made and logged.
- **experience-first** ("ship less, ship better") covers design choices inside the locked contract. Narrowing the contract is the owner's ruling.
- **guard-the-context-window** ("route bulk to subagents") covers bulk tool output, logs, and wide sweeps for unknowns, never the files the milestone touches.
- **session-pickup** ("the trail is authoritative") gives only "do not redo finished work". On resume, still read the diff and run the tests.
- **tdd** ("prefer no new test over a bad test") does not apply. The regression test stays required, written to encode intended behavior and seen to fail for the intended reason.
- **Autonomy** ("external actions proceed") does not apply. Irreversible and credentialed actions wait for the owner.
- **Delegation and fan-out** in any method happen only where the active skill allows a subagent. Otherwise do the step yourself.
- **architect** runs only for a mechanism card marked `Reversibility: one-way`, or on the owner's request. Other boundary-crossing code gets `design/design-red-flags.md` and `design/rationale-template.md`.

Leaves keep pstack's names. `how` is `explore/explorer-prompt.md` and `explainer-prompt.md`. `why` is `explore/code-archaeology.md` and `epistemics.md`. `architect` and `arena` are `design/`, `interrogate` is `review/`, `unslop` is `writing/`, and a principle skill is its file in `principles/`. Feature is `/dev` with `methods/feature-shape.md`. Opening a PR, Babysit, and Shipping are `methods/pr/`. figure-it-out is a milestone through `/plan`. show-me-your-work is the build record. A skill not named here is not installed.

## Triggers

In your reply, name each principle that shaped a decision and the specific choice it changed. Cite only principles whose file you read this session.

- **Any code.** Name the data shape first. Nontrivial multi-step work also gets the throughput checkpoint (`methods/feature-shape.md`).
- **A bug.** `methods/bug-fix.md`. A fix in shared code also gets `review/blast-radius.md`.
- **A refactor.** `methods/refactoring.md`.
- **A fork a run can settle.** `methods/prototype.md` through `/scout spike`. Only product and preference calls go to the owner.
- **A number you measured.** `methods/perf.md` before you report or act on it.
- **A runtime symptom or a captured profile.** `methods/forensics.md`. Pixel parity is `methods/visual-parity.md`.
- **Driving the app for your own check or repro.** `playwright-cli` for web, or the verification skill at `docs/project/verify/` (`verify/`). It stays out of every checker pack.
- **A subagent.** `brief.md`.
- **Prose that leaves the machine.** `writing/unslop.md` and `writing/technical-writing.md`. Commits and PR text also follow `writing/commits-and-prs.md`.
- **Comments in your diff.** `review/comment-keep-list.md`.
- **A pull request.** `methods/pr/`.

## Principles

Read the leaf in full for any principle you apply. Each entry names when it applies. Each leaf is `principles/principle-<title>.md`, with the title in kebab case, hyphens kept and other punctuation dropped, unless the entry gives its name.

**Core**

- **Laziness Protocol.** Refactoring, sizing a diff, or tempted to add abstractions, layers, or signal threading. Bias to deletion and the smallest change that solves the problem.
- **Foundational Thinking.** Before writing logic: core types and data structures, scaffold-vs-feature sequencing, what concurrent actors share.
- **Redesign from First Principles.** Integrating a new requirement into an existing design. Redesign as if it had been foundational from day one.
- **Attack the Premise.** Two or more fixes that share one premise have failed the same gate. Write the premise down and test it directly before you write another fix that assumes it.
- **Subtract Before You Add.** Sequencing an addition, refactor, or rewrite. Remove dead weight first, then build on the simpler base.
- **Minimize Reader Load.** Reviewing or shaping code that's hard to trace. Count layers and hidden state, collapse one-caller wrappers, shrink mutable scope.
- **Outcome-Oriented Execution.** Planned rewrites and migrations with explicit phase boundaries. Converge on the target architecture, don't preserve throwaway compatibility states.
- **Experience First.** Product, UX, or feature-scope tradeoffs. Choose user delight over implementation convenience.
- **Exhaust the Design Space.** A novel interaction or architectural decision with no precedent. Build 2-3 competing prototypes and compare before committing.
- **Build the Lever.** Any non-trivial work. Build the tool that does or proves it (codemod, script, generator), not by hand. The tool is the artifact a reviewer reruns.

**Architecture**

- **Model the Domain.** Writing stateful logic, or code that branches a lot or repeats a shape assumption across files. Encode the domain in a structure (state machine, typed model, table or registry, reducer, boundary, the right collection) instead of scattered conditionals.
- **Boundary Discipline.** Wiring validation, error handling, or framework adapters. Guards at system boundaries, trust internal types, keep business logic pure.
- **Type System Discipline.** Designing types or a signature in any typed language. Make illegal states unrepresentable, brand primitives, parse external data at boundaries.
- **Make Operations Idempotent.** Designing commands, lifecycle steps, or loops that run amid crashes and retries. Converge to the same end state.
- **Migrate Callers Then Delete Legacy APIs.** Introducing a new internal API while old callers exist. Migrate and delete in one wave.
- **Separate Before Serializing Shared State.** Concurrent actors might write the same file, branch, key, or object. Eliminate the sharing first.

**Verification**

- **Prove It Works.** After a task, before declaring done. Verify against the real artifact, not a proxy or "it compiles".
- **Fix Root Causes.** Debugging. Trace each symptom back to the first place the system went wrong and fix it there. A guard is a fix only when the state it handles is legitimate.
- **Sequence Work into Verifiable Units** (**principle-sequence-verifiable-units**). Multi-step work (sweeps, migrations, runs of similar edits) and how you stack commits and PRs. Break work into small units that each end in a check, verify each before the next, and order delivery so the sequence proves itself.
- **Test Behavior, Not Implementation.** Writing, changing, or keeping a test. Assert what the code's users can observe, so the test fails when that behavior breaks and keeps passing when only the internals change.
- **Explain the Number.** Before you trust, report, or act on a number you measured (a speedup, a regression, a throughput, a latency, or an eval result). Find what limits it, and rule out that it measured something other than the work you think.

**Delegation**

- **Guard the Context Window.** Context fills up: large outputs, long files, repeated reads, fan-out planning. Route bulk to subagents, keep summaries in the main thread.
- **Never Block on the Human.** Tempted to ask "should I do X?" on reversible work. Proceed, present the result, let the human course-correct.

**Meta**

- **Encode Lessons in Structure.** You catch yourself writing the same instruction a second time. Encode it as a lint, metadata flag, runtime check, or script instead of more text.

## Writing the reply

Write the reply clean as you draft it. A cleanup pass after drafting does not remove these patterns.

- **Short declarative sentences.** One thought per sentence, ended with a period.
- **No long-dash character anywhere.** Write a file-list bullet as a sentence ("`main.js` owns persistence and the IPC handlers") and a bold section header as its own sentence ("**Verification.** End to end via CDP").
- **A colon as a mid-sentence connector is also out** (unslop rule 14). A colon before a list is fine.
- **Terse is not an excuse to drop content.** Short sentences, but every section the method's reply names stays: details, tradeoffs, choices, open decisions.
- **Frame impact for the consumer and the maintainer.** Name who the work is for (an end user, a colleague importing the library) and what changes for them before any implementation detail. Then what the next engineer who owns this code inherits. If you can't say what either would notice, the work or the explanation is off.
- **Never fabricate a link, citation, or transcript reference.** Link only artifacts you produced or read this session.
- **Every claim carries its evidence or its label in the same sentence.** Measured, inferred, or guess. A prediction or an unseen cause is a guess. Never hand the human a check you could run.

## Comments

Comments follow the same rule as the reply. Write them clean as you go. Keep a comment only for a non-obvious *why* the code can't show. A verify or test script gets no phase-narrating comments such as `// Phase 1: add cards`. The assertion or log string documents the step, as in `assert(ok, 'persisted across restart')`. This applies to every file you produce, including the delegate's diff.
