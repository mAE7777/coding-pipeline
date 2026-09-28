#!/usr/bin/env python3
"""Stop hook registered by /dev: keep a milestone run going while it still owes work.

Reads the hook input (JSON on stdin) and docs/project/state.md of the project ($CLAUDE_PROJECT_DIR, else the
nearest folder above the hook's cwd that holds one). It holds the turn open (exit 2, the reason on stderr,
which Claude Code feeds back to the model) only when all of these hold:
  - the Milestone section says phase building, checkpoint, or fixing (or gate, when the Campaign section
    names an authorized campaign);
  - the Writer section names this session ("claude session <id>", or "codex session <id>" when registered in
    Codex with --tool codex);
  - the In flight section is "none" (background work reports back in a new turn anyway);
  - the final message does not end by asking the owner a question;
  - the owner's latest typed message does not ask to stop, pause, or wait (English or Chinese);
  - the Open section still has unchecked items and the Blockers section is "none".
Limits: 3 holds in a row without progress (progress = a change to the Milestone, Done, Open, or Blockers
sections; timestamps do not count), and 25 holds in the whole session; past either, the stop goes through
with a visible warning so a stuck run surfaces instead of looping. Skill hooks stay registered for the rest
of the session, which is why every condition is re-checked on each stop. An internal error lets the stop
through with a visible message.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

PAUSE = re.compile(r"\b(stop|pause|wait|hold on|hang on|halt|stand by|don'?t (continue|go on|keep going))\b|"
                   r"\u6682\u505c|\u505c\u4e0b|\u5148\u505c|\u505c\u4e00\u4e0b|\u7b49\u7b49|\u7b49\u4e00\u4e0b|\u5148\u522b|\u522b\u7ee7\u7eed|\u4e0d\u8981\u7ee7\u7eed", re.I)
SHARED = Path(__file__).resolve().parents[2] / "_shared/scripts"
STREAK_CAP = 3
SESSION_CAP = 25
ACTIVE_PHASES = ("building", "checkpoint", "fixing")
PROGRESS_SECTIONS = ("milestone", "done", "open", "blockers")


def sections(text):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    out, name = {}, None
    for line in text.splitlines():
        m = re.match(r"^## (.+?)\s*$", line)
        if m:
            name = m.group(1).strip().lower()
            out[name] = []
        elif name is not None:
            out[name].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def is_none(value):
    v = re.sub(r"\(.*?\)", "", value or "").strip().lower().strip("-. ")
    return v in ("", "none")


def find_state(data):
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and (Path(env) / "docs/project/state.md").is_file():
        return Path(env) / "docs/project/state.md"
    p = Path(data.get("cwd") or ".").resolve()
    for c in [p, *p.parents]:
        if (c / "docs/project/state.md").is_file():
            return c / "docs/project/state.md"
    return None


def counter_path(session_id):
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "unknown")
    return Path(tempfile.gettempdir()) / f"milestone-continue-{safe}.json"


def load(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {"streak": 0, "total": 0, "progress_hash": ""}


def allow(message=None):
    if message:
        print(json.dumps({"systemMessage": message}))
    return 0


def asks_owner(message):
    lines = [l.strip() for l in (message or "").strip().splitlines() if l.strip()]
    return bool(lines) and lines[-1].rstrip("*_ )").endswith(("?", "\uff1f"))


def decide(data):
    state = find_state(data)
    if state is None:
        return allow()
    secs = sections(state.read_text(encoding="utf-8"))
    phase = secs.get("milestone", "").lower()
    campaign = not is_none(secs.get("campaign", ""))
    active = any(p in phase for p in ACTIVE_PHASES) or (campaign and "phase: gate" in phase)
    if not active:
        return allow()
    session = data.get("session_id", "")
    writer = secs.get("writer", "").splitlines()[0].strip() if secs.get("writer") else ""
    tool = sys.argv[sys.argv.index("--tool") + 1] if "--tool" in sys.argv else "claude"
    if writer != f"{tool} session {session}":
        return allow()
    if not is_none(secs.get("in flight", "")):
        return allow()
    if asks_owner(data.get("last_assistant_message")):
        return allow()
    if owner_paused(data):
        return allow()
    open_items = re.findall(r"^- \[ \]\s*(.+)$", secs.get("open", ""), flags=re.M)
    cpath = counter_path(session)
    record = load(cpath)
    if not open_items or not is_none(secs.get("blockers", "")):
        record["streak"] = 0
        cpath.write_text(json.dumps(record))
        return allow()
    progress = hashlib.sha256("\n".join(secs.get(s, "") for s in PROGRESS_SECTIONS).encode()).hexdigest()
    if progress != record.get("progress_hash"):
        record["streak"] = 0
    if record["streak"] >= STREAK_CAP or record["total"] >= SESSION_CAP:
        why = (f"{STREAK_CAP} automatic continuations without progress in state.md"
               if record["streak"] >= STREAK_CAP else f"{SESSION_CAP} automatic continuations this session")
        record["streak"] = 0
        cpath.write_text(json.dumps(record))
        return allow(f"The milestone run stopped after {why}; {len(open_items)} open item(s) remain. "
                     "It may be stuck: check docs/project/state.md.")
    record.update({"streak": record["streak"] + 1, "total": record["total"] + 1, "progress_hash": progress})
    cpath.write_text(json.dumps(record))
    listed = "; ".join(i.strip() for i in open_items[:8])
    more = f" (and {len(open_items) - 8} more)" if len(open_items) > 8 else ""
    sys.stderr.write(
        f"The milestone still has {len(open_items)} open item(s) in docs/project/state.md: {listed}{more}. "
        "Continue with them. If one is blocked on something only the owner can provide, record it under "
        "Blockers in state.md with what would unblock it, then stop.\n")
    return 2


def owner_paused(data):
    """True when the owner's latest typed message asks the run to stop, pause, or wait."""
    path = data.get("transcript_path")
    if not path or not Path(path).is_file():
        return False
    sys.path.insert(0, str(SHARED))
    from rulings import last_typed  # noqa: E402
    text = last_typed(path)
    return bool(text and PAUSE.search(text[:600]))


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return allow()
    try:
        return decide(data)
    except Exception as exc:  # never break the session, never fail silently
        return allow(f"milestone-continue hit an internal error and let the stop through: {exc.__class__.__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
