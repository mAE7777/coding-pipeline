#!/usr/bin/env python3
"""Run one gate round for a milestone, start to finish, in a fixed order (cheap and deterministic first).

Usage: gate_run.py <project> --milestone M<k> [--family auto|claude|codex] [--agents-dir <dir>] [--full] [--dry-run]
       gate_run.py <project> --milestone M<k> --intent-only      the standalone intent check (/loyal check)

Start it in the background: a round takes longer than one shell call may last. Progress lines go to
stdout and to <evidence>/progress.log; the result is <evidence>/verdict.json, with the round appended to
docs/project/reviews/M<k>.md. Evidence: .evidence/gate/M<k>/r<n>/ (n = the next round number).
--full makes the round full whatever regate_scope.py would decide (for example before /deploy).

Order:
  0. freeze: the live product fingerprint must equal state.md's Candidate; one gate per project at a time.
     The round's listing goes to candidate.txt, and regate_scope.py decide writes scope.json: round 1 is
     always full; a later round is focused only when the change since the last full round (or, after a
     hotfix, since the accepted candidate) is contained (see regate_scope.py). The progress log says which
     kind of round runs and why. A full round keeps a snapshot of the candidate's product files in
     .evidence/gate/M<k>/full-candidate/, the "since" of a later focused round.
  1. copies: gate_copies.py make (review, demo, blind; a focused round removes the blind copy at once, since
     no evaluator runs in it); a FAIL skips every model review
  2. deterministic layer, written to layer1.json: gate.sh on the project, milestone_lint.py, intent_lock.py
     verify, rulings.py check, inbox.py check (no item dropped without a decision); then in the review copy,
     each through the heavy lock: the labeled install (only when the copy holds no dependency folder:
     gate_copies.py copies node_modules, .venv, venv, .yarn, Pods, and "Dependency folders" whole, so a
     project installed in place needs none, and an install could rewrite the lockfile under review),
     typecheck, lint, and build commands, the labeled test command, every "check:" of every earlier accepted
     or gate-passed milestone in milestone order and then this milestone's own ("checkpoint M1.C2"; a check
     that is prose, a manual probe, needs a running server, or exits 126 or 127 is SKIP and listed in
     layer1.json's for_reviewer), the test file each wiring row of those milestones names (a missing test on a
     proven or wired row is FAIL "wiring test missing"; running it is the test command's job), the "Gate
     command" and "Design lint" from gate.md, and last "tree unchanged"; a FAIL skips every model review
  3. code-verifier on the review copy, with layer1.json in its pack, on the model family other than the
     builder's by default: a Claude Code builder gets --family auto (Codex when it can serve, else Claude, the
     switch recorded); a Codex builder (CODEX_THREAD_ID set, see session_env.py) gets Claude. --family
     overrides. A focused round runs it in re-verify mode (--mode reverify --scope scope.json, route
     code-verifier.reverify): the open findings or the hotfix's fixes, and the delta.
  4. loyal-evaluator on the blind copy, pass 1 (persona and commands), then pass 2 in the same session (the
     goal); a random canary token planted in the real project must never appear in its transcript. A
     focused round runs no evaluator: the last full round's results are CARRIED (scope.json names them).
  5. the demo: code-verifier in demo mode on the untouched demo copy
  6. gate-judge on a verdict folder holding copies of every result and capture (in a focused round, also
     carried-loyal-evaluator.result.md, carried-loyal-evaluator-pass2.result.md, and scope.json)
  7. gate_report.py computes the verdict; the copies are deleted (their manifest stays in the evidence). An
     ACCEPT-READY round keeps .evidence/gate/M<k>/accepted-candidate/, the "since" of a hotfix re-gate.
Each checker step passes its models.json route to run_isolated.py (code-verifier.review or .reverify,
loyal-evaluator, code-verifier.demo, gate-judge), which picks the model and effort. The judge gets --require-read 'captures/*'
when the verdict folder holds captures, so a judge that never opens one is INCONCLUSIVE.
A checker that ends ERROR or INCONCLUSIVE is re-run once, never more. When its route asked for another model
than models.json's escalate model, or a lower effort, the re-run moves to the escalate model and effort, and the
step's summary records escalated: true with the reason (a retry that is not escalated records why not). The
evaluator's later passes resume pass 1's session, so they run on the model and effort pass 1 actually ran with
(read from its summary; recorded as follows_pass1) and are never escalated.
Every step runs in its own process group, stopped whole when it overruns or the round is stopped. A heavy step counts as NOT_RUN (the round INCONCLUSIVE) only
when heavy.py says BUSY, BLOCKED, or TIMEOUT, or this runner stopped it; any other exit is the step's own result.
A round that breaks writes verdict ERROR with the cause. Exit 0 when a verdict was written, 1 when the
round could not start (not frozen, another gate running) or broke, 2 on bad usage.

--intent-only runs steps 1, 4, 6, and 7 on the live tree (no freeze needed): the blind reconstruction, then a
third pass in the same session that confirms every done example, must-not-lose item, and mechanism card directly
(no reviewer runs in an intent check), and the judge's intent diff, written to .evidence/loyal/M<k>/r<n>/ and a line in docs/project/reviews/intent-ledger.md;
the milestone's status is not touched.
"""
import datetime
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fingerprint import fingerprint  # noqa: E402
from gate_copies import DEP_DIRS, clone, resolution_probe, rewrite_paths  # noqa: E402
from gate_keys import commands, read_keys  # noqa: E402
from languages import CODE  # noqa: E402
import local_only  # noqa: E402
from milestone_lint import wiring_rows  # noqa: E402
import models  # noqa: E402
from project_policy import read as policy, valid, require, OFF_TEXT  # noqa: E402
import regate_scope  # noqa: E402

