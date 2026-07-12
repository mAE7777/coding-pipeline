---
name: loyal
description: "Intent-fidelity sensor for AI-assisted (vibe) coding. After each behavioral milestone, a context-isolated evaluator reconstructs what the code ACTUALLY does as plain user-facing behavior (grounded in real run traces), guesses its purpose, and the skill machine-diffs that against your frozen original intent to surface drift at a glance, without drowning you in code review or rubber-stamp approvals. Use this skill when building with an AI agent and you want to catch intent drift early: 'did I build what I meant', 'is this drifting from my idea', 'check intent fidelity', 'vibe diff this', 'reconstruct what my code does', 'am I being led by the nose by the AI'. Modes: freeze (seal original intent), check (per-phase drift pass, default), vigilance (planted-discrepancy self-check against approval fatigue), status (drift ledger). Owns intent fidelity only. Do NOT use for pass/fail correctness or security testing (use /qa), or for writing specs (use /plan)."
argument-hint: "[freeze \"<one-line goal>\" | check | vigilance | status]"
---

<!-- Pattern: multi-tool coordination (isolated evaluator subagent + harness-side diff + deterministic gate) -->

# loyal — Intent-Fidelity Sensor for Vibe Coding

> EXECUTABLE WORKFLOW. Execute stages in order. Do not skip. HALT at gates.

This skill closes the loop on vibe coding. The AI writes the code; this skill reconstructs
what that code actually does, in your language, and tells you whether it still matches what
you meant, before drift accumulates. It is a control sensor, not a code reviewer.

**What it owns:** intent fidelity (did the build stay true to your original goal).
**What it does NOT own:** structural rot and security. Those are invisible at the behavior
level and go to a separate deterministic gate (Stage 5) and to /qa. Say this boundary out
loud in every report. Never let a clean fidelity result imply the internals are clean.

**The load-bearing design choices (do not relax these):**
1. The evaluator is **loyal to what the code IS**, not to what the spec wished. It never sees
   the specs, the phase plan, or the dev conversation. This defeats confirmation bias: an
   evaluator that reads the spec will anchor on it and confirm a match that is not there.
2. Every behavior claim is **grounded in a real executed trace or rendered artifact**, never
   narrated from reading code. Ungrounded prose is where the evaluator hallucinates and the
   human approves a fiction.
3. The **harness diffs the reconstruction against a FROZEN intent**, not against the human's
   live memory. Memory co-drifts with the build; the frozen anchor does not.
4. The report is built to be **read at a glance**. Approval fatigue is the enemy. A wall of
   text or a stream of manufactured findings trains the human to rubber-stamp.

---

## Mode Detection

Parse the argument:
- `freeze "<one-line goal>"` or `freeze` → **Freeze Mode** (seal the intent anchor).
- `check` or empty → **Check Mode** (per-phase fidelity pass). Default.
- `vigilance` → **Vigilance Mode** (planted-discrepancy self-check).
- `status` → **Status Mode** (drift ledger + vigilance stats).

Anchor and ledger live in the project root: `intent-anchor.md` (immutable) and
`intent-ledger.md` (append-only).

---

## Freeze Mode — seal the original intent (run once, at t=0)

Run this before the first build phase. Without an anchor, Check Mode has nothing to diff against.

1. Capture the anchor fields using `references/intent-anchor-template.md` for the exact shape.
   The rich, interrogated content (EARS definition-of-done + grounding examples, design intent,
   resolved hidden-details, the Assumptions Index) is produced by `/plan`'s interrogation
   (`plan/references/interrogation.md`); when freeze runs as part of `/plan`, write all of it.
   When `/loyal freeze` runs standalone, capture at minimum:
   - **Goal**: one line. What is this, in a sentence, for the person who will use it.
   - **Definition of done**: 3 to 6 user-facing behaviors, each as an EARS statement
     (`When <trigger>, the system shall <response>`; `If <bad condition>, then ...`) with one
     concrete grounding example. Behavior, not implementation. No function names, no tech.
   - **Load-bearing behavior**: the single one that, if wrong, makes the whole thing pointless.
   - **Persona**: who uses this and at what level. Sets the evaluator's scope later.
   - **Design intent** (UI only) and **Assumptions Index**: capture what you can; if running
     standalone without a full interrogation, mark these `TODO via /plan` rather than inventing.
2. Stamp it: write `intent-anchor.md` with the four fields, an ISO date, and a short content
   hash of the goal + DoD (so later drift cannot be blamed on an edited anchor).
3. If `intent-anchor.md` already exists: do NOT overwrite. Append the new version below the old
   under a dated `## Re-freeze` heading and warn the user that re-freezing resets the drift
   baseline. A moved anchor hides drift.

### Success: intent-anchor.md written, immutable, hashed.
### Failure: user cannot state a one-line goal or a load-bearing behavior. Stop and tell them the
build is not ready to start; a build with no statable intent cannot be checked for drift.

> HALT after freezing. Building happens next (via /dev or direct vibe coding), then Check Mode.

