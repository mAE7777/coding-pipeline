#!/usr/bin/env python3
"""Where a project stands and what comes next, computed from its record on disk (never from a session's memory).

Usage:
  project_status.py <project> [--json]
  project_status.py record <project> --skill <name> [--arg "<what it ran on>"] --outcome "<one line>"

The first form prints the state (record, intent lock, milestones with their latest gate verdict, the inbox,
blockers, work in flight, the last step) and the next steps in order, each with who takes it:
  builder  the agent can do it now without asking anyone
  owner    only the owner can decide it (the intent lock, a milestone acceptance, a stand-in consent, an inbox
           ruling, an irreversible action, a blocker only they can clear)
  wait     something is still running; continue when it reports
The rules, first match wins: another conversation's work after the last handoff note (fold it in); work in
flight (wait); a blocker (owner); no build record (adopt, or an idea to plan); a plan not yet locked (finish it,
then the owner locks); then the first milestone not accepted or dropped (build it, finish it, fix its gate
findings, rerun an inconclusive round, the owner accepts a gate-passed candidate, the owner decides what a
BLOCKED round names); the inbox is weighed between milestones, before the next one starts; with every milestone
accepted, a release is the owner's call. Open inbox items mid-milestone are listed after the next step.

The second form is how every skill ends: it appends a line to docs/project/journal.md (local-only: which skill
ran, on what, when, in which session, with what outcome, and what the record says comes next) and rewrites the
Last step section of state.md.

Exit 0, or 2 on bad usage.
"""
import datetime
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

STAGE = re.compile(r"^## (M\d+) ·\s*(.*?)$(.*?)(?=^## M\d+ ·|\Z)", re.M | re.S)


def section(text, heading):
    m = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text or "", re.M | re.S)
    return m.group(1).strip() if m else ""


def empty(value):
    return not value or value.strip().lower().startswith(("none", "<"))


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def round_running(root):
    """The milestone whose gate round is running now (its lock names a live process), or None."""
    lock = root / ".evidence/gate/round.running"
    try:
        held = lock.read_text().split()
    except OSError:
        return None
    return held[1] if len(held) >= 2 and alive(held[0]) else None


def milestones(root):
    ms = root / "docs/project/milestones.md"
    out = []
    for mid, name, body in STAGE.findall(ms.read_text(encoding="utf-8") if ms.is_file() else ""):
        status = re.search(r"^Status:\s*(\S+)", body, re.M)
        readiness = re.search(r"^Readiness:\s*(.+)$", body, re.M)
        rounds = sorted((root / f".evidence/gate/{mid}").glob("r*"), key=lambda p: int(p.name[1:] or 0)
                        if p.name[1:].isdigit() else 0)
        verdict = None
        for r in reversed(rounds):
            try:
                v = json.loads((r / "verdict.json").read_text())
                verdict = {"round": v.get("round"), "verdict": v.get("verdict"), "reasons": v.get("reasons") or [],
                           "fingerprint": v.get("fingerprint")}
                break
            except (OSError, ValueError):
                continue
        running = round_running(root) == mid
        out.append({"id": mid, "name": name.strip(), "status": status.group(1) if status else "planned",
                    "gate_passed": bool(readiness and "gate-passed [x]" in readiness.group(1)),
                    "released": bool(readiness and "released [x]" in readiness.group(1)),
                    "verdict": verdict, "round_running": running})
    return out


def status(root):
    root = Path(root).resolve()
    rec = root / "docs/project"
    from record_check import classify  # noqa: E402
    info = classify(root)
    state_text = (rec / "state.md").read_text(encoding="utf-8") if (rec / "state.md").is_file() else ""
    phase = section(state_text, "Milestone")
    blockers = section(state_text, "Blockers")
    in_flight = section(state_text, "In flight")
    open_items = [l.strip()[6:] for l in section(state_text, "Open").splitlines() if l.strip().startswith("- [ ]")]
    try:
        from inbox import open_items as inbox_items  # noqa: E402
        inbox = inbox_items(root)
    except Exception:
        inbox = []
    try:
        from continuity import recovery  # noqa: E402
        from session_env import current  # noqa: E402
        tool, sid = current()
        recovered = recovery(root, tool if tool in ("claude", "codex") else "claude", sid or "")
    except Exception:
        recovered = []
    ms = milestones(root)
    s = {"project": str(root), "record": info["kind"], "missing": info.get("missing", []),
         "intent_locked": info["intent_locked"], "phase": phase or "none", "open": open_items,
         "blockers": "" if empty(blockers) else blockers, "in_flight": "" if empty(in_flight) else in_flight,
         "milestones": ms, "inbox": inbox, "last_step": section(state_text, "Last step") or "none recorded",
         "recovery": bool(recovered)}
    s["next"] = with_inbox(next_steps(s, root), inbox)
    return s