PY = sys.executable
CHILD = None  # the step running now; a stopped round stops its whole process group
WORKFLOW_LEASE = None
# The build checks a regression run starts with, in order, each with the labels AGENTS.md may give it.
BUILD_LABELS = (("install", ("install",)), ("typecheck", ("typecheck", "type-check", "type check", "types")),
                ("lint", ("lint",)), ("build", ("build",)))
# A checkpoint's check: is run only when it reads as a command; anything else goes to the reviewer (a SKIP is
# cheap, a false FAIL sends the builder after a defect that does not exist).
PROSE_WORDS = {"the", "then", "see", "sees", "should", "verify", "confirm", "that", "is", "are", "shows", "show",
               "appears", "until", "user", "click", "clicks", "open", "opens", "visit", "page", "screen", "manually",
               "manual", "observe", "expect", "expected", "ensure", "look", "when", "after", "before", "it", "its",
               "into", "must", "->", "=>", "\u2192"}
ARTICLES = {"a", "an"}
EXIT_WORDS = {"passes", "pass", "passing", "green", "succeeds", "succeed", "exits", "exit", "returns", "return",
              "with", "code", "status", "0", "zero", "ok", "clean", "cleanly", "runs", "run", "without", "errors",
              "error", "is", "and", "all", "tests"}
TOOLS = {"python", "python3", "pytest", "py.test", "node", "npm", "npx", "pnpm", "yarn", "bun", "bunx", "deno", "tsc",
         "eslint", "jest", "vitest", "playwright", "mocha", "cargo", "go", "make", "bash", "sh", "zsh", "ruby",
         "bundle", "rake", "rspec", "php", "composer", "phpunit", "java", "mvn", "gradle", "gradlew", "dotnet",
         "swift", "xcodebuild", "uv", "uvx", "poetry", "pipenv", "tox", "nox", "ruff", "mypy", "pyright", "flake8",
         "mix", "dart", "flutter", "zig", "cmake", "ctest", "ninja", "bazel", "grep", "test", "diff", "cmp", "jq",
         "ls", "cat", "wc", "sqlite3", "shellcheck", "true", "false"}
SERVER = re.compile(r"localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]")
SERVER_WORDS = {"serve", "server", "dev", "start", "watch", "--watch", "runserver", "uvicorn", "gunicorn", "nodemon"}


class WorkflowOff(Exception):
    pass


class Round:
    def __init__(self, project, mid, family, agents_dir, intent_only=False):
        self.project, self.mid, self.family, self.agents_dir = project, mid, family, agents_dir
        self.intent_only = intent_only
        base = project / f".evidence/{'loyal' if intent_only else 'gate'}/{mid}"
        base.mkdir(parents=True, exist_ok=True)
        rounds = [int(p.name[1:]) for p in base.glob("r*") if p.name[1:].isdigit()]
        self.n = max(rounds, default=0) + 1
        self.ev = base / f"r{self.n}"
        self.ev.mkdir()
        self.log = open(self.ev / "progress.log", "a", encoding="utf-8")

    def say(self, msg):
        line = f"{datetime.datetime.now().strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        self.log.write(line + "\n")
        self.log.flush()


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def candidate(project):
    state = project / "docs/project/state.md"
    if not state.is_file():
        return None
    m = re.search(r"^## Candidate\s*\n+(\S+)", state.read_text(encoding="utf-8"), flags=re.M)
    return m.group(1) if m else None


