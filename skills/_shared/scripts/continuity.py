#!/usr/bin/env python3
"""Keep a project's hand-over between sessions and tools automatic: Claude Code and Codex, either way round.

Hook use (the registration names the tool; the payload arrives on stdin):
  continuity.py session-start --tool claude|codex   SessionStart: tell the new session where things stand
  continuity.py claim --tool claude|codex           PreToolUse on file edits: take the writer role on the first write
  continuity.py stop --tool claude|codex            Stop: refresh the handoff note; ask once for a state.md update
Direct use:
  continuity.py packet <project> [--tool <t> --session <id>]   write docs/project/handoffs/latest.md now
  continuity.py recover <project>    print the work done in another conversation after the last handoff note
                  (the session-start text, for a tool whose hooks are not active)
                  (the tool and session default to the ones this command runs in: session_env.py)

session-start. A project that uses the pipeline (it has docs/project) but whose record is not complete
(record_check.py) gets one instruction: adopt it before building or fixing (`/plan adopt`); an ordinary
repository gets none. Whatever the Writer line says, the new session is also told about
work the record may not hold yet: it finds the latest other conversation in this project, in either tool (Claude
Code transcripts under ~/.claude/projects, Codex sessions under ~/.codex/sessions, matched by working folder, so
it works even when a tool's hooks never ran, as when a session ends because its usage limit ran out), and when
that conversation worked after the last handoff note, it quotes the owner's messages typed there since the note,
the conversation's last message, and how to fold both into the record before building on. Otherwise, when docs/project/state.md names another writer, the
new session is told who worked last and when, the milestone and phase, the next step, open items and
blockers, which files changed since that writer's handoff note, and which read-list files changed; and it
is warned when another agent process is working in the same checkout right now.
claim. On any write inside the project by a session that is not the recorded writer (the Writer line is
compared on every write, so a session that hands over to the other tool and comes back takes the role back),
the Writer line is rewritten to this session and the change is logged in docs/project/handoffs/log.md. It never
blocks; a second agent working in the same checkout is surfaced as a warning to the owner.
stop. When this session is the writer: docs/project/handoffs/latest.md is rewritten mechanically from
state.md, the build record, and the live fingerprint (so it always passes handoff_check.py when state.md
is filled in), with the file list beside it (latest.files). If product files changed during the turn but
state.md did not, the stop is held once with a request to update state.md.

Hooks never break a session: an internal error is reported as a visible message and the call proceeds.
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fingerprint import fingerprint  # noqa: E402

READ_LIST = ("intent.md", "brief.md", "milestones.md", "state.md", "interfaces.md", "decisions.md")
WRITE_TOOLS = re.compile(r"^(Write|Edit|MultiEdit|NotebookEdit|apply_patch|write_file|edit_file)$", re.I)


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_root(start):
    p = Path(start or ".").resolve()
    for c in [p, *p.parents]:
        if (c / "docs/project").is_dir() or (c / "AGENTS.md").is_file() or (c / ".git").exists():
            return c
        if c == Path.home():
            break
    return None


def record_root(start):
    """The nearest folder at or above start (a folder or a file, which need not exist yet) holding
    docs/project/state.md, or None."""
    if not start:
        return None
    p = Path(start).resolve()
    for c in [p, *p.parents]:
        if (c / "docs/project/state.md").is_file():
            return c
    return None


# Which project a session claimed, so its stop finds the project even when the session was started in a
# parent folder (the harness then reports the parent as its working folder).
CLAIMS = Path(f"/tmp/pipeline-continuity-{os.getuid()}")


def build_root(data, tool, targets=()):
    """The project whose build record a hook acts on: the one holding an edited file, else the working folder's
    (walking up), else $CLAUDE_PROJECT_DIR when it holds a record, else the one this session claimed."""
    for t in targets:
        r = record_root(t)
        if r:
            return r
    r = record_root(data.get("cwd"))
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if not r and env and (Path(env) / "docs/project/state.md").is_file():
        r = Path(env).resolve()
    if not r:
        try:
            r = record_root((CLAIMS / f"{tool}-{data.get('session_id', '')}").read_text().strip())
        except OSError:
            r = None
    return r


def section(text, heading):
    m = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
    return m.group(1).strip() if m else ""


def writer_of(state_text):
    line = section(state_text, "Writer").splitlines()
    return line[0].strip() if line else ""


def me(tool, session):
    return f"{tool} session {session}"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"


def other_agents(root, own_pid):
    """Agent processes (claude, codex) whose working directory is inside root, other than this session."""
    try:
        out = subprocess.run(["pgrep", "-lx", "claude|codex"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    hits = []
    ancestors = set()
    pid = own_pid
    for _ in range(6):
        ancestors.add(pid)
        try:
            pid = int(subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True,
                                     timeout=5).stdout.strip() or 0)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            break
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2 or int(parts[0]) in ancestors:
            continue
        try:
            cwd = subprocess.run(["lsof", "-a", "-p", parts[0], "-d", "cwd", "-Fn"], capture_output=True, text=True,
                                 timeout=5).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        for l in cwd.splitlines():
            if l.startswith("n") and (l[1:] == str(root) or l[1:].startswith(str(root) + "/")):
                hits.append(f"{parts[1]} (pid {parts[0]})")
    return hits


def write_packet(root, tool, session):
    rec = root / "docs/project"
    state = (rec / "state.md").read_text(encoding="utf-8") if (rec / "state.md").is_file() else ""
    fp, rows = fingerprint(root, "product")
    from intent_lock import effective  # noqa: E402
    intent = (rec / "intent.md").read_text(encoding="utf-8") if (rec / "intent.md").is_file() else ""
    eff = effective(intent) if intent else {"must_not_lose": {}}
    brief = (rec / "brief.md").read_text(encoding="utf-8") if (rec / "brief.md").is_file() else ""
    constraints = [m.group(1) for m in re.finditer(r"^\|\s*(C-\d+)\s*\|(.*)\|\s*$", brief, re.M)
                   if not re.search(r"\|\s*(superseded|retired|dropped)\s*$", m.group(0), re.I)]
    milestones = (rec / "milestones.md").read_text(encoding="utf-8") if (rec / "milestones.md").is_file() else ""
    carried = [f"- {l.strip()[2:]} · from: parked" for l in milestones.splitlines()
               if l.strip().startswith("- ") and "re-enable:" in l]
    for ledger in sorted((rec / "reviews").glob("*.findings.json")) if (rec / "reviews").is_dir() else []:
        try:
            data = json.loads(ledger.read_text())
        except ValueError:
            continue
        for fid, row in data.items():
            if row.get("status") in ("open", "logged"):
                carried.append(f"- {fid} {row.get('summary', '')[:80]} · from: gate finding ({row.get('status')})")
    body = {
        "Authority": "May: continue the milestone named in state.md within its contract.\n"
                     "May not: anything the stop rules in docs/project/brief.md reserve for the owner; any "
                     "irreversible or credentialed action without the owner.",
        "Read list": "\n".join(f"- docs/project/{f} · sha256 {sha(rec / f)}" for f in READ_LIST if (rec / f).is_file()),
        "Candidate": fp,
        "Done": section(state, "Done") or "none",
        "Open": section(state, "Open") or "none",
        "In flight": section(state, "In flight") or "none",
        "Blockers": section(state, "Blockers") or "none",
        "Failures": section(state, "Failures") or "none",
        "Carried forward": "\n".join(carried) or "none",
        "Constraint IDs": ", ".join(constraints) or "none",
        "Must-not-lose IDs": ", ".join(eff["must_not_lose"]) or "none",
        "Next step": section(state, "Next step") or "none",
        "Hand back": "Keep docs/project/state.md current; record decisions in docs/project/decisions.md when they "
                     "are made. The next session reads this note.",
    }
    text = f"# Handoff\n\nFrom: {me(tool, session)}\nTo: the next session (any tool)\nWritten: {now()}\n"
    text += "".join(f"\n## {k}\n{v}\n" for k, v in body.items())
    out = rec / "handoffs"
    out.mkdir(parents=True, exist_ok=True)
    (out / "latest.md").write_text(text, encoding="utf-8")
    (out / "latest.files").write_text(fp + "\n" + "".join(f"{h[:16]}  {rel}\n" for rel, h in rows))
    return fp


def changed_since_packet(root):
    listing = root / "docs/project/handoffs/latest.files"
    if not listing.is_file():
        return None
    old = {}
    for line in listing.read_text().splitlines()[1:]:
        if "  " in line:
            h, rel = line.split("  ", 1)
            old[rel] = h
    fp, rows = fingerprint(root, "product")
    cur = {rel: h[:16] for rel, h in rows}
    return sorted(r for r in set(old) | set(cur) if old.get(r) != cur.get(r))


def read_list_changes(root):
    packet = root / "docs/project/handoffs/latest.md"
    if not packet.is_file():
        return []
    changed = []
    for rel, h in re.findall(r"^- (docs/project/\S+) · sha256 (\S+)", packet.read_text(encoding="utf-8"), re.M):
        if rel.endswith("state.md"):
            continue
        if sha(root / rel) != h:
            changed.append(rel)
    return changed


def inside(path, root):
    """True when path is root or below it, whatever symlinks either spelling goes through (/var vs /private/var)."""
    if not path:
        return False
    a, b = str(Path(path).resolve()), str(Path(root).resolve())
    return a == b or a.startswith(b + "/")


def other_conversations(root, skip):
    """[(mtime, tool, session id, path)] of Claude Code and Codex conversations run inside root, newest first."""
    home, out = Path.home(), []
    esc = re.sub(r"[^A-Za-z0-9]", "-", str(root))
    projects = home / ".claude/projects"
    for d in projects.glob(esc + "*") if projects.is_dir() else []:
        for f in d.glob("*.jsonl"):
            if f.stem in skip:
                continue
            try:
                with open(f, encoding="utf-8") as fh:
                    cwd = next((json.loads(l).get("cwd") for l in (fh.readline() for _ in range(8))
                                if l.strip() and json.loads(l).get("cwd")), None)
            except (OSError, ValueError):
                continue
            if cwd and inside(cwd, root):
                out.append((f.stat().st_mtime, "claude", f.stem, f))
    sessions = home / ".codex/sessions"
    if sessions.is_dir():
        newest = sorted(sessions.glob("*/*/*/rollout-*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)[:300]
        for f in newest:
            try:
                with open(f, encoding="utf-8") as fh:
                    meta = (json.loads(fh.readline()).get("payload") or {})
            except (OSError, ValueError):
                continue
            sid = meta.get("id") or ""
            if sid and sid not in skip and inside(meta.get("cwd") or "", root):
                out.append((f.stat().st_mtime, "codex", sid, f))
    return sorted(out, key=lambda r: r[0], reverse=True)


def last_said(path, tool, tail=3_000_000):
    """The conversation's last message (what it said it was doing), read from the end of its file."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - tail))
        lines = f.read().decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if tool == "codex":
            pl = e.get("payload") if isinstance(e.get("payload"), dict) else {}
            if e.get("type") == "event_msg" and pl.get("type") == "agent_message" and pl.get("message"):
                return pl["message"]
        elif e.get("type") == "assistant":
            texts = [c.get("text", "") for c in (e.get("message") or {}).get("content") or []
                     if isinstance(c, dict) and c.get("type") == "text" and c.get("text", "").strip()]
            if texts:
                return texts[-1]
    return None


