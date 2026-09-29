#!/usr/bin/env python3
"""The pipeline's own improvement loop: harvest what went wrong in a session, prove each problem with a
reproduction, fix it, and keep a fix only when a rule fixed in advance says the pipeline got better.

Usage:
  evolve.py harvest [--transcript <path> | --session <id> | --session codex:<id>] [--project <dir>]
  evolve.py new-incident --title "<title>" --kind <kind> --where "<pipeline part>" --signature "<key>"
                         [--harvest <dir> --candidate <n> [--candidate <n> ...]]
  evolve.py similar "<signature or words>"
  evolve.py touchmap <base ref> <head ref>
  evolve.py bench <ref> --suites "<suite>;<suite>" [--instrument <ref>] [--runs 3] [--again]
  evolve.py compare <base ref> <head ref> --suites "<suite>;<suite>" [--instrument <ref>] [--out <file>]
  evolve.py new-change --title "<title>" --incidents INC-0001[,INC-0002] --kind fix|doc|capability|rule-change
  evolve.py review CHG-0001
  evolve.py record CHG-0001
  evolve.py check
  evolve.py status

The ledger holds details of the owner's projects, so it lives outside the pipeline repository:
$PIPELINE_EVOLUTION_HOME, default $HOME/.claude/pipeline-evolution/ (one ledger for Claude Code and Codex)
  harvests/<date>-<session>/candidates.{json,md}  what a session's record shows, for the model to judge
  incidents/INC-<nnnn>.md                         one problem each, with its evidence and occurrences
  changes/CHG-<nnnn>.md (+ CHG-<nnnn>-review/)    one improvement each, with its proof
  benchmarks/<commit>/<suite>__<instrument>__<environment>.json   every measurement, kept and reused
The repository is $PIPELINE_REPO, else the "repo" that install.py records in $HOME/.claude/.pipeline-install.json.

harvest reads a Claude Code or Codex transcript (the whole session, compacted parts included) without model
tokens and lists candidates. From running the pipeline's own scripts, hooks, skills, and checkers (never from
reading files, and never a project's own failing build): failed commands, status lines (FAIL, BLOCKED,
INCONCLUSIVE, NOT_RUN, ERROR, BROKEN, STALE, LEAK, UNAVAILABLE; one run's lines of one level are one event),
tracebacks, timeouts, and a failing command run again unchanged. From anywhere: hook blocks, tool calls the
owner refused, compactions, and the owner's messages that push back. Plus the skills used and, with
--project, the project's recorded failures, blockers, and inconclusive gate rounds. Candidates are grouped
by a signature that stays the same when a problem recurs. A signature equal to a known incident's adds an
occurrence to it (once per transcript); one equal to a fixed incident's is flagged as a REGRESSION.

Suites (bench, compare):
  selftest                   the ref's own tests/pipeline-selftest.sh, plus the number of tests in each file
  fixtures:<prefix>[,...]    checker and probe fixtures (tests/agent_fixtures.py), --runs per fixture
  scenario:<name>[,...]      headless sessions on toy projects (tests/system_scenarios.py) against the
                             installed pipeline, measured only when the installed revision is exactly the ref
  test:<tests/file.py>[::<Class.test>]   one test file or test
  repro:<fixtures:...|scenario:...|test:...>   the same, marked as the reproduction of the incidents
Fixture, scenario, and test suites run with the tests/ folder of the instrument ref (default: the ref itself),
so both sides of a comparison are measured by the same instrument and only the pipeline differs. selftest
runs each ref's own tests. Every result carries the environment (Claude Code, Codex, Python, OS, and the
models the checkers ran on); a measurement already stored for the same commit, suite, instrument, and
environment is reused, never repeated; --again adds another measurement of the same size (pooled).

compare applies this rule, never judgment:
  INCOMPARABLE  a suite not measured on one side; for fixtures and scenarios no pair of measurements taken in
                the same environment, or a different number of runs
  WORSE         a selftest suite that passed now fails or is missing, or any selftest suite fails at head; a
                test file with fewer tests than before; a fixture passing a smaller share of its runs, or
                costing more than a quarter more per run (cost units, spend.py); a scenario or a
                non-reproduction test that passed now fails
  reproduction  a test must fail at base (an assertion, or the code under test raising) and pass at head; a
                test that needs a name only the change adds (an import or name error) cannot show the problem
                and does not count; a fixture must fail at least one run at base and pass every run at head;
                a scenario must fail at base and pass at head; repro:cost:fixtures:<prefix> (a change made to
                spend less) must cut the fixture's cost per run by a fifth or more and pass at least as often
  BETTER        nothing incomparable or worse, at least one reproduction, and every reproduction flipped
  SAME          otherwise, with the reason (not an improvement)

record refuses a change missing any part of its proof: existing incidents, a reproduction, two or more options
with the session's own workaround weighed among them, a BETTER comparison recomputed from the stored
measurements at the branch's current commit, an acceptance computed from the isolated change reviewer's
fields for that same commit (cause fixed, reproduction faithful, the workaround weighed, no check weakened,
the kind confirmed, no high or medium finding), and, for a capability or rule change, the owner's words
proven in their transcript. check proves the whole ledger, including that every fixed incident's change reached main.
Exit 0 on success, 1 on a failed check or a verdict other than BETTER, 2 on bad usage.
"""
import datetime
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
HOME = Path(os.environ.get("PIPELINE_EVOLUTION_HOME") or Path.home() / ".claude/pipeline-evolution")
INSTALL_MANIFEST = Path(os.environ.get("PIPELINE_INSTALL_MANIFEST") or Path.home() / ".claude/.pipeline-install.json")
KINDS = ("defect", "doc-gap", "friction", "missing-capability", "environment", "not-pipeline")
CHANGE_KINDS = ("fix", "doc", "capability", "rule-change")
OWNER_KINDS = ("capability", "rule-change")
STATUSES = ("open", "confirmed", "not-reproduced", "environment", "not-pipeline", "duplicate", "fixed", "resolved",
            "reopened")
STATUS_LINE = re.compile(r"^(FAIL|BLOCKED|INCONCLUSIVE|NOT_RUN|ERROR|BROKEN|STALE|LEAK|UNAVAILABLE)\s{2,}(\S+)\s+(.*)$", re.M)
VERDICT_WORD = re.compile(r"\b(?:verdict|status)\W{1,4}(INCONCLUSIVE|ERROR|NOT_RUN|BLOCKED|UNAVAILABLE|LEAK)\b")
NOISE_LINE = re.compile(r"^(Exit code:? -?\d+|Error:?|Script (completed|failed)|Wall time.*|Output:|Process exited.*|"
                        r"[\[\]{}(),:;\"'`-]+)$")
# Pushback, in English and in Chinese (wrong, not right, why, again, still not, stop doing, useless, a problem,
# stuck).
PUSHBACK = re.compile(r"(\u4e0d\u5bf9|\u9519\u4e86|\u4e3a\u4ec0\u4e48|\u600e\u4e48\u53c8|\u8fd8\u662f\u4e0d|"
                      r"\u522b\u518d|\u6ca1\u7528|\u6709\u95ee\u9898|\u5361\u4f4f|\bwrong\b|\bwhy\b|\bstill\b|\bagain\b|"
                      r"doesn'?t work|not working|\bbroken\b|\bstuck\b|\binstead\b)", re.I)
REFUSED = ("The user doesn't want to proceed", "Permission to use", "The tool use was rejected")
# A result counts only when it comes from running something that belongs to the pipeline: its scripts, hooks,
# skills, checkers, or gate. Reading a file that merely contains "FAIL" is not an event, and a project's own
# failing build is the project's business.
PIPELINE = re.compile(r"\.claude/(skills|hooks|agents)/|\.agents/skills/|\.codex/agent-prompts/|skills/_shared/|\bhooks/[\w-]+\.(py|sh)|\bgate\.sh\b|"
                      r"\b(run_isolated|gate_run|gate_report|gate_copies|project_status|continuity|capture|adopt|inbox|"
                      r"rulings|render_pack|record_check|milestone_lint|intent_lock|handoff_check|heavy|evolve|browse|"
                      r"baseline|closure|inventory|fingerprint|local_only)\.py\b|heavy-guard|reload-gate|typecheck-once")
