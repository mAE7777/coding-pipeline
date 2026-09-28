---
name: deploy
description: "Ship a finished build: check that the milestones being shipped were accepted by the owner, run the release checks, prove local-only files are not in the artifact, read public text for traces and standing constraints, write a thin changelog, state each irreversible or credentialed action in plain English with its exact command and get it confirmed one by one, deploy, and verify the live artifact. Use for /deploy, 'ship it', 'release', 'go live', 'publish'. Model-invocable so a venture conductor can dispatch it; its safety is the confirmation of every irreversible action."
argument-hint: "<target, or empty to detect>"
---

# /deploy

Load-bearing rules:
- Nothing irreversible or credentialed happens without the owner's confirmation of that exact action, stated
  in plain English with its exact command ("This will publish version 1.2.0 of <package> to npm. It cannot be
  unpublished after 72 hours."). One confirmation per action; routine steps need none.
- Ship on evidence: the live artifact's load-bearing behavior verified after deploying, shown. "Submitted" (a
  store review, a pull request) is never reported as "launched".
- Least privilege: scoped, expiring tokens; no ambient admin credentials.
- Venture projects: when the project has a `truth/` folder, read
  `~/.claude/skills/_shared/references/venture-mode.md` before step 1; if it is missing, stop with BLOCKED (this is a
  venture project and its rules are not installed).

## Steps
1. **Completion.** Every milestone being shipped is accepted (`milestones.md` Status accepted, with its
   proven acceptance entry), and the tree being shipped is the accepted candidate: `fingerprint.py <project>`
   equals the fingerprint in the last shipped milestone's acceptance entry (`milestone_lint.py` also checks that
   entry against the gate round that passed). A difference means code changed after acceptance: run the gate
   again, or ship only with the owner's named waiver. An earlier ship, of a milestone not yet accepted or with open blocking findings,
   needs the owner's named waiver, recorded as a decision in their words. In a venture project the private
   overlay adds helm's launch conditions.
2. **Release checks**: `~/.claude/skills/_shared/gate.sh <project>`; any FAIL blocks. A SKIP on a check that
   matters for this target (no dependency audit before publishing a package) is resolved, not waved through.
3. **Local-only files stay local.** Docker, npm, and Vercel do not read `.git/info/exclude`, so check the
   artifact itself: npm `npm pack --dry-run` lists every file; Docker, the build context (`.dockerignore`
   against `docs/project`, `.evidence`, `.env`); Vercel and similar hosts, their ignore file and the uploaded
   file list; a git-based host, `git ls-files`. None of `docs/project/{brief,state,gate}.md`, handoffs,
   reviews, research, sources, `.evidence/`, or `.env` may be inside. Target details:
   `references/deployment-targets.md`.
4. **Public text**: README, descriptions, store listings, and the changelog read as a person's writing: no AI
   or tooling traces, no inflated claims. When the owner's standing requirements file
   (`~/.claude/skills/_shared/references/owner-standing.md`) sets limits on public statements, check against
   them and stop on a conflict.
5. **Changelog**: what a person can now do and what was fixed, in the product's languages, short.
6. **Confirm** each irreversible or credentialed action (production data, money, permissions, publishing,
   DNS, anything that cannot be undone), then run it. A local tool with nothing irreversible skips this and says so.
7. **Verify live**: run the load-bearing behavior on the deployed artifact (for a web product, `playwright-cli`
   against the live URL; for a login only the owner has, ask them, or use their browser through Claude in
   Chrome only when they ask). On failure, match the symptom in `references/deployment-failure-patterns.md`,
   report at once with the rollback options.
8. **Record**: tick released and live-verified in the milestones' Readiness lines (with the version or URL),
   and note the deploy in `state.md`.
