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
  repro:cost:fixtures:<prefix>, repro:cost:scenario:<name>   the reproduction of a change made to spend less
  repro:route:fixtures:<prefix>   the reproduction of a change to the model routing table (skills/_shared/
                             models.json), judged on the matching fixtures pooled by kind (rule below)
Fixture, scenario, and test suites run with the tests/ folder of the instrument ref (default: the ref itself),
so both sides of a comparison are measured by the same instrument and only the pipeline differs. selftest
runs each ref's own tests. Every suite runs with PIPELINE_MODELS_IGNORE_OVERRIDE=1, so both sides use the
repository's own routing table, never the owner's personal override. Every result carries the environment
(Claude Code, Codex, Python, OS, and the models the checkers and sessions were served by); a measurement
already stored for the same commit, suite, instrument, and environment is reused, never repeated; --again adds
another measurement of the same size (pooled).

A fixture or scenario measurement stores each run's raw token usage by the model that served it, never a
computed cost. Cost is computed when comparing, from that raw usage and the spend.py of the evolve.py that
compares: cost units (spend.py's weights) shown for the allowance, and dollars at list prices (spend.py's
price table, by the serving model), which the rule below judges. A weight or price change therefore moves both
sides alike. Codex usage is shown beside, never priced or judged (it draws on another allowance).

compare applies this rule, never judgment. "Cost" is dollars at list prices per run (fixtures) or per
scenario run (scenarios), Claude usage only.
  INCOMPARABLE  a suite not measured on one side; for fixtures and scenarios no pair of measurements taken in
                the same environment, or a different number of runs; a cost that cannot be computed because a
                side's measurements hold no raw usage (taken before usage was stored per run: measure both
                sides again with bench --again); a cost rule (repro:cost, repro:route) whose base has no priced
                usage ($0 a run: $0 <= 0.8 x $0 would pass anything); for repro:route, a fixture with no kind,
                a run with no problem count or no count of the planted items it checked, or fewer than 30
                planted item-trials (items checked, summed over every run of every planted fixture) on either
                side, named with the --runs that would reach 30. Environments match on everything above, the
                served models included, except when the change's own diff is the routing table (every file it
                changes is skills/_shared/models.json or a document: under docs/, or a .md file outside skills/
                and agents/): then the served models are left out of the match. Whenever the diff touches the
                table, the output says "model routing changed" with each route that differs, before and after.
  WORSE         a selftest suite that passed now fails or is missing, or any selftest suite fails at head; a
                test file with fewer tests than before; a fixture passing a smaller share of its runs, or
                costing more than a quarter more per run; a scenario or a non-reproduction test that passed now
                fails; a scenario that passed at base costing more than a quarter more at head (one that failed
                at base stopped early, so its cost is no measure); under repro:route, a fixture of kind other
                (a probe) passing a smaller share of its runs
  reproduction  a test must fail at base (an assertion, or the code under test raising) and pass at head; a
                test that needs a name only the change adds (an import or name error) cannot show the problem
                and does not count; a fixture must fail at least one run at base and pass every run at head;
                a scenario must fail at base and pass at head; repro:cost:fixtures:<prefix> (a change made to
                spend less) must cut each fixture's cost per run by a fifth or more and pass at least as often;
                repro:cost:scenario:<name> must pass at head and cut the scenario's cost by a fifth or more;
                repro:route:fixtures:<prefix> (a routing change) holds when, over the fixtures the prefix
                matches, with as many runs of each on both sides: the head's problems, summed over every run
                of every planted fixture, are no more than the base's; every clean fixture passes every run at
                head; the cost per run over all of them at head is at most 0.8 of the base's; and at least one
                planted and one clean fixture match. A run's problems are the ones its expectation reported
                (a runner status other than OK is one of them); a run that gave no verdict of its own (no
                summary, no verdict block, or escalated to another model) missed everything, so it counts one
                plus every problem its expectation finds in an empty verdict.
  BETTER        nothing incomparable or worse, at least one reproduction, and every reproduction flipped
  SAME          otherwise, with the reason (not an improvement)

