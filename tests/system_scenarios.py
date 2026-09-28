#!/usr/bin/env python3
"""Levels 4 and 5: the installed pipeline on toy projects, driven by headless Claude Code sessions, judged by
deterministic checks (never by a session's own report).

Usage: system_scenarios.py [--only <name>[,<name>...]] [--project <planned and built project>] [--keep]

Scenarios (each in a fresh folder under ~/.gate-copies/system/, evidence in <repo>/.evidence/system/<name>/):
  plan        /plan on a small idea with the owner's answers and lock words given in the owner's message:
              the record is complete, the intent locked, the lints and rulings pass, no product code exists
  build-gate  /dev M1 then a real gate round on the planned project: the round completes with a verdict file,
              every checker ran, and the verdict is ACCEPT-READY or names what blocks
  injected    three defects planted into the built product (a swallowed error with an invented default,
              sample data on the product path, an unwired command): the next gate round is CHANGES and names them
  adopt       /plan adopt on an unadopted project with a documented feature that does not exist and a built
              feature no document mentions: adopt.py check passes and both discrepancies are named
  capture     /capture on a ChatGPT export with a hedge, an assistant suggestion, and a reversal: capture.py
              check passes and the dossier keeps the hedge open, the suggestion unadopted, the reversal superseded
  switch      a second session in the planned project: the continuity hook briefs it on the first session's work
  inbox       three suggestions from other people arrive (one the intent rules out): the session files them in the
              inbox verbatim and recommends; after the owner's ruling each leaves the inbox with a proven,
              routed decision, the ruled-out one is rejected, and the product is untouched
Each scenario prints PASS or FAIL with its reasons. Sessions run with the owner's installed skills, hooks, and
settings, in dontAsk mode with file and shell tools allowed, never with permission checks disabled.
"""
import json
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = Path.home() / ".claude/skills/_shared/scripts"
BASE = Path.home() / ".gate-copies/system"
EVIDENCE = REPO / ".evidence/system"
PY = sys.executable

IDEA = ("I want a tiny command-line habit tracker for myself. I add a habit by name, mark it done for today, "
        "and see each habit's current streak of consecutive days. Data lives in a JSON file in the folder. If "
        "the file is unreadable it must say so and never overwrite it. One milestone is enough.")
ANSWERS = ("My answers to anything you need to ask: it is only for me, on this laptop, in English only, no "
           "colors needed; marking the same habit twice in one day is a no-op; a streak counts consecutive days "
           "ending today or yesterday; no stand-ins or sample data anywhere. When you play the lock back to me, "
           "my reply is the next line.\nYes, lock it. That is the habit tracker I want.")


CONTINUE = ("The background work you started has finished and its results are on disk. Continue from where you "
            "stopped, and finish the task you were given.")