---

## Check Mode — per-phase fidelity pass (the main loop)

Run this once per **behavioral milestone**, not per task and not per file. A milestone is a
point where a user-facing capability became true ("the user can now log in"). Per-line is
fatigue; end-of-project is too late. One pass per milestone bounds drift to a sawtooth.

### Stage 0: Preconditions
1. Read `intent-anchor.md`. If absent, HALT: "Run /loyal freeze first." Do not proceed.
2. Determine the phase code surface: the files changed since the last ledger checkpoint (or,
   if not under version control, ask the user which files implement the milestone just reached).
3. Read `intent-ledger.md` to see which DoD behaviors were already confirmed and which deltas
   are still open. Never read a `## Vigilance` block as verdict history; if one sits at
   `outcome: pending` (a session died mid-probe), resolve and reveal it to the user first, then
   proceed. A pending planted item is not ground truth.

### Stage 1: Spawn the loyal-evaluator (isolated reconstruction)
Spawn the `loyal-evaluator` subagent with a FRESH context. Pass it ONLY these four things,
and nothing else:
- the phase code surface (the files / diff),
- the one-line **goal** from the anchor,
- the **persona** from the anchor,
- the build/run/test commands from `AGENTS.md` (commands leak no intent; they only cut
  UNGROUNDED noise and wasted toolchain rediscovery).

Do NOT pass: the definition-of-done behaviors, the load-bearing behavior, the specs, the phase
plan, the dev conversation, or your own expectations. Withholding the DoD is deliberate: the
evaluator must rediscover behaviors, not check a list. Pre-read `~/.claude/agents/loyal-evaluator.md`
is unnecessary (the subagent loads its own protocol); just spawn it with the three inputs.

The evaluator returns structured output:
- `behaviors[]`: each a user-facing statement plus a **grounding trace** (the real input it ran
  and the real output / rendered screen it observed). Behaviors it could not execute are marked
  `UNGROUNDED` and listed separately, never mixed in as if confirmed.
- `purpose_guess`: one to three sentences, "based only on what this does, this appears to be for ...".
- `orphans[]`: behaviors it found that it could not fit to any plausible purpose (strong drift or
  rot signal).

If the evaluator reports it could not execute anything (everything UNGROUNDED), tell the user the
milestone is not runnable yet and the pass is inconclusive. Do not synthesize behavior from code.

**Anti-fabrication guard (run this before trusting any of it).** A subagent can emit tool-call
syntax as plain text, execute nothing, and still fill every grounding trace with fiction. So before
Stage 2, verify the reconstruction is real:
1. Confirm the evaluator actually executed tools (a nonzero tool-call count). Zero tool calls with a
   non-empty `behaviors[]` is fabrication by definition.
2. Spot-check at least one grounding trace against reality: confirm a file / command / output it
   cites actually exists and matches. A cited artifact that does not exist (a wrong output filename,
   an env var the code never reads, a place that is not in the real data) condemns the whole report.
If either check fails, the reconstruction is FABRICATED — discard it in full; do not diff it.
Re-spawn the evaluator once with an explicit "invoke tools for real; never write tool-call syntax as
text" instruction. If the second spawn also fails, fall back to a HARNESS-GROUNDED pass: you (the
main loop) run the same commands yourself, diff from what you observe, and record in the ledger that
evaluator isolation was compromised this pass (confirmation-bias protection reduced). A harness-
grounded verdict beats a fabricated isolated one; a fabricated verdict accepted as real is the worst
possible outcome for this skill.

### Stage 2: Harness-side diff (machine surfaces the delta, not the human)
You (the main skill) now compare the evaluator's loyal reconstruction against the frozen anchor.
The human does not do this comparison; their memory has co-drifted with the build.

Compute and label each item:
- **HOLDS**: a DoD behavior is present and its grounding trace matches intent.
- **DRIFT**: a DoD behavior exists but does something different from what the anchor says.
- **MISSING**: a DoD behavior is absent from `behaviors[]`. Calibrate before alarming: absent
  can mean not built, or just never exercised (the evaluator does not know what to look for, by
  design). Check the evaluator's `ungrounded[]` and traces first, and let `/qa`'s direct check of
  that criterion settle it; loyal's strong unique signals are DRIFT, EXTRA, ORPHAN, and the
  purpose diff, not MISSING.
- **EXTRA**: a behavior exists that no DoD statement called for (scope creep / led-by-the-nose).
- **ORPHAN**: an evaluator orphan (unexplained behavior).
- **LOAD-BEARING**: the evaluator never saw the load-bearing behavior, so map it now. Read the
  load-bearing statement from `intent-anchor.md` and find the single behavior in the evaluator's
  `behaviors[]` that most directly corresponds to it. State the mapping explicitly before judging:
  "Load-bearing (anchor): X -> matched behavior: Y". If no returned behavior corresponds, the
  load-bearing behavior is MISSING, the strongest possible signal. Resolve the mapped behavior to
  HOLDS / DRIFT / MISSING and flag it as the headline regardless of the other counts.

