#!/usr/bin/env python3
"""Run one gate round for a milestone, start to finish, in a fixed order (cheap and deterministic first).

Usage: gate_run.py <project> --milestone M<k> [--family auto|claude|codex] [--agents-dir <dir>] [--dry-run]
       gate_run.py <project> --milestone M<k> --intent-only      the standalone intent check (/loyal check)

Start it in the background: a round takes longer than one shell call may last. Progress lines go to
stdout and to <evidence>/progress.log; the result is <evidence>/verdict.json, with the round appended to
docs/project/reviews/M<k>.md. Evidence: .evidence/gate/M<k>/r<n>/ (n = the next round number).

Order:
  0. freeze: the live product fingerprint must equal state.md's Candidate; one gate per project at a time
  1. copies: gate_copies.py make (review, demo, blind); a FAIL skips every model review
  2. deterministic layer, written to layer1.json: gate.sh on the project, milestone_lint.py, intent_lock.py
     verify, rulings.py check, inbox.py check (no item dropped without a decision), then in the review copy the labeled test command and the "Gate command" and
     "Design lint" from gate.md, each through the heavy lock; a FAIL skips every model review
  3. code-verifier on the review copy, on the model family other than the builder's by default: a Claude Code
     builder gets --family auto (Codex when it can serve, else Claude, the switch recorded); a Codex builder
     (CODEX_THREAD_ID set, see session_env.py) gets Claude. --family overrides.
  4. loyal-evaluator on the blind copy, pass 1 (persona and commands), then pass 2 in the same session (the
     goal); a random canary token planted in the real project must never appear in its transcript
  5. the demo: code-verifier in demo mode on the untouched demo copy
  6. gate-judge on a verdict folder holding copies of every result and capture
  7. gate_report.py computes the verdict; the copies are deleted (their manifest stays in the evidence)
A checker that ends ERROR or INCONCLUSIVE is re-run once. Every step runs in its own process group, stopped
whole when it overruns or the round is stopped. A heavy step counts as NOT_RUN (the round INCONCLUSIVE) only
when heavy.py says BUSY, BLOCKED, or TIMEOUT, or this runner stopped it; any other exit is the step's own result.
A round that breaks writes verdict ERROR with the cause. Exit 0 when a verdict was written, 1 when the
round could not start (not frozen, another gate running) or broke, 2 on bad usage.

--intent-only runs steps 1, 4, 6, and 7 on the live tree (no freeze needed): the blind reconstruction and the
judge's intent diff, written to .evidence/loyal/M<k>/r<n>/ and a line in docs/project/reviews/intent-ledger.md;
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
from gate_keys import commands, read_keys  # noqa: E402
import local_only  # noqa: E402

PY = sys.executable
CHILD = None  # the step running now; a stopped round stops its whole process group


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
    try:
        CHILD = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 start_new_session=True)
    except FileNotFoundError as exc:
        return 127, str(exc)
    try:
        out, err = CHILD.communicate(timeout=timeout)
        return CHILD.returncode, out + err
    except subprocess.TimeoutExpired:
        stop_child()
        out, err = CHILD.communicate()
        return 124, (out or "") + (err or "") + f"\n(stopped after {timeout}s)"
    finally:
        CHILD = None


def heavy(cmd_line, cwd, timeout=1500):
    return run([PY, str(HERE / "heavy.py"), "run", "--timeout", str(timeout), "--", "/bin/sh", "-c", cmd_line],
               cwd=cwd, timeout=timeout + 600)


def layer1(r, review, keys):
    checks = []

    def record(name, code, out, skip_reason=None):
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
        log = r.ev / f"layer1-{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}.log"
        log.write_text(out if not skip_reason else f"{skip_reason}\n{out}")
        checks.append({"name": name, "status": status, "exit": code, "log": str(log),
                       **({"reason": skip_reason} if skip_reason else {})})
        r.say(f"  {status:<5} {name}" + (f" ({skip_reason})" if skip_reason else f" exit {code}"))

    before, _ = fingerprint(r.project, "product")
    gate_sh = HERE.parent / "gate.sh"
    code, out = heavy(f"bash {shlex.quote(str(gate_sh))} {shlex.quote(str(r.project))}", r.project)
    record("gate.sh", code, out)
    record("milestone_lint", *run([PY, str(HERE / "milestone_lint.py"), str(r.project / "docs/project/milestones.md")]))
    record("intent_lock verify", *run([PY, str(HERE / "intent_lock.py"), "verify", str(r.project / "docs/project/intent.md")]))
    record("rulings", *run([PY, str(HERE / "rulings.py"), "check", str(r.project)]))
    record("inbox", *run([PY, str(HERE / "inbox.py"), "check", str(r.project)]))
    cmds = commands(r.project)
    if cmds.get("test"):
        record("test suite", *heavy(cmds["test"], review))
    else:
        record("test suite", 0, "", skip_reason="no 'test:' line in AGENTS.md Commands")
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
    (r.ev / "layer1.json").write_text(json.dumps({"status": status, "checks": checks}, indent=2))
    return status


def isolated(r, role, workdir, render_args, extra=(), mode=None, resume=None, attempts=2):
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
    stem = f"{role}{'-demo' if mode == 'demo' else ''}{'-pass2' if resume else ''}"
    summary = {}
    for attempt in range(1, attempts + 1):
        run(cmd, timeout=4000)
        try:
            summary = json.loads((r.ev / f"{stem}.summary.json").read_text())
        except (OSError, ValueError):
            summary = {"status": "ERROR", "reason": "no summary written"}
        r.say(f"  {stem}: {summary.get('status')} (attempt {attempt}, tools {summary.get('tool_uses')})")
        if summary.get("status") not in ("ERROR", "INCONCLUSIVE"):
            break
    return summary


def main(argv):
    if not argv or argv[0].startswith("--"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    project = Path(argv[0]).resolve()
    opts = {argv[i]: argv[i + 1] for i in range(1, len(argv) - 1) if argv[i] in ("--milestone", "--family", "--agents-dir")}
    if "--milestone" not in opts:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    mid = opts["--milestone"]
    intent_only = "--intent-only" in argv
    lock = project / ".evidence/gate/round.running"
    fp, _ = fingerprint(project, "product")
    cand = candidate(project)
    if cand != fp and not intent_only:
        print(f"gate_run: not frozen: state.md Candidate is {cand}, the tree is {fp}. Freeze first (/dev freeze).",
              file=sys.stderr)
        return 1
    if "--dry-run" in argv:
        print(json.dumps({"milestone": mid, "fingerprint": fp, "would_run": "copies, layer1, code-verifier, "
                          "loyal-evaluator x2, demo, gate-judge, report"}))
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
        code, out = run([PY, str(HERE / "gate_copies.py"), "make", str(project), "--milestone", mid])
        copies = json.loads(out[out.index("{"):]) if "{" in out else {"status": "FAIL", "problems": {"make": [out[-300:]]}}
        (r.ev / "copies.json").write_text(json.dumps(copies, indent=2))
        base = copies.get("base")
        r.say(f"copies: {copies.get('status')}")
        review = Path(copies["review"]["path"]) if copies.get("review") else None
        proceed = copies.get("status") == "PASS"
        if proceed and not intent_only:
            r.say("deterministic layer:")
            proceed = layer1(r, review, keys) == "PASS"
        if proceed:
            canary.write_text(f"{token}\n")
            if not intent_only:
                r.say("code-verifier:")
                isolated(r, "code-verifier", review, ["--project", str(project), "--milestone", mid, "--copy",
                                                      str(review)], extra=["--family", r.family, "--canary", token])
            r.say("loyal-evaluator:")
            blind = Path(copies["blind"]["path"])
            p1 = isolated(r, "loyal-evaluator", blind, ["--project", str(project), "--pass", "1"],
                          extra=["--canary", token])
            if p1.get("status") == "OK" and p1.get("session_id"):
                isolated(r, "loyal-evaluator", blind, ["--project", str(project), "--pass", "2"],
                         extra=["--canary", token], resume=p1["session_id"])
            demo = Path(copies["demo"]["path"])
            if not intent_only:
                r.say("demo:")
                isolated(r, "code-verifier", demo, ["--project", str(project), "--milestone", mid, "--mode", "demo"],
                         extra=["--canary", token], mode="demo")
            verdict_dir = Path(base) / "verdict"
            verdict_dir.mkdir()
            inputs = []
            for name in ("layer1.json", "code-verifier.result.md", "loyal-evaluator.result.md",
                         "loyal-evaluator-pass2.result.md", "code-verifier-demo.result.md"):
                if (r.ev / name).exists():
                    shutil.copy(r.ev / name, verdict_dir / name)
                    inputs += ["--inputs", str(r.ev / name)]
            captures = demo / ".demo-captures"
            if captures.is_dir():
                shutil.copytree(captures, verdict_dir / "captures")
                shutil.copytree(captures, r.ev / "captures", dirs_exist_ok=True)
            r.say("gate-judge:")
            isolated(r, "gate-judge", verdict_dir, ["--project", str(project), "--milestone", mid, "--round", str(r.n),
                                                     *inputs] + (["--intent-only"] if intent_only else []),
                     extra=["--canary", token])
        r.say("report:")
        code, out = run([PY, str(HERE / "gate_report.py"), str(project), "--milestone", mid, "--round", str(r.n),
                         "--evidence", str(r.ev), "--fingerprint", fp] + (["--intent-only"] if intent_only else []))
        r.say(out.strip()[-1200:])
        return 0 if code == 0 else 1
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
        canary.unlink(missing_ok=True)
        if base and Path(base).exists():
            run([PY, str(HERE / "gate_copies.py"), "cleanup", base, "--dest", str(Path(base).parent)])
        lock.unlink(missing_ok=True)
        if r is not None:
            r.log.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
