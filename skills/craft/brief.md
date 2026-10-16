# Subagent brief and result package

Use this for every subagent you spawn, and spawn one only where the active skill allows it (in `/dev`, a read-only explorer for a wide unknown; parallel builders only when the owner asks). The constitution's Resources limits on concurrent agents and nesting depth hold. A subagent never double-checks your own work, and none runs in capture or adoption.

## Rules

- **The brief is the product.** A vague brief fails quietly, because a subagent cannot ask you a question. A field you cannot fill is a unit you have not scoped yet.
- **Size the brief to the unit.** A one-command unit gets the template collapsed to a paragraph that still names goal, scope, the verify command, and the report shape. A 4KB scaffold around a two-line edit costs more to write and obey than the edit.
- **A dependency is a context relay.** A subagent sees neither this conversation nor its siblings. Paste an upstream report in full when the unit depends on it. Point at files instead of pasting them.
- **Name the role, not the model.** The model and effort come from the role's line in `_shared/models.json`.
- **Fresh subagent with consolidated scope.** Give new work to a fresh subagent with consolidated scope, meaning the original brief, every later directive, and the prior agent's report and branch. This holds for a fix round, a follow-up, a retry, and the next queue item. Resume, message, or queue a follow-up on an existing subagent only when the new work strictly needs state that lives in that agent and is costly to move: its local checkout, its uncommitted changes, or a process it still runs. Never resume-chain a brief. Interrupt-chained resumes silently drop directives.
- **Scale verification to the unit.** When the check is a single cheap command, the subagent runs it and reports the output, and you spot-check the receipt.
- **You own every subagent's work.** Review the diff yourself and write your own summary, don't pass through what it said. Read the lines an explorer cites before you rely on them.

## Brief

```
GOAL          one sentence, the outcome, executable by a stranger with no chat access
NON-GOALS     what this unit must not do or decide
READ          files, directories, PRs, and evidence it may read, as pointers;
              upstream reports pasted in full
WRITE         paths it may write and paths it may not; its own worktree or branch;
              "nothing" for a read-only explorer
TOOLS         the tools it may use (an explorer: Read, Grep, Glob, read-only commands)
ACCEPTANCE    one checkable criterion per line, each with the evidence required:
              a command and its output, a file:line, or a capture path
BUDGET        a deadline and a rough cap on turns and output size; at the cap,
              return partial findings and stop rather than run on
WHEN BLOCKED  one of: stop and report; wait for a named dependency; return the
              question for the owner to you. Never guess past a block.
FORBIDDEN     no merges, rebases, force-pushes, or fixes outside scope; no edits
              to docs/project/; plus unit-specific bans
REPORT        the result package below
```

## Result package

The result separates what was verified from what was assumed. A conclusion without its evidence belongs under Unverified.

```
STATUS          succeeded | failed | blocked | stopped at the budget
SUMMARY         the question answered, in two or three sentences
INPUTS          files read (path with commit or fingerprint) and commands run
VERIFIED        each conclusion with its evidence: command and output, file:line,
                or capture path
UNVERIFIED      each assumption or inference not checked, labeled inferred or guess
ARTIFACTS       paths, branches, and commits produced
KNOWN UNKNOWNS  what it could not find out, and where it looked
BLOCKED ON      what stops progress and who can clear it
NEXT ACTION     the unfinished work and the next step
RESOURCES       rough turns, tool calls, and time used
```
