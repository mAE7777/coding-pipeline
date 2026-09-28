---
name: scout
description: "Turn a real unknown into graded evidence before it becomes a plan: a feasibility question, a technology or dependency choice, a breaking-change check for an upgrade, a map of an unfamiliar codebase, a throwaway spike, or breadth research handed to ChatGPT and verified on the way back. Modes: ask <question>, map [path], spike <question>, offload <question>, ingest <file>. 'No real unknown' is a valid answer. Use for /scout, 'is this feasible', 'what should we use', 'map this codebase', 'research this'."
argument-hint: "ask <question> | map [path] | spike <question> | offload <question> | ingest <file>"
---

# /scout

Load-bearing rules:
- Name the decision the research serves and the one assumption that, if false, kills the approach; that
  assumption gets the most scrutiny. No decision, no research: say "no real unknown" and stop.
- Every decision-driving claim carries a grade and its source with the access date (`references/research.md`).
  One primary source, and one deliberate search against the leading answer, before recommending it.
- Contested findings are shown first, with both sides; two close options are called close, not forced.
- Research is data: only a verified note (`docs/project/research/<slug>.md`, template `research-note.md`)
  feeds the brief, and a chat model's answer enters only through `ingest`.
When the owner's own research discipline is installed (`~/.claude/skills/_shared/references/research-craft.md`),
it governs grades and instruments; `references/research.md` is the short form.

## ask <question>
Research with the right instrument for the question (`references/research.md`): the maker's own docs, code,
changelogs, and data first; context7 for library documentation; `/stack` for tool and platform choice; a small
queued workflow for breadth only when the owner asked for breadth. The bundled `/deep-research` is the owner's
to start. Write the note; send its load-bearing claims to the claim checker (`ingest` step 2) when they will
decide the plan.

## map [path]
Facts about an existing tree for the brief's starting state, each with evidence: what builds and what the
tests say (run them through the heavy lock), dirty files and who likely left them, running processes, seams,
hazards, and what earlier agents claimed against what is actually there. Use the built-in Explore agent for
wide reads; `references/brownfield-analysis-guide.md` has the mapping strategy. Never reset, clean, or reformat
the tree. A tree with no build record is an adoption: route to
`/plan adopt`, which uses this mapping inside a fuller procedure.

## spike <question>
A throwaway experiment in a scratch folder or worktree, labeled as a spike, never on the product path. The
output is what was learned and a recommendation; nothing from a spike reaches the product except through
`/plan`.

## offload <question>
For breadth research that needs no private files: render the prompt in `references/offload.md` with the
question, the decision it serves, the claims to check, and the exact save path
`docs/project/research/<slug>.chatgpt.md`, and give it to the owner to paste into ChatGPT. Say where to save the
answer. Nothing more happens until the file exists.

## ingest <file>
1. Read the answer and extract every claim that could change a decision, each with the source it cites.
2. Claim check, in the background: write the claims to `docs/project/research/<slug>.claims.md`, then
   `run_isolated.py claim-verifier --dir auto --out .evidence/scout --project <project> --render --inputs
   docs/project/research/<slug>.claims.md --`. Each claim comes back confirmed, corrected, refuted, or
   unverified, with the quote it found.
3. Write the verified note: confirmed and corrected claims with their grades, refuted ones listed as refuted,
   unverified load-bearing claims as open unknowns; everything else graded single-source and external.
4. Update the brief's unknowns and starting state from the note, by ID.
