# Regression & Coverage Strategy

Full regression execution and coverage-gap analysis. Load when a milestone changes behavior that earlier milestones depend on. Regression is always the first check; a broken foundation invalidates everything. Below, M{k} is the milestone under test and M{j} an earlier one; earlier milestones' checks run in milestone order.

Every command here (install, build, test suites, simulators) runs through the machine-wide lock: `python3 <heavy.py> run -- <command>`. A server the checks need runs as `python3 <heavy.py> serve -- <command>` in the background.

---

## Section 1: Regression Execution Order

Regression tests run in strict order. Stop on first failure.

### Order of Operations

1. **Build/compile checks**: These are the foundation. If the project doesn't build, nothing else matters.
   - Package installation (`npm install` / equivalent)
   - TypeScript compilation (`npx tsc --noEmit` / equivalent)
   - Linter pass (`npm run lint` / equivalent)
   - Build succeeds (`npm run build` / equivalent)

2. **Automated test suites from all earlier milestones**: Every test command recorded for every earlier milestone in `docs/project/milestones.md` (its checkpoint checks and the tests named in its wiring table), plus the project's full test command.
   - Run in milestone order: M1's checks, then M2's, then M3's, etc.
   - Each milestone's checks must all pass before moving to the next milestone's checks.
   - The demo run also replays every earlier milestone's demo ending from a clean start; a regression demo step that fails is a regression like any other.

3. **Cross-milestone interaction tests**: New tests that verify M{k} doesn't break earlier milestones.
   - Shared component rendering (components used by multiple milestones)
   - API endpoint availability (endpoints from earlier milestones still respond)
   - Data integrity (data structures from earlier milestones still valid)
   - Navigation flows (routes from earlier milestones still accessible)

### Execution Protocol

For each regression check:

```
1. Run the command exactly as recorded, through python3 <heavy.py> run -- <command>
2. Capture exit code + full output (into .evidence/gate/M<k>/r<n>/)
3. Compare against expected result
4. Record: PASS (matches) or FAIL (doesn't match); NOT_RUN with the reason if it could not run
   (exit 75 means the lock stayed busy and the command never ran: NOT_RUN, never PASS)
5. If FAIL → STOP immediately
```

### On Regression Failure

If ANY regression check fails:

1. **STOP all further checking immediately**: do not proceed to new tests
2. Identify which earlier milestone is affected
3. Determine the likely cause in M{k} (what changed that broke it)
4. Present diagnostic:

```
REGRESSION FAILURE: review halted

Failed check: {check description}
From milestone: M{j}
Command: {command}
Expected: {expected output}
Actual: {actual output}

Likely cause in M{k}:
{analysis of what M{k} changed that broke M{j}}

Recommended action:
{specific fix recommendation}

M{k} cannot pass the gate until the regression is resolved.
Run the gate on M{k} again after fixing.
```

5. The code-verifier does NOT fix regressions; it reports and halts. The owner decides whether to fix it by hand or send it back to the builder.

---

## Section 2: Coverage Gap Analysis

Before running new checks, map every testable behavior of the milestone to verify nothing is untested.

### Requirement-to-Test Mapping

For every requirement of the milestone under test in `docs/project/milestones.md` (its done examples, the carried done examples from `docs/project/intent.md`, the must-not-lose items it touches, and its wiring rows):

| Requirement (from docs/project/milestones.md) | Build Check Covering It | Gate Check Covering It | Gap? |
|------------------------------|---------------------|---------------------|------|
| {done example such as M1.D1 or I-D1, must-not-lose item such as L-01, or wiring row} | {which checkpoint or project test covers this} | {gate check or finding ID} | {Yes/No} |

A build check is one the builder wrote and ran (a checkpoint command, a project test); a gate check is one the code-verifier ran itself.

Rules:
- Every requirement MUST have at least one gate check (not just a build check)
- If a requirement has only a build check and no gate check, that's a gap: create a gate check
- If a requirement has no coverage at all, that's a critical gap: create P0 gate checks

### Error Path Coverage

For every error path in the code (identified via Grep for try/catch, error boundaries, error states):

| Error Path (file:line) | What Triggers It | Check ID | Covered? |
|------------------------|-----------------|---------|----------|
| {file:line of catch block} | {condition that triggers it} | {gate check or finding ID, or "NONE"} | {Yes/No} |

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

