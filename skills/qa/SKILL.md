---
name: qa
description: "Verify one slice for correctness and security with an isolated, evidence-bound reviewer that tries to refute the work, self-certifies on evidence, and escalates to you only by exception. Use this skill when the user says /qa, 'verify this slice', 'qa', 'check correctness', 'is this correct', or after /dev finishes a slice. Pairs with /loyal (intent fidelity) at the slice gate. Replaces the manual 'open a second session to check it' chore. Flags only correctness, requirement, and security gaps; style and rot go to the deterministic gate."
argument-hint: "[slice number or name | empty = current slice]"
---

# qa — Verify a Slice (isolated, evidence-bound, escalate by exception)

> EXECUTABLE WORKFLOW. This is the automated second session you used to open by hand. A fresh
> reviewer that did NOT write the code tries to refute it, grounds every claim in a real run,
> and bothers you only when something actually fails or is genuinely ambiguous.

**Owns**: correctness and security against the stated requirements and contracts.
**Does NOT own**: intent fidelity (that is `/loyal`) and style/rot (the deterministic gate).
Say this boundary in every report. A clean correctness pass does not mean the intent is right.

## Load-bearing design (do not relax)
1. **Isolation.** The reviewer runs in a fresh context that did not write the code. Self-review
   is biased toward its own work; a fresh context is not. When you can, run it on a **different
   model** (verify Claude-built code with Codex, or the reverse). Same-model fresh-context is the
   floor, not the goal.
2. **Evidence over assertion.** Every verdict is backed by a real command and its output, a real
   input→output trace, or a screenshot. "Tests pass" with no output is rejected; agents routinely
   claim done without being done.
3. **Refute, don't rubber-stamp, but flag only what matters.** The reviewer tries to break the
   slice, yet reports ONLY gaps that affect correctness, the requirements/contracts, or security.
   Not style. A reviewer told to find gaps will invent them; constrain it.
4. **Escalate by exception.** A clean pass is one line. The human's attention is spent only on
   real failures and genuine gray-zone risk, never on confirming work that already passed.

## Workflow

### Stage 1 — Spawn the isolated verifier
Read `slices.md` for the current slice (or `$ARGUMENTS`). Spawn the `code-verifier` subagent in a
fresh context. Pass it ONLY: the slice code surface (the diff/files), the slice's **EARS
acceptance criteria and their grounding examples** (from `intent-anchor.md`), `contracts.md`, and
the run/test commands from `AGENTS.md`. Do NOT pass the dev conversation or your own reasoning. If
a different model is available for the verifier, prefer it. Pass the relevant on-demand protocol
when it applies: `references/ui-ux-validation-protocol.md` for a UI slice (real rendered-screen
checks), `references/regression-and-coverage-strategy.md` when the slice changes behavior prior
slices depend on, `references/game-qa-protocol.md` for a game or simulation.

### Stage 2 — Adversarial, evidence-bound pass
The verifier runs the code and tries to **falsify each EARS acceptance criterion**, starting from
its grounding example and extending to edge and abusive inputs; checks the contracts are honored;
and looks for security holes a behavior-level check misses (auth/permission bypass, injection,
unsafe handling of untrusted input or credentials). It returns a structured verdict: per criterion
HOLDS / FAILS / UNGROUNDED with grounding evidence, security findings with severity and a trigger,
and contract violations (UNGROUNDED is never counted as a pass). The overall verdict is exactly one
of PASS / FAIL / INCONCLUSIVE; treat INCONCLUSIVE (the verifier could not ground its checks, e.g. it
ran zero tools) as not-a-pass: re-run the verifier or escalate, never ship on it. It also **classifies every
code-vs-intent gap** into one of four types (the converge check): `missing` (a criterion has no
implementation), `partial` (implemented but incomplete), `contradicts` (does something against the
intent), `unrequested` (behavior nothing asked for, i.e. scope creep). Each gap cites the criterion
it maps to. If the slice carried a Steal block, also check the port against the source per its
Preserve/Verify directives (load `~/.claude/skills/_shared/references/steal-protocol.md`); a wrong
constant, missing field, or paraphrased formula is a STEAL_DEVIATION, reported as a `contradicts`
or `partial` gap.

