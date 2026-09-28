# Adopting a project that has no complete build record

Loaded by `/plan adopt`. The goal: understand everything that exists, reconstruct the record every later
step relies on, prove it matches reality, and lock it with the owner. Understanding comes first and is never
cut to save rounds: every reading loop ends when a round finds nothing new, not at a count.

## Order (cheap and deterministic first)
1. **Inventory**: `adopt.py inventory <project>`. It writes `docs/project/research/adoption/` with the file
   classes, the documents ranked by authority signals, discovered commands and entry points, routes, model
   calls and degradation candidates, git facts, a reading plan by area, and the coverage ledger. Lock files,
   vendored, generated, binary, and asset files are pre-accounted there; do not read them.
2. **Documents first, all of them**, through `/capture`'s whole procedure: import every document, record, and
   log the inventory lists (`capture.py add <project> <file or folder>`; the owner's own notes with `--speaker
   owner`; chat exports and recordings the owner points to as well), organize the dossier (every document
   section and log window accounted for), run the independent extraction rounds until one finds nothing the
   dossier missed, then the fidelity reads, with `capture.py check` passing.
   Where documents disagree, record both positions and the authority signal of each; the owner settles
   the order at the lock. A document is `read`, `stale (<evidence>)`, or `superseded (<by what>)` in the
   ledger, never skimmed; a `read` row cites its source in the note (`SRC-3`), and `adopt.py check` holds
   every inventory file to a ledger row, so a row removed from the ledger is a FAIL, never an account.
3. **Code by area**, in the reading plan's order. Read each area in full and write what you learned to disk
   before moving on: the record files as they take shape, and for each area a note in
   `research/adoption/areas/<area>.md` (what it does, entry points, seams, state, failure handling,
   hazards, with `path:line` evidence), whose first line is `Load-bearing: yes (<why>)` or `Load-bearing: no
   (<why>)`. An area is load-bearing when the product's promise, its data, or its failure handling rests on
   it. Areas above the plan's size line go to a read-only explorer (the built-in Explore agent in Claude Code),
   at most three at once, each told to write its area note with evidence and to report only a short summary.
   Mark each file in the ledger: `read`, `outlined (<why the rest was not needed>)`, `delegated
   (areas/<area>.md)`, or `skipped (<reason>)`; outline only a file whose role the outline settles completely,
   and when in doubt read it in full.
   **Second reading of every load-bearing area**: a read-only explorer that has not seen your note reads the
   area's code and writes `areas/<area>.second.md` in the same shape. Compare the two and write `##
   Reconciled` in your note, one line per difference: `- <difference> · <note corrected | second reading wrong
   (<why, with path:line>) | unknown U-<nn> | owner (<question>)>`. When a difference shows your reading was
   thin, read the area again; when the second reading finds much you missed, run a third on what was missed.
4. **Run it**: write the labeled commands into `AGENTS.md` and run `adopt.py commands`. A failing build or
   test is a fact for the brief's starting state, never hidden.
5. **Reconstruct the record** with an evidence label on every reconstructed statement: `[code path:line]`,
   `[doc path]`, `[git <sha>]`, `[inferred]` (reasoned, not found), and later `[owner <date>]`.
   - `intent.md` (Status: draft): the goal, identity, and persona as the documents and the code support
     them; done examples for what the product demonstrably does, each labeled; mechanism cards for its
     load-bearing mechanisms; must-not-lose items the documents state or the code enforces.
   - `milestones.md`: `M0 · As found`, the product today, with a demo ending you have run, a wiring table
     whose statuses are what you found (UNWIRED and PHANTOM rows included), and the owner's next milestones
     after it once they are discussed.
   - `interfaces.md` from the code's real seams; `decisions.md` with the decisions the history and documents
     show, each labeled `[doc ...]` or `[git ...]`; `brief.md` with the starting state (dated, evidenced),
     constraints found in documents (labeled), unknowns, and the placeholder manifest (stand-ins found in the
     code); `gate.md` with the intent-bearing documents found; `state.md`.
   - An earlier pipeline's files: the convert steps (`convert.md`), each old file marked
     `> SUPERSEDED <date>: <what replaces it>` at its top, never deleted.
6. **Check**: `adopt.py check` (every file accounted for, every record file present, commands run, M0
   present, evidence labels, legacy marked, the dossier passing), then `intent_lock.py lint` and
   `milestone_lint.py`.
7. **Independent reads**: the documents cold reader on intent, brief, and milestones (with `--with-record`,
   until a read comes back clear, as in the plan's cold-read step); the document rounds and fidelity reads
   are already done in step 2.
8. **Characterization**: `python3 ~/.claude/skills/_shared/scripts/gate_run.py <project> --milestone M0
   --intent-only` in the background (no freeze and no lock needed: the draft intent is what is being tested,
   and the deterministic facts are already recorded by `adopt.py commands`). The blind evaluator reconstructs
   what the code does; the judge compares it with the reconstructed intent. Claims in the documents the code
   does not back come back as PHANTOM or MISSING; behavior no document mentions comes back as EXTRA or
   ORPHAN. Each is a discrepancy for the owner, not a failure of the adoption. The full `/gate M0` round runs
   after the lock, as the baseline the next milestone builds on.
9. **The lock**, discrepancies first: what the documents claim that the code does not do, what the code does
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