def recovery(root, tool, session):
    """Lines telling a new session about work in another conversation after the last handoff note, or []."""
    packet = root / "docs/project/handoffs/latest.md"
    note = re.search(r"^Written:\s*(\S+)", packet.read_text(encoding="utf-8"), re.M) if packet.is_file() else None
    since = note.group(1) if note else ""
    convs = other_conversations(root, {session})
    if not convs:
        return []
    mtime, other_tool, sid, path = convs[0]
    if packet.is_file() and mtime <= packet.stat().st_mtime + 5:
        return []
    from rulings import typed_in_lines  # noqa: E402
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 6_000_000))
        lines = f.read().decode("utf-8", errors="replace").splitlines()
    owner = [(ts, text) for _, ts, text in typed_in_lines(lines) if not since or (ts or "") > since]
    changed = changed_since_packet(root) or []
    last = last_said(path, other_tool)
    if not owner and not changed and packet.is_file():
        return []
    proof = f"codex:{sid}" if other_tool == "codex" else sid
    out = [f"Work after the last handoff note{' (' + since + ')' if since else ' (there is none)'}: the latest "
           f"conversation here is {other_tool} session {sid} ({path}); it may have stopped without updating the "
           "record (a usage limit, a closed window), so the record may not hold its last work."]
    if owner:
        out.append(f"The owner's messages typed in it since then ({len(owner)}), verbatim:")
        out += [f"- {ts or '?'} \"{text[:700]}{' ...' if len(text) > 700 else ''}\"" for ts, text in owner[-8:]]
        if len(owner) > 8:
            out.append(f"- ({len(owner) - 8} earlier message(s) in the transcript)")
    if last:
        out.append(f"Its last message: \"{last[:900]}{' ...' if len(last) > 900 else ''}\"")
    out.append("Before building on it: (1) put every decision or instruction in those owner messages into the record "
               "(decisions.md with `rulings.py record <project> --id D-<nnn> --quote \"<their words>\" --session "
               f"{proof}`, open items into state.md); ask the owner only where two readings differ; (2) check the "
               "files changed since the note for half-finished edits (git diff, then the test command); (3) update "
               "state.md, then continue. /dev resume does this.")
    return out


