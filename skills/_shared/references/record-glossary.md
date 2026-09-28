# The build record's own terms

A reader of the record's documents gets this page with them, so the record's working vocabulary is never
mistaken for ambiguity in the product.

- **Intent** (`intent.md`): what must be true for the person who uses the product. The owner confirms it
  once ("the lock"); it is then hashed, and the text above its Re-freeze log is never edited.
- **The lock, signed at the lock**: the owner's confirmation of the intent, recorded as a decision in their
  own words. Before it, the documents are drafts; after it, changes happen only by re-freeze.
- **Re-freeze log, RF-n**: owner-ruled changes to a locked intent, appended at the bottom of `intent.md`. An
  entry supersedes, adds, or drops a done example or a must-not-lose item and names what it makes stale.
- **Done example** (I-Dn in the intent, M<k>.Dn in a milestone): one testable statement plus a concrete
  example with real data. I-D examples are product-level; M.D examples belong to one milestone.
- **Must not lose** (L-nn): a property, boundary, or red line, each with how it is checked ("check:") or why
  only the owner can judge it.
- **Mechanism card**: a load-bearing mechanism's purpose, the guarantee a user or test can observe, the
  easier imitation a builder is likely to drift into (rejected), and a probe whose result differs between
  the two.
- **Persona (blind)**: a description of the user with no purpose or domain words, given alone to a
  reviewer who must guess what the product is for.
- **Assumption** (A-nn): something taken as true without proof, signed with a date.
- **Constraint** (C-nn, in the brief): a limit the build must respect, each with its source.
- **Milestone** (M<k>): a complete product state a person can use end to end, with a numbered demo ending a
  viewer can watch. Status: planned, building, gate, changes, accepted, dropped.
- **Checkpoint** (M<k>.Cn): a boundary checked during the build because later work depends on it.
- **Carries / Mechanisms lines**: which intent done examples and mechanism cards a milestone delivers.
- **Named non-goal**: something deliberately not built, with the reason. **Parked**: built code kept
  unreachable until a named condition.
- **Steal**: a component adopted from another codebase under a written protocol; "none" means nothing is
  borrowed.
- **Wiring table**: each component's trigger, consumer, visible effect, failure state, and test. Row status:
  built, validated (its own test passes), wired (reachable from the product), proven (the user-visible
  effect is shown working end to end), parked.
- **AI evals**: evaluations for a part that calls a model; "none" when no part does.
- **Readiness line**: built, gate-passed (an independent review found the milestone ready), accepted (the
  owner accepted it after watching its demo), released (shipped), live-verified (checked working where
  it was shipped).
- **The gate**: the independent review of a finished milestone (deterministic checks, isolated reviewers,
  the demo run from a clean start, a computed verdict).
- **Stand-in, placeholder manifest**: any fake, sample, or canned part on the product path. Each needs the
  owner's recorded consent; the manifest in the brief lists them (often "none").
- **Decision** (D-nnn, in `decisions.md`): a choice with its source; "[owner <date>]" marks the owner's own
  words, "[proposed]" a choice the owner has not made.
- **Unknown** (U-nn): an open question with the way it will be settled.
- **Inbox item** (IN-nnn, in `inbox.md`): a suggestion, proposed change, or new idea waiting to be weighed;
  once decided it leaves the inbox and its decision entry records where it went.
- **Journal** (`journal.md`): one line per step taken (which step, when, in which session, the outcome, and what
  came next), local-only.
- **Local-only files**: working files kept out of commits (brief, state, gate settings, handoff notes,
  reviews, research, captured sources, `.evidence/` with test and review output).
- **Gate settings** (`gate.md`): the project's extra check commands and which paths carry intent.
- **Stack pack**: conventions for the project's language or platform that the builder follows.
- **Owner standing requirements**: the owner's requirements for every project (languages, appearance, what
  committed text must not contain); copied into the brief and intent with their source.
