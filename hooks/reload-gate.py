#!/usr/bin/env python3
"""After a compaction, block writes to the project until the build record has been re-read.

Three modes, one per hook event:
  reload-gate.py arm    SessionStart, matcher "compact": inject the re-read directive and arm the gate
  reload-gate.py track  PostToolUse, matcher "Read|Bash": record which required files were read (the Read
                        tool, or a read-only shell command that prints the file: cat, head, tail, less, more,
                        bat, nl, or sed -n; ls, grep, or wc naming it does not show its content)
  reload-gate.py guard  PreToolUse, matcher "Write|Edit|MultiEdit|NotebookEdit|Bash" (Codex: "apply_patch|Bash",
                        the patch's file headers give the targets): while any required
                        file is unread, deny file edits inside the project and every shell command that is
                        not read-only (a redirection, sed -i, tee, mv, rm, a script run, and the like)

The project is $CLAUDE_PROJECT_DIR, else the nearest folder above the hook's cwd holding
docs/project/state.md, so a cd does not disarm the gate. Only such projects are affected. The required files
are whichever of docs/project/state.md, intent.md, and milestones.md exist. State lives per project and
session in ~/.claude/.reload-state/<project key>.<session>.project-needs (next to helm's own truth/ gate,
which is separate and unchanged). The conversation summary is lossy; the files are not.
On an internal error the hook allows the call and says so in a visible message.
"""
import hashlib
import json
import os
import re
import shlex
import sys
from pathlib import Path

REQUIRED = ("state.md", "intent.md", "milestones.md")
READ_ONLY = {"cat", "head", "tail", "less", "more", "bat", "sed", "awk", "grep", "rg", "ls", "find", "wc", "pwd",
             "echo", "stat", "file", "diff", "tree", "jq", "sort", "uniq", "cut", "git", "true"}
GIT_READ = {"status", "diff", "log", "show", "blame", "ls-files", "rev-parse", "branch"}
PRINTERS = {"cat", "head", "tail", "less", "more", "bat", "nl"}


def state_dir():
    d = Path(os.environ.get("RELOAD_STATE_DIR") or Path.home() / ".claude/.reload-state")
    d.mkdir(parents=True, exist_ok=True)
    return d


def project_root(cwd):
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and (Path(env) / "docs/project/state.md").is_file():
        return Path(env).resolve()
    p = Path(cwd or ".").resolve()
    for c in [p, *p.parents]:
        if (c / "docs/project/state.md").is_file():
            return c
    return p


def patch_targets(tool_input):
    """File paths named in a Codex apply_patch payload (Codex puts the patch in tool_input.command)."""
    text = tool_input.get("command") or tool_input.get("patch") or tool_input.get("input") or ""
    if not isinstance(text, str):
        return []
    return re.findall(r"^\*\*\* (?:Update|Add|Delete) File: (.+?)\s*$", text, flags=re.M)


def segments(command):
    return [s.strip() for s in re.split(r"&&|\|\||;|\||\n", command) if s.strip()]


def read_only(command):
    """True when every piece of a shell command only reads."""
    if re.search(r"(^|[^<>&0-9])>{1,2}(?!&)|\btee\b|<<", command):
        return False
    for seg in segments(command):
        try:
            words = shlex.split(seg)
        except ValueError:
            return False
        if not words:
            continue
        head = os.path.basename(words[0])
        if head not in READ_ONLY:
            return False
        if head == "sed" and any(w.startswith("-i") or w == "--in-place" for w in words[1:]):
            return False
        if head == "find" and any(w in ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0",
                                        "-fprintf", "-fls") for w in words[1:]):
            return False
        if head in ("sort", "tree") and any(w == "-o" or w.startswith(("-o", "--output")) for w in words[1:]):
            return False
        if head == "uniq" and len([w for w in words[1:] if not w.startswith("-")]) >= 2:
            return False  # uniq <input> <output> writes the output file
        if head == "git" and (len(words) < 2 or words[1] not in GIT_READ):
            return False
    return True


