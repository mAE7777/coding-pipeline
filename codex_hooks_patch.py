#!/usr/bin/env python3
"""Register the pipeline's continuity and safety hooks for Codex in ~/.codex/hooks.json.

Usage:
  python3 codex_hooks_patch.py [--home <dir>]            show the diff, change nothing
  python3 codex_hooks_patch.py --apply [--home <dir>]    back up hooks.json, then apply

The same scripts serve Claude Code and Codex (Codex's hook events, matchers, and replies follow the same shape;
its shell tool is "Bash" and its file edits are "apply_patch"). Registered: continuity at session start, on the
first edit, and at stop; the reload gate after compaction; the heavy-job guard on shell commands; the
pre-compaction snapshot; the milestone stop check for Codex writers; the once-per-turn typecheck. Codex asks the
owner to review and trust new hooks once (its /hooks command) before they run. Existing entries are kept; each
pipeline entry is added only if absent. The backup is written as hooks.json.bak-<UTC time>.
"""
import datetime
import difflib
import json
import sys
from pathlib import Path

H = "~/.claude/hooks"
S = "~/.claude/skills/_shared/scripts"
D = "~/.claude/skills/dev/scripts"
ADD = [
    ("SessionStart", "startup|resume|clear", f"python3 {S}/continuity.py session-start --tool codex", 30),
    ("SessionStart", "compact", f"python3 {H}/reload-gate.py arm", 10),
    ("PreToolUse", "Bash", f"python3 {H}/heavy-guard.py", 15),
    ("PreToolUse", "apply_patch|Bash", f"python3 {H}/reload-gate.py guard", 10),
    ("PreToolUse", "apply_patch", f"python3 {S}/continuity.py claim --tool codex", 15),
    ("PostToolUse", "Bash", f"python3 {H}/reload-gate.py track", 10),
    ("PreCompact", None, f"python3 {H}/snapshot-state.py", 15),
    ("Stop", None, f"python3 {S}/continuity.py stop --tool codex", 60),
    ("Stop", None, f"python3 {D}/milestone-continue.py --tool codex", 30),
    ("Stop", None, f"python3 {H}/typecheck-once.py", 240),
]


def patch(config):
    out = json.loads(json.dumps(config))
    hooks = out.setdefault("hooks", {})
    for event, matcher, command, timeout in ADD:
        entries = hooks.setdefault(event, [])
        if any(h.get("command") == command for e in entries for h in e.get("hooks", [])):
            continue
        entry = {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}
        if matcher:
            entry = {"matcher": matcher, **entry}
        entries.append(entry)
    return out


def main(argv):
    home = Path(argv[argv.index("--home") + 1]) if "--home" in argv else Path.home()
    path = home / ".codex/hooks.json"
    before = json.loads(path.read_text()) if path.is_file() else {}
    after = patch(before)
    diff = list(difflib.unified_diff(json.dumps(before, indent=2).splitlines(), json.dumps(after, indent=2).splitlines(),
                                     "hooks.json (now)", "hooks.json (patched)", lineterm=""))
    print("\n".join(diff) if diff else "hooks.json already has every pipeline entry")
    if "--apply" in argv and diff:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path.with_name(f"hooks.json.bak-{stamp}").write_text(path.read_text())
        path.write_text(json.dumps(after, indent=2) + "\n")
        print(f"applied to {path}; Codex will ask you to review and trust these hooks once (/hooks)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
