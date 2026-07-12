# Pipeline Charter

Principles for the coding pipeline (scout, plan, dev, qa, loyal, explain, fix, integrate, polish,
deploy). Principles, not prescriptions. Rebuilt 2026-06-20, hardened 2026-07-12, for frontier
agents at high reasoning effort (Fable 5 and Codex GPT-5.6 first; Opus 4.8 xhigh and GPT-5.5
xhigh run it too). Full rationale and evidence:
`~/Projects/lab/intent-diff-driven-design/pipeline-redesign.md` and the v2 blueprint
`~/Projects/lab/intent-diff-driven-design/pipeline-v2-design.md`.

## The governing test
A skill or rule earns its place ONLY if a frontier model at high reasoning effort does
meaningfully worse without it. Everything else is a cage: it scripts the model's thinking and
breaks on the next model upgrade. When in doubt, hand it to the model.

## The thesis
**Thick intent, thin code.** Freeze the intent after interrogating it to completeness and
explicitly confirming it; never assume anything material. Keep the plan fluid. Let the model write
the code freely and hidden. Spend human attention on the intent layer (capture + confirm), on an
isolated evidence-grounded verification stack, and on a few hard safety gates. The model writes
freely downstream because intent was pinned upstream.

## The loop
`(scout? optional) → plan [interrogate intent → EARS anchor + contracts → CONFIRM gate] → for each
slice: dev [build hidden, hard-part-first, self-verify, ask-don't-guess] → verify [loyal intent +
qa correctness/security with converge + DoD, run concurrently where the harness allows, all
isolated/evidence-bound/escalate-by-exception, plus the deterministic gate script owned by qa; a
clean pass continues to the next slice automatically] → integrate [whole-product converge +
analyze + DoD] → deploy [back-translation gate].` `fix` = off-loop targeted change. `explain` = the
4-mode (engineer/founder/investor/user) layer that keeps code hidden, on demand and after the
final slice. `polish` = optional product scrutiny, not part of the coding loop.

## Artifacts (the whole state)
- `intent-anchor.md` — immutable frozen intent: goal; definition-of-done as **EARS statements,
  each with a grounding example**; the single load-bearing behavior; persona; design-intent (UI);
  the **Assumptions Index** (signed off at the CONFIRM gate); resolved hidden-details. Written by
  `/loyal freeze` via `/plan`'s interrogation. THIS is the spec; there is no `phases.md`.
- `contracts.md` — the interface/module boundaries and data shapes the build honors.
- `slices.md` — the living, riskiest-first list of vertical slices with a `current:` marker.
  Re-sliced after each build. Replaces `phases.md`.
- `intent-ledger.md` — append-only drift history (loyal).
- `AGENTS.md` (+ a `CLAUDE.md` that imports it) — lean hand-written project memory, under ~200
  lines, only the non-obvious.
- `fix-log.md` — off-loop change log.

## Decision authority — escalate by exception, not per-transition
- The deterministic gate resolves first → the isolated evidence-bound verifier self-certifies →
  the human sees ONLY real failures, genuine gray-zone calls, and irreversible/credentialed
  actions. Blanket per-transition approval is measurably less safe (it trains rubber-stamping);
  do not reinstate it.
- **Never assume material context.** Any decision that could change the observable result is
  asked, not guessed (recommended defaults are allowed; nothing material is assumed silently). This
  binds `/plan` interrogation and `/dev` mid-build alike.
- **Two mandatory human gates**: (1) the **CONFIRM gate** in `/plan` — explicit confirmation of the
  frozen intent, played back as EARS statements + grounding examples + the Assumptions Index,
  before any code; (2) a plain-English back-translation confirmation before any irreversible or
  credentialed action (`/deploy`).

## Verification doctrine
- **Isolation**: a verifier runs in a fresh context that did not write the code; prefer a
  different model. Self-review is biased toward its own work.
- **Evidence over assertion**: every verdict is backed by a real command + output, trace, or
  screenshot. "Looks done" / "tests pass" without evidence is rejected.