record refuses a change missing any part of its proof: existing incidents, a reproduction, two or more options
with the session's own workaround weighed among them, a BETTER comparison recomputed from the stored
measurements at the branch's current commit, an acceptance computed from the isolated change reviewer's
fields for that change (a review of an earlier commit still covers it when the change's own diff is the same
byte for byte with full blob ids, no file it touches changed underneath, and each reproduction fails at the base
for the same reason once run-varying text is reduced, a base never measured counting as no reason: a rebase onto
unrelated work keeps the review) (cause
fixed, reproduction faithful, the workaround weighed, no check weakened,
the kind confirmed, no high or medium finding; and only from a reviewer run whose change-reviewer.summary.json
says OK, since an INCONCLUSIVE, ERROR, or LEAK run's result is no review, and review refuses one the same way,
naming its status and reason), and, for a capability or rule change, the owner's words
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
ROUTING_TABLE = "skills/_shared/models.json"
ROUTE_MIN_TRIALS = 30  # plan 7.3: planted item-trials on each side before the route rule judges a routing change
# Every suite measures the repository's own routing table, never the owner's personal override.
SUITE_ENV = {"PIPELINE_MODELS_IGNORE_OVERRIDE": "1"}


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
        if re.match(r"^skills/_shared/scripts/(run_isolated|render_pack|models)\.py$", f) or f == ROUTING_TABLE:
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


def suite_env():
    return {**os.environ, **SUITE_ENV}


def summary_usage(summary_files):
    """(raw usage by the model that served it, served models) over some run summaries: each summary's usage
    under its served model (served_model, else model, else "unknown"); a Codex run's under codex:<model>."""
    usage, models = {}, set()
    for f in summary_files:
        try:
            s = json.loads(Path(f).read_text())
        except (OSError, ValueError):
            continue
        model = s.get("served_model") or s.get("model") or "unknown"
        models.add(model)
        u = s.get("usage")
        if not isinstance(u, dict):
            continue
        key = f"codex:{model}" if s.get("family") == "codex" or u.get("family") == "codex" else model
        acc = usage.setdefault(key, {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0})
        for k in ("input", "cache_write", "cache_read", "output"):
            acc[k] += u.get(k) or 0
        if u.get("cache_write_1h"):  # recorded by newer runs only; the rest of the writes price as 5-minute ones
            acc["cache_write_1h"] = acc.get("cache_write_1h", 0) + u["cache_write_1h"]
    return usage, sorted(models)


def measure(tree, suite, runs):
    kind, _, arg = suite.partition(":")
    if kind in ("repro", "cost", "route"):
        return measure(tree, arg, runs)
    if kind == "selftest":
        r = subprocess.run(["bash", str(tree / "tests/pipeline-selftest.sh")], capture_output=True, text=True, cwd=tree,
                           env=suite_env())
        rows = {m.group(2): m.group(1) for m in re.finditer(r"^(PASS|FAIL)\s+(\S+)", r.stdout, re.M)}
        return {"suites": rows, "tests": test_counts(tree), "tail": r.stdout[-1500:]}
    if kind == "fixtures":
        shutil.rmtree(tree / ".evidence/fixtures", ignore_errors=True)
        r = subprocess.run([sys.executable, str(tree / "tests/agent_fixtures.py"), "--only", arg, "--runs", str(runs)],
                           capture_output=True, text=True, cwd=tree, env=suite_env())
        passes = {}
        for m in re.finditer(r"^(PASS|FAIL)\s+(\S+)\s+run (\d+)", r.stdout, re.M):
            passes.setdefault(m.group(2), []).append(m.group(1) == "PASS")
        if not passes:
            raise RuntimeError(f"no fixture matched {arg}: {(r.stdout + r.stderr)[-400:]}")
        # Each run's raw usage by served model, read from its summaries here, so the cost never depends on the
        # instrument's arithmetic; the instrument's own record adds the run's kind, problems, and escalation.
        per_run, kinds, models = {}, {}, set()
        for d in sorted((tree / ".evidence/fixtures").glob("*/run-*")):
            name = d.parent.name
            if name not in passes or not re.match(r"^run-\d+$", d.name):
                continue
            usage, served = summary_usage(sorted(d.glob("*.summary.json")))
            models.update(served)
            rec = {"run": int(d.name[4:]), "usage": usage, "models": served, "problems": None}
            res = d / "fixture-result.json"
            try:
                own = json.loads(res.read_text()) if res.is_file() else {}
            except ValueError:
                own = {}
            rec.update({k: own[k] for k in ("pass", "escalated", "status") if k in own})
            if isinstance(own.get("problem_count"), int):
                rec["problems"] = own["problem_count"]
            if isinstance(own.get("items"), int) and not isinstance(own.get("items"), bool):
                rec["items"] = own["items"]  # the planted items this run checked (route rule's sample floor)
            if own.get("kind"):
                kinds[name] = own["kind"]
            per_run.setdefault(name, []).append(rec)
        return {"fixtures": passes, "models": sorted(models) or ["unknown"], "per_run": per_run, "kinds": kinds,
                "tail": r.stdout[-1500:]}
    if kind == "scenario":
        r = subprocess.run([sys.executable, str(tree / "tests/system_scenarios.py"), "--only", arg],
                           capture_output=True, text=True, cwd=tree, env=suite_env())
        rows = {m.group(2): m.group(1) for m in re.finditer(r"^(PASS|FAIL)\s+(\S+)", r.stdout, re.M)
                if m.group(2) != "system-scenarios:"}
        if not rows:
            raise RuntimeError(f"no scenario ran for {arg}: {(r.stdout + r.stderr)[-400:]}")
        # Each scenario's raw usage (its sessions and the isolated runs they caused), as the instrument wrote it.
        cost = {}
        for name in rows:
            f = tree / ".evidence/system" / name / "cost.json"
            try:
                c = json.loads(f.read_text()) if f.is_file() else None
            except ValueError:
                c = None
            if isinstance(c, dict) and isinstance(c.get("usage"), dict):
                cost[name] = {"usage": c["usage"], "models": sorted(c["usage"])}
        models = sorted({m for c in cost.values() for m in c["models"]})
        return {"scenarios": rows, "cost": cost, **({"models": models} if models else {}), "tail": r.stdout[-1500:]}
    if kind == "test":
        path, _, name = arg.partition("::")
        if not (tree / path).is_file():
            raise RuntimeError(f"{path} is not in the instrument's tests")
        r = subprocess.run([sys.executable, str(tree / path), *([name] if name else [])], capture_output=True,
                           text=True, cwd=tree, env=suite_env())
        out = r.stdout + r.stderr
        return {"outcome": unittest_outcome(r.returncode, out), "error": error_line(out), "tail": out[-1500:]}
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
        if s.removeprefix("repro:").removeprefix("cost:").startswith("scenario:") and installed_revision() != sha:
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