def with_inbox(steps, inbox):
    """Open inbox items always show: mid-milestone they are weighed at the next stop, never dropped from view."""
    if inbox and not any(n["action"].startswith("/inbox") for n in steps):
        steps.append(step("builder", "/inbox review at the next stop",
                          "waiting: " + ", ".join(f"{i['id']} {i['title'][:40]}" for i in inbox[:5])))
    return steps


def step(who, action, why):
    return {"who": who, "action": action, "why": why}


def next_steps(s, root):
    out = []
    if s["recovery"]:
        out.append(step("builder", "/dev resume", "another conversation worked here after the last handoff note; its "
                                                  "work and the owner's words there go into the record first"))
    running = next((m["id"] for m in s["milestones"] if m["round_running"]), None)
    if running:
        return out + [step("wait", f"the {running} gate round is running; /gate {running} when it reports",
                           "its lock names a live process")]
    if s["in_flight"]:
        # Written by a session, and stale when that session was stopped: check it rather than wait on it.
        out.append(step("builder", "check that what state.md lists as in flight is still running; clear or finish it",
                        s["in_flight"][:200]))
    if s["blockers"]:
        return out + [step("owner", "clear the blocker", s["blockers"][:300])]
    if s["record"] == "empty":
        return out + [step("owner", "say what to build (or /capture the conversation where the idea lives), "
                                    "then /plan", "the folder has no code and no record yet")]
    if s["record"] not in ("complete", "partial"):
        return out + [step("builder", "/plan adopt", f"the project has no complete build record ({s['record']})")]
    if not s["intent_locked"]:
        return out + [step("builder", "/plan (finish the record and the cold read)", "the intent is not locked yet"),
                      step("owner", "lock the intent when it is played back", "only the owner locks what must be true")]
    inbox_between = [f"{i['id']} {i['title'][:50]}" for i in s["inbox"]]
    for m in s["milestones"]:
        if m["status"] in ("accepted", "dropped"):
            continue
        mid, v = m["id"], m["verdict"]
        if m["round_running"]:
            return out + [step("wait", f"the {mid} gate round is running; /gate {mid} when it reports",
                               "a round is in progress")]
        if m["status"] == "planned":
            if inbox_between:
                out.append(step("builder", "/inbox review", "weigh what is waiting before the next milestone starts: "
                                + ", ".join(inbox_between[:5])))
            return out + [step("builder", f"/dev {mid}", f"{mid} ({m['name']}) is the next milestone to build")]
        if m["status"] == "gate" and m["gate_passed"]:
            return out + [step("owner", f"watch the {mid} demo and accept it (/gate accept {mid}), or say what is wrong",
                               "the gate passed; only the owner accepts a milestone")]
        if v and v["verdict"] == "BLOCKED":
            return out + [step("owner", f"decide what the {mid} gate round {v['round']} could not",
                               "; ".join(v["reasons"])[:300])]
        if v and v["verdict"] == "INCONCLUSIVE" and m["status"] == "gate":
            return out + [step("builder", f"clear what made {mid} round {v['round']} inconclusive, then rerun "
                                          f"/gate {mid}", "; ".join(v["reasons"])[:300])]
        if m["status"] == "changes" or (v and v["verdict"] == "CHANGES"):
            return out + [step("builder", f"fix {mid} round {v['round'] if v else '?'}'s blocking findings (/fix, or "
                                          f"/dev resume for a larger change), then /dev freeze",
                               "; ".join(v["reasons"])[:300] if v else "the milestone is in changes")]
        if m["status"] == "gate":
            return out + [step("builder", f"/gate {mid}", f"{mid} is frozen and has no finished round")]
        return out + [step("builder", "/dev resume", f"{mid} is being built" +
                           (f"; open: {', '.join(s['open'][:3])}" if s["open"] else ""))]
    if inbox_between:
        out.append(step("builder", "/inbox review", "weigh what is waiting: " + ", ".join(inbox_between[:5])))
    if s["milestones"] and not all(m["released"] for m in s["milestones"] if m["status"] == "accepted"):
        out.append(step("owner", "decide whether to ship (/deploy)", "every milestone is accepted; a release is "
                                                                     "irreversible, so it is the owner's call"))
    return out or [step("owner", "add work (/inbox add, or /plan amend)", "every milestone is accepted and released")]


