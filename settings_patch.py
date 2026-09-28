#!/usr/bin/env python3
"""Register the pipeline's hooks and limits in ~/.claude/settings.json by exact, reversible edits.

Usage:
  python3 settings_patch.py [--home <dir>]            show the diff, change nothing
  python3 settings_patch.py --apply [--home <dir>]    back up settings.json, then apply

Adds (each only if not already present): the heavy-job guard on shell and browser tools; the reload gate
(arm after compaction, track reads, guard writes); the continuity hooks (session start, first edit, stop); the
pre-compaction snapshot; the once-per-turn typecheck; the leftover-debug audit at stop; and the subagent limits (5 at once, depth 2, workflows 3
agents at once). Removes: the compaction nudge after 50 tool calls and the full typecheck after every edit.
Leaves every other setting and hook exactly as it is. The backup is written next to settings.json as
settings.json.bak-<UTC time> before anything changes.
"""
import copy
import datetime
import difflib
import json
import sys
from pathlib import Path

H = "~/.claude/hooks"
S = "~/.claude/skills/_shared/scripts"
BROWSER = "mcp__plugin_playwright_playwright__.*|mcp__plugin_chrome-devtools-mcp_chrome-devtools__.*|mcp__claude-in-chrome__.*"
ADD = [
    ("PreToolUse", f"Bash|{BROWSER}", f"python3 {H}/heavy-guard.py", 15),
    ("PreToolUse", "Write|Edit|MultiEdit|NotebookEdit|Bash", f"python3 {H}/reload-gate.py guard", 10),
    ("PreToolUse", "Write|Edit|MultiEdit|NotebookEdit", f"python3 {S}/continuity.py claim --tool claude", 15),
    ("PostToolUse", "Read|Bash", f"python3 {H}/reload-gate.py track", 10),
    ("SessionStart", "compact", f"python3 {H}/reload-gate.py arm", 10),
    ("SessionStart", "startup|resume|clear", f"python3 {S}/continuity.py session-start --tool claude", 30),
    ("PreCompact", None, f"python3 {H}/snapshot-state.py", 15),
    ("Stop", None, f"python3 {S}/continuity.py stop --tool claude", 60),
    ("Stop", None, f"python3 {H}/typecheck-once.py", 240),
    ("Stop", None, f"{H}/verify-pipeline-completion.sh", 30),
]
REMOVE = ["suggest-compact.sh", "post-edit-typecheck.sh"]
ENV = {"CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "5", "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "2",
       "CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS": "3"}


def has_command(entries, command):
    return any(h.get("command") == command for e in entries for h in e.get("hooks", []))


def patch(settings):
    s = copy.deepcopy(settings)
    hooks = s.setdefault("hooks", {})
    for event, entries in list(hooks.items()):
        for e in entries:
            e["hooks"] = [h for h in e.get("hooks", []) if not any(r in h.get("command", "") for r in REMOVE)]
        hooks[event] = [e for e in entries if e.get("hooks")]
    for event, matcher, command, timeout in ADD:
        entries = hooks.setdefault(event, [])
        if has_command(entries, command):
            continue
        entry = {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}
        if matcher:
            entry = {"matcher": matcher, **entry}
        entries.append(entry)
    s.setdefault("env", {}).update(ENV)
    return s


def main(argv):
    home = Path(argv[argv.index("--home") + 1]) if "--home" in argv else Path.home()
    path = home / ".claude/settings.json"
    before = json.loads(path.read_text()) if path.is_file() else {}
    after = patch(before)
    a, b = json.dumps(before, indent=2).splitlines(), json.dumps(after, indent=2).splitlines()
    diff = list(difflib.unified_diff(a, b, "settings.json (now)", "settings.json (patched)", lineterm=""))
    print("\n".join(diff) if diff else "settings.json already has every pipeline entry")
    if "--apply" in argv and diff:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_name(f"settings.json.bak-{stamp}")
        backup.write_text(path.read_text() if path.is_file() else "{}\n")
        path.write_text(json.dumps(after, indent=2) + "\n")
        print(f"applied; backup at {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