def run_cost(usage):
    """(cost units, dollars, Codex tokens) of one run's raw usage ({model: tokens by type}), by this evolve.py's
    spend.py: computed when comparing, never stored, so a weight or price change moves both sides alike."""
    import spend
    u_sum, d_sum, codex = 0.0, 0.0, 0
    for model, u in (usage or {}).items():
        if spend.is_codex(model):
            codex += sum(u.get(k) or 0 for k in spend.WEIGHTS)
            continue
        u_sum += spend.units(u)
        d_sum += spend.dollars(model, u)[0]
    return u_sum, d_sum, codex


def fixture_costs(measurements):
    """{fixture: (units per run, dollars per run, Codex tokens per run, runs counted)} over the runs whose raw usage
    is stored; a fixture none of whose runs has it is missing (its cost cannot be computed)."""
    acc = {}
    for m in measurements:
        for name, runs in (m.get("per_run") or {}).items():
            for r in runs:
                u, d, c = run_cost(r.get("usage"))
                a = acc.setdefault(name, [0.0, 0.0, 0, 0])
                a[0], a[1], a[2], a[3] = a[0] + u, a[1] + d, a[2] + c, a[3] + 1
    return {k: (u / n, d / n, c / n, n) for k, (u, d, c, n) in acc.items() if n}


def scenario_costs(measurements):
    """{scenario: (units, dollars, Codex tokens)} per run, the mean over the measurements that stored its raw usage."""
    acc = {}
    for m in measurements:
        for name, c in (m.get("cost") or {}).items():
            u, d, x = run_cost(c.get("usage"))
            a = acc.setdefault(name, [0.0, 0.0, 0, 0])
            a[0], a[1], a[2], a[3] = a[0] + u, a[1] + d, a[2] + x, a[3] + 1
    return {k: (u / n, d / n, x / n) for k, (u, d, x, n) in acc.items() if n}


def cost_text(b, h, per="a run"):
    """How a cost moved, in dollars with the units beside: b and h are (units, dollars, Codex tokens, ...)."""
    codex = f"; Codex {b[2] / 1e3:.0f}k -> {h[2] / 1e3:.0f}k tokens, not priced" if b[2] or h[2] else ""
    return f"${b[1]:.2f} -> ${h[1]:.2f} {per} ({b[0] / 1e3:.0f}k -> {h[0] / 1e3:.0f}k units){codex}"