def stop_child():
    """Stop the running step and everything it started (checkers start servers and browsers)."""
    p = CHILD
    if p is None or p.poll() is not None:
        return
    for sig, wait in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
        try:
            os.killpg(p.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            p.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def run(cmd, cwd=None, timeout=None):
    global CHILD
    if WORKFLOW_LEASE and not valid(WORKFLOW_LEASE):
        raise WorkflowOff(OFF_TEXT)
    try:
        # No step reads this runner's input: a check that waits for a keypress fails at once instead of hanging.
        CHILD = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, start_new_session=True)
    except FileNotFoundError as exc:
        return 127, str(exc)
    try:
        started = time.monotonic()
        while True:
            if WORKFLOW_LEASE and not valid(WORKFLOW_LEASE):
                stop_child()
                raise WorkflowOff(OFF_TEXT)
            remaining = None if timeout is None else timeout - (time.monotonic() - started)
            if remaining is not None and remaining <= 0:
                raise subprocess.TimeoutExpired(cmd, timeout)
            try:
                out, err = CHILD.communicate(timeout=min(0.5, remaining) if remaining is not None else 0.5)
                return CHILD.returncode, out + err
            except subprocess.TimeoutExpired:
                continue
    except subprocess.TimeoutExpired:
        stop_child()
        out, err = CHILD.communicate()
        return 124, (out or "") + (err or "") + f"\n(stopped after {timeout}s)"
    finally:
        if CHILD is not None:
            for pipe in (CHILD.stdout, CHILD.stderr):
                if pipe is not None:
                    pipe.close()
        CHILD = None


def heavy(cmd_line, cwd, timeout=1500):
    return run([PY, str(HERE / "heavy.py"), "run", "--timeout", str(timeout), "--", "/bin/sh", "-c", cmd_line],
               cwd=cwd, timeout=timeout + 600)


def layer1_milestones(ms_text, mid):
    """(id, section) of every earlier accepted or gate-passed milestone in milestone order, then mid itself: the
    milestones whose checks and wiring tests layer 1 runs (regression-and-coverage-strategy.md)."""
    found = [(m.group(1), m.group(0)) for m in re.finditer(r"^## (M\d+) \u00b7.*?(?=^## |\Z)", ms_text or "",
                                                            flags=re.M | re.S)]
    ids = [m for m, _ in found]
    if mid not in ids:
        return []
    return [(m, text) for m, text in found[:ids.index(mid)]
            if re.search(r"^Status:\s*accepted", text, flags=re.M) or "gate-passed [x]" in text] + \
        [found[ids.index(mid)]]


def checkpoint_plan(ms_text, mid):
    """(milestone, id, check text) for every "check:" of the milestones layer 1 covers, in order."""
    plan = []
    for m, text in layer1_milestones(ms_text, mid):
        n = 0
        for line in text.splitlines():
            if not re.search(r"\bcheck:", line) or not line.lstrip().startswith("- "):
                continue
            n += 1
            cid = re.search(rf"\b{re.escape(m)}\.C\d+\b", line)
            plan.append((m, cid.group(0) if cid else f"{m}.check{n}", line.split("check:", 1)[1].strip()))
    return plan


def runnable(check, cmds):
    """(command, None) when a check: reads as a shell command the deterministic layer can run, else (None, why).
    Prose, a manual probe, an expectation beyond the exit status, or a check that needs a running server goes to
    the reviewer: when unsure, SKIP rather than a false FAIL."""
    spans = re.findall(r"`([^`]+)`", check)
    if len(spans) > 1:
        return None, "several commands with words between them"
    if spans:
        cmd = spans[0].strip()
        extra = [w for w in re.findall(r"[^\s.,;:()!?]+", re.sub(r"`[^`]+`", " ", check).lower())
                 if w not in EXIT_WORDS]
        if extra:
            return None, f"it names what to observe beyond the exit status ({' '.join(extra[:6])})"
        prose = PROSE_WORDS
    else:
        cmd = check.strip()
        if cmd.endswith("."):
            return None, "it reads as a sentence"
        prose = PROSE_WORDS | ARTICLES | EXIT_WORDS
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return None, "it does not parse as a shell command"
    low = [t.lower() for t in tokens]
    hits = [t for t in low if t in prose]
    if hits:
        return None, f"it reads as prose ({', '.join(hits[:4])})"
    if any(SERVER.search(t) for t in low) or set(low) & SERVER_WORDS or cmd in (cmds.get("run"), cmds.get("demo")):
        return None, "it needs or starts a running server"
    i = 0
    while i < len(tokens) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[i]):
        i += 1
    if i == len(tokens):
        return None, "it names no command"
    first = tokens[i]
    if "/" in first or first in TOOLS:
        return cmd, None
    if shutil.which(first) and any(t.startswith("-") or "/" in t or t in ("&&", "||", "|", ";", ">")
                                   for t in tokens[i + 1:]):
        return cmd, None
    return None, f"{first} is not a command the deterministic layer recognizes"


def test_paths(cell):
    """The paths a wiring row's Test cell names (a pytest node id or file:line reduced to the file)."""
    out = []
    for raw in re.split(r"[,;\s]+", cell.replace("`", " ")):
        t = re.sub(r"::.*$", "", raw.strip("'\"()[]").rstrip(".:"))
        t = re.sub(r":\d+(?::\d+)?$", "", t).split("#", 1)[0]
        while t.startswith("./"):
            t = t[2:]
        t = t.lstrip("/")
        if not t or t.startswith("<") or "://" in t:
            continue
        suffix = Path(t).suffix
        if suffix in CODE or suffix.lower() in CODE or \
                ("/" in t and not re.fullmatch(r"[A-Za-z]{1,3}/[A-Za-z]{1,3}", t)):  # not n/a or and/or
            out.append(t)
    return out