def prints(seg):
    """True when a read-only command segment shows file content (so naming a file in it means reading it)."""
    try:
        words = shlex.split(seg)
    except ValueError:
        return False
    if not words:
        return False
    head = os.path.basename(words[0])
    return head in PRINTERS or (head == "sed" and "-n" in words[1:])


def key(root, session):
    h = hashlib.sha1(str(root).encode()).hexdigest()[:16]
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (session or "nosid"))
    return state_dir() / f"{h}.{safe}.project-needs"


def required(root):
    docs = root / "docs/project"
    return [str((docs / name).resolve()) for name in REQUIRED if (docs / name).is_file()]


def arm(data):
    root = project_root(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    if not (root / "docs/project/state.md").is_file():
        return 0
    needs = required(root)
    key(root, data.get("session_id")).write_text(json.dumps({"needs": needs, "read": []}))
    snaps = sorted((root / ".evidence/compact").glob("*.md"))
    snap = f", and the snapshot {snaps[-1].relative_to(root)}" if snaps else ""
    listed = ", then ".join(str(Path(p).relative_to(root)) for p in needs)
    text = ("The conversation was just compacted, and the summary above is lossy. Before any further edit, "
            f"re-read {listed}, plus docs/project/brief.md and the tail of docs/project/decisions.md{snap}. "
            "Writes to this project are blocked until those three files have been read. Compare git status "
            "with state.md and say what differs. Anything with an ID (constraints C-, must-not-lose L-, "
            "decisions D-, findings) comes from the files, never from the summary. If a decision made before "
            "compaction is missing from decisions.md, write it once the files are read.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))
    return 0


def load(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def track(data):
    root = project_root(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    path = key(root, data.get("session_id"))
    record = load(path)
    if not record:
        return 0
    tool_input = data.get("tool_input") or {}
    targets = []
    if data.get("tool_name") == "Bash":
        command = tool_input.get("command", "")
        if read_only(command):
            for seg in segments(command):
                if not prints(seg):
                    continue
                for need in record["needs"]:
                    rel = str(Path(need).relative_to(root))
                    if need in seg or re.search(rf"(^|[\s'\"/]){re.escape(rel)}\b", seg):
                        targets.append(need)
    elif tool_input.get("file_path"):
        targets.append(str(Path(tool_input["file_path"]).expanduser().resolve()))
    for resolved in targets:
        if resolved in record["needs"] and resolved not in record["read"]:
            record["read"].append(resolved)
    if set(record["needs"]) <= set(record["read"]):
        path.unlink(missing_ok=True)
    else:
        path.write_text(json.dumps(record))
    return 0


def guard(data):
    root = project_root(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")
    record = load(key(root, data.get("session_id")))
    if not record:
        return 0
    remaining = [str(Path(p).relative_to(root)) for p in record["needs"] if p not in record["read"]]
    if not remaining:
        return 0
    tool_input = data.get("tool_input") or {}
    if data.get("tool_name") == "Bash":
        if read_only(tool_input.get("command", "")):
            return 0
        what = "shell commands that change files"
    else:
        targets = patch_targets(tool_input) or [tool_input.get("file_path") or tool_input.get("notebook_path") or ""]
        if data.get("tool_name") == "apply_patch" and not any(targets):
            # A patch whose files cannot be read out of it may write anywhere: fail closed while armed.
            targets = [str(root)]
        inside = []
        for target in [t for t in targets if t]:
            path = Path(target).expanduser()
            path = path if path.is_absolute() else Path(data.get("cwd") or root) / path
            try:
                path.resolve().relative_to(root)
                inside.append(target)
            except ValueError:
                continue
        if not inside:
            return 0
        what = "edits in this project"
    reason = (f"Blocked: {what} wait until the build record is re-read after compaction (the summary is "
              "lossy). Read these first (the Read tool, or cat): " + ", ".join(remaining) + ".")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    return 0


def main(argv):
    if len(argv) != 1 or argv[0] not in ("arm", "track", "guard"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    try:
        return {"arm": arm, "track": track, "guard": guard}[argv[0]](data)
    except Exception as exc:
        print(json.dumps({"systemMessage": f"reload-gate {argv[0]} hit an internal error and allowed the call: "
                                           f"{exc.__class__.__name__}: {exc}"}))
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