def no_raw_usage(what, side, suite):
    return (f"{what}: cost not comparable: the {side}'s stored measurements hold no raw usage (taken before usage was "
            f"stored per run); measure both sides again with evolve.py bench <ref> --suites \"{suite}\" --again")


def unpriced_base(what):
    """A cost rule's ratio needs a base cost: with no priced usage at base, $0 <= 0.8 x $0 would pass anything."""
    return (f"{what}: no priced usage at base ($0.00 a run), so the cost rule cannot judge (Codex usage and models "
            "spend.py has no price for count nothing): measure with usage the price table prices")


def summary_line(data):
    last = data["measurements"][-1]
    if "suites" in last:
        bad = [k for k, v in last["suites"].items() if v != "PASS"]
        return f"{len(last['suites']) - len(bad)}/{len(last['suites'])} suites pass" + (f", failing {', '.join(bad)}" if bad else "")
    if "fixtures" in last:
        costs = fixture_costs(data["measurements"])
        return ", ".join(f"{k} {p}/{n}" + (f" ${costs[k][1]:.2f} a run" if k in costs else "")
                         for k, (p, n) in pooled(data["measurements"]).items())
    if "scenarios" in last:
        costs = scenario_costs(data["measurements"])
        return ", ".join(f"{k} {v}" + (f" ${costs[k][1]:.2f}" if k in costs else "") for k, v in last["scenarios"].items())
    return last.get("outcome", "?")


def flat_routes(obj, path=""):
    """{route: its setting} of a routing table: each innermost object (a role's model and effort) is one route,
    written "model claude-opus-5-5, effort xhigh"; a value outside such an object is a route of its own."""
    if isinstance(obj, dict):
        if path and obj and all(not isinstance(v, (dict, list)) for v in obj.values()):
            return {path: ", ".join(f"{k} {v}" for k, v in obj.items())}
        out = {}
        for k, v in obj.items():
            out.update(flat_routes(v, f"{path}.{k}" if path else str(k)))
        return out
    return {path or "(the table)": obj if isinstance(obj, str) else json.dumps(obj)}


def routes_at(sha):
    text = git("show", f"{sha}:{ROUTING_TABLE}")
    if not text:
        return {}
    try:
        return flat_routes(json.loads(text))
    except ValueError as exc:
        return {"(the table)": f"not JSON ({exc})"}


def routing_change(base, head):
    """The routes that differ, [(route, before, after)], when the change's own diff touches the routing table;
    None when it does not."""
    if ROUTING_TABLE not in git("diff", "--name-only", base, head).splitlines():
        return None
    before, after = routes_at(base), routes_at(head)
    return [(k, before.get(k, "(none)"), after.get(k, "(none)")) for k in sorted(set(before) | set(after))
            if before.get(k) != after.get(k)]


def is_document(path):
    """A file that only documents: under docs/, or a Markdown file outside skills/ and agents/ (those are the
    pipeline's own instructions, so they change what is measured)."""
    return path.startswith("docs/") or (path.endswith(".md") and not path.startswith(("skills/", "agents/")))


def only_routing(base, head):
    """True when the change's own diff is the routing table: every file it changes is skills/_shared/models.json or
    a document. Only then are the served models left out of the environment match."""
    changed = [f for f in git("diff", "--name-only", base, head).splitlines() if f]
    return ROUTING_TABLE in changed and all(f == ROUTING_TABLE or is_document(f) for f in changed)


def same_env(x, y, ignore_models):
    drop = (lambda e: {k: v for k, v in e.items() if k != "models"}) if ignore_models else (lambda e: e)
    return drop(x["env"]) == drop(y["env"])