def emit(event, context=None, message=None):
    out = {}
    if context:
        out["hookSpecificOutput"] = {"hookEventName": event, "additionalContext": context}
    if message:
        out["systemMessage"] = message
    if out:
        print(json.dumps(out))


def session_start(data, tool):
    root = find_root(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd"))
    if root is None:
        return 0
    from record_check import classify  # noqa: E402
    info = classify(root)
    invoke = "$plan adopt" if tool == "codex" else "/plan adopt"
    lines = []
    # Only a project that already uses the pipeline (it has docs/project) is told to adopt: an ordinary repository
    # is the owner's to decide about, and an adoption is too large to start on a hook's say-so.
    if info["kind"] not in ("complete", "empty") and (root / "docs/project").is_dir():
        lines.append(f"This project has no complete build record (kind: {info['kind']}"
                     + (f"; missing: {', '.join(info['missing'])}" if info["missing"] else "") +
                     f"). Before building, fixing, or gating, adopt it with {invoke}: read the code and every "
                     "existing document, reconstruct the record with evidence, verify it, and lock it with the "
                     "owner. Questions about the code can be answered without it.")
    state_path = root / "docs/project/state.md"
    state = state_path.read_text(encoding="utf-8") if state_path.is_file() else ""
    writer = writer_of(state)
    session = data.get("session_id", "")
    if state and writer and writer != me(tool, session):
        updated = re.search(r"^Updated:\s*(.+)$", state, re.M)
        lines.append(f"Last writer: {writer}" + (f", updated {updated.group(1)}." if updated else "."))
        lines.append("Milestone: " + (section(state, "Milestone") or "none"))
        lines.append("Next step: " + (section(state, "Next step") or "none"))
        open_items = [l for l in section(state, "Open").splitlines() if l.strip().startswith("- [ ]")]
        lines.append(f"Open items: {len(open_items)}; blockers: {section(state, 'Blockers') or 'none'}")
        changed = changed_since_packet(root)
        if changed is None:
            lines.append("No handoff note from that writer: reconcile the tree against state.md before acting.")
        elif changed:
            lines.append(f"{len(changed)} product file(s) changed since that writer's handoff note: "
                         + ", ".join(changed[:12]) + (" ..." if len(changed) > 12 else ""))
        docs = read_list_changes(root)
        if docs:
            lines.append("Changed since the note: " + ", ".join(docs))
        lines.append("Read docs/project/state.md and docs/project/handoffs/latest.md, restate the milestone promise "
                     "and must-not-lose items, and take over as writer when you start changing files.")
    if info["kind"] in ("complete", "partial"):
        try:
            from project_status import status  # noqa: E402
            st = status(root)
            if st["last_step"] != "none recorded":
                lines.append(f"Last step: {st['last_step']}")
            prefix = "$" if tool == "codex" else "/"
            for i, n in enumerate(st["next"][:3]):
                action = n["action"].replace("/", prefix, 1) if n["action"].startswith("/") else n["action"]
                lines.append(f"{'Next' if i == 0 else 'Then'} ({n['who']}, computed from the record): {action} · "
                             f"{n['why'][:200]}")
        except Exception as exc:  # the briefing must never hide that the next step could not be computed
            lines.append(f"(Could not compute the next step: {exc.__class__.__name__}: {exc}.)")
    try:
        from inbox import open_items  # noqa: E402
        waiting = open_items(root)
        if waiting:
            lines.append(f"Inbox: {len(waiting)} open item(s) waiting to be weighed ("
                         + ", ".join(f"{i['id']} {i['title'][:40]}" for i in waiting[:5])
                         + (" ..." if len(waiting) > 5 else "") + f"); {'$' if tool == 'codex' else '/'}inbox review.")
    except Exception as exc:  # the briefing must never hide that the inbox could not be read
        lines.append(f"(Could not read docs/project/inbox.md: {exc.__class__.__name__}: {exc}.)")
    try:
        lines += recovery(root, tool, session)
    except Exception as exc:  # the briefing must never hide that recovery could not be read
        lines.append(f"(Could not read the other conversations in this project: {exc.__class__.__name__}: {exc}. "
                     "Check git status and state.md by hand before building on.)")
    others = other_agents(root, os.getppid())
    msg = None
    if others:
        msg = f"Another agent is working in this checkout: {', '.join(others)}. One writer at a time."
        lines.append(msg)
    if lines:
        emit("SessionStart", "\n".join(lines), msg)
    return 0


def claim(data, tool):
    if not WRITE_TOOLS.match(str(data.get("tool_name", ""))):
        return 0
    session = data.get("session_id", "")
    tool_input = data.get("tool_input") or {}
    # Codex's apply_patch carries the patch in tool_input.command (its hooks guide); older payloads used input.
    patch = tool_input.get("command") or tool_input.get("patch") or tool_input.get("input") or ""
    targets = re.findall(r"^\*\*\* (?:Update|Add|Delete) File: (.+?)\s*$", patch, flags=re.M) if isinstance(patch, str) else []
    targets = targets or [tool_input.get("file_path") or tool_input.get("path") or ""]
    base = Path(data.get("cwd") or ".")
    resolved = [str((Path(t) if Path(t).is_absolute() else base / t).resolve()) for t in targets if t]
    root = build_root(data, tool, resolved)
    if root is None:
        return 0
    state_path = root / "docs/project/state.md"
    if resolved and not any(inside(r, root) for r in resolved):
        return 0
    try:
        CLAIMS.mkdir(parents=True, exist_ok=True)
        (CLAIMS / f"{tool}-{session}").write_text(str(root))
    except OSError:
        pass  # only a convenience for the stop hook; the working folder still finds the project
    state = state_path.read_text(encoding="utf-8")
    old = writer_of(state)
    new = me(tool, session)
    if old == new:
        return 0
    msg = None
    if old != new:
        if re.search(r"^## Writer[ \t]*\n", state, re.M):
            state = re.sub(r"(^## Writer[ \t]*\n)(.*?)(?=\n## |\Z)", lambda m: m.group(1) + new + "\n", state,
                           count=1, flags=re.M | re.S)
        else:
            state += f"\n## Writer\n{new}\n"
        state_path.write_text(state, encoding="utf-8")
        log = root / "docs/project/handoffs/log.md"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"- {now()} · {new} took over from {old or 'no recorded writer'}\n")
        others = other_agents(root, os.getppid())
        if others:
            msg = f"Taking over as writer while another agent works in this checkout: {', '.join(others)}."
    if msg:
        emit("PreToolUse", message=msg)
    return 0


