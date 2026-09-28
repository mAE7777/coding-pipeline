# Game QA Protocol

Executable testing protocols for game projects. Every protocol below produces concrete test specifications the code-verifier executes against the milestone under test.

**When to load**: when the project is a game or simulation.

---

## Applicability

Not every protocol applies to every game or every milestone. Select protocols based on what the milestone actually touches:

| Protocol | Applies When |
|----------|-------------|
| Content Graph Integrity | Milestone creates/modifies content data files (JSON/YAML with cross-references) |
| Save/Load Round-Trip | Milestone modifies game state structure or adds new store modules |
| Cross-System Interaction | Milestone adds/modifies a game system that reads from or writes to shared state |
| Simulation & Reachability | Milestone adds gameplay content (events, quests, progression gates, AP actions) |
| Deterministic Replay | Milestone uses or modifies RNG-dependent logic |
| i18n Completeness | Milestone adds user-facing text (any `t()` calls or locale keys) |
| State Machine Correctness | Milestone implements or modifies a state machine (combat phases, game phases, event flow) |

If a milestone doesn't touch any of these concerns, omit the corresponding protocol's tests entirely and report the protocol SKIP with the reason. Never generate game tests for a milestone that only changes configuration, tooling, or non-game code.

---

## Protocol 1: Content Graph Integrity

Games are webs of cross-references. Schema validation catches malformed data; this protocol catches broken references: an event that names an enemy that doesn't exist, a reward that references an item with no definition, a stat check against a stat name that isn't in the stat system.

### What to Validate

For every content data file created or modified in this milestone:

1. **Foreign key resolution**: Extract all ID references (enemy IDs, item IDs, stat names, location IDs, event IDs, NPC IDs). Resolve each to its target definition. Flag any that don't resolve.

2. **Numeric constraint validation**: For every numeric value that interacts with a game system, verify it falls within system constraints:
   - Stat check difficulty ≤ stat cap (e.g., if max stat is 10, a check requiring 12 is impossible)
   - AP costs ≤ max AP pool per phase
   - Prices ≤ max earnable currency at that game stage (if determinable)
   - Damage values are non-negative
   - Probability weights are > 0

3. **Completeness checks**:
   - Every event has at least one choice
   - Every choice has at least one outcome
   - Every enemy has defined stats (HP, damage, etc.)
   - Every item has a defined effect or description
   - No content file is empty or has only a schema wrapper with no data

4. **Orphan detection**: Content defined but never referenced by any event, quest, location, or other trigger. Orphaned content is dead weight: it passes all tests but players never see it.

### Test Generation

```
ID: B-CG-{NN}
Category: Functional Correctness (Content Graph)
Priority: P0
Description: All {content_type} references in {file} resolve to existing definitions
Given: {file} contains references to {referenced_type} IDs [{id_list}]
When: Each reference ID is looked up in {target_directory_or_registry}
Then: Every reference resolves to a valid definition. Zero dangling IDs.
Tool: Grep + Read (extract IDs from source, verify existence in target)
Verification: List of resolved vs unresolved references
```

```
ID: B-CG-NC-{NN}
Category: Functional Correctness (Content Graph: Numeric Constraints)
Priority: P0
Description: {value_name} in {file} falls within system constraints
Given: {file} defines {value_name} = {value}
When: Value is compared against system constraint ({constraint_name} = {constraint_value})
Then: Value satisfies constraint ({comparison})
Tool: Read + arithmetic comparison
Verification: Value vs constraint
```

---

## Protocol 2: Save/Load Round-Trip

A save must capture ALL game state. A load must restore it exactly. If any store module is missed, the loaded game diverges. This protocol tests serialization fidelity, not just "does save/load not crash."

### What to Validate

For every milestone that modifies state structure (adds a store module such as a new Zustand store or Redux reducer, changes a schema, adds a new persistent value):

1. **Module inventory**: List every store module that should persist. Compare against what the save function actually serializes. Flag any module present in the store but absent from serialization.

2. **Round-trip fidelity**: For each store module:
   - Create a known state (non-default values: edge cases like empty arrays, max values, special characters in strings)
   - Serialize (save)
   - Destroy all in-memory state
   - Deserialize (load)
   - Assert every field matches the pre-save values exactly (deep equality, not reference equality)