def render(s):
    lines = [f"Project: {Path(s['project']).name} · record {s['record']}"
             + (f" (missing: {', '.join(s['missing'])})" if s["missing"] else "")
             + f" · intent {'locked' if s['intent_locked'] else 'not locked'}",
             f"Phase: {s['phase']}",
             "Milestones: " + (" · ".join(
                 f"{m['id']} {m['status']}" + (" gate-passed" if m["gate_passed"] else "")
                 + (f" (round {m['verdict']['round']} {m['verdict']['verdict']})" if m["verdict"] else "")
                 for m in s["milestones"]) or "none"),
             f"Inbox: {len(s['inbox'])} open" + (f" ({', '.join(i['id'] for i in s['inbox'][:6])})" if s["inbox"] else ""),
             f"Blockers: {s['blockers'] or 'none'} · In flight: {s['in_flight'] or 'none'}",
             f"Last step: {s['last_step']}"]
    for i, n in enumerate(s["next"]):
        lines.append(f"{'Next' if i == 0 else 'Then'} ({n['who']}): {n['action']} · {n['why']}")
    return "\n".join(lines)


def record(root, skill, arg, outcome):
    root = Path(root).resolve()
    rec = root / "docs/project"
    rec.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    from session_env import current  # noqa: E402
    tool, sid = current()
    who = f"{tool} session {sid}" if tool in ("claude", "codex") else "unknown session"
    s = status(root)
    nxt = s["next"][0] if s["next"] else None
    nxt_text = f"{nxt['action']} ({nxt['who']})" if nxt else "nothing"
    last = f"{skill}{' ' + arg if arg else ''} · {stamp} · {who} · {outcome}"
    journal = rec / "journal.md"
    if not journal.is_file():
        journal.write_text("# Journal\n\nOne line per step: when, which step, in which session, the outcome, and what the "
                           "record said came next. Local-only.\n\n", encoding="utf-8")
    with open(journal, "a", encoding="utf-8") as f:
        f.write(f"- {stamp} · {skill}{' ' + arg if arg else ''} · {who} · {outcome} · next: {nxt_text}\n")
    state = rec / "state.md"
    if state.is_file():
        text = state.read_text(encoding="utf-8")
        if re.search(r"^## Last step[ \t]*$", text, re.M):
            text = re.sub(r"(^## Last step[ \t]*\n)(.*?)(?=^## |\Z)", lambda m: m.group(1) + last + "\n\n", text,
                          count=1, flags=re.M | re.S)
        else:
            text = text.rstrip("\n") + f"\n\n## Last step\n{last}\n"
        state.write_text(text, encoding="utf-8")
    from local_only import ensure  # noqa: E402
    try:
        ensure(root, ["/docs/project/journal.md"])
    except Exception:
        pass  # not a git checkout; nothing to keep out of commits
    print(f"recorded: {last}")
    print(f"Next ({nxt['who']}): {nxt['action']} · {nxt['why']}" if nxt else "Next: nothing")
    return 0


def main(argv):
    if not argv or argv[0].startswith("--"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if argv[0] == "record":
        if len(argv) < 2:
            print(__doc__.strip(), file=sys.stderr)
            return 2
        opts = {argv[i]: argv[i + 1] for i in range(2, len(argv) - 1) if argv[i] in ("--skill", "--arg", "--outcome")}
        if "--skill" not in opts or "--outcome" not in opts:
            print(__doc__.strip(), file=sys.stderr)
            return 2
        return record(argv[1], opts["--skill"], opts.get("--arg", ""), opts["--outcome"])
    s = status(argv[0])
    print(json.dumps(s, indent=2, ensure_ascii=False) if "--json" in argv else render(s))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
