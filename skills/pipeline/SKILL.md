---
name: pipeline
description: "Set or inspect a project's coding workflow choice: /pipeline on, /pipeline off, /pipeline status, each with an optional project folder; /pipeline update installs the pipeline's latest version from its repository, and the fast workflow's when it is installed. Typed by the owner; no other skill, 'continue', existing record, or lock ever turns a project on."
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
which pipeline revision is installed, whether the repository holds commits not installed, and runs in progress;
the same for the fast workflow when it is installed (its revision, repository, and commits not installed).

## Update

`/pipeline update` (it takes no project) runs
`python3 ~/.claude/skills/_shared/scripts/pipeline_sync.py update` in the foreground with the longest shell
timeout (installing Codex's copies can take minutes). It pulls the pipeline repository, installs it, and
registers its hooks, or refuses with the reason. Then, when the fast workflow is installed, it runs fast's
`install.py update` (the same rules) and reports it on its own `fast:` lines; one part's refusal never stops
the other, and the exit is 1 when either was refused or failed. Report each part in plain words: current,
updated (the revisions, the commits, what changed), or refused or failed with the script's reason and what it
says to do. Never work around a refusal: an edit in progress or a running gate is the reason it waits.

When it updated, the skill text already in this conversation is the old version. Before continuing the work
this session was doing, re-read the SKILL.md of the skill in use (`~/.claude/skills/<name>/SKILL.md`) and the
references the current step relies on, or invoke that skill again (for example `/dev resume`) when its SKILL.md
changed, since a skill's own hooks are registered when it is invoked. When fast updated, the same holds for a
fast skill in use (`~/.claude/skills/<name>-fast/SKILL.md`). Scripts, hooks, and checkers already run the new
version. Other open sessions are told at their next prompt.