def route_rule(suite, bms, hms):
    """(incomparable, worse, reproduction) of repro:route:fixtures:<prefix>, the pooled rule for a routing change:
    see the module text. Only measurements that stored each run's record take part."""
    inc, worse = [], []
    b_runs, h_runs, kinds = {}, {}, {}
    for ms, runs in ((bms, b_runs), (hms, h_runs)):
        for m in ms:
            kinds.update(m.get("kinds") or {})
            for name, rs in (m.get("per_run") or {}).items():
                runs.setdefault(name, []).extend(rs)
    for side, runs in (("base", b_runs), ("head", h_runs)):
        if not runs:
            inc.append(no_raw_usage(suite, side, suite))
    if inc:
        return inc, worse, None
    counts = {"planted": [0, 0], "clean": [0, 0]}
    cost, n_runs, clean_ok, clean_runs = [0.0, 0.0], [0, 0], 0, 0
    trials, per_round, planted_runs = [0, 0], 0, 0  # planted item-trials per side; items in one run of each fixture
    for name in sorted(set(b_runs) | set(h_runs)):
        b, h = b_runs.get(name, []), h_runs.get(name, [])
        kind = kinds.get(name)
        if len(b) != len(h):
            inc.append(f"fixture {name}: {len(b)} runs at base, {len(h)} at head (measure both sides alike)")
            continue
        if kind not in ("planted", "clean", "other"):
            inc.append(f"fixture {name} has no kind (planted, clean, or other) in the instrument's records: measure "
                       f"with an instrument whose fixture_expectations.py gives every fixture one")
            continue
        if kind == "planted" and any(r.get("problems") is None for r in b + h):
            inc.append(f"fixture {name}: a run records no problem count: measure with an instrument that counts them")
            continue
        if kind == "planted" and any(not isinstance(r.get("items"), int) for r in b + h):
            inc.append(f"fixture {name}: a run records no count of the planted items it checked (measured before "
                       "agent_fixtures.py wrote one): measure both sides again with an instrument that records it")
            continue
        for i, rs in enumerate((b, h)):
            for r in rs:
                cost[i] += run_cost(r.get("usage"))[1]
                n_runs[i] += 1
        if kind == "planted":
            counts["planted"][0] += sum(r["problems"] for r in b)
            counts["planted"][1] += sum(r["problems"] for r in h)
            for i, rs in enumerate((b, h)):
                trials[i] += sum(r["items"] for r in rs)
            per_round += max(r["items"] for r in b + h) if b + h else 0
            planted_runs = max(planted_runs, len(b))
        elif kind == "clean":
            counts["clean"][0] += 1
            clean_runs += len(h)
            clean_ok += sum(1 for r in h if r.get("pass") is True)
        else:
            bp, hp = sum(1 for r in b if r.get("pass") is True), sum(1 for r in h if r.get("pass") is True)
            if hp < bp:
                worse.append(f"fixture {name} ({kind}): {bp}/{len(b)} at base, {hp}/{len(h)} at head")
    if inc:
        return inc, worse, None
    planted = sum(1 for n in b_runs if kinds.get(n) == "planted")
    bd, hd = cost[0] / max(n_runs[0], 1), cost[1] / max(n_runs[1], 1)
    if planted and min(trials) < ROUTE_MIN_TRIALS:
        need = -(-ROUTE_MIN_TRIALS // per_round) if per_round else 0
        inc.append(f"{suite}: {trials[0]} planted item-trials at base and {trials[1]} at head ({per_round} planted "
                   f"item(s) a run, {planted_runs} run(s)); the rule needs at least {ROUTE_MIN_TRIALS} on each side: "
                   + (f"bench both sides with --runs {need} to reach it" if need else
                      "the planted fixtures check no item, so no number of runs reaches it"))
        return inc, worse, None
    if n_runs[0] and not bd:
        inc.append(unpriced_base(suite))
        return inc, worse, None
    bp, hp = counts["planted"]
    checks = [(planted > 0, f"{planted} planted fixture(s)"),
              (counts["clean"][0] > 0, f"{counts['clean'][0]} clean fixture(s)"),
              (hp <= bp, f"planted problems {bp} at base, {hp} at head"),
              (clean_runs > 0 and clean_ok == clean_runs, f"clean runs passing at head {clean_ok}/{clean_runs}"),
              (n_runs[0] > 0 and hd <= 0.8 * bd, f"${bd:.2f} -> ${hd:.2f} a run" + (f" ({hd / bd:.2f} of base, at "
                                                                                     f"most 0.80)" if bd else ""))]
    how = "; ".join(text for _, text in checks)
    return inc, worse, (f"route {suite.removeprefix('repro:').removeprefix('route:')}", all(ok for ok, _ in checks), how)


def compare(base_sha, head_sha, suites, inst_sha):
    """(verdict, reasons, rows) by the rule fixed in advance."""
    worse, incomparable, repro, rows = [], [], [], []
    routing = routing_change(base_sha, head_sha)
    ignore_models = routing is not None and only_routing(base_sha, head_sha)
    if routing is not None:
        rows.append({"suite": "model routing changed", "note": True,
                     "routes": [{"route": k, "before": v, "after": w} for k, v, w in routing],
                     "base": "; ".join(f"{k}: {v}" for k, v, _ in routing) or "no route differs",
                     "head": "; ".join(f"{k}: {v}" for k, _, v in routing) or "no route differs"})
    for s in suites:
        is_repro = s.startswith("repro:")
        inner = s.removeprefix("repro:")
        cost_repro, route = inner.startswith("cost:"), inner.startswith("route:")
        inner = inner.removeprefix("cost:").removeprefix("route:")
        b_all, h_all = stored(base_sha, s, inst_sha), stored(head_sha, s, inst_sha)
        if not b_all or not h_all:
            incomparable.append(f"{s} is not measured at {'base' if not b_all else 'head'}")
            continue
        b, h = b_all[-1], h_all[-1]
        if inner.startswith(("fixtures:", "scenario:")):
            pairs = [(x, y) for x in b_all for y in h_all if same_env(x, y, ignore_models)]
            if not pairs:
                only_models = any(same_env(x, y, True) for x in b_all for y in h_all)
                why = ""
                if only_models and routing is None:
                    why = (f"; only the served models differ, and a change meant to move work to another model changes "
                           f"{ROUTING_TABLE}")
                elif only_models:
                    why = (f"; only the served models differ, but this change touches more than {ROUTING_TABLE} and "
                           "documents, so the models it is served by are part of what it changed: change the routing "
                           "table on its own")
                incomparable.append(f"{s}: base and head were measured in different environments "
                                    f"({b['env']} / {h['env']}){why}")
                continue
            b, h = pairs[-1]
        rows.append({"suite": s, "base": summary_line(b), "head": summary_line(h)})
        bm, hm = b["measurements"][-1], h["measurements"][-1]
        if route:
            if not inner.startswith("fixtures:"):
                incomparable.append(f"{s}: the route rule judges fixtures only (repro:route:fixtures:<prefix>)")
                continue
            i, w, r = route_rule(s, b["measurements"], h["measurements"])
            incomparable += i
            worse += w
            if r:
                repro.append(r)
        elif s == "selftest":
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
            bc, hc = fixture_costs(b["measurements"]), fixture_costs(h["measurements"])
            for name, (p, n) in bp.items():
                hp_, hn = hp.get(name, (0, 0))
                costed = name in bc and name in hc
                cost = cost_text(bc[name], hc[name]) if costed else ""
                if not costed:
                    incomparable.append(no_raw_usage(f"fixture {name}", "base" if name not in bc else "head", s))
                if hn != n:
                    incomparable.append(f"fixture {name}: {n} runs at base, {hn} at head (measure both sides alike)")
                elif cost_repro and costed and not bc[name][1]:
                    incomparable.append(unpriced_base(f"fixture {name}"))
                elif cost_repro:
                    ok = hp_ * n >= p * hn and costed and hc[name][1] <= 0.8 * bc[name][1]
                    repro.append((f"fixture {name} cost", ok, f"{cost or 'no cost measured'}; passes {p}/{n} -> {hp_}/{hn}"))
                elif is_repro:
                    repro.append((f"fixture {name}", p < n and hp_ == hn, f"base {p}/{n}, head {hp_}/{hn}"))
                elif hp_ * n < p * hn:
                    worse.append(f"fixture {name}: {p}/{n} at base, {hp_}/{hn} at head")
                if not cost_repro and costed and hc[name][1] > 1.25 * bc[name][1]:
                    worse.append(f"fixture {name} costs more: {cost} (more than a quarter over, beyond run-to-run noise)")
        elif inner.startswith("scenario:"):
            bc, hc = scenario_costs(b["measurements"]), scenario_costs(h["measurements"])
            for name, st in bm["scenarios"].items():
                hst = hm["scenarios"].get(name)
                costed = name in bc and name in hc
                cost = cost_text(bc[name], hc[name], "a run") if costed else ""
                if not costed:
                    incomparable.append(no_raw_usage(f"scenario {name}", "base" if name not in bc else "head", s))
                if cost_repro and costed and not bc[name][1]:
                    incomparable.append(unpriced_base(f"scenario {name}"))
                elif cost_repro:
                    repro.append((f"scenario {name} cost", hst == "PASS" and costed and hc[name][1] <= 0.8 * bc[name][1],
                                  f"{cost or 'no cost measured'}; base {st}, head {hst}"))
                elif is_repro:
                    repro.append((f"scenario {name}", st == "FAIL" and hst == "PASS", f"base {st}, head {hst}"))
                elif st == "PASS" and hst != "PASS":
                    worse.append(f"scenario {name}: PASS at base, {hst or 'missing'} at head")
                if not cost_repro and costed and st == "PASS" and hc[name][1] > 1.25 * bc[name][1]:
                    worse.append(f"scenario {name} costs more: {cost} (more than a quarter over, beyond run-to-run noise)")
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
        if r.get("note"):
            print(f"model routing changed ({ROUTING_TABLE}): " + ("; ".join(
                f"{x['route']}: {x['before']} -> {x['after']}" for x in r["routes"]) or "the file changed, no route did"))
        else:
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


def read_verdict(text):
    """(verdict, why there is none): the last fenced JSON block of a checker's message, and only that one. A raw
    control character inside a string (a quoted command's tab or newline) does not void it; a last block that is not
    JSON is no verdict, never an earlier block (a draft, a quote) standing in for it."""
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text or "", flags=re.S)
    if not blocks:
        return None, "the message holds no fenced json block"
    try:
        return json.loads(blocks[-1], strict=False), ""
    except ValueError as exc:
        return None, f"its last json block does not parse ({exc})"


