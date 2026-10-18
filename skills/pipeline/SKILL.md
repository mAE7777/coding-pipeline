---
name: pipeline
description: "Set or inspect a project's coding workflow choice: /pipeline on, /pipeline off, /pipeline status, each with an optional project folder; /pipeline update installs the pipeline's latest version from its repository. Typed by the owner; no other skill, 'continue', existing record, or lock ever turns a project on."
argument-hint: "on | off | status [project] | update"
disable-model-invocation: true
---

# Project workflow control

Run `python3 ~/.claude/skills/_shared/scripts/project_policy.py <on|off|status> <project>`.
The project is the user's named folder, otherwise the current project. Resolve it before writing.
An explicit request to turn it off or on is sufficient authorization; do it immediately and report the
mode and exact project. No adoption, owner lock, decision ledger, amendment or confirmation is needed.
Without an explicit on or off, run status. What the choice means for every other skill, OFF and ON:
`~/.claude/skills/_shared/references/project-control.md`.

Turning ON does not itself start adoption or change project intent.
This control does not run project_status.py record or dispatch a next workflow step.

`/pipeline status` also runs `python3 ~/.claude/skills/_shared/scripts/pipeline_sync.py status` and reports
which pipeline revision is installed, whether the repository holds commits not installed, and runs in progress.

## Update

`/pipeline update` (it takes no project) runs
`python3 ~/.claude/skills/_shared/scripts/pipeline_sync.py update` in the foreground with the longest shell
timeout (installing Codex's copies can take minutes). It pulls the pipeline repository, installs it, and
registers its hooks, or refuses with the reason. Report the result in plain words: current, updated (the
revisions, the commits, what changed), or refused or failed with the script's reason and what it says to do.
Never work around a refusal: an edit in progress or a running gate is the reason it waits.

When it updated, the skill text already in this conversation is the old version. Before continuing the work
this session was doing, re-read the SKILL.md of the skill in use (`~/.claude/skills/<name>/SKILL.md`) and the
references the current step relies on, or invoke that skill again (for example `/dev resume`) when its SKILL.md
changed, since a skill's own hooks are registered when it is invoked. Scripts, hooks, and checkers already run
the new version. Other open sessions are told at their next prompt.
