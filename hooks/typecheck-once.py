#!/usr/bin/env python3
"""Stop hook: typecheck once per turn, and only when TypeScript files changed.

Replaces a full-project `tsc --noEmit` after every single edit (steady heat and latency on large repos).
At the end of a turn, if any .ts/.tsx file changed since this hook last ran in this session (git's view of
the working tree, or file times outside git), it runs `npx --no-install tsc --noEmit` once, through the
heavy-job lock owned by this session and with the lock's own timeout (so tsc never outlives the lock).
Errors that fall in the files changed this turn go to the model as the Stop hook's additionalContext
({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": ...}}), so it continues the turn and
fixes them; the owner sees a one-line note that they were sent. When the payload says stop_hook_active (the
turn already continued once because of a Stop hook), the same errors go to the owner as a system message
only, so the hook can never keep a turn going in a loop. Errors in other files are summarized for the owner
as a system message and never sent to the model. When it cannot run (TypeScript not installed, the lock
busy, a timeout), it says so as NOT_RUN in a system message instead of staying silent. An internal error is
reported the same way; the stop always goes ahead.
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
sys.path.insert(0, str(HEAVY_PY.parent))
from project_policy import managed, hook_project  # noqa: E402


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
    if not managed(hook_project(data)):
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
    found = [l for l in output.splitlines() if "error TS" in l]
    mine = [l for l in found if any(f in l for f in files)]
    elsewhere = [l for l in found if l not in mine]
    return report(mine, elsewhere, bool(data.get("stop_hook_active")))


def listing(errors, limit):
    return "\n".join(errors[:limit]) + (f"\n(+{len(errors) - limit} more)" if len(errors) > limit else "")


def report(mine, elsewhere, already_continued):
    """Errors in files changed this turn go to the model (unless a Stop hook already continued this turn); the
    owner gets a system message for everything else, and a note of what was sent."""
    out, notes = {}, []
    if mine and not already_continued:
        out["hookSpecificOutput"] = {"hookEventName": "Stop", "additionalContext": (
            "TypeScript errors in files changed this turn (tsc --noEmit, run once at the end of the turn):\n"
            + listing(mine, 10) + "\nFix them before ending the turn, or say plainly why one stays.")}
        notes.append(f"Typecheck: {len(mine)} error(s) in files changed this turn were sent to the model to fix.")
    elif mine:
        notes.append("TypeScript errors in files changed this turn (not sent to the model again: this turn already "
                     "continued once for a Stop hook):\n" + listing(mine, 10))
    if elsewhere:
        notes.append(f"Typecheck: {len(elsewhere)} error(s) in files not changed this turn (not sent to the model):\n"
                     + listing(elsewhere, 3))
    if notes:
        out["systemMessage"] = "\n".join(notes)
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # the hook must never hold the stop back because of its own bug, nor fail silently
        say(f"typecheck-once hit an internal error and let the turn end: {exc.__class__.__name__}: {exc}")
        sys.exit(0)