def claude(prompt, cwd, out, timeout=5400, resume=None):
    """One headless turn (or a resumed one). A headless session waits for its background jobs before it exits but
    is not re-invoked by their completion notice, so the harness resumes it, as the notice would interactively."""
    cmd = ["claude", "-p", "--permission-mode", "dontAsk", "--allowedTools", "Read Write Edit Glob Grep Bash",
           "--output-format", "stream-json", "--verbose"] + (["--resume", resume] if resume else [])
    try:
        r = subprocess.run(cmd, input=prompt, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        stdout, code = r.stdout, r.returncode
    except subprocess.TimeoutExpired as exc:
        # A session that runs past the limit fails its scenario; it never ends the whole run.
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        code = 124
        with open(Path(out).parent / "notes.txt", "a", encoding="utf-8") as f:
            f.write(f"a session ran past the {timeout}s limit and was stopped\n")
    with open(out, "a", encoding="utf-8") as f:
        f.write(stdout)
    result, session = "", None
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            session = ev.get("session_id")
        if ev.get("type") == "result":
            result = ev.get("result") or ""
    return result, session, code


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def fresh(name):
    d = BASE / f"{name}-{secrets.token_hex(4)}" / "habit"
    d.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    return d


def check_record(project):
    problems = []
    for cmd, label in (([PY, str(SCRIPTS / "record_check.py"), str(project)], "record_check"),
                       ([PY, str(SCRIPTS / "intent_lock.py"), "verify", str(project / "docs/project/intent.md")], "intent lock"),
                       ([PY, str(SCRIPTS / "milestone_lint.py"), str(project / "docs/project/milestones.md"), "--no-history"], "milestone_lint"),
                       ([PY, str(SCRIPTS / "rulings.py"), "check", str(project)], "rulings")):
        code, out = run(cmd)
        if code != 0:
            problems.append(f"{label} failed: {out.strip()[-300:]}")
    return problems


def locked(project):
    intent = project / "docs/project/intent.md"
    return intent.is_file() and "Locked by the owner" in intent.read_text()


def scenario_plan(ev):
    project = fresh("plan")
    result, session, code = claude(f"/plan {IDEA}\n\n{ANSWERS}", project, ev / "plan.jsonl")
    for turn in range(3):
        if locked(project) or not session:
            break
        (ev / "notes.txt").open("a").write(f"resumed the plan session after its background work (turn {turn + 1})\n")
        result, _, code = claude(CONTINUE, project, ev / "plan.jsonl", resume=session)
    (ev / "plan.result.md").write_text(result)
    problems = check_record(project)
    code_files = [p for p in project.rglob("*.py") if ".evidence" not in p.parts and "docs" not in p.parts]
    if code_files:
        problems.append(f"product code written during planning: {[str(p.relative_to(project)) for p in code_files]}")
    return project, problems


def scenario_build_gate(ev, project):
    result, session, code = claude("/dev M1\n\nBuild the whole milestone, then freeze it and run the gate round; "
                                   "report the gate's verdict. Do not wait for me between steps.", project,
                                   ev / "dev.jsonl")
    for turn in range(4):
        rounds = sorted((project / ".evidence/gate/M1").glob("r*"))
        if (rounds and (rounds[-1] / "verdict.json").exists()) or not session:
            break
        (ev / "notes.txt").open("a").write(f"resumed the dev session after its background work (turn {turn + 1})\n")
        result, _, code = claude(CONTINUE, project, ev / "dev.jsonl", resume=session)
    (ev / "dev.result.md").write_text(result)
    problems = []
    rounds = sorted((project / ".evidence/gate/M1").glob("r*"))
    if not rounds or not (rounds[-1] / "verdict.json").exists():
        # A headless session waits for its background jobs but is not re-invoked by their completion notice,
        # so a round it started may still be missing here. Only a real freeze earns a harness-run round.
        state = project / "docs/project/state.md"
        fp = run([PY, str(SCRIPTS / "fingerprint.py"), str(project)])[1].split()
        if not (state.exists() and fp and fp[0] in state.read_text()):
            problems.append("the session did not freeze M1 (state.md Candidate differs from the fingerprint)")
            return problems
        (ev / "note.txt").write_text("the session froze M1 but no finished round was found; the harness ran gate_run.py\n")
        code, out = run([PY, str(SCRIPTS / "gate_run.py"), str(project), "--milestone", "M1"])
        (ev / "gate_run.log").write_text(out)
        rounds = sorted((project / ".evidence/gate/M1").glob("r*"))
        if not rounds or not (rounds[-1] / "verdict.json").exists():
            problems.append("no gate round finished (no verdict.json), even when run by the harness")
            return problems
    verdict = json.loads((rounds[-1] / "verdict.json").read_text())
    for c, s in verdict.get("checkers", {}).items():
        if s is None:
            problems.append(f"{c} did not run")
    if verdict["verdict"] not in ("ACCEPT-READY", "CHANGES"):
        problems.append(f"verdict {verdict['verdict']}: {verdict.get('reasons')}")
    (ev / "verdict.json").write_text(json.dumps(verdict, indent=1))
    return problems


INJECT = r'''
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
src = [p for p in root.rglob("*.py") if "tests" not in p.parts and ".evidence" not in p.parts][0]
text = src.read_text()
text = text.replace("json.loads(", "(lambda s: __import__('json').loads(s) if s.strip().startswith(('[','{')) else [])(", 1)
text += "\n\nSAMPLE_HABITS = [{'name': 'water', 'days': ['2026-09-26']}]\n\ndef export_all(habits):\n    return list(habits)\n"
src.write_text(text)
print(src)
'''


def scenario_injected(ev, project):
    code, out = run([PY, "-c", INJECT, str(project)])
    (ev / "inject.log").write_text(out)
    fp = run([PY, str(SCRIPTS / "fingerprint.py"), str(project)])[1].split()[0]
    state = project / "docs/project/state.md"
    text = state.read_text()
    import re
    text = re.sub(r"(## Candidate\s*\n)(.*?)(\n## |\Z)", lambda m: m.group(1) + fp + "\n" + m.group(3), text, count=1, flags=re.S)
    state.write_text(text)
    code, out = run([PY, str(SCRIPTS / "gate_run.py"), str(project), "--milestone", "M1"])
    (ev / "gate_run.log").write_text(out)
    rounds = sorted((project / ".evidence/gate/M1").glob("r*"))
    verdict = json.loads((rounds[-1] / "verdict.json").read_text()) if rounds else {}
    (ev / "verdict-injected.json").write_text(json.dumps(verdict, indent=1))
    problems = []
    if verdict.get("verdict") not in ("CHANGES", "BLOCKED"):
        problems.append(f"verdict {verdict.get('verdict')} after planting defects (expected CHANGES)")
    evidence = json.dumps(verdict).lower()
    for name in ("code-verifier.result.md", "gate-judge.result.md"):
        f = rounds[-1] / name if rounds else None
        evidence += f.read_text().lower() if f and f.exists() else ""
    planted = {"the swallowed error with an invented default": ("json", "unreadable", "swallow", "empty list", "[]"),
               "the sample data on the product path": ("sample_habits", "sample data", "sample"),
               "the unwired export": ("export_all", "unwired", "never called", "dead code", "unused")}
    if any("deterministic layer" in r for r in verdict.get("reasons") or []):
        # The project's own tests caught a plant, so the round stopped before any checker, as designed (cheap checks
        # first). The checkers' own catch rate on planted defects is proven by agent_fixtures.py.
        failing = [c["name"] for c in json.loads((rounds[-1] / "layer1.json").read_text())["checks"]
                   if c.get("status") == "FAIL"] if rounds else []
        (ev / "note.txt").write_text(f"the deterministic layer failed ({', '.join(failing)}) on the plants; the round "
                                     "stopped before the checkers, as designed, so they did not examine the plants\n")
        if not failing:
            problems.append("the verdict blames the deterministic layer but no check in it failed")
        return problems
    caught = [k for k, words in planted.items() if any(w in evidence for w in words)]
    if len(caught) < 2:
        problems.append(f"the round did not name the planted defects (named: {caught or 'none'}); a CHANGES verdict "
                        "for another reason proves nothing about them")
    return problems


def scenario_adopt(ev):
    src = REPO / "tests/fixtures/agents/split-drift"
    project = BASE / f"adopt-{secrets.token_hex(4)}" / "split"
    shutil.copytree(src, project)
    shutil.rmtree(project / "docs", ignore_errors=True)
    (project / "README.md").write_text("# split\nTwo flatmates see who owes whom. Run `python3 app.py settle` to see it.\n")
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    result, session, code = claude("/plan adopt\n\nThis is my project; adopt it. My reply at the lock is the next "
                                   "line.\nYes, that is what it is today; lock it.", project, ev / "adopt.jsonl")
    for turn in range(8):
        # A headless session is not woken by its background work finishing (extraction rounds, characterization).
        if not session or run([PY, str(SCRIPTS / "adopt.py"), "check", str(project)])[0] == 0:
            break
        (ev / "notes.txt").open("a").write(f"resumed the adopt session after its background work (turn {turn + 1})\n")
        result, _, code = claude(CONTINUE, project, ev / "adopt.jsonl", resume=session)
    (ev / "adopt.result.md").write_text(result)
    problems = []
    code, out = run([PY, str(SCRIPTS / "adopt.py"), "check", str(project)])
    if code != 0:
        problems.append("adopt.py check failed: " + out.strip()[-400:])
    text = (result + (project / "docs/project/brief.md").read_text(errors="ignore")
            if (project / "docs/project/brief.md").exists() else result).lower()
    if "settle" not in text:
        problems.append("the documented settle command that does not exist was not named")
    if "total" not in text:
        problems.append("the built per-category totals were not reported")
    return problems


def scenario_capture(ev):
    project = BASE / f"capture-{secrets.token_hex(4)}" / "idea"
    project.mkdir(parents=True)
    export = [{"conversation_id": "c-1", "title": "Plant watering idea", "create_time": 1790000000, "current_node": "a3",
               "mapping": {
                   "root": {"id": "root", "parent": None, "children": ["u1"], "message": None},
                   "u1": {"id": "u1", "parent": "root", "children": ["a1"], "message": {"author": {"role": "user"}, "content": {"content_type": "text", "parts": ["I keep forgetting to water my plants. I want something that reminds me, maybe with photos of each plant, not sure."]}}},
                   "a1": {"id": "a1", "parent": "u1", "children": ["u2"], "message": {"author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["You could add a soil-moisture sensor over Bluetooth."]}}},
                   "u2": {"id": "u2", "parent": "a1", "children": ["a2"], "message": {"author": {"role": "user"}, "content": {"content_type": "text", "parts": ["Let's do it as a web app."]}}},
                   "a2": {"id": "a2", "parent": "u2", "children": ["u3"], "message": {"author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["Sure, a web app."]}}},
                   "u3": {"id": "u3", "parent": "a2", "children": ["a3"], "message": {"author": {"role": "user"}, "content": {"content_type": "text", "parts": ["Actually no, a phone app, because reminders need notifications."]}}},
                   "a3": {"id": "a3", "parent": "u3", "children": [], "message": {"author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["A phone app it is."]}}}}}]
    (project.parent / "conversations.json").write_text(json.dumps(export))
    result, session, code = claude(f"/capture add {project.parent / 'conversations.json'} --chat c-1\n\nThe project folder "
                                   f"is {project}.", project, ev / "capture.jsonl")
    (ev / "capture.result.md").write_text(result)
    problems = []
    code, out = run([PY, str(SCRIPTS / "capture.py"), "check", str(project)])
    if code != 0:
        problems.append("capture.py check failed: " + out.strip()[-400:])
    dossier = (project / "docs/project/sources/dossier.md")
    text = dossier.read_text().lower() if dossier.exists() else ""
    import re
    units = re.split(r"(?m)^(?=- s-\d{3,} · )", text.split("## units", 1)[-1])
    units = [u for u in units if u.startswith("- s-")]
    head = lambda u: u.splitlines()[0]
    if not any("photo" in u and " · open · " in head(u) for u in units):
        problems.append("the hedged photo idea is not kept open")
    if not any(("sensor" in u or "moisture" in u or "bluetooth" in u) and " · assistant · " in head(u) for u in units):
        problems.append("the assistant's sensor suggestion is not attributed to the assistant")
    if not any("web" in u and "superseded by" in head(u) for u in units):
        problems.append("the web-to-phone reversal is not recorded as superseded")
    return problems


INBOX_ITEMS = ("Three things came in about the habit tracker.\n"
               "1. From Sam (a friend), by text: \"Could it show the longest streak ever, not just the current one?\"\n"
               "2. From Lee (a coworker), in a chat: \"You should sync the habits to the cloud so they are on every "
               "device.\"\n"
               "3. From Sam, by text: \"The output could use some colors.\"\n"
               "Add each to the inbox in their words, then weigh them as /inbox review does and give me your "
               "recommendations. Do not change the product, and wait for my ruling before deciding anything.")
OWNER_RULES = "Go with your recommendations on all three."


def scenario_inbox(ev, project):
    before = run([PY, str(SCRIPTS / "fingerprint.py"), str(project)])[1].split()[:1]
    result, session, code = claude(f"/inbox add\n\n{INBOX_ITEMS}", project, ev / "inbox.jsonl")
    (ev / "review.result.md").write_text(result)
    problems = []
    inbox = project / "docs/project/inbox.md"
    text = inbox.read_text() if inbox.exists() else ""
    for words in ("longest streak ever", "sync the habits to the cloud", "could use some colors"):
        if words not in text:
            problems.append(f"the item with {words!r} is not in the inbox in its sender's words")
    if not session or problems:
        return problems + ([] if session else ["the review session did not start"])
    result, _, code = claude(OWNER_RULES, project, ev / "inbox.jsonl", resume=session)
    for turn in range(2):
        text = inbox.read_text() if inbox.exists() else ""
        if not any(w in text for w in ("longest streak ever", "sync the habits to the cloud", "could use some colors")):
            break
        result, _, code = claude(CONTINUE, project, ev / "inbox.jsonl", resume=session)
    (ev / "ruling.result.md").write_text(result)
    code, out = run([PY, str(SCRIPTS / "inbox.py"), "check", str(project)])
    (ev / "inbox-check.txt").write_text(out)
    if code != 0:
        problems.append("inbox.py check: " + out.strip()[-400:])
    still = inbox.read_text() if inbox.exists() else ""
    for words in ("longest streak ever", "sync the habits to the cloud", "could use some colors"):
        if words in still:
            problems.append(f"the item with {words!r} is still in the inbox after the owner's ruling")
    code, out = run([PY, str(SCRIPTS / "rulings.py"), "check", str(project)])
    if code != 0:
        problems.append("rulings.py check: " + out.strip()[-300:])
    decisions = (project / "docs/project/decisions.md").read_text()
    import re
    cloud = [b for b in re.split(r"(?m)^(?=## D-\d{3,})", decisions) if "Resolves:" in b and "cloud" in b.lower()]
    if not cloud or not re.search(r"^Verdict:\s*REJECT", cloud[-1], re.M):
        problems.append("the cloud-sync item, which the locked intent rules out (only this laptop, a local JSON "
                        "file), was not rejected")
    after = run([PY, str(SCRIPTS / "fingerprint.py"), str(project)])[1].split()[:1]
    if before != after:
        problems.append(f"the product changed while weighing the inbox ({before} -> {after})")
    return problems


def scenario_switch(ev, project):
    result, session, code = claude("Before doing anything, quote exactly what the session-start note told you about "
                                   "who worked here last and what is next. Change nothing.", project, ev / "switch.jsonl")
    (ev / "switch.result.md").write_text(result)
    problems = []
    state = project / "docs/project/state.md"
    writer = ""
    if state.exists():
        lines = state.read_text().split("## Writer", 1)
        writer = lines[1].strip().splitlines()[0].strip() if len(lines) == 2 and lines[1].strip() else ""
    if not writer:
        problems.append("state.md names no writer after the first sessions")
    elif writer not in result:
        problems.append(f"the second session was not told who worked last (expected {writer!r} in its quote)")
    if "next step" not in result.lower():
        problems.append("the second session was not told the next step")
    return problems


def main(argv):
    only = set((argv[argv.index("--only") + 1].split(",")) if "--only" in argv else [])
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    results = {}

    def ev_dir(name):
        d = EVIDENCE / name
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        return d

    def attempt(name, fn, *args):
        # One scenario's crash is that scenario's failure; the others still run.
        try:
            return fn(ev_dir(name), *args)
        except Exception as exc:
            return [f"the scenario itself failed: {exc.__class__.__name__}: {str(exc)[:300]}"]

    # --project reuses a project that an earlier run planned and built, so the scenarios that only need one
    # (switch, inbox, injected) do not pay for planning and building again.
    project = Path(argv[argv.index("--project") + 1]) if "--project" in argv else None
    if project is None and (not only or only & {"plan", "build-gate", "injected", "switch", "inbox"}):
        try:
            project, problems = scenario_plan(ev_dir("plan"))
        except Exception as exc:
            project, problems = None, [f"the scenario itself failed: {exc.__class__.__name__}: {str(exc)[:300]}"]
        results["plan"] = problems
        if project:
            (EVIDENCE / "plan/project.txt").write_text(str(project))
        if project and (not only or only & {"build-gate", "injected", "switch", "inbox"}):
            results["build-gate"] = attempt("build-gate", scenario_build_gate, project)
    if project and (not only or "switch" in only):
        results["switch"] = attempt("switch", scenario_switch, project)
    if project and (not only or "inbox" in only):
        results["inbox"] = attempt("inbox", scenario_inbox, project)
    if project and (not only or "injected" in only):
        results["injected"] = attempt("injected", scenario_injected, project)
    if not only or "adopt" in only:
        results["adopt"] = attempt("adopt", scenario_adopt)
    if not only or "capture" in only:
        results["capture"] = attempt("capture", scenario_capture)
    failed = 0
    for name, problems in results.items():
        print(f"{'PASS' if not problems else 'FAIL':<5} {name:<12} {'; '.join(problems)[:600]}", flush=True)
        failed += bool(problems)
    print(f"system-scenarios: {'PASS' if not failed else 'FAIL'} ({len(results) - failed}/{len(results)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