def last_json(text):
    return read_verdict(text)[0]


def fingerprint(base, head, suites=()):
    """What a review covers: the change's own diff, byte for byte (whitespace included, and each file's full blob ids
    so a binary file's content counts too) but without the hunk line numbers that move with the base; each file it
    touches, renames split into their old and new paths, as it was at the base; and why each reproduction failed at
    the base."""
    diff = subprocess.run(["git", "-C", str(repo()), "diff", "--no-renames", "--no-ext-diff", "--no-textconv",
                           "--full-index", f"{base}..{head}"], capture_output=True, text=True).stdout
    kept = [re.sub(r"^@@ -\d+(,\d+)? \+\d+(,\d+)? @@", "@@", line) for line in diff.splitlines()]
    names = subprocess.run(["git", "-C", str(repo()), "diff", "--no-renames", "--name-only", "-z", f"{base}..{head}"],
                           capture_output=True, text=True).stdout
    touched = [f for f in names.split("\0") if f]
    return {"diff_sha256": hashlib.sha256("\n".join(kept).encode()).hexdigest(),
            "touched": {f: git("rev-parse", "--verify", "--quiet", f"{base}:{f}") for f in touched},
            "repro_failures": {s: failure_reason(base, s, head) for s in suites if s.startswith("repro:")}}


