#!/bin/bash
# Stop hook: flag console.log / console.debug / debugger left in JS and TS lines added in this working tree
# (tests, configs, type declarations, JSON, and Markdown are skipped). Only added lines count: the lines
# `git diff -U0 HEAD` shows as added (staged or not), plus every line of an untracked file, so a leftover that
# was committed long ago in a file touched now is not reported again. Whether a milestone is finished is
# checked elsewhere (the build's own stop check and the gate); this hook only catches debug leftovers.
# It informs the owner through a system message and never makes the model continue the turn.
# Output is always JSON so a plain-text reply can never be mistaken for a user turn; an internal error is
# reported as a system message and the stop goes ahead.

INPUT=$(cat)
CWD=$(printf '%s' "$INPUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("cwd",""))' 2>/dev/null)
if [ -z "$CWD" ] || [ ! -d "$CWD" ]; then
  printf '{"suppressOutput": true}\n'
  exit 0
fi
HERE="$(cd "$(dirname "$0")" && pwd)"
if ! python3 "$HERE/../skills/_shared/scripts/project_policy.py" check "$CWD"; then
  printf '{"suppressOutput": true}\n'
  exit 0
fi

python3 - "$CWD" <<'PY'
import json
import re
import subprocess
import sys

SKIP = re.compile(r"\.test\.|\.spec\.|__tests__/|\.config\.|\.d\.ts$|\.json$|\.md$")
CODE = (".ts", ".tsx", ".js", ".jsx")
LEFTOVER = re.compile(r"console\.(log|debug)|debugger")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
# The prefixes are named, so diff.noprefix or diff.mnemonicPrefix in the owner's git config cannot change the
# "+++ b/<path>" lines read here; no color and no external diff tool, for the same reason.
DIFF = ("-U0", "--no-color", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/")


def git(top, *args):
    r = subprocess.run(["git", "-C", top, "-c", "core.quotepath=off", *args], capture_output=True, text=True,
                       errors="replace")
    return r.stdout if r.returncode == 0 else None


def wanted(path):
    return path.endswith(CODE) and not SKIP.search(path)


def added_lines(top):
    """{path relative to the repository: [(line number, text)]} for every line added in the working tree."""
    added = {}
    has_head = git(top, "rev-parse", "--verify", "-q", "HEAD") is not None
    diffs = [git(top, "diff", *DIFF, "HEAD")] if has_head else [git(top, "diff", *DIFF, "--cached"),
                                                                 git(top, "diff", *DIFF)]
    for diff in diffs:
        path, line = None, 0
        for raw in (diff or "").splitlines():
            if raw.startswith("+++ "):
                name = raw[4:].strip().strip('"')
                path = name[2:] if name.startswith("b/") else None
            elif raw.startswith("@@"):
                m = HUNK.match(raw)
                line = int(m.group(1)) if m else 0
            elif raw.startswith("+") and path:
                added.setdefault(path, []).append((line, raw[1:]))
                line += 1
            elif raw.startswith(" "):
                line += 1
    for path in (git(top, "ls-files", "--others", "--exclude-standard", "-z") or "").split("\0"):
        if path and wanted(path):
            try:
                with open(f"{top}/{path}", encoding="utf-8", errors="replace") as f:
                    added[path] = [(n, text.rstrip("\n")) for n, text in enumerate(f, 1)]
            except OSError:
                continue
    return added


def main(cwd):
    top = (git(cwd, "rev-parse", "--show-toplevel") or "").strip()
    if not top:
        return {"suppressOutput": True}
    notes = []
    for path, lines in sorted(added_lines(top).items()):
        if not wanted(path):
            continue
        hits = [f"{n}:{text}" for n, text in lines if LEFTOVER.search(text)][:5]
        if hits:
            notes.append(f"NOTE: console.log/debugger found in {path}:\n" + "\n".join(hits))
    return {"systemMessage": "\n\n".join(notes)} if notes else {"suppressOutput": True}


try:
    result = main(sys.argv[1])
except Exception as exc:  # the stop goes ahead; the owner is told the check did not run
    result = {"systemMessage": f"verify-pipeline-completion hit an internal error and checked nothing: "
                               f"{exc.__class__.__name__}: {exc}"}
print(json.dumps(result))
PY
exit 0
