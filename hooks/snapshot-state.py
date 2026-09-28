#!/usr/bin/env python3
"""PreCompact hook: write a mechanical snapshot before the conversation is compacted.

For a project with docs/project/state.md, writes .evidence/compact/<UTC time>.md containing git status,
git diff --stat, the state.md hash, and a verbatim copy of state.md's Milestone, Open, Blockers, and Next
step sections. The snapshot cannot be lost or summarized away, and the post-compaction hook points the
model at it. Projects without state.md are left alone. Never blocks compaction.
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def run(cmd, cwd):
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "(unavailable)"


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    start = Path(env) if env and (Path(env) / "docs/project/state.md").is_file() else Path(data.get("cwd") or ".")
    cwd = next((c for c in [start.resolve(), *start.resolve().parents] if (c / "docs/project/state.md").is_file()), None)
    if cwd is None:
        return 0
    state = cwd / "docs/project/state.md"
    raw = state.read_text(encoding="utf-8")
    keep = []
    for name in ("Milestone", "Open", "Blockers", "Next step"):
        m = re.search(rf"^## {re.escape(name)}\s*$(.*?)(?=^## |\Z)", raw, flags=re.M | re.S)
        keep.append(f"## {name}\n{m.group(1).strip() if m else '(missing)'}")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = cwd / ".evidence/compact"
    out_dir.mkdir(parents=True, exist_ok=True)
    body = [
        f"# Compaction snapshot {stamp}",
        f"trigger: {data.get('trigger', 'unknown')} · session: {data.get('session_id', 'unknown')}",
        f"state.md sha256: {hashlib.sha256(raw.encode()).hexdigest()}",
        "", "## git status --short", run(["git", "status", "--short"], cwd) or "(clean or not a repo)",
        "", "## git diff --stat", run(["git", "diff", "--stat"], cwd) or "(no diff)",
        "", "## state.md excerpt", *keep, "",
    ]
    (out_dir / f"{stamp}.md").write_text("\n".join(body), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