def wiring_plan(ms_text, mid):
    """(milestone, component, status, test paths) for each wiring row of the milestones layer 1 covers whose Test
    cell names a path."""
    plan = []
    for m, text in layer1_milestones(ms_text, mid):
        for cells in wiring_rows(text.splitlines()):
            if len(cells) < 7 or cells[0].startswith("<"):
                continue
            paths = test_paths(cells[5])
            if paths:
                plan.append((m, cells[0], cells[6].strip().lower(), paths))
    return plan


def install_needed(review, keys):
    """(needed, why): gate_copies.py copies the dependency folders whole (paths rewritten), so the copy needs an
    install only when it holds none; an install over copied dependencies could rewrite the lockfile under review."""
    names = {d.rstrip("/") for d in (*DEP_DIRS, *(keys.get("Dependency folders") or []))}
    held, level = [], [review]
    for _ in range(3):  # the copy's root, and a workspace's packages one or two folders down
        held += sorted(str((d / n).relative_to(review)) for d in level for n in names if (d / n).exists())
        if held:
            break
        level = [s for d in level for s in sorted(d.iterdir()) if s.is_dir() and not s.is_symlink()
                 and s.name not in names and not s.name.startswith(".")]
    if held:
        return False, f"the review copy holds the dependencies the candidate was built with ({', '.join(held)})"
    return True, "the review copy holds no dependency folder"


def layer1(r, review, keys):
    checks, for_reviewer, extra_out = [], [], {}
    logs = set()

    def record(name, code, out, skip_reason=None, detail=None, **fields):
        # A heavy job that never got to run, or ran out of time, says nothing about the product: NOT_RUN, so the
        # round is INCONCLUSIVE (run it again), never CHANGES for a defect that may not exist.
        # Only heavy.py's own words make it NOT_RUN: a test suite may exit 75 or 124 by itself.
        not_run = {75: ("BUSY", "the machine was busy: another heavy job held the lock for the whole wait"),
                   77: ("BLOCKED", "the heavy lock could not be opened"),
                   124: ("TIMEOUT", "timed out (hung, or the machine is overloaded)")}
        said = code in not_run and f"heavy.py: {not_run[code][0]}" in out
        stopped = code == 124 and "(stopped after" in out  # this runner's own limit on a hung step
        if not skip_reason and (said or stopped):
            skip_reason = not_run[code][1]
            status = "NOT_RUN"
        else:
            status = "SKIP" if skip_reason else ("PASS" if code == 0 else "FAIL")
        base = stem = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80]
        k = 1
        while stem in logs:  # two rows with one name keep two logs
            k += 1
            stem = f"{base}-{k}"
        logs.add(stem)
        log = r.ev / f"layer1-{stem}.log"
        log.write_text(out if not skip_reason else f"{skip_reason}\n{out}")
        checks.append({"name": name, "status": status, "exit": code, "log": str(log),
                       **({"reason": skip_reason} if skip_reason else {}), **({"detail": detail} if detail else {}),
                       **fields})
        said = skip_reason or detail
        r.say(f"  {status:<5} {name}" + (f" ({said})" if said else f" exit {code}"))
        return status

    before, _ = fingerprint(r.project, "product")
    gate_sh = HERE.parent / "gate.sh"
    code, out = heavy(f"bash {shlex.quote(str(gate_sh))} {shlex.quote(str(r.project))}", r.project)
    record("gate.sh", code, out)
    record("milestone_lint", *run([PY, str(HERE / "milestone_lint.py"), str(r.project / "docs/project/milestones.md")]))
    record("intent_lock verify", *run([PY, str(HERE / "intent_lock.py"), "verify", str(r.project / "docs/project/intent.md")]))
    record("rulings", *run([PY, str(HERE / "rulings.py"), "check", str(r.project)]))
    record("inbox", *run([PY, str(HERE / "inbox.py"), "check", str(r.project)]))
    cmds = commands(r.project)
    # What the reviewer used to re-run, in the order a regression run takes it: the build checks first.
    for label, aliases in BUILD_LABELS:
        cmd = next((cmds[a] for a in aliases if cmds.get(a)), None)
        if not cmd:
            continue  # a project without this label has nothing to run here
        if label == "install":
            needed, why = install_needed(review, keys)
            extra_out["install"] = {"ran": needed, "reason": why}
            if not needed:
                r.say(f"  -     install not run: {why}")
                continue
        record(label, *heavy(cmd, review), command=cmd)
    if cmds.get("test"):
        record("test suite", *heavy(cmds["test"], review))
    else:
        record("test suite", 0, "", skip_reason="no 'test:' line in AGENTS.md Commands")
    ms_path = r.project / "docs/project/milestones.md"
    ms_text = ms_path.read_text(encoding="utf-8") if ms_path.is_file() else ""
    for m, cid, text in checkpoint_plan(ms_text, r.mid):
        name = f"checkpoint {cid}"
        cmd, why = runnable(text, cmds)
        if cmd:
            code, out = heavy(cmd, review)
            if code not in (126, 127):
                record(name, code, out, milestone=m, command=cmd)
                continue
            why = f"exit {code}: the shell could not run it as a command"
        record(name, None, text, skip_reason=f"not a runnable command: {why}", milestone=m, check=text)
        for_reviewer.append({"milestone": m, "id": cid, "what": text, "why": why})
    for m, component, row_status, paths in wiring_plan(ms_text, r.mid):
        for p in paths:
            name = f"wiring test {m} {component}" + (f" ({p})" if len(paths) > 1 else "")
            if (review / p).exists():
                if cmds.get("test"):
                    record(name, 0, f"{p} exists; covered by the test suite command\n",
                           detail="covered by the test suite command", milestone=m, test=p)
                else:
                    record(name, None, "", skip_reason=f"{p} exists, but AGENTS.md has no test command that runs it",
                           milestone=m, test=p)
            elif row_status in ("proven", "wired"):
                record(name, 1, f"wiring test missing: {p} is not in the review copy, yet the row is {row_status}\n",
                       detail=f"wiring test missing: {p}", milestone=m, test=p)
            else:
                record(name, None, "", skip_reason=f"{p} is not there yet; the row is {row_status}, not proven or "
                       "wired", milestone=m, test=p)
    for label in ("Gate command", "Design lint"):
        if keys.get(label):
            record(label, *heavy(keys[label], review))
    after, _ = fingerprint(r.project, "product")
    if after != before:
        record("tree unchanged", 1, f"the product files changed while the deterministic layer ran ({before} -> {after}): "
               "a lint script with --fix, or a test writing into the project; the frozen candidate is no longer "
               "what was checked")
    else:
        record("tree unchanged", 0, f"{before} before and after")
    status = "FAIL" if any(c["status"] == "FAIL" for c in checks) else \
        "NOT_RUN" if any(c["status"] == "NOT_RUN" for c in checks) else "PASS"
    (r.ev / "layer1.json").write_text(json.dumps({"status": status, "checks": checks, "for_reviewer": for_reviewer,
                                                  **extra_out}, indent=2))
    return status


