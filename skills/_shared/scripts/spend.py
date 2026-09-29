#!/usr/bin/env python3
"""What a phase of work on a project has cost, against the owner's budget for it.

Usage:
  spend.py start <project> --phase <name> [--target <percent>] [--cap <percent>]
  spend.py status <project>                 the active phase's spend so far (exit 1 when it is over its cap)
  spend.py estimate <project>               what reading the sources not yet read would cost, before starting
  spend.py raise <project> --cap <percent> --quote "<the owner's words>" [--session <id> | --session codex:<id>]
  spend.py stop <project>                   close the phase and record its total
  spend.py calibrate <percent> <project> [--since <ISO time>]
                                            the owner's usage page showed <percent> of the week used by this
                                            project's spend since <time>: set the weekly allowance from it

Spend is counted in cost units, tokens weighted by their price: input 1, cache write 1.25, cache read 0.1,
output 5. It counts, from the phase's start: every Claude Code conversation working in the project (its
transcripts under $HOME/.claude/projects, the helpers it started included; a conversation started in a parent
folder counts when its working folder is inside the project) and every isolated run whose summary is under
the project's .evidence (their usage is recorded by run_isolated.py; an older summary without it is read from
its stream file). Codex conversations working in the project ($HOME/.codex/sessions) and Codex runs are shown
apart: Codex draws on a different allowance.

The weekly allowance and the defaults live in $HOME/.claude/.pipeline-budget.json (weekly_units, target_percent,
cap_percent). The default allowance was calibrated on 2026-09-29 from a real adoption: about 270 million units
of spend showed as about half of the week. A phase stays within its target (default 5 percent of the week)
and stops at its cap (default 10 percent): run_isolated.py refuses to start a run while the project's active
phase is over its cap, until the owner raises the cap in their own words, proven against their transcript.
The active phase is .evidence/spend/active.json; each closed phase is .evidence/spend/<phase>-<time>.json.
Exit 0 on success, 1 when over the cap (status) or on a failed step, 2 on bad usage.
"""
import datetime
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
WEIGHTS = {"input": 1.0, "cache_write": 1.25, "cache_read": 0.1, "output": 5.0}
DEFAULTS = {"weekly_units": 540_000_000, "target_percent": 5, "cap_percent": 10,
            "calibrated": "2026-09-29: about 270 million units showed as about half of the week"}
# Reading a source costs about this many units per token of source: an extraction read (the source as input,
# its load-bearing points as output), an audit read (the source and the units citing it), a share of re-audits,
# and the builder's own work on the dossier and the record.
UNITS_PER_SOURCE_TOKEN = 5.0


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def budget():
    f = Path.home() / ".claude/.pipeline-budget.json"
    data = dict(DEFAULTS)
    if f.is_file():
        try:
            data.update(json.loads(f.read_text()))
        except ValueError:
            pass
    return data


def units(u):
    return sum((u.get(k) or 0) * w for k, w in WEIGHTS.items())


def active_file(project):
    return Path(project) / ".evidence/spend/active.json"


def claude_folder_key(path):
    return re.sub(r"[^A-Za-z0-9-]", "-", str(path))


def transcript_usage(path, since, project):
    """Usage of one transcript's model calls at or after since, when it works in the project."""
    total = {k: 0 for k in WEIGHTS}
    inside = None
    seen = set()
    root = str(project)
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return total, False
    with f:
        for line in f:
            if '"usage"' not in line and '"cwd"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            cwd = e.get("cwd")
            if cwd and inside is None:
                inside = cwd == root or cwd.startswith(root + os.sep)
            if e.get("type") != "assistant":
                continue
            t = parse_time(e.get("timestamp"))
            if since and t and t < since:
                continue
            msg = e.get("message") or {}
            if msg.get("id") in seen:
                continue
            seen.add(msg.get("id"))
            u = msg.get("usage") or {}
            total["input"] += u.get("input_tokens", 0)
            total["cache_write"] += u.get("cache_creation_input_tokens", 0)
            total["cache_read"] += u.get("cache_read_input_tokens", 0)
            total["output"] += u.get("output_tokens", 0)
    return total, bool(inside)


def claude_sessions(project, since):
    """(usage, conversations counted) of the Claude Code conversations working in the project since the time."""
    base = Path.home() / ".claude/projects"
    total, count = {k: 0 for k in WEIGHTS}, 0
    own = base / claude_folder_key(Path(project))
    cutoff = since.timestamp() if since else 0
    for t in base.glob("*/*.jsonl") if base.is_dir() else []:
        if t.stat().st_mtime < cutoff:
            continue
        u, inside = transcript_usage(t, since, project)
        if t.parent != own and not inside:
            continue
        files = [t] + (sorted((t.parent / t.stem).rglob("*.jsonl")) if (t.parent / t.stem).is_dir() else [])
        for f in files[1:]:
            su, _ = transcript_usage(f, since, project)
            for k in total:
                u[k] += su[k]
        if units(u):
            count += 1
        for k in total:
            total[k] += u[k]
    return total, count


