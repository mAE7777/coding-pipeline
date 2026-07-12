# Regression & Coverage Strategy

Full regression execution and coverage-gap analysis. Load when a slice changes behavior that prior slices depend on. Regression is always the first check, a broken foundation invalidates everything. "Phase" below means a unit of prior work (a slice); run prior slices' gates in order.

---

## Section 1: Regression Execution Order

Regression tests run in strict order. Stop on first failure.

### Order of Operations

1. **Build/compile gates from Phase 0**: These are the foundation. If the project doesn't build, nothing else matters.
   - Package installation (`npm install` / equivalent)
   - TypeScript compilation (`npx tsc --noEmit` / equivalent)
   - Linter pass (`npm run lint` / equivalent)
   - Build succeeds (`npm run build` / equivalent)

2. **Automated test suites from all prior phases**: Every `npm test` or equivalent command from every prior phase's Validation Gates.
   - Run in phase order: Phase 0 gates, then Phase 1, then Phase 2, etc.
   - Each phase's gates must all pass before moving to the next phase's gates.

3. **Cross-phase interaction tests**: New tests that verify Phase N doesn't break prior phases.
   - Shared component rendering (components used by multiple phases)
   - API endpoint availability (endpoints from prior phases still respond)
   - Data integrity (data structures from prior phases still valid)
   - Navigation flows (routes from prior phases still accessible)

### Execution Protocol

For each regression gate:

```
1. Run the command exactly as specified in phases.md
2. Capture exit code + full output
3. Compare against expected result
4. Record: PASS (matches) or FAIL (doesn't match)
5. If FAIL → STOP immediately
```

### On Regression Failure

If ANY regression gate fails:

1. **STOP all qa testing immediately** — do not proceed to new tests
2. Identify which prior phase is affected
3. Determine the likely cause in Phase N (what changed that broke it)
4. Present diagnostic:

```
REGRESSION FAILURE — qa Halted

Failed gate: {gate description}
From phase: Phase {M}
Command: {command}
Expected: {expected output}
Actual: {actual output}

Likely cause in Phase {N}:
{analysis of what Phase N changed that broke Phase M}

Recommended action:
{specific fix recommendation}

qa cannot proceed until regression is resolved.
Re-run /qa {N} after fixing.
```

5. qa does NOT fix regressions — it reports and halts. The user decides whether to fix manually or re-run `/dev`.

---

## Section 2: Coverage Gap Analysis

After Stage 2 (Phase Analysis), map every testable behavior to verify nothing is untested.

### Requirement-to-Test Mapping

For every requirement in `phases.md` for the target phase:

| Requirement (from phases.md) | dev Gate Covering It | qa Tests Covering It | Gap? |
|------------------------------|---------------------|---------------------|------|
| {task or AC description} | {which dev gate tests this} | {qa test IDs} | {Yes/No} |

Rules:
- Every requirement MUST have at least one qa test (not just a dev gate)
- If a requirement has only a dev gate and no qa test, that's a gap — create a qa test
- If a requirement has no coverage at all, that's a critical gap — create P0 qa tests

### Error Path Coverage

For every error path in the code (identified via Grep for try/catch, error boundaries, error states):

| Error Path (file:line) | What Triggers It | Test ID | Covered? |
|------------------------|-----------------|---------|----------|
| {file:line of catch block} | {condition that triggers it} | {qa test ID or "NONE"} | {Yes/No} |

Rules:
- Every catch block must have at least one test that triggers it
- Every error boundary must have at least one test that causes it to render
- Every error state in UI must have at least one test that displays it

### Coverage Summary

After mapping, produce:

```
Coverage Summary:
- Requirements: {covered}/{total} ({percentage}%)
- Error paths: {covered}/{total} ({percentage}%)
- UI states: {covered}/{total} ({percentage}%)
- Gaps identified: {count}
- New tests created to fill gaps: {count}
```

Target: 100% requirement coverage, 80%+ error path coverage, 100% UI state coverage.

---