3. **RNG state preservation** (if applicable):
   - Save game state including RNG state
   - Record the next N random outputs (e.g., 10 calls to rng())
   - Load game state
   - Generate N random outputs
   - Assert both sequences are identical

4. **Schema migration** (when state schema changes between milestones):
   - Create a save in the OLD schema format
   - Load with the NEW code
   - Assert migration produces valid state (no undefined fields, no type mismatches)
   - Assert gameplay continues correctly from migrated state

5. **Corruption resilience**:
   - Truncated save data → graceful error, not crash
   - Missing fields → defaults applied or clear error message
   - Extra fields (from future version) → ignored, not crash

### Test Generation

```
ID: J-SL-{NN}
Category: Game Simulation (Save/Load)
Priority: P0
Description: Save/load round-trip preserves {store_module} with non-default values
Given: Game store has {store_module} set to known non-default values {specific_values}
When: Full state serialized to persistence layer, all in-memory state cleared, then deserialized
Then: {store_module} values match pre-save values exactly (deep equality)
Tool: Vitest (unit test against store + persistence layer)
Verification: Deep equality assertion on every field
```

```
ID: J-SL-RNG-{NN}
Category: Game Simulation (Save/Load: RNG)
Priority: P0
Description: RNG state survives save/load cycle
Given: Game initialized with seed {seed}, RNG advanced {M} times
When: State saved, in-memory cleared, state loaded, then RNG called {N} times
Then: The {N} outputs match what the original RNG would have produced
Tool: Vitest
Verification: Sequence comparison
```

---

## Protocol 3: Cross-System Interaction

Games have many systems that share state. Unit tests verify each system in isolation. This protocol tests the connections between systems, where bugs actually hide.

### What to Validate

When a milestone adds or modifies a game system, identify every other system that:
- Reads state this system writes (downstream consumers)
- Writes state this system reads (upstream producers)

For each intersection, create a scenario that exercises the connection.

### Common Intersection Patterns

| System A (Producer) | System B (Consumer) | What to Test |
|---------------------|---------------------|-------------|
| Stats | Combat | Stat values correctly modify damage/defense formulas |
| Stats | Events | Stat thresholds correctly gate event choices |
| Inventory | Events | Items enable/disable event options |
| Inventory | Combat | Equipment modifies combat stats |
| Combat | Stats | Combat outcomes grant correct stat XP |
| Combat | Inventory | Victory loot is added to inventory |
| Events | Stats | Event outcomes modify stats correctly |
| Events | Conditions | Event outcomes apply/remove conditions |
| Conditions | Combat | Active conditions modify combat behavior |
| Conditions | Events | Active conditions gate event availability |
| Calendar | Events | Week/season correctly filters event pools |
| Calendar | Stats | Time passage triggers stat decay/growth |
| AP System | All Actions | AP cost enforced; insufficient AP prevents action |

### Test Generation

```
ID: J-CS-{NN}
Category: Game Simulation (Cross-System)
Priority: P0
Description: {System A} state correctly affects {System B} via {shared_state}
Given: {System A} has set {shared_state} to {specific_value}
When: {System B} performs {action} that reads {shared_state}
Then: {System B}'s result reflects {shared_state}'s value per {formula_or_rule}
Tool: Vitest (both systems initialized, no mocks for shared state)
Verification: Assert result matches formula computation
```

### Key Principle

Cross-system tests must use **real system instances**, not mocks. The whole point is to verify the wiring between systems. Mocking the connection is testing nothing.

---

## Protocol 4: Simulation & Reachability

The most important game-specific question: "Can the player get stuck?" This protocol uses automated playthroughs to detect unwinnable states, dead-end paths, and impossible progression gates.

### What to Validate

For milestones that add gameplay content (events, quests, progression gates, AP-costed actions):

1. **Progress definition**: Define what "progress" means for this milestone:
   - Week advances (calendar moves forward)
   - Quest stage completed
   - Story flag set
   - New area unlocked
   - Boss defeated

