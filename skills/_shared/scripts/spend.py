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
  spend.py report <project> [--milestone M<k>] [--since <ISO time>] [--json]
                                            what the work cost, per milestone, round, and checker role; it
                                            reports and never caps

Spend is counted in cost units, tokens weighted by their price: input 1, cache write 1.25, cache read 0.1,
output 5. It counts, from the phase's start: every Claude Code conversation working in the project (its
transcripts under $HOME/.claude/projects, the helpers it started included; a conversation started in a parent
folder counts when its working folder is inside the project) and every isolated run whose summary is under
the project's .evidence (their usage is recorded by run_isolated.py; an older summary without it is read from
its stream file). Codex conversations working in the project ($HOME/.codex/sessions) and Codex runs are shown
apart: Codex draws on a different allowance.

Beside the units, every output gives the same spend in US dollars at list prices, by the model that served
each call (a transcript line's message.model; an isolated run's served model). Units stay model-blind, as the
allowance and its caps were calibrated in them; dollars show what moving work to another model saves. Prices
are per million tokens, as of 2026-10-06:
  claude-opus-5-5     input 4.00   cache write 5.00    cache read 0.20   output 20.00
  claude-sonnet-5-5   input 2.00   cache write 2.50    cache read 0.20   output 10.00
  claude-haiku-5-5    input 0.10   cache write 0.125   cache read 0.01   output 0.50
Haiku's cache prices are assumed at 1.25 and 0.1 times its input price. Haiku's higher price for prompts over
100K tokens is ignored: usage is summed per call or per run, so the size of each prompt is not known. A model
id that is missing or not in the table is priced as claude-opus-5-5 (never as free) and counted as
unpriced_model, with its ids named. Codex usage is never priced.

report sums every isolated run summary under the project's .evidence (gate and loyal rounds, the dev
understanding check, plan cold reads, capture, scout, and any other folder), grouped by milestone, round, and
role (the summary's file name: code-verifier, code-verifier-demo, loyal-evaluator-pass2, ...; a shadow run,
whose summary sits in a folder named shadow, is "<role> (shadow)", so its cost shows apart), with units,
dollars, tokens by type, the served models, and the cache-read share (cache reads over all input tokens:
input, cache writes, and cache reads). It adds the Claude Code conversations in the project over the same
window, and Codex apart. The window starts at --since, or, with --milestone M<k>, when that milestone's
baseline was recorded (the time .evidence/baseline-M<k>.txt was written by baseline.py record); one of the
two is required. --milestone keeps the runs of that milestone and the runs of no milestone (plan, dev,
capture) in the window; runs of other milestones are left out. --json prints everything as JSON.

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
# List prices in US dollars per million tokens, as of 2026-10-06 (see the module text for Haiku's assumptions).
PRICES = {
    "claude-opus-5-5": {"input": 4.00, "cache_write": 5.00, "cache_read": 0.20, "output": 20.00},
    "claude-sonnet-5-5": {"input": 2.00, "cache_write": 2.50, "cache_read": 0.20, "output": 10.00},
    "claude-haiku-5-5": {"input": 0.10, "cache_write": 0.125, "cache_read": 0.01, "output": 0.50},
}
PRICED_AS = "claude-opus-5-5"  # an unknown or missing model is priced as the dearest, never as free
CODEX = "codex"  # usage keyed by this name, or by "codex:<model>", is Codex's: shown apart, never priced
# Reading a source costs about this many units per token of source: an extraction read (the source as input,
# its load-bearing points as output), an audit read (the source and the units citing it), a share of re-audits,
# and the builder's own work on the dossier and the record.
UNITS_PER_SOURCE_TOKEN = 5.0


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def is_codex(model):
    return str(model or "") == CODEX or str(model or "").startswith(CODEX + ":")


def model_key(model):
    """The price table's name for a served model id: a context-window suffix ("[1m]") and a date suffix dropped."""
    m = re.sub(r"\[[^\]]*\]$", "", str(model or "")).strip()
    return re.sub(r"-\d{8}$", "", m)


def dollars(model, u):
    """(US dollars, priced): one usage's tokens at the list price of the model that served them; a model that is
    missing or not in the table at claude-opus-5-5's price, with priced False."""
    rate = PRICES.get(model_key(model))
    return sum((u.get(k) or 0) * (rate or PRICES[PRICED_AS])[k] for k in WEIGHTS) / 1e6, rate is not None


def tally_add(tally, model, u, entries=1):
    """Add usage (input, cache_write, cache_read, output) to a tally of {model: tokens by type and entries}."""
    t = tally.setdefault(model or "", {**{k: 0 for k in WEIGHTS}, "entries": 0})
    for k in WEIGHTS:
        t[k] += u.get(k) or 0
    t["entries"] += entries


