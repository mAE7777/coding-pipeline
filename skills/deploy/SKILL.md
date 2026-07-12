---
name: deploy
description: "Ship a finished build: verify the loop is complete, run the deterministic release safety gates, write a thin changelog, and execute the deployment behind a plain-English confirmation for any irreversible or credentialed action. Use this skill when the user says /deploy, 'ship it', 'deploy', 'release', 'go live', or 'publish'. Keeps the human in the loop only at the one place models still fail: high-risk, irreversible actions."
argument-hint: "<target | empty = detect>"
---

# deploy — Ship (thin, safety-gated)

> EXECUTABLE WORKFLOW. The deterministic gates are the harness. The human is asked exactly once,
> at the irreversible action, in plain English.

Owns the last mile: prove the build is complete and safe, then release. The only mandatory human
gate is the back-translation confirmation before an irreversible or credentialed action.

## Workflow

### Stage 1 — Completion check
Read `slices.md`: all slices done. Confirm the load-bearing behavior HOLDS (latest `/loyal` pass)
and the latest `/qa` verdict is PASS. If any slice is unverified or the load-bearing behavior is
not proven, HALT and say which.

### Stage 2 — Release safety gate (deterministic, blocking)
Run `~/.claude/skills/_shared/gate.sh <project-dir>` (build/typecheck, secret scan, dependency
audit, leftover-debug and AI-trace scan, tracked-.env and `.gitignore` checks) and show its table.
Any FAIL blocks the release; a SKIP on a check that matters for this target (e.g. no dependency
audit before publishing a package) is resolved, not waved through. On top of the script, for a
public repo: README and description read as human-written, with no AI-styled prose tics.

### Stage 3 — Thin changelog
From the slice list and the intent, write a short user-facing changelog (what a user can now do,
what was fixed). De-AI writing rules apply. No ceremony, no fixed taxonomy.

### Stage 4 — Back-translation gate (the one human gate)
For each irreversible or credentialed action in this deploy (production DB migration/write, money
movement, IAM/permission change, publishing to a registry or public URL, anything that cannot be
undone), back-translate it to plain English: "This will <do X> to <Y>. It cannot be undone." Show
the exact command. Require explicit confirmation per high-risk action. Use the least privilege
that works (scoped, expiring tokens; no ambient admin). If the project is a local tool with no
credentials and nothing irreversible, this gate is a no-op: say so and proceed.

### Stage 5 — Execute and post-deploy verify
For platform-specific deploy commands and auth, load `references/deployment-targets.md`. Run the
deployment. Then prove it actually works: exercise the load-bearing behavior end-to-end on the
deployed artifact and show the evidence. If post-deploy verification fails, load
`references/deployment-failure-patterns.md` to match the symptom to a known platform failure, then
surface it immediately with rollback options.

### Success: gates green, high-risk actions confirmed, deployed, and the live artifact's load-bearing behavior verified with evidence.
### Failure: a gate failed, or post-deploy verification failed. HALT with the evidence and options.

## Guardrails
- Don't ask for blanket approval of routine steps; ask only at the irreversible action.
- Don't ship on "looks done"; ship on a green post-deploy check shown as evidence.

## Ecosystem
- **Reads**: `slices.md`, `intent-anchor.md`, latest `/loyal` and `/qa` results, `AGENTS.md`.
- **Writes**: `CHANGELOG.md`; deploys.
- **Gates**: deterministic release safety + the back-translation confirmation (the
  vibe-diff-before-high-risk control from the security research).
