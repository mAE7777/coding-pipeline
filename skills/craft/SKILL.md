---
name: craft
description: "Code craft from pstack, on demand: /craft review | architect | blast-radius | unslop | verify-skill | pr. A read-only review of the current diff, design before code, what a change could break, plain prose, a builder-side app driver, and pull request work."
argument-hint: "review [base | files] | architect | blast-radius | unslop [file] | verify-skill | pr <open | check | babysit | ship>"
---

## Project workflow choice (first)

Run `python3 ~/.claude/skills/_shared/scripts/project_policy.py status <project> --json` first; when OFF, do the request directly (see `_shared/references/project-control.md`).
When ON, the active pipeline step's rules and the owner's gates win every conflict with a craft file.

# /craft

pstack's craft layer, vendored under its MIT license (`LICENSE-pstack`, provenance in `UPSTREAM.json`).
Paths below are relative to this folder (`~/.claude/skills/craft/`). Read `index.md` first: its override
lines say where this pipeline's rules win, and its triggers say which leaf to open. Then read only the file the
method names. Pipeline steps point at the same files; this skill is the entry when you ask for one directly.

## review [base | files]
A read-only review of the current diff: `git diff <base>...HEAD` plus the working tree, base `main` unless
named, or the files named.
1. State the intent in one paragraph from the request, the commit messages, the PR description, and the code.
   When the intent is unclear, ask before reviewing.
2. Review through `review/rubric.md`, `review/code-quality-review.md`, and `review/comment-keep-list.md`.
   Add `review/blast-radius.md` for a change in shared code or a small diff you do not trust.
3. Judge each finding with `review/lead-judgment.md` and report it in one of four buckets: Act on, Consider,
   Noted, Dismissed. Each carries its `file:line` and a one-line reason.
A separate reviewer runs only when the user asks for one: one read-only subagent built from
`review/reviewer-prompt.md` with the intent, the diff, the rubric, and the code-quality lens, briefed per
`brief.md`. The review changes no file. It is advice, never a gate verdict: it does not count as `/gate`, a
checker, or the owner's acceptance, and the report says so.

## architect
Read `design/architect.md` and follow it. Its arena (`design/arena.md`) runs two runners from the
`architect-runner` role, each given `design/runner-prompt.md`; every candidate is screened against
`design/design-red-flags.md`. Produces the type sketch with the caller's usage first, and the rationale per
`design/rationale-template.md`. In a pipeline project it runs for a mechanism card marked
`Reversibility: one-way`, or on the owner's request. Any other shape gets only the red-flag screen and the
rationale template, which you apply yourself.

## blast-radius
Read `review/blast-radius.md`. Produces what the change does, the one fact it is safe because of (proven by a
script that runs the real code, or marked unproven), the risks with `file:line`, what was cleared, and the
cheapest check before merge.

## unslop [file]
Edit the named text, or the last outbound text, per `writing/unslop.md`. Docs, READMEs, changelogs, commits,
and PR text also follow `writing/technical-writing.md` and `writing/commits-and-prs.md`. Produces the edited
text with meaning and tone kept.

## verify-skill
When the project has no `docs/project/verify/`, create its verification skill per
`verify/create-verification-skill.md` (feature map shape in `verify/feature-map-example/`, UI repro contract
in `verify/control-adapter.md`). When it has one, keep it honest per `verify/maintain-verification-skill.md`.
Produces a proven launch, doctor, drive, evidence, and cleanup recipe plus a feature map. These files are
local-only and builder-side. They are never rendered into any checker pack, because a checker that read the
builder's beliefs about the product would no longer check independently.

## pr <open | check | babysit | ship>
GitHub through `gh` only. The watcher is `python3 ~/.claude/skills/_shared/scripts/pr_watch.py`.
- `open`: `methods/pr/opening-a-pr.md`, with the text per `writing/commits-and-prs.md`. Produces a ready PR
  and its URL. Opening does not start a babysit.
- `check`: `methods/pr/babysit.md` in `check` mode, one `--status-only` pass. Produces a status report.
- `babysit`: `methods/pr/babysit.md` (`drive` unless asked otherwise), triaging review bots per
  `methods/pr/review-bot-triage.md`; fixes go through `/fix`. Ends at merge-ready, never merges.
- `ship`: `methods/pr/shipping.md`, on the owner's explicit request to land. Lands bottom-up only heads whose
  `land-check` passes. Produces what landed and how it was confirmed.

## The other leaves
Opened from `index.md` triggers or a pipeline step, not through an argument:

| File | Read when | Produces |
|---|---|---|
| `methods/bug-fix.md` | a bug or `/fix` | a reproduced, root-caused fix with its regression test |
| `methods/refactoring.md` | a behavior-preserving reshape | the reshape, its pin, and the reader-load delta |
| `methods/feature-shape.md` | any code; multi-step work | the named data shape and the throughput checkpoint |
| `methods/prototype.md` | a fork a run can settle (`/scout spike`) | the observed answer and a throwaway artifact |
| `methods/perf.md` | a measured number or slowness | a vetted number with its run count, spread, and limiter |
| `methods/forensics.md` | a runtime symptom or a profile | a cited diagnosis, no fix |
| `methods/visual-parity.md` | pixel-exact UI work | per-component image-diff results |
| `brief.md` | any subagent | the brief and the result package |
| `explore/*.md` | how code works or why it is shaped so | a grounded explanation with graded claims |
| `principles/*.md` | the index entry's trigger | the principle, read in full before you cite it |