def tally_merge(into, other):
    for model, t in other.items():
        tally_add(into, model, t, t.get("entries", 1))
    return into


def tokens(tally):
    """The tally's tokens by type, every model together."""
    out = {k: 0 for k in WEIGHTS}
    for t in tally.values():
        for k in WEIGHTS:
            out[k] += t.get(k) or 0
    return out


def tally_price(tally):
    """(dollars, unpriced entries, unpriced model ids) of a tally; Codex usage in it is left out (never priced)."""
    usd, unpriced, ids = 0.0, 0, set()
    for model, t in tally.items():
        if is_codex(model):
            continue
        d, known = dollars(model, t)
        usd += d
        if not known and any(t.get(k) for k in WEIGHTS):
            unpriced += t.get("entries", 1)
            ids.add(model or "missing")
    return usd, unpriced, sorted(ids)


def cache_share(tok):
    """Cache reads over every input token (input, cache writes, cache reads); None when there were none."""
    total = (tok.get("input") or 0) + (tok.get("cache_write") or 0) + (tok.get("cache_read") or 0)
    return (tok.get("cache_read") or 0) / total if total else None


def active_file(project):
    return Path(project) / ".evidence/spend/active.json"


def claude_folder_key(path):
    return re.sub(r"[^A-Za-z0-9-]", "-", str(path))


def transcript_usage(path, since, project):
    """(usage by model, works in the project) of one transcript's model calls at or after since."""
    tally = {}
    inside = None
    seen = set()
    root = str(project)
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return tally, False
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
            tally_add(tally, msg.get("model"), {"input": u.get("input_tokens", 0),
                                                "cache_write": u.get("cache_creation_input_tokens", 0),
                                                "cache_read": u.get("cache_read_input_tokens", 0),
                                                "output": u.get("output_tokens", 0)})
    return tally, bool(inside)


def claude_sessions(project, since):
    """(usage by model, conversations counted) of the Claude Code conversations working in the project since the
    time."""
    base = Path.home() / ".claude/projects"
    total, count = {}, 0
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
            tally_merge(u, transcript_usage(f, since, project)[0])
        if units(tokens(u)):
            count += 1
        tally_merge(total, u)
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


def stream_model(stream):
    """The model a stream's session started on (its init event), or None."""
    for line in stream.read_text(encoding="utf-8", errors="replace").splitlines():
        if '"init"' in line:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") == "system" and e.get("subtype") == "init":
                return e.get("model")
    return None


