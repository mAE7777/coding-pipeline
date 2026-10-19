---
name: scout
description: "Turn a real unknown into graded evidence before it becomes a plan: feasibility, a technology or dependency choice, an upgrade's breaking changes, an unfamiliar codebase, a throwaway spike, or research handed to ChatGPT and verified. Modes: ask <question>, map [path], spike <question>, offload <question>, ingest <file>. Use for /scout, 'is this feasible', 'what should we use', 'map this codebase', 'research this'."
argument-hint: "ask <question> | map [path] | spike <question> | offload <question> | ingest <file>"
---

**Workflow choice, first.** Run `python3 ~/.claude/skills/_shared/scripts/project_policy.py status <project> --json`. OFF or no choice: when the status names the fast workflow, use its matching /<name>-fast skill if it lists one; otherwise do the requested work directly from the existing documents, code, and tests, with no formal step, record, or End chain. ON: the rules below apply; recheck the choice before each next step. Only the owner's explicit on or off, through /pipeline, changes it. Contract: `~/.claude/skills/_shared/references/project-control.md`.

# /scout

Load-bearing rules:
- Name the decision the research serves and the one assumption that, if false, kills the approach; that
  assumption gets the most scrutiny. No decision, no research: say "no real unknown" and stop.
- Every decision-driving claim carries a grade and its source with the access date, phrased at its grade
  (`references/research.md`). One primary source, and one deliberate search against the leading answer,
  before recommending it.
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
tests say (through `heavy.py run`), dirty files and who likely left them, running processes, seams, hazards,
and what earlier agents claimed against what is actually there. For wide reads, brief each Explore agent with
`~/.claude/skills/craft/explore/explorer-prompt.md` (one angle each, within the session's subagent limits),
and write the map in the shape of `~/.claude/skills/craft/explore/explainer-prompt.md` (Overview, Key concepts,
How it works, Where things live, Gotchas), the facts above included; `references/brownfield-analysis-guide.md`
has the mapping strategy. Never reset, clean, or reformat the tree. A tree `record_check.py` routes to
`/plan adopt` goes there: adoption uses this mapping inside a fuller procedure.

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

## End
`python3 ~/.claude/skills/_shared/scripts/project_status.py record <project> --skill scout --outcome "<one line>"`, then close the report with the Next line it prints (`project-control.md`, End).