def ran_with(summary):
    """The --model and --effort flags that repeat the model and effort a run asked for (a resumed pass keeps
    them), and the record of them; empty when the summary does not say."""
    model, effort = summary.get("requested_model"), summary.get("requested_effort")
    if not model or not effort:
        return [], None
    return (["--model", model] if model != "default" else []) + ["--effort", effort], {"model": model, "effort": effort}


def escalation(first, route, resumed):
    """The flags for the retry after attempt 1 ended ERROR or INCONCLUSIVE, and the record of why. A routed role
    moves to models.json's escalate model and effort unless it already ran there; a resumed pass stays put."""
    said = f"attempt 1 ended {first.get('status')}" + (f" ({str(first.get('reason'))[:200]})" if first.get("reason") else "")
    if resumed:
        return [], {"escalated": False, "escalation_reason": f"{said}; a resumed pass stays on pass 1's model and effort"}
    if first.get("route_applies") is False:
        return [], {"escalated": False, "escalation_reason": f"{said}; the Codex family keeps its own model and effort"}
    try:
        esc = models.resolve(route)["escalate"]
        model, effort = first.get("requested_model"), first.get("requested_effort")
        if not model or not effort:  # attempt 1 left no routing record: what its route resolves to
            chosen = models.choose(route)
            model, effort = chosen["model"], chosen["effort"]
    except models.ModelsError as exc:
        return [], {"escalated": False, "escalation_reason": f"{said}; no escalation, model routing failed: {exc}"}
    why = models.escalation(model, effort, esc)
    if not why:
        return [], {"escalated": False, "escalation_reason": f"{said}; retried as routed ({model}, {effort}), "
                                                              "nothing to escalate"}
    return ["--model", esc["model"], "--effort", esc["effort"]], {
        "escalated": True, "escalation_reason": f"{said}; {why}, so the retry runs on {esc['model']} at {esc['effort']}",
        "first_attempt": {k: first.get(k) for k in ("status", "reason", "requested_model", "requested_effort",
                                                      "served_model")}}


def shadowed(route):
    """True when the personal override sets a shadow for this route (run_isolated.py runs it after the checker)."""
    try:
        return bool(models.shadow(route))
    except models.ModelsError:
        return False  # run_isolated records the routing problem


def shadow_copy(r, route, src):
    """A fresh copy of src for the shadow of a route whose checker changes its copy (the code-verifier's review,
    re-verify, and demo), made before the main run touches src; None when the route has no shadow or the copy
    still points into src. It sits beside src in the round's copies folder, so cleanup removes it in any case."""
    if not shadowed(route):
        return None
    dst = src.parent / f"shadow-{src.name}"  # never "<src>-shadow": the probe would find src's path inside it
    try:
        clone(src, dst)
        _, failed = rewrite_paths(src, dst)
        left = resolution_probe(src, dst)
    except (OSError, RuntimeError) as exc:
        failed, left = [str(exc)], []
    if failed or left:
        r.say(f"  {route}: the shadow copy still points into {src.name}; no shadow this round")
        shutil.rmtree(dst, ignore_errors=True)
        return None
    return dst