## Section 3: Cross-Phase Interaction Testing

Phase N may break prior phases in subtle ways. Test for these patterns:

### Shared File Modifications

If Phase N modified any file that exists since a prior phase:

1. Identify ALL features in prior phases that depend on that file
2. For each feature, run its original validation or create a new test
3. Verify the modification didn't change behavior for prior features

### New Dependencies

If Phase N added new packages:

1. Run `npm ls` or equivalent to check for dependency conflicts
2. Verify no peer dependency warnings
3. Check that prior phase imports still resolve
4. Verify bundle size didn't dramatically increase

### Changed Types/Interfaces

If Phase N modified any shared types or interfaces:

1. Grep for all usages of the changed type across the codebase
2. Verify every consumer still compiles
3. Verify runtime behavior matches — types can compile but behave differently

### Shared State

If Phase N modifies global state, context, or shared stores:

1. Test that prior phases read the correct values from shared state
2. Verify no state pollution between features
3. Check that state initialization still works for prior phase flows

---

## Section 4: Regression Failure Handling

### Classification

All regression failures are automatically **P0 CRITICAL**. No exceptions.

A regression means Phase N broke something that was working. This is always worse than a new feature not working, because it indicates:
- The change had unintended side effects
- The developer missed a dependency between phases
- The project's integrity guarantee is broken

### Response Protocol

1. **Record the failure with full evidence**: command, expected, actual, error output
2. **Do NOT attempt to fix**: qa reports, it does not modify code
3. **Do NOT proceed with other tests**: Results would be unreliable on a broken foundation
4. **Do NOT mark any tests as "skipped due to regression"**: They are simply "not run"
5. **Report clearly**: The user needs to know exactly what broke and likely why
6. **Suggest resolution**: Based on analysis, suggest what in Phase N likely caused the regression

### After Resolution

When the user reports the regression is fixed:
- Re-run `/qa {N}` from the beginning
- Do NOT resume from where qa stopped — start fresh
- The entire regression suite must pass before any new tests run

---

## Section 5: Game-Specific Regression Surfaces (Archetype G)

Game projects have regression surfaces that standard web apps don't. These must be re-validated in Category A alongside build/test gates.

### 5.1 Content Graph Regression

When prior phases established content data files (JSON/YAML with cross-references):
- Re-validate all foreign key references from ALL prior phases' content files
- A new phase may have renamed, moved, or deleted content that prior content references
- Tool: Grep to extract IDs, Read to verify targets exist

### 5.2 Save/Load Regression

When prior phases established save/load infrastructure:
- Re-run all prior phases' save/load round-trip tests
- A new phase adding state slices may break serialization of existing slices
- A schema change may invalidate existing save formats
- Tool: Vitest (run existing save/load test files)

### 5.3 Deterministic Replay Regression

When golden replay fixtures exist from prior phases (`tests/engine/fixtures/`):
- Re-run ALL golden replays
- A code change that alters RNG call order, state transition logic, or formula calculations will cause a replay deviation
- Any deviation is a P0 regression — it means the game behaves differently for the same inputs
- Tool: Vitest (replay fixture files)

### 5.4 Cross-System Interaction Regression

When prior phases established system interactions:
- Re-run all prior phases' cross-system interaction tests
- A new phase modifying shared state may break downstream consumers
- Tool: Vitest (run existing cross-system test files)

### 5.5 i18n Key Regression

When prior phases added translation keys:
- Verify all prior phases' keys still exist in all locale files
- A refactor that changes component structure may orphan translation keys
- Tool: Grep + diff against locale files

### Execution Order (Extended for Games)

After the standard regression order (Section 1), append:

4. **Content graph regression** (if content files exist from prior phases)
5. **Save/load round-trip regression** (if save/load tests exist)
6. **Golden replay regression** (if fixture files exist in `tests/engine/fixtures/`)
7. **Cross-system interaction regression** (if cross-system tests exist)
8. **i18n key regression** (if locale files have keys from prior phases)