ERROR_LINE = re.compile(r"^\s*[\w.]*(Error|Exception|Exit)\b")


def error_line(out):
    """The exception line of a test's output: the first unindented line after its last traceback's frames, or, in
    output without a traceback, its last error line; None when there is none."""
    lines = (out or "").splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith("Traceback (most recent call last):"):
            return next((l.strip() for l in lines[i + 1:] if l.strip() and not l.startswith(" ")), None)
    found = [l.strip() for l in lines if ERROR_LINE.match(l.strip())]
    return found[-1] if found else None


def run_varying_reduced(line):
    """An error line with what differs from one run of the same failure to the next reduced (paths, commit ids and
    addresses, numbers); its words and quoted text stay, so two different failed comparisons stay different."""
    t = re.sub(r"(~|\.{0,2})?(/[\w.@+-]+)+/?", "<path>", line)
    t = re.sub(r"\b(0x)?[0-9a-f]{7,}\b", "<id>", t)
    t = re.sub(r"\d+", "<n>", t)
    return re.sub(r"\s+", " ", t).strip()[:300]


def reason_of(m):
    """Why one measurement failed, in what stays the same from run to run: which fixtures, scenarios, or suites
    failed; for a test, its outcome and its exception line, run-varying text reduced. None when a test's exception
    line was not stored (a reason that cannot be told never passes for the same one)."""
    for field in ("fixtures", "scenarios", "suites"):
        if field in m:
            failed = sorted(k for k, v in m[field].items() if (not all(v) if isinstance(v, list) else v != "PASS"))
            return f"{field} failing: {', '.join(failed) or 'none'}"
    line = m.get("error") or error_line(m.get("tail"))
    return f"{m.get('outcome', 'no outcome')}: {run_varying_reduced(line)}" if line else None