def stop(data, tool):
    root = build_root(data, tool)
    if root is None:
        return 0
    state_path = root / "docs/project/state.md"
    session = data.get("session_id", "")
    if writer_of(state_path.read_text(encoding="utf-8")) != me(tool, session):
        return 0
    track = root / ".evidence/continuity" / f"{session}.json"
    track.parent.mkdir(parents=True, exist_ok=True)
    prev = json.loads(track.read_text()) if track.is_file() else {}
    fp = write_packet(root, tool, session)
    state_sha = sha(state_path)
    track.write_text(json.dumps({"fingerprint": fp, "state_sha": state_sha, "at": now()}))
    if prev and fp != prev.get("fingerprint") and state_sha == prev.get("state_sha") and not data.get("stop_hook_active"):
        reason = ("Product files changed this turn but docs/project/state.md did not. Update its Done, Open, and "
                  "Next step (a short edit) so the next session, in either tool, starts from the truth; then finish.")
        print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def main(argv):
    if len(argv) >= 1 and argv[0] == "packet":
        if len(argv) < 2:
            print(__doc__.strip(), file=sys.stderr)
            return 2
        opts = {argv[i]: argv[i + 1] for i in range(2, len(argv) - 1) if argv[i] in ("--tool", "--session")}
        from session_env import current  # noqa: E402
        tool, sid = current()
        tool, sid = opts.get("--tool") or tool, opts.get("--session") or sid
        if tool in (None, "ambiguous") or not sid:
            print(f"continuity: cannot tell which session is writing ({tool or 'no session variable set'}); "
                  "pass --tool claude|codex --session <id>", file=sys.stderr)
            return 2
        print(write_packet(Path(argv[1]).resolve(), tool, sid))
        return 0
    if len(argv) >= 2 and argv[0] == "recover":
        from session_env import current  # noqa: E402
        tool, sid = current()
        root = find_root(argv[1])
        found = recovery(root, tool or "claude", sid or "") if root else []
        print("\n".join(found) if found else "no work after the last handoff note in another conversation")
        return 0
    if not argv or argv[0] not in ("session-start", "claim", "stop"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    tool = argv[argv.index("--tool") + 1] if "--tool" in argv else "claude"
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        data = {}
    try:
        return {"session-start": session_start, "claim": claim, "stop": stop}[argv[0]](data, tool)
    except Exception as exc:  # a hook must never break the session, and must never fail silently
        emit(data.get("hook_event_name") or "Notification",
             message=f"continuity.py {argv[0]} hit an internal error and did nothing: {exc.__class__.__name__}: {exc}")
        traceback.print_exc(file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
