# Steal Reference Specification

> Format for all steal reference docs at `~/.claude/projects/<name>.md`.
> Consumed by: /plan (Phase 1 step 1c, Phase 4 task annotation, Phase 4b audit),
>              task-implementer (pre-implementation reading).

A steal reference is an implementation guide — not insights, not lessons, not inspiration.
It answers exactly: what code/pattern to read, what to preserve verbatim, what minimal
adaptations are required, and how to verify the port is correct.

**The core rule**: stealing is complete and accurate. "Adapting" a steal into something
different is improvising, which defeats the purpose. When unsure, port MORE not less.
The port must be provably equivalent to the source in all ways that matter. Improvements
come AFTER the port is verified — never during.

**Source integrity**: Steal items reference specific file paths + line ranges. If you cannot
cite an exact file path, the item is a design-pattern, not code-portable — spec it accordingly.

---

## Item Types

**`code-portable`** — Source code exists locally. Port it verbatim: read source file, copy
the implementation, apply only mechanical changes listed in Adaptation Notes. Nothing else.
Examples: EventStream class, agent loop, hybrid search scorer, decay formula, ring buffer.

**`design-pattern`** — No code to copy; pattern is reconstructed from analysis, research,
or proprietary systems. Implement from the fully-specified algorithm description.
Examples: Planner-Executor-Verifier, three-layer memory, one-action-per-iteration rule.

**`philosophy`** — A design constraint that governs implementation decisions, eliminating
entire classes of choices. Not an algorithm, but a rule with hard invariants.
Examples: "LLM as algorithm — no state machines", "orchestrator under 300 lines".

**`tech-choice`** — A specific technology selection plus the configuration that makes it
correct. The steal is the choice + its exact parameters, not just "use X".
Examples: SQLite FTS5 for BM25, bge-large-en-v1.5 for embeddings, score weight 0.3/0.7.

**`ui-ux`** — A user experience or interface pattern. Port the interaction model.

**`se-technique`** — A software engineering technique applicable across contexts.
Examples: trajectory reduction algorithm, recoverable compression, confidence decay system.

---

## Steal Tiers

Every steal item has a tier (1-5) that determines implementation rules throughout the
pipeline. The tier is assigned at /plan time and travels through phases.md → dev → qa.

### Tier 1: Direct Port
Source code exists in a compatible language (TypeScript/JavaScript). READ the source file.
PORT it with ZERO unnecessary changes. Only allowed changes: import paths, logging mechanism
(console→pino), type annotations. If source is <100 LOC, implementation should be similar
LOC (±30%). ANY deviation from the source requires user approval via AskUserQuestion.
Do NOT redesign the API. Do NOT change data structures. Do NOT add features.

### Tier 2: Cross-Language Port
Source exists in a different language (Rust, Python, Go). READ the source file. REWRITE
into TypeScript preserving: all constants (exact values), all algorithms (same logic flow),
all data structures (same fields), function signatures (equivalent types). Only change what
the language difference requires. If a language difference forces an architectural change,
pause and ask the user.

### Tier 3: Architecture Steal
No portable code exists, but architecture and algorithm are fully specified in steal docs.
IMPLEMENT from the Preserve/Verify constraints. The steal doc is the authority. Source file
reading is optional (for reference only, not for porting).

### Tier 4: Philosophy Steal
Ideas, design principles, lessons learned. Inform design decisions. No direct code to port.
Apply the philosophy to guide implementation choices.

### Tier 5: Original Creation
No reference exists anywhere. Created completely from scratch using best practices and the
project's established conventions.

### Tier Inference (backward compatibility)
When a steal item has no explicit Tier field, infer from item type:
- `code-portable` → Tier 1 (if same language) or Tier 2 (if different language)
- `design-pattern` → Tier 3
- `philosophy` → Tier 4
- `tech-choice` → Tier 3
- `ui-ux` → Tier 3
- `se-technique` → Tier 3

---

## Item Format

```markdown
### <N>. <Item Name>

**Tier**: 1 | 2 | 3 | 4 | 5
**Type**: code-portable | design-pattern | philosophy | tech-choice | ui-ux | se-technique
**Source**: `<project>` — `<file-path>:<L{start}-{end}>` | described from research
**What**: one sentence — exactly what this is, not why it matters
**Why steal**: why this implementation is worth copying over writing fresh — what makes
  it proven, production-tested, or demonstrably better than naive alternatives

**Exact location** (code-portable only):
- `path/to/file.ext` (L{start}-{end}) — `FunctionName()` — what this does

**Preserve** (verbatim — do not paraphrase, summarize, or reinterpret):
- Formula: `confidence *= decay_rate ^ (days_since_last_use)` — exact, do not approximate
- Constant: `BM25_WEIGHT = 0.3` — calibrated, do not adjust
- Invariant: "one action per iteration, mandatory observation before next" — structural rule

**Adaptation Notes** (only mechanical, required changes — nothing else):
- Python `async for` → TypeScript `for await` (structure unchanged, mechanical mapping)
- Python dict → TypeScript typed interface (same shape, mechanical annotation)
- Module path only — not logic changes

**Do NOT change**:
- The loop structure (must stay under 300 lines — verify with wc -l)
- The tool execution pattern (extract → execute → append → loop)
- Simplicity — no state machines, switch statements, or abstractions layered on top

**Validation**:
- `core/orchestrator.ts` is under 300 lines
- All tool calls route through the same execution path (no direct calls)
- No switch/case on state variable anywhere in the module
```

