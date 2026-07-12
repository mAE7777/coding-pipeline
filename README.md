# Claude Code Pipeline II

A development harness for [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview), built for frontier agents at high reasoning effort (Fable 5 and Codex GPT-5.6 first; Opus 4.8 and GPT-5.5 at xhigh run it too). It replaces the earlier [coding-team](https://github.com/mAE7777/coding-team) pipeline, which froze a heavy `phases.md` up front and asked for approval at every transition.

One position drives the whole thing: **thick intent, thin code**. The field answers AI-code drift with more specs, but a spec is feedforward, it sets the target once and hopes. What actually bounds drift is a sensor. So the rigor goes to two layers and nowhere else: the intent layer (interrogate what to build until it is complete, play it back, freeze it) and the verification layer (isolated, evidence-bound checks that reconstruct behavior from the finished code alone). The code layer is left to the model, written freely and kept hidden.

The governing test for every rule in here: a skill or constraint earns its place only if a frontier model at high reasoning effort does meaningfully worse without it. Everything else is a cage that scripts the model's thinking and breaks on the next upgrade. When in doubt, hand it to the model. The full charter lives in [`skills/_shared/references/pipeline-constitution.md`](skills/_shared/references/pipeline-constitution.md).

## The loop

```
(scout?) → plan → for each slice:  dev → verify → integrate → deploy
                                            │
  plan    = interrogate intent, EARS anchor, CONFIRM gate    └→ fix (off-loop)
  verify  = loyal (intent drift) + qa (correctness/security) + the gate script,
            run concurrently; a clean pass rolls straight into the next slice
  explain = on-demand recap in the reader's register (engineer/founder/investor/user)
```

A "phase" here is not a layer or a formula. It is a vertical slice, one user-facing capability cut end to end, sized to what the model builds reliably and a human verifies in one pass. The riskiest, load-bearing slice goes first; the hard part is never deferred to a later slice or version.

## The skills

| Command | Role |
|---------|------|
| `/scout` | Optional pre-build research: feasibility, tech choices, mapping an unfamiliar codebase |
| `/plan` | Frame the build. Interrogate intent to completeness, ground it in examples, freeze it behind an explicit CONFIRM gate. Never assume anything material |
| `/dev` | Build one vertical slice, hidden, hard-part-first, self-verified before it calls itself done |
| `/qa` | Isolated correctness and security verification that tries to refute each acceptance criterion, then converges the gaps |
| `/loyal` | Intent-drift sensor. Reconstructs what the code actually does from behavior and diffs it against the frozen intent |
| `/explain` | Re-derives the change for a chosen reader: engineer, founder, investor, or user. Keeps the code hidden |
| `/fix` | Off-loop targeted change scoped to a handful of files, with real root-cause analysis |
| `/integrate` | Whole-product convergence and the full definition-of-done pass |
| `/polish` | Optional external stress-test before a real launch. Not part of the coding loop |
| `/deploy` | Release safety gates, a thin changelog, and a plain-English confirmation before any irreversible action |

## Verification doctrine

Every slice passes through four layers, kept separate on purpose, because a clean intent pass says nothing about the internals:

1. **Intent drift** via `/loyal`: behavior reconstructed from the finished code, diffed against the frozen anchor.
2. **Correctness and security** via `/qa`: isolated, ideally a different model, falsifying each acceptance criterion and classifying every gap as missing, partial, contradicting, or unrequested.
3. **Rot and secrets** via the deterministic gate, a real script ([`skills/_shared/gate.sh`](skills/_shared/gate.sh), owned by `/qa`): secret scan, lint, typecheck, dependency audit, leftover-debug and AI-trace scan, complexity/clones when the project's tools exist. Every check reports PASS, FAIL, WARN, or SKIP; a skipped check is named, never implied as a pass. Deterministic means a script runs it, not a model re-deriving it.
4. **The definition-of-done** exit gate.

Two rules hold across all of it. Isolation: a verifier runs in a fresh context that did not write the code, preferably a different model, because self-review is biased toward its own work. Evidence over assertion: every verdict is backed by a real command and its output, a trace, or a screenshot. "Looks done" is rejected. There are no finding quotas; a forced minimum trains the eye to skim.

## Decision authority

Attention is spent by exception, not per transition. The deterministic gate resolves first, then the isolated verifier self-certifies, and the human sees only real failures, genuine gray-zone calls, and irreversible or credentialed actions. Blanket per-transition approval is measurably less safe because it trains rubber-stamping.

There are exactly two mandatory human gates: the CONFIRM gate in `/plan`, where the frozen intent is played back as acceptance statements plus grounding examples plus the assumptions index before any code is written, and a plain-English back-translation before `/deploy` does anything irreversible.

## Artifacts

The whole state of a build lives in a few files, not a ceremony:

- `intent-anchor.md`, the immutable frozen intent, written by `/loyal freeze` through `/plan`'s interrogation. This is the spec; there is no `phases.md`.
- `contracts.md`, the interface and module boundaries the build honors.
- `slices.md`, the living, riskiest-first list of vertical slices with a current marker, re-sliced after each build.
- `intent-ledger.md`, the append-only drift history.
- `AGENTS.md` (imported by a `CLAUDE.md`), lean hand-written project memory, only the non-obvious.
- `fix-log.md`, the off-loop change log.

## Architecture

**Skills.** Each skill is a `SKILL.md` that instructs Claude how to behave at one stage, loading references on demand and delegating heavy work to isolated subagents. Curated depth loads only when the case applies: `/scout` pulls a brownfield-mapping guide, `/qa` pulls UI, regression, and game protocols, `/fix` pulls a root-cause catalog, `/deploy` pulls platform targets and failure patterns.

**Agents.** Two isolated verifiers do the evidence-bound work:

| Agent | Used by | Role |
|-------|---------|------|
| `code-verifier` | `/qa` | Fresh-context correctness and security review, grounded in real command output |
| `loyal-evaluator` | `/loyal` | Reconstructs user-facing behavior from the code alone, never the build conversation |

**The steal protocol** (`skills/_shared/references/steal-protocol.md`) is wired across `/plan → /dev → /qa` for verbatim porting from a known source: read the source rather than reimplement from a summary, preserve every constant and invariant exactly, classify by tier, and surface any tier-1 deviation for approval.

## Install

These are Claude Code skills and agents. To use them, copy the trees into your Claude config:

```bash
git clone <this-repo> coding-team-II
cp -R coding-team-II/skills/*   ~/.claude/skills/
cp -R coding-team-II/agents/*   ~/.claude/agents/
```

Then invoke any stage by its slash command (`/plan`, `/dev`, `/qa`, and so on) inside Claude Code.