Also diff `purpose_guess` against the anchor goal: do they describe the same thing? A purpose
guess that drifts from the goal is the back-translation signal that the build has wandered even
when every individual behavior looks fine.

### Stage 3: Glance report + judgment (anti-fatigue is a hard constraint)
Render the delta using `references/delta-report-format.md`. Hard rules:
- First line is the load-bearing verdict. Nothing precedes it.
- Then the frozen goal and the reconstructed purpose_guess, side by side, one line each.
- Then only the items that are NOT HOLDS, one line each, behavior language, zero code.
- If nothing drifted, say exactly that in one line. Do not manufacture findings to look useful;
  manufactured findings are what train the eye to skim.
- Grounding traces are collapsed by default and shown only when the user inspects an item.

Offer the user four moves: **accept** / **correct** (hand the delta back to the dev session as a
fix instruction) / **inspect** (reveal an item's grounding trace) / **ask** (question any item).

### Stage 4: Record to the ledger
Append to `intent-ledger.md`: milestone name, date, the per-item verdicts, the user's decision,
and any correction sent back to dev. This ledger is the drift history and the input to Status Mode.

### Stage 5: Deterministic quality gate boundary
The rot/security gate is an actual script, `~/.claude/skills/_shared/gate.sh`, and `/qa` is its
sole owner inside the pipeline loop; do not duplicate the run here when `/qa` is part of this
build. Only when loyal runs standalone (vibe coding with no `/qa` in the loop), run the script
yourself and report its table as a SEPARATE, clearly-labeled block (never folded into the
fidelity glance). Either way, state the boundary verbatim: "Intent fidelity is judged above;
internal quality and security are judged by the deterministic gate and /qa. A clean fidelity
result does not mean the internals are clean."

### Success: a glanceable delta the user judged in one pass, ledger updated, gate run.
### Failure: evaluator could not ground any behavior (inconclusive), or no anchor exists (HALT).

> A no-drift pass is one line and continues the loop. HALT for a user decision only when an item
> is not HOLDS, the pass is inconclusive, or fabrication was detected.

---

## Vigilance Mode — keep the human (and this skill) honest

The failure mode this skill most fears is becoming another approve button. Automation-bias
research finds that operators stop monitoring automation they trust, and more so under load. This
mode measures whether that is happening, and it only works if the planted lie is persisted to disk
before the user sees it, never held in the model's head across turns.

**Manual only.** A vigilance pass runs ONLY when the user explicitly invokes `/loyal vigilance`
(or has set an explicit cadence themselves). It never fires automatically: at the scale of a solo
build a scheduled probe barely ever triggers, and a planted verdict is not something this skill
inserts unasked. What must stay hidden is WHICH item in the report is false; knowing a probe is
running does not let the user fake catching it, because they still have to find the planted item.

When a Check pass is also a vigilance pass:
1. **Plant and persist first.** Before rendering the Stage 3 report, pick one item to falsify (flip
   a real HOLDS to a plausible DRIFT, or swap in a plausible wrong purpose_guess) and write a
   `## Vigilance` block to `intent-ledger.md` recording: milestone index, the planted item text,
   the true verdict it replaced, and `outcome: pending`. Ground truth lives in the ledger, not in
   your context, so the reveal does not depend on memory.
2. **Render with no tell.** Show the Stage 3 report with the planted item formatted exactly like a
   real one.
3. **Score and reveal.** After the user responds, read the `## Vigilance` block back. If they
   questioned or corrected the planted item, set `outcome: caught`; if they accepted it, set
   `outcome: missed`. Reveal the plant to the user either way; seeing your own miss is the only
   thing that resets a skimming habit.
4. **Watch the trend (Status Mode).** Plot catch rate over milestone index. A rate decaying toward
   chance is the early warning that the loop has degraded into ritual. When that happens, say so
   plainly and recommend lengthening the cadence or pausing the build, not adding more reports.

---

## Status Mode — the drift ledger

1. Read `intent-ledger.md`.
2. Show: which DoD behaviors currently HOLD, which carry open DRIFT/MISSING, the load-bearing
   behavior's standing, the per-milestone delta counts (the sawtooth), and the vigilance catch
   rate over time.
3. One screen. If the sawtooth is trending up (each milestone opening more drift than the last),
   say so: that is the signal the anchor itself may be wrong or the build should pause.

---

## Ecosystem Hooks

- **Upstream**: consumes the goal a user would otherwise put in /plan. Run Freeze before /dev.
- **Per-phase**: intended to run at each /dev phase completion. /dev can invoke `/loyal check`
  as its milestone-completion gate instead of, or alongside, marking the phase done.
- **Boundary siblings**: hands correctness/security to /qa and rot to the Stage 5 gate. When a
  DRIFT turns out to be a real defect, route the fix through /fix.
- **Research**: if the evaluator repeatedly cannot ground behaviors for a given stack (no runner,
  no render path), build a grounding harness for that stack (a runner, a render route, a test
  entry point) rather than silently narrating.