def failure_reason(base, suite, instrument):
    """reason_of the latest measurement of a reproduction at the base; None when the base was never measured."""
    runs = stored(base, suite, instrument)
    return reason_of(runs[-1]["measurements"][-1]) if runs else None


def review_record(base, head, suites, pack):
    """What a review writes beside its result: the commits, when, the pack's hash, and the fingerprint of what it
    covers."""
    return {"base": base, "head": head, "reviewed": now(), "pack_sha256": hashlib.sha256(pack.read_bytes()).hexdigest(),
            **fingerprint(base, head, suites)}


def review_covers(meta, base, head, suites=()):
    """(covered, why not): a review of one commit still covers another when the change's own diff is the same, no file
    it touches changed underneath it, and each reproduction still fails at the base for the same reason; a rebase onto
    unrelated work does not buy a second review."""
    if meta.get("head") == head:
        return True, ""
    if not meta.get("diff_sha256"):
        return False, "the review recorded no fingerprint of the change"
    now = fingerprint(base, head, suites)
    if set(now["touched"]) != set(meta.get("touched", {})):
        return False, "it touches other files now"
    moved = sorted(f for f, blob in meta["touched"].items() if now["touched"].get(f) != blob)
    if moved:
        return False, f"{', '.join(moved)} changed underneath it"
    if now["diff_sha256"] != meta["diff_sha256"]:
        return False, "the change's own diff is different"
    reviewed = meta.get("repro_failures") or {}
    if set(reviewed) - set(now["repro_failures"]):
        return False, "the record's reproductions changed since the review"
    for suite in now["repro_failures"]:
        was, is_now = reviewed.get(suite), now["repro_failures"][suite]
        if was is None:
            return False, f"the review holds no failure reason for the reproduction {suite}"
        if is_now is None:
            return False, f"the new base was never measured on {suite}: bench it first"
        if is_now != was:
            return False, f"the reproduction {suite} fails at the new base for another reason ({is_now}; was {was})"
    return True, ""


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
    (out / "meta.json").write_text(json.dumps(review_record(base, head, suites, out / "pack.md")))
    result = out / "change-reviewer.result.md"
    data, why = read_verdict(result.read_text(encoding="utf-8")) if result.is_file() else (None, "no result file")
    body = re.sub(r"^Result:.*$", f"Result: {result}", text, count=1, flags=re.M)
    (HOME / "changes" / f"{cid}.md").write_text(body, encoding="utf-8")
    run_problem = reviewer_run_problem(out)
    if run_problem:
        return fail(f"{cid}: {run_problem}")
    if not data:
        return fail(f"{cid}: the reviewer returned no verdict: {why} ({(r.stdout + r.stderr)[-300:]})")
    problems = review_problems(data)
    print(f"{cid}: reviewer {data.get('verdict')}, {'accepted' if not problems else 'not accepted: ' + '; '.join(problems)} "
          f"-> {result}")
    return 0 if not problems else 1


def reviewer_run_problem(review):
    """Why the isolated change reviewer's run does not count, else None: its result is a review only when
    run_isolated.py's change-reviewer.summary.json says OK (INCONCLUSIVE: it ran no tool or skipped a required
    read; ERROR, LEAK, and the rest: the run itself failed)."""
    f = Path(review) / "change-reviewer.summary.json"
    try:
        s = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"the change reviewer's run left no readable {f.name}, so its result is not a review: review again"
    if not isinstance(s, dict):
        s = {}
    if s.get("status") == "OK":
        return None
    reason = s.get("reason") or s.get("unavailable_reason") or (
        f"{s['tool_uses']} tool use(s)" if isinstance(s.get("tool_uses"), int) else "no reason given")
    return (f"the change reviewer's run is {s.get('status') or 'without a status'} ({reason}), not OK, so its "
            "result is not a review: review again")


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
    run_problem = reviewer_run_problem(review) if review.is_dir() else None
    if run_problem:
        out.append(f"{cid}: {run_problem}")
    elif rp:
        out.append(f"{cid}: the isolated change review does not accept it: " + "; ".join(rp)[:400])
    elif not review_covers(meta, base, head, suites)[0]:
        out.append(f"{cid}: the review was of {str(meta.get('head'))[:12]}, the branch is at {head[:12]}, and "
                   f"{review_covers(meta, base, head, suites)[1]}: review again")
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
