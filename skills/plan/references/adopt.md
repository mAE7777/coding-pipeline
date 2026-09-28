# Adopting a project that has no complete build record

Loaded by `/plan adopt`. The goal: understand everything that exists, reconstruct the record every later
step relies on, prove it matches reality, and lock it with the owner. Understanding comes first and is never
cut to save rounds: every reading loop ends when a round finds nothing new, not at a count.

## Order (cheap and deterministic first)
1. **Inventory**: `adopt.py inventory <project>`. It writes `docs/project/research/adoption/` with the file
   classes, the documents ranked by authority signals, discovered commands and entry points, routes, model
   calls and degradation candidates, git facts, a reading plan by area, and the coverage ledger. Lock files,
   vendored, generated, binary, and asset files are pre-accounted there; do not read them.
2. **Everything that exists, read through `/capture`'s rounds**, documents and code alike, so a detail lost or
   misread anywhere is caught the same way:
   - `capture.py add <project> --inventory`: every file the inventory lists (documents, code, tests,
     configuration, anything else with text) becomes a source; code in windows of 150 lines. The coverage
     ledger rows become `captured · SRC-<n>`; a file that could not be read stays todo with the reason.
   - `capture.py add <project> --git-log`: the commit history, one unit per commit, where the reasons behind
     decisions often live. `capture.py add <project> --tracker`: the GitHub issues and pull requests with their
     comments; when it cannot be read (no access, no GitHub remote), write `Tracker: not read (<reason>)` in
     the brief so the owner sees it at the lock. The owner's chats, notes, and recordings join the same way.
   - Organize the dossier in the `/capture` grammar: every document section, code window, and record carried by
     a unit or listed as read with nothing to keep. For code, units say what it does and how: entry points,
     commands and routes, what it reads and writes, state and invariants, failure handling (and where a failure
     goes silent), external calls, configuration, hazards, dead or unwired parts, each quoting the line and
     citing the window. Large areas can go to read-only explorers (the built-in Explore agent), at most three at
     once, each reading its area in full and returning draft units with verbatim quotes; you add them.
   - The independent extraction rounds over every source, code included, until a round finds nothing the
     dossier missed; then the fidelity reads. `capture.py check` passing is the proof.
   Where documents disagree with each other or with the code, record both positions and the authority signal
   of each; the owner settles it at the lock. Nothing is skimmed: outlining is not reading, and a file is
   captured, or skipped with a reason the owner can see.
3. **Every point lands in the record.** Each dossier unit gets a row in the brief's `## Source closure`
   (`intent (...)`, `brief (...)`, `interfaces (...)`, `milestone M0`, `unknown U-<nn>`, `named non-goal (...)`,
   `not adopted (...)`); `capture.py closure` passing is the proof that nothing understood was lost on the way
   into the record.
4. **Run it**: write the labeled commands into `AGENTS.md` and run `adopt.py commands`. A failing build or
   test is a fact for the brief's starting state, never hidden.
5. **Reconstruct the record** with an evidence label on every reconstructed statement: `[code path:line]`,
   `[doc path]`, `[git <sha>]`, `[inferred]` (reasoned, not found), and later `[owner <date>]`.
   - `intent.md` (Status: draft): the goal, identity, and persona as the documents and the code support
     them; done examples for what the product demonstrably does, each labeled; mechanism cards for its
     load-bearing mechanisms; must-not-lose items the documents state or the code enforces, each labeled.
   - `milestones.md`: `M0 · As found`, the product today, with a demo ending you have run, a wiring table
     whose statuses are what you found (UNWIRED and PHANTOM rows included), and the owner's next milestones
     after it once they are discussed.
   - `interfaces.md` from the code's real seams; `decisions.md` with the decisions the history and documents
     show, each labeled `[doc ...]` or `[git ...]`; `brief.md` with the starting state (dated, evidenced),
     constraints found in documents (labeled), unknowns, and the placeholder manifest (stand-ins found in the
     code); `gate.md` with the intent-bearing documents found; `state.md`.
   - An earlier pipeline's files: the convert steps (`convert.md`), each old file marked
     `> SUPERSEDED <date>: <what replaces it>` at its top, never deleted.
6. **Check**: `adopt.py check` (every file captured or skipped with a reason, the history and tracker read,
   the dossier's rounds and closure passing, every record file present, commands run, M0 present, evidence
   labels, legacy marked, the characterization current; that last part passes once step 8 has run), then
   `intent_lock.py lint` and `milestone_lint.py`.
7. **Independent reads**: the documents cold reader on intent, brief, and milestones (with `--with-record`,
   until a read comes back clear, as in the plan's cold-read step); the document rounds and fidelity reads
   are already done in step 2.
8. **Characterization**: `python3 ~/.claude/skills/_shared/scripts/gate_run.py <project> --milestone M0
   --intent-only` in the background (no freeze and no lock needed: the draft intent is what is being tested,
   and the deterministic facts are already recorded by `adopt.py commands`). The blind evaluator reconstructs
   what the code does; the judge compares it with the reconstructed intent. Claims in the documents the code
   does not back come back as PHANTOM or MISSING; behavior no document mentions comes back as EXTRA or
   ORPHAN. Where the draft was simply wrong, correct it and characterize again; repeat until a run finds
   nothing the draft should have said (`adopt.py check` fails while the latest run read an older draft). What
   remains is a real discrepancy between the documents, the code, and what the owner may want: list each row
   in the brief's `## Discrepancies` with what it is and the owner's question. The full `/gate M0` round runs
   after the lock, as the baseline the next milestone builds on.
9. **The lock**, once `adopt.py check` passes in full, discrepancies first: what the documents claim that the code does not do, what the code does
   that nothing documents, conflicting documents and the proposed authority order, failing commands, stand-ins
   found. The owner confirms or corrects; the intent is locked (`/plan` step 8) and the owner's acceptance of
   M0 is recorded as the baseline.

## Context first, then economy
Enough context is the point; economy only means never paying twice for the same thing. What you learn goes to
disk at once, so nothing has to be re-read after a compaction, and nothing is re-read without a reason. A
reason is enough: when a later finding shows an earlier reading was thin, read it again. Documents are read in
full because they carry intent; code is read in full wherever its role is not settled by an outline, and every
outline records why it was enough. Running the product and its tests answers many questions more cheaply than
reading, and adds to reading rather than replacing it. Explorers return summaries, not file dumps, and their
notes on disk carry the detail.