def isolated(r, role, workdir, render_args, extra=(), mode=None, resume=None, attempts=2, route=None, pin=None):
    """One checker step through run_isolated.py, re-run once when it ends ERROR or INCONCLUSIVE (never more).
    route names its models.json route; pin (a resumed pass) repeats pass 1's model and effort."""
    keys = read_keys(r.project)
    fence = [x for host in keys.get("Gate network") or [] for x in ("--network", host)] + \
        [x for path in keys.get("Gate read allow") or [] for x in ("--allow-read", path)]
    cmd = [PY, str(HERE / "run_isolated.py"), role, "--dir", str(workdir), "--out", str(r.ev),
           "--project", str(r.project), "--render", *render_args, "--", *extra, *fence]
    if mode:
        cmd += ["--mode", mode]
    if resume:
        cmd += ["--resume", resume]
    if r.agents_dir:
        cmd += ["--agent-file", str(Path(r.agents_dir) / f"{role}.md")]
    route = route or models.route_for(role, mode)
    cmd += ["--route", route]
    pin_flags, pinned = ran_with(pin) if pin else ([], None)
    cmd += pin_flags
    pass_no = render_args[render_args.index("--pass") + 1] if "--pass" in render_args[:-1] else None
    stem = f"{role}{'-demo' if mode == 'demo' else ''}" + \
        ((f"-pass{pass_no}" if pass_no and pass_no != "1" else "-pass2") if resume else "")
    summary, bump, record = {}, [], {}
    sdir = None
    if role == "code-verifier" and not resume:
        sdir = shadow_copy(r, route, Path(workdir))
        if sdir:
            cmd += ["--shadow-dir", str(sdir)]
    limit = 8000 if shadowed(route) else 4000  # a shadow runs after the checker, inside the same call
    for attempt in range(1, attempts + 1):
        run(cmd + bump, timeout=limit)
        try:
            summary = json.loads((r.ev / f"{stem}.summary.json").read_text())
        except (OSError, ValueError):
            summary = {"status": "ERROR", "reason": "no summary written"}
        r.say(f"  {stem}: {summary.get('status')} (attempt {attempt}, tools {summary.get('tool_uses')}, "
              f"{summary.get('requested_model', '?')} {summary.get('requested_effort', '?')})")
        if summary.get("status") not in ("ERROR", "INCONCLUSIVE"):
            break
        if attempt < attempts:
            bump, record = escalation(summary, route, bool(resume))
            r.say(f"  {stem}: retry: {record['escalation_reason']}")
    if sdir:
        shutil.rmtree(sdir, ignore_errors=True)  # the shadow keeps what it needs in <ev>/shadow/
    record.update({"follows_pass1": pinned} if pinned else {})
    if record:
        summary.update(record)
        if (r.ev / f"{stem}.summary.json").is_file():
            (r.ev / f"{stem}.summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def decide_scope(r, force_full):
    """scope.json for this round (regate_scope.py decide); a full round, with the reason, when it cannot decide."""
    out = r.ev / "scope.json"
    code, text = run([PY, str(HERE / "regate_scope.py"), "decide", str(r.project), "--milestone", r.mid, "--round",
                      str(r.n), "--out", str(out)] + (["--full"] if force_full else []))
    scope = regate_scope.load(out) if code == 0 else None
    if not isinstance(scope, dict) or scope.get("scope") not in ("focused", "full"):
        scope = {"scope": "full", "milestone": r.mid, "kind": None, "since": None, "changed_files": [],
                 "changed_lines": 0, "delta_patch": None, "findings": [], "fixes": [], "carried": {},
                 "reasons": [f"regate_scope.py could not decide (exit {code}: {text.strip()[-200:]}), so the round "
                             "is full"]}
        out.write_text(json.dumps(scope, indent=2))
    return scope


def main(argv):
    global WORKFLOW_LEASE
    if not argv or argv[0].startswith("--"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    project = Path(argv[0]).resolve()
    if not require(project):
        return 3
    WORKFLOW_LEASE = policy(project)
    opts = {argv[i]: argv[i + 1] for i in range(1, len(argv) - 1) if argv[i] in ("--milestone", "--family", "--agents-dir")}
    if "--milestone" not in opts:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    mid = opts["--milestone"]
    intent_only = "--intent-only" in argv
    lock = project / ".evidence/gate/round.running"
    fp, rows = fingerprint(project, "product")
    cand = candidate(project)
    if cand != fp and not intent_only:
        print(f"gate_run: not frozen: state.md Candidate is {cand}, the tree is {fp}. Freeze first (/dev freeze).",
              file=sys.stderr)
        return 1
    if "--dry-run" in argv:
        print(json.dumps({"milestone": mid, "fingerprint": fp, "would_run": "scope (regate_scope.py), copies, layer1, "
                          "code-verifier (review, or re-verify in a focused round), loyal-evaluator x2 (carried in a "
                          "focused round), demo, gate-judge, report"}))
        return 0
    lock.parent.mkdir(parents=True, exist_ok=True)
    # The lock appears with its content already in it (written aside, then linked into place), so a reader never
    # sees an empty lock from a live round; an empty or unreadable one older than a few seconds is stale.
    mine = lock.with_name(f".round.{os.getpid()}.tmp")
    mine.write_text(f"{os.getpid()} {mid}")
    try:
        for attempt in (1, 2):
            try:
                os.link(mine, lock)
                break
            except FileExistsError:
                try:
                    held, age = lock.read_text().split(), time.time() - lock.stat().st_mtime
                except OSError:
                    held, age = [], 0
                stale = (held and held[0].isdigit() and not alive(held[0])) or (not held and age > 5)
                if attempt == 1 and stale:
                    print(f"gate_run: removed a stale round lock ({' '.join(held) or 'empty'}); its round is no "
                          "longer running", file=sys.stderr)
                    lock.unlink(missing_ok=True)
                    continue
                print(f"gate_run: a gate round is already running in this project ({' '.join(held[1:]) or '?'}, "
                      f"pid {held[0] if held else '?'}); one round per project", file=sys.stderr)
                return 1
    finally:
        mine.unlink(missing_ok=True)
    # A round killed without cleanup leaves its canary behind: only one round runs, so any canary is stale.
    for old in (project / "docs/project").glob(".gate-canary-*.md"):
        old.unlink(missing_ok=True)
    local_only.ensure(project, ["/docs/project/.gate-canary-*", "/.evidence/"])
    def stopped(signum, frame):
        stop_child()
        sys.exit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, stopped)
    canary = project / f"docs/project/.gate-canary-{secrets.token_hex(4)}.md"
    token = f"CANARY-{secrets.token_hex(8)}"
    r = base = None
    try:
        from session_env import current  # noqa: E402
        builder, _ = current()
        r = Round(project, mid, opts.get("--family") or ("claude" if builder == "codex" else "auto"),
                  opts.get("--agents-dir"), intent_only)
        r.say(f"gate {mid} round {r.n} · {fp}")
        keys = read_keys(project)
        scope = None
        if not intent_only:
            regate_scope.write_listing(r.ev / "candidate.txt", fp, rows)
            scope = decide_scope(r, "--full" in argv)
            r.say(f"scope: {scope['scope']} round" + (f" ({scope['kind']})" if scope.get("kind") else "") + ": "
                  + "; ".join(scope.get("reasons") or []))
            if scope["scope"] == "full":
                r.say(regate_scope.keep_snapshot(project, mid, "full", r.n, fp, rows)[1])
        focused = bool(scope) and scope["scope"] == "focused"
        code, out = run([PY, str(HERE / "gate_copies.py"), "make", str(project), "--milestone", mid])
        copies = json.loads(out[out.index("{"):]) if "{" in out else {"status": "FAIL", "problems": {"make": [out[-300:]]}}
        (r.ev / "copies.json").write_text(json.dumps(copies, indent=2))
        base = copies.get("base")
        r.say(f"copies: {copies.get('status')}")
        if focused and copies.get("blind"):
            shutil.rmtree(copies["blind"]["path"], ignore_errors=True)  # no evaluator runs in a focused round
            r.say("blind copy removed: the evaluator's results are carried")
        review = Path(copies["review"]["path"]) if copies.get("review") else None
        proceed = copies.get("status") == "PASS"
        if proceed and not intent_only:
            r.say("deterministic layer:")
            proceed = layer1(r, review, keys) == "PASS"
        if proceed:
            canary.write_text(f"{token}\n")
            layer1_arg = ["--layer1", str(r.ev / "layer1.json")]
            if focused:
                r.say("code-verifier (re-verify):")
                isolated(r, "code-verifier", review, ["--project", str(project), "--milestone", mid, "--mode", "reverify",
                                                      "--scope", str(r.ev / "scope.json"), *layer1_arg],
                         extra=["--family", r.family, "--canary", token], mode="reverify", route="code-verifier.reverify")
            elif not intent_only:
                r.say("code-verifier:")
                isolated(r, "code-verifier", review, ["--project", str(project), "--milestone", mid, "--copy",
                                                      str(review), *layer1_arg],
                         extra=["--family", r.family, "--canary", token], route="code-verifier.review")
            carried = []
            if focused:
                for stem, c in (scope.get("carried") or {}).items():
                    if Path(c.get("result") or "").is_file():
                        shutil.copy(c["result"], r.ev / f"carried-{stem}.result.md")
                        carried.append(f"carried-{stem}.result.md")
                r.say("loyal-evaluator: CARRIED: " + (", ".join(f"{s} from r{c.get('round')} ({c.get('fingerprint')})"
                                                              for s, c in (scope.get("carried") or {}).items())
                                                    or "nothing to carry"))
            else:
                r.say("loyal-evaluator:")
                blind = Path(copies["blind"]["path"])
                p1 = isolated(r, "loyal-evaluator", blind, ["--project", str(project), "--pass", "1"],
                              extra=["--canary", token], route="loyal-evaluator")
                if p1.get("status") == "OK" and p1.get("session_id"):
                    # The later passes resume pass 1's session: same model and effort as pass 1 actually ran with.
                    p2 = isolated(r, "loyal-evaluator", blind, ["--project", str(project), "--pass", "2"],
                                  extra=["--canary", token], resume=p1["session_id"], route="loyal-evaluator", pin=p1)
                    if intent_only and p2.get("status") == "OK":
                        # No reviewer runs in an intent check, so after the blind passes the same evaluator confirms
                        # every named item directly: completeness never depends on what a blind run happened to try.
                        isolated(r, "loyal-evaluator", blind, ["--project", str(project), "--pass", "3", "--milestone", mid],
                                 extra=["--canary", token], resume=p1["session_id"], route="loyal-evaluator", pin=p1)
            demo = Path(copies["demo"]["path"])
            if not intent_only:
                r.say("demo:")
                isolated(r, "code-verifier", demo, ["--project", str(project), "--milestone", mid, "--mode", "demo"],
                         extra=["--canary", token], mode="demo", route="code-verifier.demo")
            verdict_dir = Path(base) / "verdict"
            verdict_dir.mkdir()
            inputs = []
            for name in ("layer1.json", "code-verifier.result.md", "loyal-evaluator.result.md",
                         "loyal-evaluator-pass2.result.md", "loyal-evaluator-pass3.result.md",
                         "code-verifier-demo.result.md", *carried, *(["scope.json"] if focused else [])):
                if (r.ev / name).exists():
                    shutil.copy(r.ev / name, verdict_dir / name)
                    inputs += ["--inputs", str(r.ev / name)]
            captures = demo / ".demo-captures"
            if captures.is_dir():
                shutil.copytree(captures, verdict_dir / "captures")
                shutil.copytree(captures, r.ev / "captures", dirs_exist_ok=True)
            # The judge must open every capture it is handed (its own minimum tool count is 0).
            has_captures = (verdict_dir / "captures").is_dir() and \
                any(p.is_file() for p in (verdict_dir / "captures").iterdir())
            r.say("gate-judge:")
            isolated(r, "gate-judge", verdict_dir, ["--project", str(project), "--milestone", mid, "--round", str(r.n),
                                                     *inputs] + (["--intent-only"] if intent_only else []),
                     extra=["--canary", token] + (["--require-read", "captures/*"] if has_captures else []),
                     route="gate-judge")
        r.say("report:")
        code, out = run([PY, str(HERE / "gate_report.py"), str(project), "--milestone", mid, "--round", str(r.n),
                         "--evidence", str(r.ev), "--fingerprint", fp] + (["--intent-only"] if intent_only else []))
        r.say(out.strip()[-1200:])
        verdict = regate_scope.load(r.ev / "verdict.json") or {}
        if not intent_only and verdict.get("verdict") == "ACCEPT-READY":
            # The candidate a hotfix re-gate measures from; a full round's own snapshot is this candidate already.
            rec = regate_scope.load(project / f".evidence/gate/{mid}/full-candidate.json") or {}
            source = project / f".evidence/gate/{mid}/full-candidate" if rec.get("round") == r.n else None
            r.say(regate_scope.keep_snapshot(project, mid, "accepted", r.n, fp, rows, source=source)[1])
        return 0 if code == 0 else 1
    except WorkflowOff:
        print(OFF_TEXT, file=sys.stderr)
        return 3
    except Exception as exc:
        # The round broke, not the product: say so where the verdict would be, never leave a silent half-round.
        msg = f"{exc.__class__.__name__}: {exc}"
        if r is not None:
            (r.ev / "verdict.json").write_text(json.dumps({
                "milestone": mid, "round": r.n, "fingerprint": fp, "verdict": "ERROR",
                "reasons": [f"the gate round itself failed ({msg[:300]}); fix the cause and run it again"]}, indent=2))
            r.say(f"ERROR: the round failed: {msg}")
        print(f"gate_run: ERROR: the round failed: {msg}", file=sys.stderr)
        return 1
    finally:
        stop_child()
        WORKFLOW_LEASE = None  # cleanup is allowed after revocation; no new workflow step is started
        canary.unlink(missing_ok=True)
        if base and Path(base).exists():
            run([PY, str(HERE / "gate_copies.py"), "cleanup", base, "--dest", str(Path(base).parent)])
        lock.unlink(missing_ok=True)
        if r is not None:
            r.log.close()


if __name__ == "__main__":
    if "--help" in sys.argv[1:3] or sys.argv[1:] == ["-h"]:
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
