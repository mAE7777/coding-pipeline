#!/usr/bin/env python3
"""Stop hook: typecheck once per turn, and only when TypeScript files changed.

Replaces a full-project `tsc --noEmit` after every single edit (steady heat and latency on large repos).
At the end of a turn, if any .ts/.tsx file changed since this hook last ran in this session (git's view of
the working tree, or file times outside git), it runs `npx --no-install tsc --noEmit` once, through the
heavy-job lock owned by this session and with the lock's own timeout (so tsc never outlives the lock),
and reports the errors that fall in the changed files as a system message. It never blocks the stop.
When it cannot run (TypeScript not installed, the lock busy, a timeout), it says so as NOT_RUN instead of
staying silent.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HEAVY_PY = Path(__file__).resolve().parents[1] / "skills/_shared/scripts/heavy.py"
if not HEAVY_PY.exists():
    HEAVY_PY = Path.home() / ".claude/skills/_shared/scripts/heavy.py"


def say(msg):
    print(json.dumps({"systemMessage": msg}))
    return 0


SKIP = {"node_modules", ".git", "dist", "build", ".next", "out", "coverage"}


def changed_ts(cwd, since):
    try:
        r = subprocess.run(["git", "-C", str(cwd), "ls-files", "--modified", "--others", "--exclude-standard"],
                           capture_output=True, text=True, timeout=15)
        names = r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        names = None
    if names is None:
        found = []
        for dirpath, dirnames, filenames in os.walk(cwd):
            dirnames[:] = [d for d in dirnames if d not in SKIP]
            found += [str((Path(dirpath) / f).relative_to(cwd)) for f in filenames if f.endswith((".ts", ".tsx"))]
            if len(found) > 20000:
                break
        names = "\n".join(found)
    out = []
    for rel in names.splitlines():
        if rel.endswith((".ts", ".tsx")) and "node_modules/" not in rel:
            p = cwd / rel
            if p.exists() and p.stat().st_mtime > since:
                out.append(rel)
    return out


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    start = Path(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()
    # The nearest tsconfig.json at or above the working folder (a session may have cd'd into a subfolder).
    cwd = next((c for c in [start, *start.parents] if (c / "tsconfig.json").is_file() or c == Path.home()), start)
    if not (cwd / "tsconfig.json").is_file():
        return 0
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", data.get("session_id") or "unknown")
    stamp = Path(tempfile.gettempdir()) / f"typecheck-once-{safe}"
    since = stamp.stat().st_mtime if stamp.exists() else 0
    files = changed_ts(cwd, since)
    if not files:
        return 0
    started = time.time()
    try:
        proc = subprocess.run([sys.executable, str(HEAVY_PY), "run", "--wait", "20", "--timeout", "170",
                               "--owner", data.get("session_id") or "typecheck", "--",
                               "npx", "--no-install", "tsc", "--noEmit", "--pretty", "false"],
                              cwd=cwd, capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired:
        return say("Typecheck NOT_RUN: the lock wrapper did not return in 240s.")
    stamp.touch()
    os.utime(stamp, (started, started))
    if proc.returncode == 75:
        return say("Typecheck NOT_RUN: another heavy job holds the lock; the next stop tries again.")
    if proc.returncode == 124:
        return say("Typecheck NOT_RUN: tsc took longer than 170s and was stopped.")
    output = proc.stdout + proc.stderr
    if proc.returncode != 0 and "error TS" not in output:
        return say(f"Typecheck NOT_RUN: tsc could not run ({output.strip().splitlines()[-1][:120] if output.strip() else 'no output'}).")
    errors = [l for l in output.splitlines() if "error TS" in l and any(f in l for f in files)]
    if errors:
        more = f" (+{len(errors) - 10} more)" if len(errors) > 10 else ""
        return say("TypeScript errors in files changed this turn:\n" + "\n".join(errors[:10]) + more)
    return 0


if __name__ == "__main__":
    sys.exit(main())