- **Four verification layers per slice, isolated and evidence-bound**: (1) intent drift → `/loyal`
  (behavior reconstruction vs the frozen anchor); (2) correctness + security → `/qa` (isolated,
  ideally a different model; falsifies each EARS criterion; classifies gaps as
  missing/partial/contradicts/unrequested); (3) rot + secrets → the deterministic gate, an actual
  script (`~/.claude/skills/_shared/gate.sh`, sole owner `/qa`): secrets, lint, typecheck,
  dependency audit, AI traces, complexity/clones when the project's tools exist; deterministic
  means a script runs it, not a model re-deriving it; (4) the Definition-of-Done exit gate. Keep
  them separate; a clean intent pass does not mean clean internals. `integrate` runs the whole-product versions
  (converge + analyze + full DoD).
- **No quotas**: never force a minimum finding count. Manufactured findings train the eye to skim.

## Build doctrine
- A "phase" is a **vertical slice** (steel thread): one user-facing capability cut end-to-end,
  sized to what the model builds reliably and a human verifies in one pass. Not a layer, not a
  formula.
- **Riskiest / load-bearing first**: slice #1 threads the behavior that, if wrong, makes the
  whole thing pointless. Never defer the hard part to "a later slice or version"; that is
  distraction, not sequencing.
- **Anti-tech-debt layer**: contract-first interfaces, a clean blessed first thread, lean
  `AGENTS.md`, small slices. Quality is never lowered; thin means thin in SCOPE. Every slice is
  production-grade for its scope.
- Don't over-build: a senior engineer should not call the result overcomplicated.
- **Scales by slice count, not by harness.** A 5-slice CLI and a 60-slice full-stack app run the
  same loop. The large build just has a richer `contracts.md` (the system architecture), a
  walking-skeleton first slice, and nested `AGENTS.md`. "Thin" is thin in scaffolding, not in the
  size of thing it can build. Regulated/multi-team/audited codebases add spec-anchored governance
  on top; solo and small-team full-stack is this loop's sweet spot.

## On-demand curated depth
The thin skill bodies stay lean; curated references load ONLY when the specific case applies
(progressive disclosure), so the v1 knowledge is preserved without re-bloating: `/scout` →
brownfield-mapping guide; `/qa` → UI-UX, regression, and game protocols; `/fix` → root-cause
catalog; `/deploy` → platform targets + failure patterns. The **steal protocol**
(`_shared/references/steal-protocol.md`) is wired across `/plan → /dev → /qa` for verbatim porting
from a known source: read the source (never reimplement from a summary), preserve every constant
and invariant exactly, classify by tier, and a Tier-1 deviation needs approval; a STEAL_DEVIATION
surfaces in qa's converge check. This restores the v1 curated capability and the steal-tier system
as a true superset, on demand.

## Security is continuous
Write-time hooks, the per-slice gate script (SCA/secrets), the verifier's security lens,
and the pre-deploy audit + back-translation gate. Not just at deploy. Untrusted input and
credentials are where models still fail regardless of capability.

## Taste: stand with users, leave no AI traces
Every decision traces to "what happens when a real person uses this." Output (code, commits,
READMEs, changelogs) reads as human-written: no AI traces, and the de-AI writing rules in
`working-rules.md` apply. Identity and constraints live in `working-rules.md`; facts and stack
in `tech-ledger.md`.

## Deprecated (rebuilt 2026-06-20)
Superseded and no longer used by the pipeline: `phases.md` and the phase-decomposition machinery
(four lenses, mandatory Phase 0, 6-task split, cross-validation phase, version-decomposition);
the dev orchestrator + `dev-planner` + `task-implementer` split + multi-section plan file +
complexity tiers; qa's category taxonomy + `qa-planner` + `category-executor` + find-N-findings
quota; forced classifications (investigation type, testing archetypes A-G, AI-determinism
tiers); `pipeline-state.md` ceremony; mandatory key-learnings; blanket per-transition approval.
The shared references `decomposition-framework.md`, `phase-design-principles.md`,
`testing-strategy-archetypes.md`, `ai-output-determinism.md`, `user-journey-simulation.md` and
the agents `dev-planner`/`task-implementer`/`qa-planner`/`category-executor` are retained for
reference but unwired. Prior pipeline backup: `~/.claude/_backups/pipeline-20260620/`.