## Section 3: Cross-Milestone Interaction Testing

M{k} may break earlier milestones in subtle ways. Test for these patterns:

### Shared File Modifications

If M{k} modified any file that exists since an earlier milestone:

1. Identify ALL features in earlier milestones that depend on that file
2. For each feature, run its original check or create a new test
3. Verify the modification didn't change behavior for earlier features

### New Dependencies

If M{k} added new packages:

1. Run `npm ls` or equivalent to check for dependency conflicts
2. Verify no peer dependency warnings
3. Check that earlier milestones' imports still resolve
4. Verify bundle size didn't dramatically increase

### Changed Types/Interfaces

If M{k} modified any shared types or interfaces:

1. Grep for all usages of the changed type across the codebase
2. Verify every consumer still compiles
3. Verify runtime behavior matches: types can compile but behave differently

### Shared State

If M{k} modifies global state, context, or shared stores:

1. Test that earlier milestones read the correct values from shared state
2. Verify no state pollution between features
3. Check that state initialization still works for earlier milestones' flows

---

## Section 4: Regression Failure Handling

### Classification

All regression failures are automatically **P0 CRITICAL**. No exceptions.

A regression means M{k} broke something that was working. This is always worse than a new feature not working, because it indicates:
- The change had unintended side effects
- The developer missed a dependency between milestones
- The project's integrity guarantee is broken

### Response Protocol

1. **Record the failure with full evidence**: command, expected, actual, error output
2. **Do NOT attempt to fix**: the code-verifier reports; it does not fix the code
3. **Do NOT proceed with other tests**: Results would be unreliable on a broken foundation
4. **Do NOT mark any tests as "skipped due to regression"**: They are NOT_RUN, with the regression as the reason (never SKIP, which means the check does not apply, and never PASS)
5. **Report clearly**: The owner needs to know exactly what broke and likely why
6. **Suggest resolution**: Based on analysis, suggest what in M{k} likely caused the regression

### After Resolution

When the regression is reported fixed:
- Run the gate on M{k} again from the beginning, as a new round
- Do NOT resume from where the halted round stopped; start fresh (evidence from the earlier build is STALE)
- The entire regression suite must pass before any new tests run

---

## Section 5: Game-Specific Regression Surfaces

Game projects have regression surfaces that standard web apps don't. These must be re-validated as regression checks alongside the build and test checks.

### 5.1 Content Graph Regression

When earlier milestones established content data files (JSON/YAML with cross-references):
- Re-validate all foreign key references from ALL earlier milestones' content files
- A new milestone may have renamed, moved, or deleted content that earlier content references
- Tool: Grep to extract IDs, Read to verify targets exist

### 5.2 Save/Load Regression

When earlier milestones established save/load infrastructure:
- Re-run all earlier milestones' save/load round-trip tests
- A new milestone adding store modules may break serialization of existing modules
- A schema change may invalidate existing save formats
- Tool: Vitest (run existing save/load test files)

### 5.3 Deterministic Replay Regression

When golden replay fixtures exist from earlier milestones (`tests/engine/fixtures/`):
- Re-run ALL golden replays
- A code change that alters RNG call order, state transition logic, or formula calculations will cause a replay deviation
- Any deviation is a P0 regression: it means the game behaves differently for the same inputs
- Tool: Vitest (replay fixture files)

### 5.4 Cross-System Interaction Regression

When earlier milestones established system interactions:
- Re-run all earlier milestones' cross-system interaction tests
- A new milestone modifying shared state may break downstream consumers
- Tool: Vitest (run existing cross-system test files)

### 5.5 i18n Key Regression

When earlier milestones added translation keys:
- Verify all earlier milestones' keys still exist in all locale files
- A refactor that changes component structure may orphan translation keys
- Tool: Grep + diff against locale files

### Execution Order (Extended for Games)

After the standard regression order (Section 1), append:

4. **Content graph regression** (if content files exist from earlier milestones)
5. **Save/load round-trip regression** (if save/load tests exist)
6. **Golden replay regression** (if fixture files exist in `tests/engine/fixtures/`)
7. **Cross-system interaction regression** (if cross-system tests exist)
8. **i18n key regression** (if locale files have keys from earlier milestones)