---

## Writing Preserve Directives — Sweep Protocol

Writing a Preserve section is not a creative task — it is a search task. Every preservable element must be found, not imagined. After writing an initial Preserve list, run this sweep:

1. **Formula sweep**: Are there mathematical operations, formulas, or equations? Quote every one exactly, including all variables and operators. Do not approximate.
2. **Constant sweep**: Are there numeric constants, thresholds, weights, rates, sizes, timeouts? List every one with its exact value and what it controls.
3. **Ordering sweep**: Does anything depend on execution order? (e.g., "X must run before Y," "append then loop never loop then append") Capture every ordering invariant.
4. **Naming sweep**: Are there naming conventions that affect behavior? (e.g., "sorted filenames encode intensity — 00.mp3 to 59.mp3") Capture patterns that must be preserved.
5. **Structural sweep**: Are there structural invariants? (e.g., "loop must stay under 300 lines," "no state machines," "single binary") Capture every non-obvious structural rule.
6. **Interface sweep**: Are there API shapes, schema fields, or protocol expectations that must be exactly preserved? Capture every required field name, type, and expected behavior.

After running this sweep: review the final Preserve list one more time and ask "what would break if I changed this?" — anything that would break belongs in Preserve.

---

## Quality Rules

1. **Exact locations for code-portable items.** File path + line range is mandatory.
   A steal without line numbers is a guess. Read the source, find the exact range.

2. **Preserve directives are complete.** Run the sweep protocol above before finalizing.
   The goal is not "the most important invariants" — it is ALL invariants. If unsure whether
   something is worth preserving, preserve it. The cost of over-preservation is zero.
   The cost of missing a critical invariant is a broken port.

3. **Minimal Adaptation Notes.** Each adaptation note must be a mechanical transformation
   (type system, module path, syntax). If you are adding logic — that is not an adaptation,
   it is a design decision. Keep them separate. A maximum of 5 adaptation notes per item;
   if you need more, you are re-designing, not porting.

4. **Validation is hard.** Each validation check must be binary (pass/fail), runnable without
   reading the source. "Follows the pattern" is NOT a valid validation — it cannot be verified.
   Good: "wc -l orchestrator.ts shows under 300 lines." Bad: "implementation follows the loop pattern."

5. **Source version tracking.** The containing projects/<name>.md must have
   `source-version: <git-sha>` so staleness is detectable when the project updates.

6. **No lossy compression.** Quote formulas, constants, and invariants exactly as they appear
   in the source. "approximately 0.03" when the value is 0.025 is a steal corruption — the
   resulting implementation will be wrong in exactly the way that matters most.

---

## How /plan Consumes This

/plan discovers steal docs at two points:

**Phase 1 step 1b** (local): reads steal-*.md, reference-*.md at project root.

**Phase 1 step 1c** (global): reads `~/.claude/projects.md`, checks each external project's
"Stealable" entries against this project's tech stack + domain, loads `~/.claude/projects/<name>.md`
for any matching project.

For each task that maps to a steal item, /plan generates a Steal block in task notes:
```
Steal: ~/.claude/projects/<name>.md §<N>. <Item Name> (type: code-portable)
Preserve: <verbatim Preserve directives>
Verify: <check derived from Preserve — e.g., "BM25_WEIGHT constant equals 0.3">
```

Phase 4b runs a steal cross-reference audit: checks that task narrative matches steal doc
(no substitutions, no wrong constants, no missing fields). Any STEAL_DEVIATION is surfaced
to user before proceeding.

---

## How task-implementer Consumes This

When a task has a Steal block:

1. Read `~/.claude/projects/<name>.md §<N>` before writing any code.
2. For code-portable: read the source file at the exact path and line range. Read it, do not infer.
3. Port verbatim — apply ONLY adaptations listed. Nothing extra.
4. Run all Validation checks before marking task complete.
5. If any Preserve directive cannot be honored exactly, stop and document the deviation
   in key-learnings with rationale. Do not silently deviate.