2. **Strategy simulation**: Run automated playthroughs with different player strategies:

   | Strategy | Description | What It Catches |
   |----------|-------------|-----------------|
   | Random valid | Choose random legal action each turn | Crashes, invalid states, assertion failures |
   | Greedy stat | Always pick highest stat-gain action | Stat system edge cases, cap overflow |
   | Combat-avoidant | Avoid combat whenever possible | Can player progress without fighting? |
   | Combat-focused | Always seek combat | Combat reward balance, difficulty curve |
   | Minimal AP | Spend minimum AP per week | Can player progress with conservative play? |
   | Worst-case | Make the worst valid choice each turn | Dead-end detection, unwinnable states |

3. **Invariant checking**: After every action in every simulation:
   - Game state is valid (no negative HP, no stats above cap, no negative AP)
   - At least one legal action exists (player is not stuck)
   - No infinite loops (action count per week is bounded)

4. **Reachability analysis**: After N simulated weeks:
   - At least one progress marker was reached
   - If not: flag as potential dead-end with the action sequence that led there

### Test Generation

```
ID: J-SIM-{NN}
Category: Game Simulation (Reachability)
Priority: P0
Description: {strategy} strategy reaches progress within {N} weeks
Given: New game initialized with {starting_conditions}
When: Player follows {strategy} pattern for {N} game weeks (engine-level, no UI)
Then: At least one progress marker reached; no invalid state encountered at any step
Tool: Vitest (engine function calls in a loop; no UI, no browser)
Verification: Assert progress markers exist; assert all intermediate states valid
```

### Simulation Loop Template (Turn-Based)

Simulation tests follow this pattern, whether they ship with the project or the code-verifier writes them as a scratch harness in its copy:

```
initialize game with seed
for each week up to N:
  get available actions from engine
  assert at least one action is available (not stuck)
  choose action per strategy
  execute action via engine
  assert game state is valid (all invariants hold)
  if week should advance:
    advance week via engine
    assert week state is valid
assert at least one progress marker reached
```

This runs entirely at the engine level: pure function calls, no rendering, no browser. Fast and deterministic.

---

## Protocol 5: Deterministic Replay

When a game uses seeded RNG, the same seed + same actions must produce the same outcomes. This is a powerful regression tool: record a "golden replay" and re-run it after every code change.

### What to Validate

1. **Golden replay creation** (first time a game system is introduced):
   - Pick a seed
   - Execute a specific action sequence
   - Record every outcome (damage dealt, event drawn, stat changed, item received)
   - Store as a test fixture: `{ seed, actions: [...], expectedOutcomes: [...] }`

2. **Replay regression** (every subsequent milestone):
   - Load fixture
   - Initialize game with seed
   - Execute action sequence
   - Assert every outcome matches the fixture
   - Any deviation = regression (code change altered game behavior)

3. **RNG isolation**: Verify that RNG calls are deterministic:
   - Same seed always produces same sequence
   - RNG state advances consistently (no skipped or extra calls)
   - Adding a new system doesn't alter RNG sequence for existing systems (each system should have its own RNG stream, or the call order must be stable)

### Test Generation

```
ID: A-DR-{NN}
Category: Regression (Deterministic Replay)
Priority: P0
Description: Golden replay "{replay_name}" produces identical outcomes after M{k} changes
Given: Seed {seed}, action sequence [{actions}]
When: Game initialized with seed, actions executed in order via engine
Then: Each outcome matches recorded expected outcome exactly
Tool: Vitest (engine-level replay against fixture file)
Verification: Per-action outcome comparison
```

### When to Create New Golden Replays

- When a new game system is introduced (combat, events, crafting, etc.)
- When an existing system's behavior is intentionally changed (update the fixture)
- Keep replays small (5-15 actions) and focused on one system each
- Store fixtures in `tests/engine/fixtures/` or equivalent

---

## Protocol 6: i18n Completeness

For text-first games, a missing translation key = a broken game screen. This protocol ensures every key used in code exists in every locale file.

### What to Validate

1. **Key extraction**: Find all translation key usages in the milestone's code:
   - `t("key")`, `t('key')` calls
   - `useTranslations("namespace")` scopes
   - Message references in components
   - Template literal keys: `t(\`dynamic.${var}\`)`; flag as dynamic, verify base namespace exists

