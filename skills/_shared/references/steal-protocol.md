# Steal Protocol

Loaded on demand when a build ports code or design from a known source. It exists because a
model will NOT port verbatim unaided: left alone it reimplements from a summary and silently
corrupts the constants, formulas, and invariants that are the whole reason the source was worth
stealing. This protocol forces reading the source and preserving it exactly.

A steal reference is an **implementation guide**, not insights or inspiration. It answers exactly:
what code/pattern to read, what to preserve verbatim, what minimal adaptations are required, and
how to verify the port is correct.

**The core rule**: stealing is complete and accurate. "Adapting" a steal into something different
is improvising, which defeats the purpose. When unsure, port MORE not less. The port must be
provably equivalent to the source in all ways that matter. Improvements come AFTER the port is
verified, never during.

**Source integrity**: steal items cite specific file paths + line ranges. If you cannot cite an
exact path, the item is a design-pattern, not code-portable; spec it accordingly.

---

## Item Types
- **code-portable**: source code exists locally. Port it verbatim: read the source file, copy the
  implementation, apply only the mechanical changes in Adaptation Notes. Nothing else.
- **design-pattern**: no code to copy; reconstructed from analysis/research. Implement from the
  fully-specified algorithm description.
- **philosophy**: a design constraint that governs decisions and eliminates whole classes of
  choices. A rule with hard invariants, not an algorithm.
- **tech-choice**: a specific technology selection plus the configuration that makes it correct
  (the choice + its exact parameters, not just "use X").
- **ui-ux**: a user-experience or interface pattern; port the interaction model.
- **se-technique**: a software-engineering technique applicable across contexts.

## Steal Tiers
Every steal item has a tier (1-5) that determines implementation rules. The tier is assigned at
`/plan` time and travels via the Steal block in the milestone's section of `docs/project/milestones.md` → `/dev` → the gate.

- **Tier 1: Direct Port.** Source code exists in a compatible language. READ the source file. PORT
  it with ZERO unnecessary changes. Only allowed changes: import paths, logging mechanism, type
  annotations. If source is <100 LOC, the port should be similar LOC (±30%). ANY deviation from
  the source requires user approval via AskUserQuestion. Do NOT redesign the API, change data
  structures, or add features.
- **Tier 2: Cross-Language Port.** Source exists in a different language. READ the source file.
  REWRITE preserving: all constants (exact values), all algorithms (same logic flow), all data
  structures (same fields), function signatures (equivalent types). Only change what the language
  difference requires. If a language difference forces an architectural change, pause and ask.
- **Tier 3: Architecture Steal.** No portable code, but architecture/algorithm are fully specified
  in the steal doc. IMPLEMENT from the Preserve/Verify constraints; the steal doc is the authority.
  Reading a source file is optional (reference only).
- **Tier 4: Philosophy Steal.** Ideas and design principles. Inform design decisions; no direct
  code to port.
- **Tier 5: Original Creation.** No reference exists. Created from scratch using best practices and
  the project's conventions.

**Tier inference** (when no explicit Tier): code-portable → Tier 1 (same language) or 2 (different);
design-pattern → 3; philosophy → 4; tech-choice → 3; ui-ux → 3; se-technique → 3.

## Steal Block format (carried into the milestone that uses the item)
```
Steal: <source-doc> §<N>. <Item Name> (tier: <1-5>, type: <type>)
Source: `<project>`: `<file-path>:L{start}-{end}` | described from research
Preserve (verbatim, do not paraphrase):
  - Formula: `confidence *= decay_rate ^ days_since_last_use`  (exact, do not approximate)
  - Constant: `BM25_WEIGHT = 0.3`  (calibrated, do not adjust)
  - Invariant: "one action per iteration, observation before next"  (structural rule)
Adaptation Notes (only mechanical, max 5): Python dict → typed interface; module path only.
Verify (binary, runnable without reading the source): "BM25_WEIGHT constant equals 0.3";
  "orchestrator.ts is under 300 lines (wc -l)".
```

## Writing Preserve directives: sweep protocol
Writing Preserve is a search task, not a creative one. Every preservable element must be found,
not imagined. After an initial list, run the sweep:
1. **Formula sweep**: quote every equation exactly, all variables and operators.
2. **Constant sweep**: every numeric constant/threshold/weight/rate/size/timeout with its value.
3. **Ordering sweep**: every execution-order invariant ("X before Y", "append then loop").
4. **Naming sweep**: naming conventions that affect behavior (e.g. "00.mp3..59.mp3 encode order").
5. **Structural sweep**: structural invariants ("loop under 300 lines", "no state machines").
6. **Interface sweep**: every API shape, schema field, type, expected behavior.
Then review the list and ask "what would break if I changed this?": anything that would break
belongs in Preserve. Over-preservation costs zero; a missed invariant costs a broken port.

## Quality rules
1. Exact file path + line range for every code-portable item. No line numbers = a guess.
2. Preserve directives are COMPLETE (run the sweep). Not "the most important invariants", ALL of them.
3. Adaptation Notes are mechanical only (type/module/syntax). Adding logic is a design decision,
   not an adaptation; keep them separate. Max 5 per item.
4. Validation is hard: each check binary and runnable without reading the source ("wc -l shows
   under 300", not "follows the pattern").
5. No lossy compression: quote formulas/constants/invariants exactly. "approximately 0.03" when
   the value is 0.025 is a steal corruption that breaks the implementation in the way that matters.

---

## How the pipeline consumes this

**`/plan`** (intake): detect steal/reference docs at the project root (`steal-*.md`, `reference-*.md`,
`port-*.md`) and check any project index you keep for a stealable match against this project's stack
and domain. For each stolen item, classify the tier and write a **Steal block** into the milestone that
uses it, in `docs/project/milestones.md` (its `Steal:` line). Run the Preserve sweep so the block is complete before the build starts.

**`/dev`** (build): when the current milestone carries a Steal block, for Tier 1-2 READ the original
source file at the exact path before writing a line; port verbatim, applying ONLY the listed
mechanical adaptations; a Tier 1 deviation beyond imports/types/logging HALTs for approval; run the
Verify checks before the milestone is frozen. Never reimplement a stolen item from the summary.

**The gate** (verify): if the milestone carried Steal blocks, the code-verifier checks the port against the
source per the Preserve/Verify directives (the Steal block is part of the milestone contract in its pack). A
wrong constant, missing field, or paraphrased formula is a **STEAL_DEVIATION** finding and blocks.