def stream_usage(stream):
    for line in reversed(stream.read_text(encoding="utf-8", errors="replace").splitlines()):
        if '"type":"result"' in line.replace(" ", ""):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            u = e.get("usage") or {}
            return {"input": u.get("input_tokens", 0), "cache_write": u.get("cache_creation_input_tokens", 0),
                    "cache_read": u.get("cache_read_input_tokens", 0), "output": u.get("output_tokens", 0)}
    return None


def isolated_runs(project, since):
    """(Claude usage, Codex usage, runs counted) of the isolated runs recorded under the project since the time."""
    claude, codex, n = {k: 0 for k in WEIGHTS}, {k: 0 for k in WEIGHTS}, 0
    cutoff = since.timestamp() if since else 0
    ev = Path(project) / ".evidence"
    for s in ev.rglob("*.summary.json") if ev.is_dir() else []:
        if s.stat().st_mtime < cutoff:
            continue
        try:
            d = json.loads(s.read_text())
        except (OSError, ValueError):
            continue
        u = d.get("usage")
        if u is None:
            stream = s.with_name(s.name.replace(".summary.json", ".jsonl"))
            u = stream_usage(stream) if stream.is_file() else None
        if not u:
            continue
        acc = codex if (d.get("family") == "codex" or u.get("family") == "codex") else claude
        for k in acc:
            acc[k] += u.get(k) or 0
        n += 1
    return claude, codex, n


def codex_sessions(project, since):
    """Usage of the Codex conversations working in the project since the time (their turns' token counts)."""
    total = {k: 0 for k in WEIGHTS}
    base = Path.home() / ".codex/sessions"
    cutoff = since.timestamp() if since else 0
    root = str(project)
    for t in base.rglob("rollout-*.jsonl") if base.is_dir() else []:
        if t.stat().st_mtime < cutoff:
            continue
        inside = None
        with open(t, encoding="utf-8", errors="replace") as f:
            for line in f:
                if inside is None and '"session_meta"' in line:
                    try:
                        cwd = (json.loads(line).get("payload") or {}).get("cwd") or ""
                    except ValueError:
                        cwd = ""
                    inside = cwd == root or cwd.startswith(root + os.sep)
                    if not inside:
                        break
                if '"token_count"' not in line or not inside:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                ts = parse_time(e.get("timestamp"))
                if since and ts and ts < since:
                    continue
                u = ((e.get("payload") or {}).get("info") or {}).get("last_token_usage") or {}
                cached = u.get("cached_input_tokens", 0)
                total["input"] += max(0, u.get("input_tokens", 0) - cached)
                total["cache_read"] += cached
                total["cache_write"] += u.get("cache_write_input_tokens", 0)
                total["output"] += u.get("output_tokens", 0)
    return total


def measure(project, since):
    s, conversations = claude_sessions(project, since)
    r, codex, runs = isolated_runs(project, since)
    return {"conversations": units(s), "isolated": units(r), "codex": units(codex) + units(codex_sessions(project, since)),
            "runs": runs, "conversation_count": conversations}


def cmd_start(project, opts):
    if not opts.get("--phase"):
        return usage()
    b = budget()
    f = active_file(project)
    if f.is_file():
        print(f"FAIL   spend       a phase is already active ({json.loads(f.read_text())['phase']}); stop it first")
        return 1
    f.parent.mkdir(parents=True, exist_ok=True)
    data = {"phase": opts["--phase"], "started": now(), "target_percent": float(opts.get("--target", b["target_percent"])),
            "cap_percent": float(opts.get("--cap", b["cap_percent"])), "raises": []}
    f.write_text(json.dumps(data, indent=2))
    print(f"spend: phase {data['phase']} started; target {data['target_percent']:g}% of the week, cap "
          f"{data['cap_percent']:g}% ({b['weekly_units'] * data['cap_percent'] / 100 / 1e6:.0f}M units)")
    return 0


def status(project):
    """(state dict, lines) of the active phase, or (None, reason)."""
    f = active_file(project)
    if not f.is_file():
        return None, ["no active phase (spend.py start)"]
    a = json.loads(f.read_text())
    m = measure(Path(project).resolve(), parse_time(a["started"]))
    b = budget()
    spent = m["conversations"] + m["isolated"]
    pct = 100 * spent / b["weekly_units"]
    state = {**a, **m, "spent": spent, "percent": pct, "over_target": pct > a["target_percent"],
             "over_cap": pct > a["cap_percent"]}
    lines = [f"phase {a['phase']} since {a['started']}: {spent / 1e6:.1f}M units = {pct:.1f}% of the week "
             f"(target {a['target_percent']:g}%, cap {a['cap_percent']:g}%)",
             f"  conversations {m['conversations'] / 1e6:.1f}M ({m['conversation_count']}) · isolated runs "
             f"{m['isolated'] / 1e6:.1f}M ({m['runs']})" + (f" · Codex {m['codex'] / 1e6:.1f}M (its own allowance)"
                                                          if m["codex"] else "")]
    if state["over_cap"]:
        lines.append("  OVER THE CAP: stop and tell the owner what is done, what remains, and what it would cost; "
                     "only the owner raises the cap (spend.py raise)")
    elif state["over_target"]:
        lines.append("  over the target: at the next stop, tell the owner the spend, what remains, and the estimate")
    return state, lines