2. **Locale completeness**: For each key found:
   - Exists in the primary locale (the project's main language, for example zh) → P0 if missing
   - Exists in all other locales (en, etc.) → P1 if missing

3. **Orphan keys**: Keys in locale files that aren't referenced by any code. Not a bug, but indicates dead content that should be cleaned up. P2.

4. **Structural consistency**: Locale files should have identical key structures. A key nested under `game.combat.hit` in zh.json but `game.combat.strike` in en.json is a structural mismatch.

### Test Generation

```
ID: H-I18N-{NN}
Category: Convention Compliance (i18n Completeness)
Priority: P0
Description: All translation keys in M{k} code exist in {locale} locale file
Given: Milestone code uses translation keys via t() or useTranslations()
When: Keys are extracted from code and compared against {locale_file}
Then: Every code-referenced key exists in the locale file. Zero missing keys.
Tool: Grep (extract t() calls) + Read (check locale JSON) + Bash (diff)
Verification: List of missing keys (expect empty)
```

```
ID: H-I18N-STRUCT-{NN}
Category: Convention Compliance (i18n Structure)
Priority: P1
Description: All locale files have identical key structures
Given: Locale files {locale_files} exist
When: Key paths are extracted from each file and compared
Then: Every key path in any locale exists in all locales. No structural mismatches.
Tool: Bash (extract JSON key paths, diff)
Verification: Diff output is empty
```

---

## Protocol 7: State Machine Correctness

Games are full of state machines: combat phases, game turn phases, event resolution flows, menu navigation. Each has valid states, valid transitions, and (critically) invalid transitions that must be rejected.

### What to Validate

For every state machine in the milestone:

1. **State inventory**: List every state from the code. Compare against design spec. Flag undocumented states.

2. **Transition coverage**:
   - Every valid transition: trigger condition → assert new state + side effects
   - Every invalid transition: trigger condition that shouldn't cause transition → assert state unchanged
   - Terminal states: assert no further transitions possible (or that only "reset" transitions exist)

3. **State persistence**: State machines must survive save/load (cross-reference with Protocol 2).

4. **Concurrent state machines**: If multiple state machines run simultaneously (e.g., combat state + condition timers), verify they don't interfere with each other.

### Test Generation

```
ID: J-SM-{NN}
Category: Game Simulation (State Machine)
Priority: P0
Description: {state_machine} transitions from {state_A} on {trigger} to {state_B}
Given: {state_machine} is in state {state_A}
When: {trigger} condition occurs
Then: State becomes {state_B}; {state_A} behavior stops; {state_B} behavior is active; side effects {effects} applied
Tool: Vitest (engine-level state machine test)
Verification: Assert currentState, assert side effects, assert old behavior inactive
```

```
ID: J-SM-INV-{NN}
Category: Game Simulation (State Machine: Invalid Transition)
Priority: P0
Description: {state_machine} rejects {invalid_trigger} in state {state_A}
Given: {state_machine} is in state {state_A}
When: {invalid_trigger} occurs (not a valid trigger for {state_A})
Then: State remains {state_A}; no side effects applied; no crash
Tool: Vitest
Verification: Assert currentState unchanged, no errors thrown (or specific error thrown)
```

---

## Integration with the Gate

### How This File Gets Used

1. **Selecting protocols**: The code-verifier reads this file when the project is a game, picks the protocols the Applicability table selects for the milestone under test, and derives test specifications from the templates. A protocol that does not apply is reported SKIP with the reason.

2. **Automated checks**: Content graph checks and replay regression run as test commands alongside the project's own suite, each through the machine-wide lock: `python3 <heavy.py> run -- <command>`.

3. **Engine-level simulation**: Simulation, save/load, cross-system, and state machine tests run as engine-level test commands through the same lock, never through the browser script. They're engine-level, not UI-level.

4. **Coverage review**: The code-verifier also checks whether game systems have tests for the protocols above. A system without cross-system tests or without save/load coverage is a finding, even when every test that exists passes. A protocol that applies but could not run is NOT_RUN with the reason, never counted as passing.

### Category Mapping

| Protocol | Test category (ID prefix) | Priority |
|----------|------------|----------|
| Content Graph Integrity | B (Functional Correctness) | P0 |
| Save/Load Round-Trip | J (Game Simulation) | P0 |
| Cross-System Interaction | J (Game Simulation) | P0 |
| Simulation & Reachability | J (Game Simulation) | P0 |
| Deterministic Replay | A (Regression) | P0 |
| i18n Completeness | H (Convention Compliance) | P0 |
| State Machine Correctness | J (Game Simulation) | P0 |
