# Adopting a project that has no complete build record

Loaded by `/plan adopt`. The goal: understand everything that exists, reconstruct the record every later
step relies on, prove it matches reality, and lock it with the owner, within the owner's budget: an adoption
stays within 5 percent of the week's allowance and stops at 10 until the owner raises it. Every load-bearing
point is read and checked; a detail that decides nothing stays one lookup away in the verbatim files. Every
checking loop ends when a pass finds nothing material, never at a count.

## Order (cheap and deterministic first)
0. **Budget**: `python3 ~/.claude/skills/_shared/scripts/spend.py start <project> --phase adopt`. After every
   step, `spend.py status <project>`: over the target, tell the owner at the next stop what it has cost, what
   remains, and the estimate; over the cap, the runner refuses new reads, so stop and report; only the owner
   raises the cap (`spend.py raise`, in their words). There are no helper agents in an adoption: reading is
   yours or an isolated run's, so its cost is bounded and measured.
1. **Inventory**: `adopt.py inventory <project>`. It writes `docs/project/research/adoption/` with the file
   classes, the documents ranked by authority signals, discovered commands and entry points, routes, model
   calls and degradation candidates, git facts, a reading plan by area, and the coverage ledger. Lock files,
   vendored, generated, binary, and asset files are pre-accounted there; do not read them.
2. **Everything that exists, each kind read the way that understands it**:
   - `capture.py add <project> --inventory`: documents, reports, and small configuration become sources (ledger
     `captured · SRC-<n>`); code and tests are mapped (`mapped (code map)`); data, raw output, and logs are
     registered with a script summary in `research/adoption/bulk.md` (`registered (bulk)`); a file that could
     not be read stays todo with the reason. Then `spend.py estimate <project>`: above the target, tell the owner
     before reading, with what a smaller plan would leave unread (the largest sources first), and let them
     choose.
   - `capture.py add <project> --git-log`: the commit history, one unit per commit, where the reasons behind
     decisions often live. `capture.py add <project> --tracker`: the GitHub issues and pull requests with their
     comments; when it cannot be read (no access, no GitHub remote), write `Tracker: not read (<reason>)` in
     the brief so the owner sees it at the lock. The owner's chats, notes, and recordings join the same way.
   - The sources are read the `/capture` way (its steps 2 to 4): an isolated extraction drafts the dossier, you
     edit it, and isolated audits check it until an audit finds nothing material; `capture.py check` passing is
     the proof. The highest-authority documents in the reading plan you also read yourself.
   - Code is understood by running it and reading what matters: the map (`inventory.json`: entry points,
     commands, routes, model calls, degradation candidates), then every module that carries a mechanism the
     documents name and every entry point, read in full, the rest where the map leaves its role open; what you
     learn goes to `research/adoption/areas/<area>.md` with file:line. The product's commands and tests run in
     step 4, and the characterization (step 8) reconstructs what the code does without seeing any document.
   - A registered file is read when a question points to it (an error line in a log, a record the documents
     cite), and the brief says so.
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
   until a read comes back clear, as in the plan's cold-read step); the sources' drafts and audits are already
   done in step 2.
8. **Characterization**: `python3 ~/.claude/skills/_shared/scripts/gate_run.py <project> --milestone M0
   --intent-only` in the background (no freeze and no lock needed: the draft intent is what is being tested,
   and the deterministic facts are already recorded by `adopt.py commands`). The blind evaluator reconstructs
   what the code does; the judge compares it with the reconstructed intent. Claims in the documents the code
   does not back come back as PHANTOM or MISSING; behavior no document mentions comes back as EXTRA or
   ORPHAN. Where the draft was simply wrong, correct it and characterize again; repeat until a run finds
   nothing the draft should have said (`adopt.py check` fails while the latest run read an older draft). What
   remains is a real discrepancy between the documents, the code, and what the owner may want: list each row
   and each finding the judge left for the owner in the brief's `## Discrepancies`, citing its ID as the judge
   wrote it (`EXTRA-1`, `ORPHAN-2`, `M0-F01`; one entry may cite several), with what it is and the owner's
   question. `adopt.py check` matches those IDs. The full `/gate M0` round runs
   after the lock, as the baseline the next milestone builds on.
9. **The lock**, once `adopt.py check` passes in full, discrepancies first: what the documents claim that the code does not do, what the code does
   that nothing documents, conflicting documents and the proposed authority order, failing commands, stand-ins
   found. The owner confirms or corrects; the intent is locked (`/plan` step 8) and the owner's acceptance of
   M0 is recorded as the baseline.

## Enough context, within the budget
Every load-bearing point is read and checked; that is never cut. What is not paid for: a detail that decides
nothing (it stays in the verbatim files), a second full reading of what an audit already cleared, and a helper
re-reading a large brief to settle rows a script or one audit could settle. What you learn goes to disk at once,
so nothing has to be re-read after a compaction. When a later finding shows an earlier reading was thin, read
that part again. Running the product and its tests answers many questions more cheaply than reading, and adds
to reading rather than replacing it. When the budget and the reading disagree, the owner decides, told plainly
what a smaller plan would leave unread.