def cmd_status(project):
    state, lines = status(project)
    for line in lines:
        print(line)
    return 1 if state and state["over_cap"] else 0


def source_tokens(project):
    """{source id: (role, tokens)} for the imported sources, by their transcripts' length."""
    out = {}
    root = Path(project) / "docs/project/sources"
    for meta in root.glob("SRC-*/meta.json") if root.is_dir() else []:
        try:
            m = json.loads(meta.read_text())
        except ValueError:
            continue
        t = meta.parent / "transcript.md"
        size = t.stat().st_size if t.is_file() else 0
        out[m.get("id", meta.parent.name)] = (m.get("kind", ""), size // 4)
    return out


def cmd_estimate(project):
    b = budget()
    srcs = source_tokens(project)
    reading = {k: v for k, v in srcs.items() if v[0] != "code"}
    tokens = sum(v[1] for v in reading.values())
    est = tokens * UNITS_PER_SOURCE_TOKEN
    pct = 100 * est / b["weekly_units"]
    print(f"estimate: {len(reading)} source(s) to read, about {tokens / 1e3:.0f}k tokens -> about {est / 1e6:.1f}M units "
          f"= {pct:.1f}% of the week (target {b['target_percent']:g}%, cap {b['cap_percent']:g}%)")
    if pct > b["target_percent"]:
        print("  above the target: tell the owner before starting, with what reading less would leave unread "
              "(the largest sources first), and let them choose")
    return 0


def cmd_raise(project, opts):
    f = active_file(project)
    if not f.is_file() or not opts.get("--cap") or not opts.get("--quote"):
        return usage()
    from rulings import resolve_transcript, find_quote
    from session_env import current
    session = opts.get("--session")
    if not session:
        tool, sid = current()
        session = f"codex:{sid}" if tool == "codex" else sid
    path = resolve_transcript(session) if session else None
    if not path or not find_quote(path, opts["--quote"]):
        print("FAIL   spend       the quote is not a whole sentence or message the owner typed in that session; "
              "only the owner raises a cap")
        return 1
    a = json.loads(f.read_text())
    a["raises"].append({"from": a["cap_percent"], "to": float(opts["--cap"]), "quote": opts["--quote"],
                        "session": session, "at": now()})
    a["cap_percent"] = float(opts["--cap"])
    f.write_text(json.dumps(a, indent=2))
    print(f"spend: cap raised to {a['cap_percent']:g}% on the owner's words")
    return 0


def cmd_stop(project):
    state, lines = status(project)
    if state is None:
        print(lines[0])
        return 1
    stamp = now().replace(":", "")
    out = active_file(project).with_name(f"{state['phase']}-{stamp}.json")
    out.write_text(json.dumps({**state, "stopped": now()}, indent=2))
    active_file(project).unlink()
    print(lines[0].replace("since", "closed; ran since"))
    return 0


def cmd_calibrate(argv):
    opts = parse(argv[2:])
    if len(argv) < 2:
        return usage()
    percent, project = float(argv[0]), Path(argv[1]).resolve()
    since = parse_time(opts.get("--since")) if opts.get("--since") else None
    m = measure(project, since)
    spent = m["conversations"] + m["isolated"]
    if not spent or percent <= 0:
        print("FAIL   spend       nothing measured to calibrate from")
        return 1
    f = Path.home() / ".claude/.pipeline-budget.json"
    data = budget()
    data["weekly_units"] = int(spent * 100 / percent)
    data["calibrated"] = f"{now()}: {spent / 1e6:.0f}M units of {project.name} showed as {percent:g}% of the week"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=2))
    print(f"spend: the week is about {data['weekly_units'] / 1e6:.0f}M units ({data['calibrated']})")
    return 0


def usage():
    print(__doc__.strip(), file=sys.stderr)
    return 2


def parse(argv):
    opts, i = {}, 0
    while i < len(argv):
        if argv[i].startswith("--") and i + 1 < len(argv):
            opts[argv[i]] = argv[i + 1]
            i += 2
        else:
            i += 1
    return opts


def main(argv):
    if not argv:
        return usage()
    cmd = argv[0]
    if cmd == "calibrate":
        return cmd_calibrate(argv[1:])
    if len(argv) < 2:
        return usage()
    project = Path(argv[1]).resolve()
    opts = parse(argv[2:])
    table = {"start": lambda: cmd_start(project, opts), "status": lambda: cmd_status(project),
             "estimate": lambda: cmd_estimate(project), "raise": lambda: cmd_raise(project, opts),
             "stop": lambda: cmd_stop(project)}
    return table[cmd]() if cmd in table else usage()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