def run_summaries(project, since=None):
    """Every isolated run recorded under the project's .evidence since the time: its summary's place, role, family,
    served model, and usage (None when neither the summary nor its stream holds any)."""
    cutoff = since.timestamp() if since else 0
    ev = Path(project) / ".evidence"
    for s in sorted(ev.rglob("*.summary.json")) if ev.is_dir() else []:
        try:
            mtime = s.stat().st_mtime
            if mtime < cutoff:
                continue
            d = json.loads(s.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        u, model = d.get("usage"), d.get("served_model") or d.get("model")
        stream = s.with_name(s.name.replace(".summary.json", ".jsonl"))
        if u is None and stream.is_file():
            u = stream_usage(stream)
        if not model and u and stream.is_file():
            model = stream_model(stream)
        codex = d.get("family") == "codex" or (isinstance(u, dict) and u.get("family") == "codex")
        role = s.name[:-len(".summary.json")] + (" (shadow)" if s.parent.name == "shadow" else "")
        yield {"path": s.relative_to(ev).as_posix(), "written": mtime, "role": role,
               "status": d.get("status"), "codex": codex, "model": model, "usage": u or None}


def isolated_runs(project, since):
    """(Claude usage by model, Codex usage by model, runs counted) of the isolated runs recorded under the project
    since the time."""
    claude, codex, n = {}, {}, 0
    for r in run_summaries(project, since):
        if not r["usage"]:
            continue
        tally_add(codex if r["codex"] else claude, r["model"], r["usage"])
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
    s_usd, s_unpriced, s_ids = tally_price(s)
    r_usd, r_unpriced, r_ids = tally_price(r)
    return {"conversations": units(tokens(s)), "isolated": units(tokens(r)),
            "codex": units(tokens(codex)) + units(codex_sessions(project, since)),
            "runs": runs, "conversation_count": conversations,
            "dollars": {"conversations": s_usd, "isolated": r_usd},
            "unpriced_model": s_unpriced + r_unpriced, "unpriced_models": sorted(set(s_ids) | set(r_ids))}


def usd(x):
    return f"${x:,.2f}"


def unpriced_line(n, ids):
    return (f"  unpriced_model: {n} usage entr{'y' if n == 1 else 'ies'} had a model the price table does not know "
            f"({', '.join(ids)}); priced as {PRICED_AS}") if n else None


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
    spent_usd = m["dollars"]["conversations"] + m["dollars"]["isolated"]
    pct = 100 * spent / b["weekly_units"]
    state = {**a, **m, "spent": spent, "spent_dollars": spent_usd, "percent": pct,
             "over_target": pct > a["target_percent"], "over_cap": pct > a["cap_percent"]}
    lines = [f"phase {a['phase']} since {a['started']}: {spent / 1e6:.1f}M units = {pct:.1f}% of the week "
             f"(target {a['target_percent']:g}%, cap {a['cap_percent']:g}%); {usd(spent_usd)} at list prices",
             f"  conversations {m['conversations'] / 1e6:.1f}M ({m['conversation_count']}, "
             f"{usd(m['dollars']['conversations'])}) · isolated runs {m['isolated'] / 1e6:.1f}M ({m['runs']}, "
             f"{usd(m['dollars']['isolated'])})" + (f" · Codex {m['codex'] / 1e6:.1f}M (its own allowance)"
                                                    if m["codex"] else "")]
    if unpriced_line(m["unpriced_model"], m["unpriced_models"]):
        lines.append(unpriced_line(m["unpriced_model"], m["unpriced_models"]))
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
    tokens_ = sum(v[1] for v in reading.values())
    est = tokens_ * UNITS_PER_SOURCE_TOKEN
    pct = 100 * est / b["weekly_units"]
    print(f"estimate: {len(reading)} source(s) to read, about {tokens_ / 1e3:.0f}k tokens -> about {est / 1e6:.1f}M units "
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


# ---------- report ----------

def run_place(rel):
    """(area, milestone, round) of a run from its summary's path under .evidence: gate/M2/r1/x -> (gate, M2, r1);
    plan-r2/x -> (plan, -, r2); capture/extract-3/x -> (capture, -, -)."""
    parts = rel.split("/")[:-1]
    area, rnd = (parts[0] if parts else "-"), "-"
    m = re.match(r"^(.+)-(r\d+)$", area)
    if m:
        area, rnd = m.group(1), m.group(2)
    milestone = next((p for p in parts if re.match(r"^M\d+$", p)), "-")
    rnd = next((p for p in parts[1:] if re.match(r"^r\d+$", p)), rnd)
    return area, milestone, rnd


def figures(tally, runs=None):
    """Units, dollars, tokens by type, served models, and cache-read share of a Claude tally."""
    tok = tokens(tally)
    d, unpriced, ids = tally_price(tally)
    out = {"units": units(tok), "dollars": d, "tokens": tok,
           "models": sorted(m or "missing" for m, t in tally.items() if any(t.get(k) for k in WEIGHTS)),
           "cache_read_share": cache_share(tok), "unpriced_model": unpriced, "unpriced_models": ids}
    if runs is not None:
        out["runs"] = runs
    return out


def order(key):
    num = lambda s: (0, int(s[1:])) if re.match(r"^[Mr]\d+$", s) else (1 if s == "-" else 0, s)
    return (num(key[0]), key[1], num(key[2]), key[3])


def report(project, milestone, since):
    """Every cost in the window, grouped (see the module text)."""
    groups, iso_claude, iso_codex, runs, codex_runs, bare = {}, {}, {}, 0, 0, 0
    for r in run_summaries(project, since):
        area, ms, rnd = run_place(r["path"])
        if milestone and ms not in (milestone, "-"):
            continue
        if not r["usage"]:
            bare += 1
            continue
        g = groups.setdefault((ms, area, rnd, r["role"]), {"claude": {}, "codex": {}, "runs": 0})
        g["runs"] += 1
        key = r["model"] or ""
        tally_add(g["codex" if r["codex"] else "claude"], key, r["usage"])
        tally_add(iso_codex if r["codex"] else iso_claude, key, r["usage"])
        runs += not r["codex"]
        codex_runs += r["codex"]
    rows = []
    for key in sorted(groups, key=order):
        g = groups[key]
        row = {"milestone": key[0], "area": key[1], "round": key[2], "role": key[3], **figures(g["claude"], g["runs"])}
        if g["codex"]:
            row["codex_tokens"] = tokens(g["codex"])
            row["models"] = sorted(set(row["models"]) | {f"codex:{m}" if m else "codex" for m in g["codex"]})
        rows.append(row)
    sessions, count = claude_sessions(project, since)
    cx_sessions = codex_sessions(project, since)
    total = tally_merge(tally_merge({}, iso_claude), sessions)
    return {"project": str(project), "milestone": milestone, "since": iso(since.timestamp()), "groups": rows,
            "isolated": figures(iso_claude, runs), "isolated_without_usage": bare,
            "sessions": {**figures(sessions), "conversations": count},
            "codex": {"runs": codex_runs, "run_tokens": tokens(iso_codex), "session_tokens": cx_sessions,
                      "note": "Codex draws on its own allowance; never priced"},
            "total": figures(total), "unpriced_model": tally_price(total)[1], "unpriced_models": tally_price(total)[2]}


def amount(n):
    return f"{n / 1e6:.1f}M" if n >= 1e5 else f"{n / 1e3:.1f}k" if n else "0"


def share(x):
    return f"{100 * x:.0f}%" if x is not None else "-"


def print_report(rep, since_from):
    print(f"spend report · {rep['project']}" + (f" · {rep['milestone']}" if rep["milestone"] else "") +
          f" · since {rep['since']} ({since_from}) · dollars at list prices")
    head = ("milestone", "area", "round", "role", "runs", "units", "dollars", "input", "c.write", "c.read", "output",
            "c.read%", "models")
    fmt = "{:<9} {:<8} {:<5} {:<28} {:>4} {:>8} {:>10} {:>8} {:>8} {:>8} {:>8} {:>7}  {}"
    print(fmt.format(*head))
    for r in rep["groups"]:
        t = r["tokens"]
        print(fmt.format(r["milestone"], r["area"], r["round"], r["role"][:28], r["runs"], amount(r["units"]),
                         usd(r["dollars"]), amount(t["input"]), amount(t["cache_write"]), amount(t["cache_read"]),
                         amount(t["output"]), share(r["cache_read_share"]), ", ".join(r["models"])))
    if not rep["groups"]:
        print("(no isolated run with recorded usage in the window)")
    i, s, c, tot = rep["isolated"], rep["sessions"], rep["codex"], rep["total"]
    print(f"isolated runs: {i['runs']} Claude run(s), {amount(i['units'])} units, {usd(i['dollars'])}, cache reads "
          f"{share(i['cache_read_share'])}" + (f"; {rep['isolated_without_usage']} run(s) recorded no usage (no model "
                                               f"call was made, or the run stopped before one)"
                                               if rep["isolated_without_usage"] else ""))
    print(f"sessions: {s['conversations']} Claude Code conversation(s), {amount(s['units'])} units, {usd(s['dollars'])}, "
          f"cache reads {share(s['cache_read_share'])}, models {', '.join(s['models']) or 'none'}")
    codex_total = sum(c["run_tokens"].values()) + sum(c["session_tokens"].values())
    if codex_total:
        print(f"Codex (its own allowance, not priced): {c['runs']} run(s), {amount(codex_total)} tokens")
    print(f"total: {amount(tot['units'])} units, {usd(tot['dollars'])}")
    line = unpriced_line(rep["unpriced_model"], rep["unpriced_models"])
    if line:
        print(line.strip())


def cmd_report(project, argv):
    opts = parse([a for a in argv if a != "--json"])
    milestone = opts.get("--milestone")
    if milestone is not None and not re.match(r"^M\d+$", milestone):
        print(f"spend report: --milestone takes M<k>, not {milestone!r}", file=sys.stderr)
        return 2
    try:
        since = parse_time(opts.get("--since")) if opts.get("--since") else None
    except ValueError:
        print(f"spend report: --since takes an ISO time such as 2026-10-01T09:00:00Z, not {opts['--since']!r}",
              file=sys.stderr)
        return 2
    if since and since.tzinfo is None:
        since = since.replace(tzinfo=datetime.timezone.utc)
    since_from = "--since"
    if since is None and milestone:
        baseline = Path(project) / f".evidence/baseline-{milestone}.txt"
        if not baseline.is_file():
            print(f"spend report: {milestone} has no recorded baseline ({baseline} is missing), so its start is not "
                  f"known; pass --since <ISO time>", file=sys.stderr)
            return 2
        since = datetime.datetime.fromtimestamp(baseline.stat().st_mtime, datetime.timezone.utc)
        since_from = f"when {milestone}'s baseline was recorded"
    if since is None:
        print("spend report: give the window: --milestone M<k> (from when its baseline was recorded) or --since "
              "<ISO time> (--since 1970-01-01T00:00:00Z counts everything)", file=sys.stderr)
        return 2
    rep = report(Path(project), milestone, since)
    if "--json" in argv:
        print(json.dumps({**rep, "since_from": since_from}, indent=2))
    else:
        print_report(rep, since_from)
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
             "stop": lambda: cmd_stop(project), "report": lambda: cmd_report(project, argv[2:])}
    return table[cmd]() if cmd in table else usage()


if __name__ == "__main__":
    if "--help" in sys.argv[1:3] or sys.argv[1:] == ["-h"]:
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
