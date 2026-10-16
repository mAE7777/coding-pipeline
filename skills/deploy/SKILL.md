---
name: deploy
description: "Ship a finished build: check the shipped milestones were accepted, run the release checks, keep local-only files and traces out of the artifact, confirm each irreversible or credentialed action one by one, deploy, and verify the live artifact. Takes a target, or none to detect it. Use for /deploy, 'ship it', 'release', 'go live', 'publish'. A venture conductor may dispatch it; each irreversible action is still confirmed."
argument-hint: "<target, or empty to detect>"
---

**Workflow choice, first.** Run `python3 ~/.claude/skills/_shared/scripts/project_policy.py status <project> --json`. OFF or no choice: do the requested work directly from the existing documents, code, and tests, with no formal step, record, or End chain. ON: the rules below apply; recheck the choice before each next step. Only the owner's explicit on or off, through /pipeline, changes it. Contract: `~/.claude/skills/_shared/references/project-control.md`.

# /deploy

Load-bearing rules:
- Nothing irreversible or credentialed (production data, money, permissions, publishing, DNS, anything that
  cannot be undone) happens without the owner's confirmation of that exact action, stated in plain English
  with its exact command ("This will publish version 1.2.0 of <package> to npm. It cannot be unpublished
  after 72 hours."). One confirmation per action; routine steps need none.
- Ship on evidence: the live artifact's load-bearing behavior verified after deploying, shown. "Submitted" (a
  store review, a pull request) is never reported as "launched".
- Least privilege: scoped, expiring tokens; no ambient admin credentials.

Venture projects (a `truth/` folder): read `~/.claude/skills/_shared/references/venture-mode.md` first; if it is missing, stop BLOCKED.

## Steps
1. **Completion.** Every milestone being shipped is accepted (`milestones.md` Status accepted, with its
   proven acceptance entry), and the tree being shipped is the accepted candidate: `fingerprint.py <project>`
   equals the fingerprint in the last shipped milestone's acceptance entry (`milestone_lint.py` also checks that
   entry against the gate round that passed). A difference means code changed after acceptance: run the gate
   again, or ship only with the owner's named waiver. An earlier ship, of a milestone not yet accepted or with open blocking findings,
   needs the owner's named waiver, recorded as a decision in their words. In a venture project the private
   overlay adds helm's launch conditions.
2. **Through a pull request**, when the milestone ships as one: `/craft pr <open | check | babysit | ship>`
   (babysit fixes go through `/fix`; `ship` only on the owner's explicit request to land). Before any PR
   lands, `python3 ~/.claude/skills/_shared/scripts/pr_watch.py land-check <pr> --project <dir> --milestone M<k>`
   must pass. Exit 1 means the head is not the accepted candidate: a focused re-gate and the owner's
   acceptance first. Exit 2 means no owner acceptance with a fingerprint, or a head it could not read.
3. **Release checks**: `~/.claude/skills/_shared/gate.sh <project>`; any FAIL blocks. A SKIP on a check that
   matters for this target (no dependency audit before publishing a package) is resolved, not waved through.
4. **Local-only files stay local.** Docker, npm, and Vercel do not read `.git/info/exclude`, so check the
   artifact itself: npm `npm pack --dry-run` lists every file; Docker, the build context (`.dockerignore`
   against `docs/project`, `.evidence`, `.env`); Vercel and similar hosts, their ignore file and the uploaded
   file list; a git-based host, `git ls-files`. None of `docs/project/{brief,state,gate}.md`, handoffs,
   reviews, research, sources, `.evidence/`, or `.env` may be inside. Target details:
   `references/deployment-targets.md`.
5. **Public text** (README, descriptions, store listings, the changelog): written per
   `~/.claude/skills/craft/writing/unslop.md`, with no AI or tooling traces and no inflated claims. When the
   owner's standing requirements file (`~/.claude/skills/_shared/references/owner-standing.md`) sets limits
   on public statements, check against them and stop on a conflict.
6. **Changelog**: what a person can now do and what was fixed, in the product's languages, short.
7. **Confirm** each irreversible or credentialed action as the first rule says, then run it. A local tool
   with nothing irreversible skips this and says so.
8. **Verify live** on the deployed artifact (for a web product, `playwright-cli` against the live URL; for a
   login only the owner has, ask them, or use their browser through Claude in Chrome only when they ask). On
   failure, match the symptom in `references/deployment-failure-patterns.md` and report at once with the
   rollback options.
9. **Record**: tick released and live-verified in the milestones' Readiness lines (with the version or URL),
   and note the deploy in `state.md`.

## End
`python3 ~/.claude/skills/_shared/scripts/project_status.py record <project> --skill deploy --outcome "<one line>"`, then close the report with the Next line it prints (`project-control.md`, End).
