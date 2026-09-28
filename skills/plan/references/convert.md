# Converting an earlier pipeline's files

Loaded by `/plan convert` and by adoption when `record_check.py` reports `legacy-v2`. Every old file is kept
and marked `> SUPERSEDED <date>: <what replaces it>` on its first line; nothing is deleted.

| Old file | New home | How |
|---|---|---|
| `intent-anchor.md` | `docs/project/intent.md` | Goal, identity, persona, must-not-lose items carry over. Each requirement statement becomes a done example with one concrete example (write the example; if you cannot, it is a question for the owner). Mechanism cards are written fresh for the load-bearing mechanisms. The old hash and CONFIRM record become a decision entry quoting the original sign-off; the new intent is locked again with the owner. |
| `slices.md` | `docs/project/milestones.md` | Group slices into milestones by demo ending: consecutive slices that together let a person do one new thing end to end form one milestone. Slice acceptance criteria become milestone done examples; shipped and verified slices make an accepted milestone only when the owner accepts it again from a fresh demo. The idea-anchor footer becomes the `## Idea-anchor closure` table (`| K1 | ... | IN-MILESTONE @M2 |`); slice part brackets become `Parts:` lines. |
| `contracts.md` | `docs/project/interfaces.md` | Ports, shapes, failure semantics, and the contract tests, each owned by the milestone that introduces it. |
| `qa-reports/` | `docs/project/reviews/` | Keep as history; findings still open go into the new findings ledger as logged items. |
| `pipeline-state.md`, `phases.md` | `docs/project/state.md` | The current position, open items, blockers, and next step. |
| `key-learnings.md` | `docs/project/decisions.md` and `brief.md` | Decisions with their reasons become decision entries labeled `[doc key-learnings.md]`; environment facts go to the brief's starting state. |
| `AGENTS.md` / `CLAUDE.md` pipeline sections | `docs/project/gate.md` | Gate keys and heavy commands move to the local gate settings; the map and labeled commands stay. |

After converting, run `record_check.py` (it should report `complete` once the lock is done), `milestone_lint.py`,
and `intent_lock.py verify`.