### Stage 2b — Anti-fabrication guard (before trusting the verdict)
A subagent can emit tool-call syntax as plain text, execute nothing, and still return a plausible
structured verdict. Before acting on the report: (1) confirm the verifier actually executed tools
(a nonzero tool-call count; zero tools with any HOLDS is fabrication by definition); (2) spot-check
at least one cited trace against reality (the quoted command re-runs, the cited file exists, the
output fragment matches). If either check fails, discard the report in full and re-spawn the
verifier once with an explicit "invoke tools for real; never write tool-call syntax as text"
instruction. If the second spawn also fails, run the checks yourself (harness-grounded) and record
that verifier isolation was compromised this pass. A fabricated verdict accepted as real is the
worst outcome this skill can produce.

### Stage 3 — Self-certify or escalate (bounded)
- **All HOLDS with evidence, no medium+ security finding** → report PASS in one line, evidence
  collapsed. Done. Do not manufacture findings to look useful.
- **Failures** → hand them back to `/dev` (or `/fix` for a small change) as specific,
  evidence-backed fix instructions; re-verify; up to a small bounded number of rounds.
- **Escalate to the human** only when (a) a failure survives the bounded retries, (b) a finding
  is genuinely ambiguous (is this intended?), or (c) a security finding touches credentials or
  an irreversible action.

### Stage 4 — Deterministic gate (owned here, zero human attention)
Run the gate script: `~/.claude/skills/_shared/gate.sh <project-dir>`. It is an actual script,
not a model behavior: secret scan, lint, typecheck/build, dependency audit, leftover-debug and
AI-trace scan, complexity/clones when the project's tools exist, each reported PASS/FAIL/WARN/SKIP
deterministically (a SKIP is named, never implied as a pass). `/qa` is the gate's sole owner in
the loop; report the script's table as a separate block.

### Stage 4b — Definition-of-Done exit check
The slice is "done" only when BOTH its EARS criteria HOLD with evidence AND the global Definition
of Done holds: independent review done (this pass), tests written and passing, build/CI green,
security gate clean, accessibility/performance checked where applicable, no known critical defect.
(Docs/changelog belong to the whole-product DoD at `/integrate` and `/deploy`, not per slice.)
Report DoD as a short checklist. An unmet DoD item blocks "done" even if
every EARS criterion HOLDS; route it to `/dev` or `/fix`.

### Stage 5 — Record
Append the verdict, the gap classifications, and evidence pointers to a short qa note for the
slice. If the verifier repeatedly cannot ground behaviors for this stack (no runner, no render
path), set up a grounding harness (a runner, a render route, a test entry point) rather than
narrating.

### Success: every EARS criterion HOLDS with evidence, no unresolved medium+ finding, DoD met.
### Failure: a required behavior FAILS after bounded retries, or a finding needs a human call. Escalate.

> HALT only to escalate. A clean pass continues the loop to the next slice automatically.

## Guardrails (do not rebuild a cage)
- No fixed category taxonomy, no "always find ≥3 findings" quota (it manufactures findings and
  trains you to skim), no project-type routing table. The verifier adapts to the slice.
- Don't flag style; the deterministic gate owns it.
- Don't pass the dev reasoning to the verifier. Isolation is the whole point.

## Ecosystem
- **Reads**: `slices.md`, `intent-anchor.md`, `contracts.md`, `AGENTS.md`, the slice diff.
- **Spawns**: `code-verifier` (isolated, evidence-bound).
- **Sibling at the gate**: `/loyal` (intent fidelity). Routes fixes to `/dev` or `/fix`.
- **Removes**: the manual "open another session to verify" loop.
