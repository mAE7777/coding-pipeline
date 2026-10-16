---
name: pipeline
description: "Set or inspect a project's coding workflow choice: /pipeline on, /pipeline off, /pipeline status, each with an optional project folder. Typed by the owner; no other skill, 'continue', existing record, or lock ever turns a project on."
argument-hint: "on | off | status [project]"
disable-model-invocation: true
---

# Project workflow control

Run `python3 ~/.claude/skills/_shared/scripts/project_policy.py <on|off|status> <project>`.
The project is the user's named folder, otherwise the current project. Resolve it before writing.
An explicit request to turn it off or on is sufficient authorization; do it immediately and report the
mode and exact project. No adoption, owner lock, decision ledger, amendment or confirmation is needed.
Without an explicit choice use status; never infer ON from a request to continue development.

OFF persists across sessions, compaction and tools. Follow the current request and existing documents
directly. Half-finished adoption, old locks, handoffs and unfinished milestones do not block development.
Skills remain available as independent tools; their formal workflow rules apply only when ON.
ON uses the existing formal workflow. Turning ON does not itself start adoption or change project intent.
This control does not run project_status.py record or dispatch a next workflow step.