READ_ONLY_TOOLS = ("Read", "Grep", "Glob", "WebFetch", "WebSearch", "NotebookRead")
READ_ONLY_COMMAND = re.compile(r"^\s*(cat|sed|grep|egrep|rg|head|tail|less|wc|ls|find|file|stat|diff|git (show|log|diff|"
                               r"status|blame|grep)|python3? -c|jq)\b")
MAX_EXCERPT = 500


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def usage():
    print(__doc__.strip(), file=sys.stderr)
    return 2


def fail(msg):
    print(f"FAIL   evolve      {msg}")
    return 1


def repo():
    env = os.environ.get("PIPELINE_REPO")
    if env:
        return Path(env)
    if INSTALL_MANIFEST.is_file():
        r = json.loads(INSTALL_MANIFEST.read_text()).get("repo")
        if r:
            return Path(r)
    if (HERE.parents[2] / ".git").exists():
        return HERE.parents[2]
    raise SystemExit("FAIL   evolve      the pipeline repository is unknown; run install.py apply from it or set PIPELINE_REPO")


def git(*args):
    r = subprocess.run(["git", "-C", str(repo()), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def sha_of(ref):
    return git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") if ref else ""


def clip(text, n=MAX_EXCERPT):
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return text if len(text) <= n else text[: n // 2] + "\n...\n" + text[-n // 2:]


def first_meaningful(text):
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not NOISE_LINE.match(line):
            return line
    return (text or "").strip()[:200]


def signature(kind, text):
    """A key that stays the same when the same problem recurs: paths, ids, numbers, and quoted values reduced."""
    t = first_meaningful(text)
    t = re.sub(r"(~|\.{0,2})?(/[\w.@+-]+)+/?", "<path>", t)
    t = re.sub(r"\b[0-9a-f]{7,}\b", "<id>", t)
    t = re.sub(r"\d+", "<n>", t)
    t = re.sub(r"\"[^\"]*\"|'[^']*'|`[^`]*`", "<q>", t)
    return f"{kind}: " + re.sub(r"\s+", " ", t).strip()[:160]


# ---------- harvest ----------

def texts_of(content):
    if isinstance(content, str):
        return [content]
    out = []
    for c in content or []:
        if isinstance(c, dict):
            if isinstance(c.get("text"), str):
                out.append(c["text"])
            elif isinstance(c.get("content"), (str, list)):
                out += texts_of(c["content"])
    return out


def cand(kind, at, where, excerpt, ctx="", key=None):
    """One signal. The key is what its signature is made of (the excerpt when none is given)."""
    return {"kind": kind, "at": at, "where": where, "excerpt": clip(excerpt), "context": clip(ctx or "", 240),
            "key": key if key is not None else excerpt}


def script_of(ctx):
    """The pipeline script or hook a command ran (its file name), for signatures that name the culprit."""
    ctx = ctx or ""
    if not PIPELINE.search(ctx):
        return ""
    m = re.search(r"(?:scripts|hooks|_shared)/([\w-]+\.(?:py|sh))\b", ctx)
    return m.group(1) if m else re.sub(r".*/", "", PIPELINE.search(ctx).group(0).rstrip("/"))


def scan_text(text, at, where, ctx, cands):
    """Add the signals in one tool result; return how many were added. One run's status lines of one level are
    one event (a check printing twenty FAIL lines failed once)."""
    before = len(cands)
    by_level = {}
    for m in STATUS_LINE.finditer(text):
        by_level.setdefault(m.group(1), []).append(m)
    for level, ms in by_level.items():
        names = sorted({re.sub(r"(/[\w.@+-]+)+|[\w.-]+/[\w./-]+|:\d+", "<path>", m.group(2)) for m in ms})
        head = " ".join(ms[0].group(3).split(": ")[0].split()[:8])
        excerpt = "\n".join(m.group(0) for m in ms)
        cands.append(cand(f"status-{level.lower()}", at, where, (f"{len(ms)} lines:\n" if len(ms) > 1 else "") + excerpt,
                          ctx, key=f"{script_of(ctx)} {' '.join(names)[:80]} {head}"))
    for m in VERDICT_WORD.finditer(text):
        start = text.rfind("\n", 0, m.start()) + 1
        start = text.rfind("\n", 0, max(0, start - 1)) + 1
        end = text.find("\n", m.end())
        cands.append(cand(f"verdict-{m.group(1).lower()}", at, where, text[start:end if end >= 0 else len(text)], ctx,
                          key=f"{script_of(ctx)} {m.group(1)}"))
    if "Traceback (most recent call last)" in text:
        tail = text[text.rindex("Traceback (most recent call last)"):]
        lines = [l for l in tail.splitlines() if l.strip()]
        exc = next((l for l in reversed(lines) if re.match(r"^\s*[\w.]*(Error|Exception|Exit|Interrupt)\b", l)), lines[-1])
        cands.append(cand("traceback", at, where, exc + "\n" + clip(tail, 700), ctx, key=f"{script_of(ctx)} {exc}"))
    if re.search(r"timed out|TimeoutExpired|\bexit(?: code)?:? 124\b", text):
        line = next((l for l in text.splitlines() if re.search(r"timed out|TimeoutExpired|124", l)), text)
        cands.append(cand("timeout", at, where, line, ctx, key=f"{script_of(ctx)} {first_meaningful(line)}"))
    return len(cands) - before


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def codex_command(raw):
    """The shell command inside a Codex tool call (an exec script, JSON arguments, or an argv list)."""
    raw = as_obj(raw)
    if isinstance(raw, dict):
        raw = raw.get("cmd") or raw.get("command") or json.dumps(raw)
    if isinstance(raw, list):
        raw = " ".join(str(x) for x in raw)
    raw = str(raw or "")
    m = re.search(r"\bcmd\s*:\s*\"((?:[^\"\\]|\\.)*)\"", raw)
    if m:
        raw = m.group(1).encode().decode("unicode_escape", errors="replace")
    raw = re.sub(r"^\s*(/bin/)?(ba|z)?sh\s+-\w*c\s+", "", raw).strip().strip("'\"")
    return re.sub(r"\s+", " ", raw).strip()


def as_obj(v):
    """Codex nests some records as JSON text; read them when they are."""
    if isinstance(v, str) and v[:1] in "{[":
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def scan_transcript(lines):
    """(candidates, skills used) from a Claude Code or Codex transcript (its JSON lines)."""
    from rulings import typed_in_lines
    cands, tool_inputs, failed, skills, codex_calls = [], {}, {}, [], {}
    for n, line in enumerate(lines, 1):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("isSidechain"):
            continue
        where, at = e.get("uuid") or f"line {n}", e.get("timestamp", "")
        if e.get("isCompactSummary") or e.get("type") == "compacted":
            cands.append(cand("compaction", at, where, "the conversation was compacted"))
            continue
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        content = msg.get("content")
        if e.get("type") == "assistant" and isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    inp = c.get("input") if isinstance(c.get("input"), dict) else {}
                    tool_inputs[c.get("id")] = (c.get("name"), inp)
                    if c.get("name") == "Skill" and inp.get("skill"):
                        skills.append(inp["skill"])
        if e.get("type") == "user":
            if isinstance(content, str):
                m = re.search(r"<command-name>/?([\w:-]+)</command-name>", content)
                if m:
                    skills.append(m.group(1))
            for c in content if isinstance(content, list) else []:
                if not isinstance(c, dict) or c.get("type") != "tool_result":
                    continue
                text = "\n".join(texts_of(c.get("content")))
                name, inp = tool_inputs.get(c.get("tool_use_id")) or ("", {})
                ctx = json.dumps(inp, ensure_ascii=False)
                reading = name in READ_ONLY_TOOLS or bool(READ_ONLY_COMMAND.match(str(inp.get("command") or "")))
                ours = bool(PIPELINE.search(ctx)) or bool(PIPELINE.search(text[:4000]))
                specific = scan_text(text, at, where, ctx, cands) if ours and not reading else 0
                if c.get("is_error"):
                    body = [l for l in text.splitlines() if l.strip() and not NOISE_LINE.match(l.strip())]
                    if text.lstrip().startswith(REFUSED):
                        cands.append(cand("tool-refused", at, where, text, ctx))
                    elif re.search(r"hook\b.*\b(error|denied|blocked)|\bBlocked:|\bdenied\b", text, re.I):
                        cands.append(cand("hook-block", at, where, text, ctx))
                    elif body and ours and not reading and not specific:
                        cands.append(cand("tool-error", at, where, text, ctx))
                    if ours and isinstance(inp.get("command"), str):
                        failed.setdefault(re.sub(r"\s+", " ", inp["command"]).strip(), []).append(where)
        # Codex rollouts
        payload = e.get("payload") if isinstance(e.get("payload"), dict) else None
        if payload:
            ptype = payload.get("type")
            if ptype in ("custom_tool_call", "function_call"):
                codex_calls[payload.get("call_id")] = codex_command(payload.get("input") or payload.get("arguments") or "")
            if ptype in ("custom_tool_call_output", "function_call_output"):
                out = as_obj(payload.get("output"))
                text = "\n".join(texts_of(out)) if isinstance(out, list) else str(out or "")
                cmd = codex_calls.get(payload.get("call_id"), "")
                if (PIPELINE.search(cmd) or PIPELINE.search(text[:4000])) and not READ_ONLY_COMMAND.match(cmd):
                    scan_text(text, at, where, cmd, cands)
            if e.get("type") == "event_msg" and ptype == "error":
                cands.append(cand("tool-error", at, where, payload.get("message") or json.dumps(payload)))
            for d in walk({k: as_obj(v) for k, v in payload.items()}):
                code = d.get("exit_code")
                if isinstance(code, int) and code != 0:
                    out = d.get("aggregated_output") or d.get("formatted_output") or \
                        (d.get("stdout") or "") + (d.get("stderr") or "")
                    cmd = codex_command(d.get("command"))
                    ours = PIPELINE.search(cmd) or PIPELINE.search(str(out)[:4000])
                    if first_meaningful(out) and ours and not READ_ONLY_COMMAND.match(cmd):
                        cands.append(cand("tool-error", at, where, f"exit {code}: {out}", cmd, key=first_meaningful(out)))
                        failed.setdefault(cmd, []).append(where)
    # The same failing command run again unchanged: the session was stuck or retrying blind.
    for cmd, wheres in failed.items():
        if cmd and len(wheres) >= 2:
            cands.append(cand("retried-failure", "", ", ".join(wheres[:4]), f"failed {len(wheres)} times, unchanged: {cmd}",
                              key=cmd))
    for uid, at, text in typed_in_lines(lines):
        if PUSHBACK.search(text):
            cands.append(cand("owner-pushback", at, uid, text[:500]))
    return cands, sorted(set(skills))


def section(text, head):
    m = re.search(rf"^## {re.escape(head)}[ \t]*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def field(text, name):
    m = re.search(rf"^{re.escape(name)}:[ \t]*(.*)$", text, re.M)
    return m.group(1).strip() if m else ""


def scan_project(project):
    """The touched project's own record of trouble."""
    cands, root = [], Path(project)
    state = root / "docs/project/state.md"
    if state.is_file():
        text = state.read_text(encoding="utf-8")
        for head in ("Failures", "Blockers"):
            body = section(text, head)
            if body and not re.match(r"^(-\s*)?_?none\b", body, re.I):
                cands.append(cand(f"project-{head.lower()}", "", str(state), body))
    for v in sorted(root.glob(".evidence/*/*/r*/verdict.json")):
        try:
            d = json.loads(v.read_text())
        except (OSError, ValueError):
            continue
        if d.get("verdict") in ("INCONCLUSIVE", "ERROR"):
            cands.append(cand("round-" + d["verdict"].lower(), d.get("written", ""), str(v),
                              "; ".join(d.get("reasons") or []) or d["verdict"]))
    return cands


def incidents():
    out = {}
    for f in sorted((HOME / "incidents").glob("INC-*.md")):
        text = f.read_text(encoding="utf-8")
        sigs = [s.strip() for s in field(text, "Signature").split(" || ") if s.strip()]
        out[f.stem] = {"file": f, "signatures": sigs, "status": field(text, "Status") or "open", "text": text,
                       "title": text.splitlines()[0].lstrip("# ").strip() if text else f.stem}
    return out


def words(s):
    return set(re.findall(r"[a-z]{3,}|[\u4e00-\u9fff]", s.lower())) - {"path", "the", "and"}


def overlap(a, b):
    wa = words(a)
    return len(wa & words(b)) / len(wa) if wa else 0.0


def add_occurrence(inc, line, transcript):
    text = inc["file"].read_text(encoding="utf-8")
    if str(transcript) in section(text, "Occurrences"):
        return False
    m = re.search(r"^## Occurrences[ \t]*\n", text, re.M)
    if m:
        nxt = re.search(r"^## ", text[m.end():], re.M)
        cut = m.end() + (nxt.start() if nxt else len(text) - m.end())
        body = text[m.end():cut].rstrip("\n")
        text = text[:m.end()] + (body + "\n" if body else "") + line + "\n" + ("\n" if nxt else "") + text[cut:]
    else:
        text = text.rstrip("\n") + "\n\n## Occurrences\n" + line + "\n"
    inc["file"].write_text(text, encoding="utf-8")
    return True


def cmd_harvest(opts):
    from rulings import resolve_transcript
    path = Path(opts["--transcript"]) if opts.get("--transcript") else None
    session = opts.get("--session")
    if path is None:
        if not session:
            from session_env import current
            tool, sid = current()
            if tool in (None, "ambiguous"):
                return fail("this session cannot be identified; pass --session <id> (codex:<id>) or --transcript <path>")
            session = f"codex:{sid}" if tool == "codex" else sid
        path = resolve_transcript(session)
    if not path or not Path(path).is_file():
        return fail(f"no transcript found for {session or path}")
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    cands, skills = scan_transcript(lines)
    project = opts.get("--project")
    if project:
        cands += scan_project(project)
    grouped = {}
    for c in cands:
        c["signature"] = signature(c["kind"], c.pop("key"))
        g = grouped.setdefault(c["signature"], {**c, "count": 0, "wheres": []})
        g["count"] += 1
        g["wheres"].append(c["where"])
    known = incidents()
    stamp = datetime.date.today().isoformat()
    out = HOME / "harvests" / f"{stamp}-{Path(path).stem[-12:]}"
    out.mkdir(parents=True, exist_ok=True)
    rows, added = [], 0
    for i, g in enumerate(grouped.values(), 1):
        g["n"], g["known"], g["possibly"], g["regression"] = i, None, None, False
        for iid, inc in known.items():
            if g["signature"] in inc["signatures"]:
                g["known"] = iid
                g["regression"] = inc["status"].startswith(("fixed", "resolved"))
                added += add_occurrence(inc, f"- {stamp} · harvest {out.name} · x{g['count']} · {path}", path)
                break
        if not g["known"]:
            best = max(((max((overlap(g["signature"], s) for s in inc["signatures"]), default=0), iid)
                        for iid, inc in known.items()), default=(0, None))
            if best[0] >= 0.8:
                g["possibly"] = best[1]
        rows.append(g)
    (out / "candidates.json").write_text(json.dumps({"transcript": str(path), "project": project, "harvested": now(),
                                                     "skills": skills, "candidates": rows}, indent=2, ensure_ascii=False))
    fresh = [g for g in rows if not g["known"]]
    regressions = [g for g in rows if g["regression"]]
    md = [f"# Candidates from {Path(path).name}", "",
          f"Transcript: {path}", f"Project: {project or 'none given'}",
          f"Skills used: {', '.join(skills) or 'none recorded'}",
          f"Harvested: {now()} · {len(rows)} distinct candidates from {len(cands)} signals, "
          f"{len(rows) - len(fresh)} already known", "",
          "Each is a lead, not a verdict. Decide per candidate: a pipeline problem (a new incident, or an occurrence",
          "of an existing one), outside the pipeline (the environment, the project's own code, a choice), or noise.",
          "Then add what no script can see: friction, unclear instructions, wasted work, a wrong step the session",
          "later corrected.", ""]
    if regressions:
        md += ["## REGRESSIONS (a fixed incident's signature appeared again)", ""]
        md += [f"- {g['known']} · candidate {g['n']} · x{g['count']} · {g['signature']}" for g in regressions] + [""]
    for g in fresh:
        flag = f" · possibly {g['possibly']}" if g["possibly"] else ""
        md += [f"## {g['n']}. {g['kind']} x{g['count']}{flag}", f"Signature: {g['signature']}",
               f"Where: {', '.join(g['wheres'][:6])}" + (" ..." if len(g["wheres"]) > 6 else ""), "", "```",
               g["excerpt"], "```"]
        if g["context"] and g["context"] != "{}":
            md += ["Context:", "```", g["context"], "```"]
        md.append("")
    known_rows = [g for g in rows if g["known"] and not g["regression"]]
    if known_rows:
        md += ["## Known (an occurrence was added to the incident)", ""]
        md += [f"- {g['known']} · candidate {g['n']} · x{g['count']} · {g['signature']}" for g in known_rows] + [""]
    (out / "candidates.md").write_text("\n".join(md), encoding="utf-8")
    print(f"harvest: {len(rows)} candidates, {len(fresh)} new, {len(rows) - len(fresh)} known "
          f"({added} occurrence(s) added), {len(regressions)} regression(s) -> {out / 'candidates.md'}")
    return 0


# ---------- incidents and changes ----------

def next_id(folder, prefix):
    nums = [int(m.group(1)) for f in (HOME / folder).glob(f"{prefix}-*.md") if (m := re.match(rf"{prefix}-(\d+)$", f.stem))]
    return f"{prefix}-{max(nums, default=0) + 1:04d}"


def cmd_new_incident(opts):
    if not all(opts.get(k) for k in ("--title", "--kind", "--where", "--signature")):
        return usage()
    if opts["--kind"] not in KINDS:
        return fail(f"kind is one of {', '.join(KINDS)}")
    (HOME / "incidents").mkdir(parents=True, exist_ok=True)
    iid = next_id("incidents", "INC")
    evidence, occurrences = [], []
    if opts.get("--harvest"):
        data = json.loads((Path(opts["--harvest"]) / "candidates.json").read_text())
        wanted = {int(n) for n in opts.get("--candidate", [])}
        for g in data["candidates"]:
            if g["n"] in wanted:
                evidence += [f"Candidate {g['n']} ({g['kind']} x{g['count']}) at {', '.join(g['wheres'][:4])}:",
                             "```", g["excerpt"], "```"]
        occurrences.append(f"- {datetime.date.today().isoformat()} · harvest {Path(opts['--harvest']).name} · "
                           f"{data['transcript']}")
    try:
        version = git("rev-parse", "--short", "HEAD") or "unknown"
    except SystemExit:
        version = "unknown"
    text = "\n".join([
        f"# {iid} · {opts['--title']}", "",
        "Status: open",
        f"Kind: {opts['--kind']}",
        f"Where: {opts['--where']}",
        f"Signature: {opts['--signature']}",
        f"Pipeline version: {version}", "",
        "## Symptom", *(evidence or ["<the verbatim evidence: tool output, message, or file line, with where it is>"]), "",
        "## Impact", "<what it cost: a wrong verdict, a blocked or repeated step, the owner's time>", "",
        "## What the session did", "<the workaround or fix, whether it worked, and the evidence; or: nothing>", "",
        "## Occurrences", *occurrences, "",
        "## Reproduction", "<the suite that shows it on the current pipeline, or each attempt and why it did not>", ""])
    (HOME / "incidents" / f"{iid}.md").write_text(text, encoding="utf-8")
    print(f"{iid} -> {HOME / 'incidents' / (iid + '.md')}")
    return 0


def cmd_similar(argv):
    if not argv:
        return usage()
    q = " ".join(argv)
    hits = []
    for iid, inc in incidents().items():
        exact = q in inc["signatures"]
        score = 1.0 if exact else max([overlap(q, s) for s in inc["signatures"]] + [overlap(q, inc["title"])])
        if score >= 0.5:
            hits.append((score, iid, inc["status"], inc["title"]))
    for score, iid, status, title in sorted(hits, reverse=True):
        print(f"{iid} · {status} · {score:.0%} · {title}")
    if not hits:
        print("no similar incident")
    return 0


def cmd_new_change(opts):
    if not opts.get("--title") or not opts.get("--incidents") or opts.get("--kind") not in CHANGE_KINDS:
        return usage()
    known = incidents()
    ids = [i.strip() for i in opts["--incidents"].split(",") if i.strip()]
    missing = [i for i in ids if i not in known]
    if missing:
        return fail(f"no such incident: {', '.join(missing)}")
    (HOME / "changes").mkdir(parents=True, exist_ok=True)
    cid = next_id("changes", "CHG")
    base = sha_of("main") or sha_of("HEAD")
    owner = "[owner <date>] \"<their words>\" · session <id or codex:id>" if opts["--kind"] in OWNER_KINDS \
        else "not needed (a fix or a document change inside the pipeline's rules)"
    text = "\n".join([
        f"# {cid} · {opts['--title']}", "",
        f"Incidents: {', '.join(ids)}",
        f"Kind: {opts['--kind']}",
        f"Base: {base}",
        f"Branch: evolve/{cid.lower()}",
        "Suites: <selftest;...;repro:test:tests/test_x.py::Class.test_y>", "",
        "## Root cause", "<why it happened, with file:line>", "",
        "## Options",
        "- <the session's own workaround>: what, how, why or why not; measured: <verdict, or why it cannot be>",
        "- <another option>: what, how, why or why not", "",
        "Chosen: <option, and why it beats the others>",
        "Session workaround: <adopted as is | generalized | replaced (why) | none existed>", "",
        "## Review", "Result: <filled by evolve.py review>", "",
        "## Owner", f"Ruling: {owner}", ""])
    (HOME / "changes" / f"{cid}.md").write_text(text, encoding="utf-8")
    print(f"{cid} -> {HOME / 'changes' / (cid + '.md')} (branch evolve/{cid.lower()} from {base[:12]})")
    return 0


# ---------- benchmarks ----------

FLOW = [
    (r"^skills/capture/|^skills/_shared/scripts/capture\.py$", "scenario:capture"),
    (r"^skills/plan/references/adopt\.md$|^skills/_shared/scripts/(adopt|closure)\.py$", "scenario:adopt"),
    (r"^skills/inbox/|^skills/_shared/scripts/inbox\.py$", "scenario:inbox"),
    (r"^skills/plan/", "scenario:plan"),
    (r"^skills/(dev|gate)/|^skills/_shared/scripts/(gate_run|gate_report|gate_copies)\.py$", "scenario:build-gate"),
    (r"^skills/_shared/scripts/continuity\.py$|^skills/handoff/", "scenario:switch"),
]
FIXTURES_OF_AGENT = {"code-verifier": "code-verifier,escape", "loyal-evaluator": "loyal-evaluator,escape",
                     "gate-judge": "gate-judge", "cold-reader": "cold-reader", "claim-verifier": "claim-verifier",
                     "change-reviewer": "change-reviewer"}
ALL_CHECKERS = "code-verifier,loyal-evaluator,gate-judge,cold-reader,claim-verifier,change-reviewer,escape,probe"


def probe_fixtures(root, changed):
    """Fixture names whose pack embeds a changed file ({repo:<path>})."""
    table = root / "tests/fixture_expectations.py"
    if not table.is_file():
        return []
    names = []
    for m in re.finditer(r'"([\w-]+)":\s*\{[^{}]*?"folder":\s*"([^"]+)"', table.read_text()):
        for pack in (root / "tests/fixtures/agents" / m.group(2)).glob("*.md"):
            if any(r in changed for r in re.findall(r"\{repo:([^}]+)\}", pack.read_text(errors="replace"))):
                names.append(m.group(1))
    return sorted(set(names))


def cmd_touchmap(argv):
    if len(argv) != 2:
        return usage()
    changed = [f for f in git("diff", "--name-only", argv[0], argv[1]).splitlines() if f]
    fixtures, flows = set(), []
    for f in changed:
        m = re.match(r"^agents/([\w-]+)\.md$", f)
        if m and m.group(1) in FIXTURES_OF_AGENT:
            fixtures.update(FIXTURES_OF_AGENT[m.group(1)].split(","))
        if re.match(r"^skills/_shared/scripts/(run_isolated|render_pack)\.py$", f):
            fixtures.update(ALL_CHECKERS.split(","))
        if f == "skills/_shared/scripts/gate_copies.py":
            fixtures.update(["code-verifier", "loyal-evaluator", "escape"])
        for pattern, flow in FLOW:
            if re.search(pattern, f) and flow not in flows:
                flows.append(flow)
    fixtures.update(probe_fixtures(repo(), changed))
    suites = ["selftest"] + ([f"fixtures:{','.join(sorted(fixtures))}"] if fixtures else [])
    print("changed: " + (", ".join(changed) or "nothing"))
    print("required: " + ";".join(suites))
    if flows:
        print("flows touched: " + ";".join(flows) + "  (headless sessions; required when the change alters what "
              "that flow does, not for wording no scenario step depends on)")
    return 0


def env_fingerprint():
    env = {"python": platform.python_version(), "os": platform.system() + " " + platform.release()}
    for tool in ("claude", "codex"):
        exe = shutil.which(tool)
        if not exe:
            env[tool] = "absent"
            continue
        try:
            r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60)
            env[tool] = first_meaningful(r.stdout or r.stderr) or "unknown"
        except (OSError, subprocess.TimeoutExpired):
            env[tool] = "unknown"
    return env


def export(sha, dest, paths=()):
    """The tree of a commit (or some of its paths), without .git, into dest."""
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as tmp:
        r = subprocess.run(["git", "-C", str(repo()), "archive", "--format=tar", sha, *paths], stdout=tmp,
                           stderr=subprocess.PIPE)
        if r.returncode != 0:
            raise RuntimeError(f"git archive {sha[:12]} failed: {r.stderr.decode()[-300:]}")
        tmp.seek(0)
        with tarfile.open(fileobj=tmp) as tar:
            try:
                tar.extractall(dest, filter="data")
            except TypeError:
                tar.extractall(dest)


def test_counts(tree):
    return {f.stem: len(re.findall(r"^\s+def (test_\w+)\(", f.read_text(errors="replace"), re.M))
            for f in sorted((tree / "tests").glob("test_*.py"))}


MISSING_NAME = re.compile(r"^(ImportError: cannot import name|ModuleNotFoundError: No module named|NameError: name '.+' is "
                          r"not defined|AttributeError: (module|type object) '.+' has no attribute)", re.M)


def unittest_outcome(returncode, out):
    """pass; fail (an assertion); crash (the code under test raised); missing-name (the test needs a name this
    version does not have, so it cannot show a problem here); error (nothing ran)."""
    ran = re.search(r"^Ran (\d+) tests?", out, re.M)
    if returncode == 0:
        return "pass" if ran and int(ran.group(1)) > 0 else "error"
    if MISSING_NAME.search(out):
        return "missing-name"
    m = re.search(r"FAILED \(([^)]*)\)", out)
    errors = int(re.search(r"errors=(\d+)", m.group(1)).group(1)) if m and "errors=" in m.group(1) else 0
    failures = int(re.search(r"failures=(\d+)", m.group(1)).group(1)) if m and "failures=" in m.group(1) else 0
    if errors:
        return "crash"
    return "fail" if failures else "error"


def measure(tree, suite, runs):
    kind, _, arg = suite.partition(":")
    if kind in ("repro", "cost"):
        return measure(tree, arg, runs)
    if kind == "selftest":
        r = subprocess.run(["bash", str(tree / "tests/pipeline-selftest.sh")], capture_output=True, text=True, cwd=tree)
        rows = {m.group(2): m.group(1) for m in re.finditer(r"^(PASS|FAIL)\s+(\S+)", r.stdout, re.M)}
        return {"suites": rows, "tests": test_counts(tree), "tail": r.stdout[-1500:]}
    if kind == "fixtures":
        shutil.rmtree(tree / ".evidence/fixtures", ignore_errors=True)
        r = subprocess.run([sys.executable, str(tree / "tests/agent_fixtures.py"), "--only", arg, "--runs", str(runs)],
                           capture_output=True, text=True, cwd=tree)
        passes = {}
        for m in re.finditer(r"^(PASS|FAIL)\s+(\S+)\s+run (\d+)", r.stdout, re.M):
            passes.setdefault(m.group(2), []).append(m.group(1) == "PASS")
        if not passes:
            raise RuntimeError(f"no fixture matched {arg}: {(r.stdout + r.stderr)[-400:]}")
        summaries = list((tree / ".evidence/fixtures").glob("*/run-*/*.summary.json"))
        models = sorted({json.loads(f.read_text()).get("model") or "unknown" for f in summaries})
        from spend import units as cost_units
        cost = {}
        for f in summaries:
            name, run = f.parent.parent.name, f.parent.name
            u = json.loads(f.read_text()).get("usage") or {}
            cost.setdefault(name, {}).setdefault(run, 0)
            cost[name][run] += cost_units(u)
        return {"fixtures": passes, "models": models, "units": {k: sorted(v.values()) for k, v in cost.items()},
                "tail": r.stdout[-1500:]}
    if kind == "scenario":
        r = subprocess.run([sys.executable, str(tree / "tests/system_scenarios.py"), "--only", arg],
                           capture_output=True, text=True, cwd=tree)
        rows = {m.group(2): m.group(1) for m in re.finditer(r"^(PASS|FAIL)\s+(\S+)", r.stdout, re.M)
                if m.group(2) != "system-scenarios:"}
        if not rows:
            raise RuntimeError(f"no scenario ran for {arg}: {(r.stdout + r.stderr)[-400:]}")
        return {"scenarios": rows, "tail": r.stdout[-1500:]}
    if kind == "test":
        path, _, name = arg.partition("::")
        if not (tree / path).is_file():
            raise RuntimeError(f"{path} is not in the instrument's tests")
        r = subprocess.run([sys.executable, str(tree / path), *([name] if name else [])], capture_output=True,
                           text=True, cwd=tree)
        out = r.stdout + r.stderr
        return {"outcome": unittest_outcome(r.returncode, out), "tail": out[-1500:]}
    raise ValueError(f"unknown suite {suite}")


def suite_key(suite):
    return re.sub(r"[^A-Za-z0-9_.,-]+", "_", suite)[:120]


def instrument_key(suite, instrument_sha):
    return "own" if suite == "selftest" else git("rev-parse", f"{instrument_sha}:tests")[:12]


def env_key(env):
    return hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()[:8]


def stored(sha, suite, instrument_sha):
    """Every stored measurement file of this commit, suite, and instrument, whatever the environment."""
    folder = HOME / "benchmarks" / sha[:12]
    pattern = f"{suite_key(suite)}__{instrument_key(suite, instrument_sha)}__*.json"
    return [json.loads(f.read_text()) for f in sorted(folder.glob(pattern))] if folder.is_dir() else []


def installed_revision():
    return json.loads(INSTALL_MANIFEST.read_text()).get("revision", "") if INSTALL_MANIFEST.is_file() else ""


def cmd_bench(argv):
    opts = parse(argv[1:])
    if not argv or argv[0].startswith("--") or not opts.get("--suites"):
        return usage()
    sha = sha_of(argv[0])
    inst_sha = sha_of(opts.get("--instrument", argv[0]))
    if not sha or not inst_sha:
        return fail(f"unknown ref {argv[0] if not sha else opts.get('--instrument')}")
    runs = int(opts.get("--runs", 3))
    suites = [s.strip() for s in opts["--suites"].split(";") if s.strip()]
    for s in suites:
        if s.removeprefix("repro:").startswith("scenario:") and installed_revision() != sha:
            return fail(f"{s} runs against the installed pipeline, which is {installed_revision()[:20] or 'unknown'}, "
                        f"not {sha[:12]}: install that exact commit first (install.py apply from a clean checkout)")
    env = env_fingerprint()
    todo = []
    for s in suites:
        prior = [d for d in stored(sha, s, inst_sha) if {k: v for k, v in d["env"].items() if k != "models"} == env]
        if prior and "--again" not in argv:
            print(f"  {s}: stored, reused ({summary_line(prior[-1])})")
            continue
        todo.append((s, prior[-1] if prior else None))
    copies = Path.home() / ".gate-copies"
    copies.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="evolve-bench-", dir=str(copies)))
    try:
        own, lent = work / "own", work / "lent"
        if any(s == "selftest" for s, _ in todo):
            export(sha, own)
        if any(s != "selftest" for s, _ in todo):
            export(sha, lent)
            shutil.rmtree(lent / "tests", ignore_errors=True)
            export(inst_sha, lent, ["tests"])
        for s, prior in todo:
            try:
                m = {"measured": now(), "runs": runs, **measure(own if s == "selftest" else lent, s, runs)}
            except (RuntimeError, ValueError) as exc:
                return fail(f"{s}: {exc}")
            env_m = {**env, "models": m["models"]} if m.get("models") else env
            data = prior if prior and prior["env"] == env_m else \
                {"suite": s, "commit": sha, "instrument": instrument_key(s, inst_sha), "instrument_ref": inst_sha,
                 "env": env_m, "measurements": []}
            data["measurements"].append(m)
            f = HOME / "benchmarks" / sha[:12] / f"{suite_key(s)}__{instrument_key(s, inst_sha)}__{env_key(env_m)}.json"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(data, indent=2))
            print(f"  {s}: measured ({summary_line(data)}) -> {f}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


def pooled(measurements):
    out = {}
    for m in measurements:
        for name, results in m.get("fixtures", {}).items():
            p, n = out.get(name, (0, 0))
            out[name] = (p + sum(results), n + len(results))
    return out


def mean_units(measurements):
    out = {}
    for m in measurements:
        for name, runs in (m.get("units") or {}).items():
            out.setdefault(name, []).extend(runs)
    return {k: sum(v) / len(v) for k, v in out.items() if v}


def summary_line(data):
    last = data["measurements"][-1]
    if "suites" in last:
        bad = [k for k, v in last["suites"].items() if v != "PASS"]
        return f"{len(last['suites']) - len(bad)}/{len(last['suites'])} suites pass" + (f", failing {', '.join(bad)}" if bad else "")
    if "fixtures" in last:
        return ", ".join(f"{k} {p}/{n}" for k, (p, n) in pooled(data["measurements"]).items())
    if "scenarios" in last:
        return ", ".join(f"{k} {v}" for k, v in last["scenarios"].items())
    return last.get("outcome", "?")


def compare(base_sha, head_sha, suites, inst_sha):
    """(verdict, reasons, rows) by the rule fixed in advance."""
    worse, incomparable, repro, rows = [], [], [], []
    for s in suites:
        is_repro = s.startswith("repro:")
        inner = s.removeprefix("repro:")
        cost_repro = inner.startswith("cost:")
        inner = inner.removeprefix("cost:")
        b_all, h_all = stored(base_sha, s, inst_sha), stored(head_sha, s, inst_sha)
        if not b_all or not h_all:
            incomparable.append(f"{s} is not measured at {'base' if not b_all else 'head'}")
            continue
        b, h = b_all[-1], h_all[-1]
        if inner.startswith(("fixtures:", "scenario:")):
            pairs = [(x, y) for x in b_all for y in h_all if x["env"] == y["env"]]
            if not pairs:
                incomparable.append(f"{s}: base and head were measured in different environments "
                                    f"({b['env']} / {h['env']})")
                continue
            b, h = pairs[-1]
        rows.append({"suite": s, "base": summary_line(b), "head": summary_line(h)})
        bm, hm = b["measurements"][-1], h["measurements"][-1]
        if s == "selftest":
            for name, st in bm["suites"].items():
                if st == "PASS" and hm["suites"].get(name) != "PASS":
                    worse.append(f"selftest {name}: PASS at base, {hm['suites'].get(name, 'missing')} at head")
            for name, st in hm["suites"].items():
                if st != "PASS" and bm["suites"].get(name) != "PASS":
                    worse.append(f"selftest {name} fails at head")
            for name, n in bm["tests"].items():
                if hm["tests"].get(name, 0) < n:
                    worse.append(f"{name}: {n} tests at base, {hm['tests'].get(name, 0)} at head (tests removed)")
        elif inner.startswith("fixtures:"):
            bp, hp = pooled(b["measurements"]), pooled(h["measurements"])
            bu, hu = mean_units(b["measurements"]), mean_units(h["measurements"])
            for name, (p, n) in bp.items():
                hp_, hn = hp.get(name, (0, 0))
                cost = f"{bu[name] / 1e3:.0f}k -> {hu[name] / 1e3:.0f}k units a run" if name in bu and name in hu else ""
                if hn != n:
                    incomparable.append(f"fixture {name}: {n} runs at base, {hn} at head (measure both sides alike)")
                elif cost_repro:
                    ok = hp_ * n >= p * hn and name in bu and name in hu and hu[name] <= 0.8 * bu[name]
                    repro.append((f"fixture {name} cost", ok, f"{cost or 'no cost measured'}; passes {p}/{n} -> {hp_}/{hn}"))
                elif is_repro:
                    repro.append((f"fixture {name}", p < n and hp_ == hn, f"base {p}/{n}, head {hp_}/{hn}"))
                elif hp_ * n < p * hn:
                    worse.append(f"fixture {name}: {p}/{n} at base, {hp_}/{hn} at head")
                if not cost_repro and name in bu and name in hu and hu[name] > 1.25 * bu[name]:
                    worse.append(f"fixture {name} costs more: {cost} (more than a quarter over, beyond run-to-run noise)")
        elif inner.startswith("scenario:"):
            for name, st in bm["scenarios"].items():
                if is_repro:
                    repro.append((f"scenario {name}", st == "FAIL" and hm["scenarios"].get(name) == "PASS",
                                  f"base {st}, head {hm['scenarios'].get(name)}"))
                elif st == "PASS" and hm["scenarios"].get(name) != "PASS":
                    worse.append(f"scenario {name}: PASS at base, {hm['scenarios'].get(name, 'missing')} at head")
        elif inner.startswith("test:"):
            bo, ho = bm["outcome"], hm["outcome"]
            if is_repro:
                why = {"fail": "", "crash": "",
                       "missing-name": " (the test needs a name the change adds, so it cannot show the problem)",
                       "error": " (the test did not run at base)",
                       "pass": " (passes at base: it does not show the problem)"}.get(bo, "")
                repro.append((f"test {inner[5:]}", bo in ("fail", "crash") and ho == "pass", f"base {bo}, head {ho}{why}"))
            elif bo == "pass" and ho != "pass":
                worse.append(f"test {inner[5:]}: pass at base, {ho} at head")
    if incomparable:
        return "INCOMPARABLE", incomparable, rows
    if worse:
        return "WORSE", worse, rows
    stuck = [f"{name}: {how}" for name, ok, how in repro if not ok]
    if repro and not stuck:
        return "BETTER", ["every reproduction flipped: " + "; ".join(f"{name}: {how}" for name, _, how in repro)], rows
    return "SAME", stuck or ["no reproduction among the suites (mark one with repro:)"], rows


def cmd_compare(argv):
    opts = parse(argv[2:])
    if len(argv) < 2 or argv[1].startswith("--") or not opts.get("--suites"):
        return usage()
    base, head = sha_of(argv[0]), sha_of(argv[1])
    inst = sha_of(opts.get("--instrument", argv[1]))
    if not base or not head or not inst:
        return fail("a ref does not resolve")
    suites = [s.strip() for s in opts["--suites"].split(";") if s.strip()]
    verdict, reasons, rows = compare(base, head, suites, inst)
    for r in rows:
        print(f"  {r['suite']}: base {r['base']} | head {r['head']}")
    print(f"{verdict}: " + "; ".join(reasons))
    if opts.get("--out"):
        Path(opts["--out"]).write_text(json.dumps({"base": base, "head": head, "instrument": inst, "suites": suites,
                                                   "verdict": verdict, "reasons": reasons, "rows": rows,
                                                   "compared": now()}, indent=2))
    return 0 if verdict == "BETTER" else 1


# ---------- review, record, check ----------

def change_text(cid):
    f = HOME / "changes" / f"{cid}.md"
    return f.read_text(encoding="utf-8") if f.is_file() else None


def last_json(text):
    """The last JSON block of a checker's message. A raw control character inside a string (a quoted command's tab
    or newline) does not void the verdict; what is not JSON still reads as no verdict."""
    for b in reversed(re.findall(r"```json\s*(\{.*?\})\s*```", text or "", flags=re.S)):
        try:
            return json.loads(b, strict=False)
        except ValueError:
            continue
    return None


def review_problems(data):
    """Why the reviewer's own fields do not add up to an acceptance (empty when they do). The reviewer's
    headline verdict alone never accepts a change."""
    if not data:
        return ["no verdict from the change reviewer"]
    out = []
    if str(data.get("verdict", "")).upper() != "ACCEPT":
        out.append(f"the reviewer says {data.get('verdict')}")
    if (data.get("root_cause") or {}).get("status") != "FIXED":
        out.append(f"root cause {(data.get('root_cause') or {}).get('status', 'not assessed')}")
    if (data.get("reproduction") or {}).get("status") != "FAITHFUL":
        out.append(f"reproduction {(data.get('reproduction') or {}).get('status', 'not assessed')}")
    if (data.get("session_workaround") or {}).get("status") == "WAVED-AWAY":
        out.append("the session's workaround was waved away, not weighed")
    if data.get("checks_weakened"):
        out.append("checks weakened: " + "; ".join(f"{c.get('where')} {c.get('what')}" for c in data["checks_weakened"])[:300])
    if data.get("kind_ok") is not True:
        out.append(f"kind not confirmed (the reviewer reads it as {data.get('kind')})")
    serious = [f for f in data.get("findings") or [] if str(f.get("severity", "")).lower() in ("high", "medium")]
    out += [f"{f.get('id')} {f.get('class')} ({f.get('severity')}): {str(f.get('summary'))[:160]}" for f in serious]
    return out


def suites_of(text):
    return [s.strip() for s in field(text, "Suites").split(";") if s.strip() and not s.strip().startswith("<")]


def review_pack(base, head, record, incidents_text, rows, verdict_line, tails, diff, charter):
    """The change reviewer's whole input (the fixture generator renders its packs with this too)."""
    return "\n".join([
        "# Change review", "",
        f"Base: {base}", f"Head: {head}", "The folder you are in holds the head commit's tree.", "",
        "## The change record", record, "",
        "## The incidents it answers", incidents_text, "",
        "## The comparison (computed by script from the stored measurements)",
        *[f"- {r['suite']}: base {r['base']} | head {r['head']}" for r in rows], f"Verdict: {verdict_line}", "",
        "## The reproductions' output", *tails, "",
        "## The diff (base..head)", "```diff", diff[:300000], "```", "",
        "## The pipeline's charter", charter])


def cmd_review(argv):
    if not argv:
        return usage()
    cid = argv[0]
    text = change_text(cid)
    if text is None:
        return fail(f"no change record {cid}")
    base, head = sha_of(field(text, "Base")), sha_of(field(text, "Branch"))
    if not base or not head:
        return fail(f"{cid}: base or branch does not resolve")
    suites = suites_of(text)
    verdict, reasons, rows = compare(base, head, suites, head)
    if verdict != "BETTER":
        return fail(f"{cid}: the comparison says {verdict} ({'; '.join(reasons)[:300]}); a change is reviewed once it is BETTER")
    out = HOME / "changes" / f"{cid}-review"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    known = incidents()
    incs = "\n\n".join(known[i]["text"] for i in [x.strip() for x in field(text, "Incidents").split(",")] if i in known)
    tails = []
    for s in suites:
        if s.startswith("repro:"):
            for which, sha in (("base", base), ("head", head)):
                m = stored(sha, s, head)
                tails += [f"### {s} at {which}", "```", (m[-1]["measurements"][-1].get("tail") or "")[-1200:] if m else "", "```"]
    constitution = repo() / "skills/_shared/references/pipeline-constitution.md"
    pack = review_pack(base, head, text, incs, rows, f"{verdict}: {'; '.join(reasons)}", tails,
                       git("diff", f"{base}..{head}"),
                       constitution.read_text(encoding="utf-8") if constitution.is_file() else "(missing)")
    (out / "pack.md").write_text(pack, encoding="utf-8")
    tree = Path.home() / ".gate-copies" / f"evolve-review-{cid.lower()}-{secrets.token_hex(3)}"
    agent = repo() / "agents/change-reviewer.md"
    try:
        export(head, tree)
        r = subprocess.run([sys.executable, str(HERE / "run_isolated.py"), "change-reviewer", "--dir", str(tree),
                            "--pack", str(out / "pack.md"), "--out", str(out),
                            *(["--agent-file", str(agent)] if agent.is_file() else [])], capture_output=True, text=True)
    finally:
        shutil.rmtree(tree, ignore_errors=True)
    (out / "meta.json").write_text(json.dumps({"base": base, "head": head, "reviewed": now(),
                                               "pack_sha256": hashlib.sha256((out / "pack.md").read_bytes()).hexdigest()}))
    result = out / "change-reviewer.result.md"
    data = last_json(result.read_text(encoding="utf-8")) if result.is_file() else None
    body = re.sub(r"^Result:.*$", f"Result: {result}", text, count=1, flags=re.M)
    (HOME / "changes" / f"{cid}.md").write_text(body, encoding="utf-8")
    if not data:
        return fail(f"{cid}: the reviewer returned no verdict ({(r.stdout + r.stderr)[-300:]})")
    problems = review_problems(data)
    print(f"{cid}: reviewer {data.get('verdict')}, {'accepted' if not problems else 'not accepted: ' + '; '.join(problems)} "
          f"-> {result}")
    return 0 if not problems else 1


def owner_problem(text):
    m = re.search(r"\[owner (\d{4}-\d{2}-\d{2})\]\s*\"([^\"]+)\"\s*·\s*session\s+(\S+)", section(text, "Owner"))
    if not m:
        return "needs the owner's ruling: [owner <date>] \"<their words>\" · session <id>"
    from rulings import resolve_transcript, find_quote
    path = resolve_transcript(m.group(3))
    if not path:
        return f"the owner's session {m.group(3)} has no transcript on this machine"
    if not find_quote(path, m.group(2)):
        return "the quoted words are not a whole sentence or message the owner typed in that session"
    return None


def change_problems(cid, need_merged=False):
    text = change_text(cid)
    if text is None:
        return [f"no change record {cid}"]
    out, known = [], incidents()
    ids = [x.strip() for x in field(text, "Incidents").split(",") if x.strip()]
    if not ids:
        out.append(f"{cid}: names no incident")
    out += [f"{cid}: incident {i} does not exist" for i in ids if i not in known]
    proven = re.search(r"head ([0-9a-f]{40})", field(text, "Proven"))
    base = sha_of(field(text, "Base"))
    # Once proven, the proof is about that exact commit (the branch may be gone after the merge).
    head = sha_of(proven.group(1)) if proven and need_merged else sha_of(field(text, "Branch"))
    if not base or not head:
        return out + [f"{cid}: base or branch does not resolve"]
    suites = suites_of(text)
    if not any(s.startswith("repro:") for s in suites):
        out.append(f"{cid}: no reproduction among the suites")
    verdict, reasons, _ = compare(base, head, suites, head)
    if verdict != "BETTER":
        out.append(f"{cid}: the comparison says {verdict}: " + "; ".join(reasons)[:300])
    options = [l for l in section(text, "Options").splitlines() if l.startswith("- ") and not l.startswith("- <")]
    if len(options) < 2:
        out.append(f"{cid}: fewer than two options weighed")
    for name in ("Chosen", "Session workaround"):
        v = field(text, name)
        if not v or v.startswith("<"):
            out.append(f"{cid}: '{name}' is not filled in")
    review = HOME / "changes" / f"{cid}-review"
    meta = json.loads((review / "meta.json").read_text()) if (review / "meta.json").is_file() else {}
    data = last_json((review / "change-reviewer.result.md").read_text(encoding="utf-8")) \
        if (review / "change-reviewer.result.md").is_file() else None
    rp = review_problems(data)
    if rp:
        out.append(f"{cid}: the isolated change review does not accept it: " + "; ".join(rp)[:400])
    elif meta.get("head") != head:
        out.append(f"{cid}: the review was of {str(meta.get('head'))[:12]}, the branch is at {head[:12]}: review again")
    elif data.get("kind") != field(text, "Kind"):
        out.append(f"{cid}: recorded as {field(text, 'Kind')}, the reviewer reads it as {data.get('kind')}")
    if field(text, "Kind") in OWNER_KINDS:
        p = owner_problem(text)
        if p:
            out.append(f"{cid}: {p}")
    if need_merged:
        merged = subprocess.run(["git", "-C", str(repo()), "merge-base", "--is-ancestor", head, "main"],
                                capture_output=True).returncode == 0
        if not proven:
            out.append(f"{cid}: never proven with evolve.py record")
        elif not merged:
            out.append(f"{cid}: proven at {head[:12]} but not merged into main")
    return out


def cmd_record(argv):
    if not argv:
        return usage()
    cid = argv[0]
    problems = change_problems(cid)
    if problems:
        for p in problems:
            fail(p)
        return 1
    text = change_text(cid)
    head = sha_of(field(text, "Branch"))
    text = re.sub(r"^Proven:.*\n", "", text, flags=re.M)
    text = re.sub(r"^(Branch:.*)$", rf"\1\nProven: {now()} · head {head}", text, count=1, flags=re.M)
    (HOME / "changes" / f"{cid}.md").write_text(text, encoding="utf-8")
    for i in [x.strip() for x in field(text, "Incidents").split(",") if x.strip()]:
        f = HOME / "incidents" / f"{i}.md"
        t = f.read_text(encoding="utf-8")
        f.write_text(re.sub(r"^Status:.*$", f"Status: fixed ({cid})", t, count=1, flags=re.M), encoding="utf-8")
    print(f"PASS   evolve      {cid} proven at {head[:12]}: every reproduction flipped, nothing got worse, the "
          f"reviewer accepted; incidents marked fixed. Next: merge into main, install, sync Codex.")
    return 0


def cmd_check(argv):
    fails, known = [], incidents()
    for iid, inc in known.items():
        st, text = inc["status"], inc["text"]
        word = st.split(" ")[0]
        if word not in STATUSES:
            fails.append(f"{iid}: unknown status '{st}' (one of {', '.join(STATUSES)})")
        if field(text, "Kind") not in KINDS:
            fails.append(f"{iid}: unknown kind '{field(text, 'Kind')}'")
        if not inc["signatures"]:
            fails.append(f"{iid}: no signature")
        repro = section(text, "Reproduction")
        if word in ("confirmed", "fixed", "not-reproduced") and (not repro or repro.startswith("<")):
            fails.append(f"{iid}: {word}, but the Reproduction section records nothing")
        if word in ("environment", "not-pipeline") and not re.search(r"\(.+\)", st):
            fails.append(f"{iid}: {word} needs its reason in parentheses")
        if word == "duplicate":
            m = re.search(r"INC-\d{4}", st)
            if not m or m.group(0) not in known or m.group(0) == iid:
                fails.append(f"{iid}: a duplicate must name the incident it duplicates")
        if word == "resolved":
            # A change the owner directed outside this loop: its commit must be on main, and how it was verified said.
            m = re.match(r"resolved \(([0-9a-f]{7,40}) · (.{10,})\)$", st)
            if not m:
                fails.append(f"{iid}: resolved needs (<commit> · <how it was verified>)")
            elif subprocess.run(["git", "-C", str(repo()), "merge-base", "--is-ancestor", m.group(1), "main"],
                                capture_output=True).returncode != 0:
                fails.append(f"{iid}: resolved by {m.group(1)}, which is not on main")
        if word == "fixed":
            m = re.match(r"fixed \((CHG-\d{4})\)", st)
            if not m:
                fails.append(f"{iid}: fixed without naming its change")
            else:
                fails += change_problems(m.group(1), need_merged=True)
    for p in sorted(set(fails)):
        print(f"FAIL   evolve      {p}")
    if not fails:
        print(f"PASS   evolve      {len(known)} incident(s); every fixed one proven and merged")
    return 1 if fails else 0


def cmd_status(argv):
    known = incidents()
    counts = {}
    for inc in known.values():
        w = inc["status"].split(" ")[0]
        counts[w] = counts.get(w, 0) + 1
    changes = sorted((HOME / "changes").glob("CHG-*.md"))
    print(f"ledger {HOME}: incidents " + (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none")
          + f"; changes {len(changes)} ({sum(1 for c in changes if 'Proven:' in c.read_text())} proven)")
    live = [(len([l for l in section(inc["text"], "Occurrences").splitlines() if l.startswith("- ")]), iid, inc)
            for iid, inc in known.items() if inc["status"].split(" ")[0] in ("open", "confirmed", "reopened", "not-reproduced")]
    for occ, iid, inc in sorted(live, key=lambda x: (-x[0], x[1])):
        print(f"  {iid} · {inc['status']} · seen {occ}x · {inc['title'][:90]}")
    return 0


def parse(argv):
    opts, i = {}, 0
    while i < len(argv):
        if argv[i].startswith("--") and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            if argv[i] == "--candidate":
                opts.setdefault("--candidate", []).append(argv[i + 1])
            else:
                opts[argv[i]] = argv[i + 1]
            i += 2
        else:
            i += 1
    return opts


def main(argv):
    if not argv:
        return usage()
    cmd, rest = argv[0], argv[1:]
    table = {"harvest": lambda: cmd_harvest(parse(rest)), "new-incident": lambda: cmd_new_incident(parse(rest)),
             "similar": lambda: cmd_similar(rest), "touchmap": lambda: cmd_touchmap(rest),
             "bench": lambda: cmd_bench(rest), "compare": lambda: cmd_compare(rest),
             "new-change": lambda: cmd_new_change(parse(rest)), "review": lambda: cmd_review(rest),
             "record": lambda: cmd_record(rest), "check": lambda: cmd_check(rest), "status": lambda: cmd_status(rest)}
    if cmd not in table:
        return usage()
    return table[cmd]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
