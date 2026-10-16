#!/usr/bin/env python3
"""Levels 4 and 5: the installed pipeline on toy projects, driven by headless Claude Code sessions, judged by
deterministic checks (never by a session's own report).

Usage: system_scenarios.py [--only <name>[,<name>...]] [--project <planned and built project>] [--keep] [--dry-run]

Scenarios (each in a fresh folder under ~/.gate-copies/system/, evidence in <repo>/.evidence/system/<name>/):
  plan        /plan on a small idea with the owner's answers and lock words given in the owner's message:
              the record is complete, the intent locked, the lints and rulings pass, no product code exists
  build-gate  /dev M1 then a real gate round on the planned project: the round completes with a verdict file,
              every checker ran, and the verdict is ACCEPT-READY or names what blocks
  build-gate-3  a reading log planned as three milestones, then for each: /dev builds it and drives its gate
              rounds to ACCEPT-READY, and /gate accept records the owner's acceptance words; every round
              has a verdict and every checker ran, each milestone ends accepted, the rulings pass, and the
              last M3 round's demo replayed the demo endings of M1 and M2 (regression demos). Rounds per
              milestone are written to rounds.json. It runs only when named with --only: it is the most
              expensive scenario.
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
Each scenario prints PASS or FAIL with its reasons, then its cost. Sessions run with the owner's installed skills,
hooks, and settings, in dontAsk mode with file and shell tools allowed, never with permission checks disabled.

Cost: each scenario writes cost.json into its evidence folder (evolve.py reads it from there): the raw token
usage, by the model that served it, of the headless sessions it ran (their stream-json output, the *.jsonl files
in its evidence folder: each model call once, by message id, under the model the message names) and of the
isolated runs those sessions or the harness started (every run summary written under the scenario's projects'
.evidence while it ran, under its served model; Codex runs under codex:<model>, never priced). It adds the
dollars at list prices by this tree's spend.py, for the reader (null when its spend.py has no price table);
evolve.py computes its own from the raw usage.

--dry-run prints each chosen scenario's steps (build-gate-3's prompts, resumes, and checks; the others' line
above) and calls no model, makes no folder, and removes no evidence. An unknown name in --only is bad usage.
Exit 0 when every scenario passes, 1 otherwise, 2 on bad usage.
"""
import json
import re
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
CURRENT = {"projects": []}  # the projects the running scenario made or works in: where its isolated runs land
TOKEN_KEYS = ("input", "cache_write", "cache_read", "output")

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
    # The session's final answer, as the runner reads a checker's: the last turn's result event, with what was
    # written before an output-limit cut put back in front (the event holds only the resumed part).
    answers, texts, cut, session = [], [], [], None
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        kind = ev.get("type")
        if kind == "system" and ev.get("subtype") == "init":
            session = session or ev.get("session_id")
        elif kind == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    texts, cut = [], []
                elif isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text") or "")
        elif kind == "user":
            content = (ev.get("message") or {}).get("content")
            blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
            limit = any(isinstance(b, dict) and "output token limit" in (b.get("text") or "").lower() for b in blocks)
            cut = cut + ["".join(texts)] if limit else []
            texts = []
        elif kind == "result":
            answers.append("".join(cut) + (ev.get("result") or ""))
            texts, cut = [], []
    return (answers[-1] if answers else ""), session, code


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def fresh(name, folder="habit"):
    d = BASE / f"{name}-{secrets.token_hex(4)}" / folder
    d.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    CURRENT["projects"].append(d)
    return d


# ---------- cost ----------

def add_usage(acc, model, u):
    t = acc.setdefault(model, {k: 0 for k in TOKEN_KEYS})
    for k in TOKEN_KEYS:
        t[k] += u.get(k) or 0


def api_usage(u):
    """A model call's usage as the pipeline counts it (input, cache_write, cache_read, output)."""
    return {"input": u.get("input_tokens", 0) or 0, "cache_write": u.get("cache_creation_input_tokens", 0) or 0,
            "cache_read": u.get("cache_read_input_tokens", 0) or 0, "output": u.get("output_tokens", 0) or 0}


def stream_usage(path):
    """Raw usage by model of the headless sessions whose stream-json output one file holds (several turns appended,
    resumed ones included). Each model call counts once, by its message id, with the latest usage the stream gave
    it, under the model the message names (else the model its session started on). A turn whose stream holds no
    call with usage (stopped before one was written) counts its result event's usage under its session's model."""
    calls, fallback, model, seen_calls = {}, [], None, 0
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        kind = ev.get("type")
        if kind == "system" and ev.get("subtype") == "init":
            model, seen_calls = ev.get("model") or model, 0
        elif kind == "assistant":
            msg = ev.get("message") or {}
            if isinstance(msg.get("usage"), dict) and msg.get("id"):
                calls[msg["id"]] = (msg.get("model") or model or "unknown", api_usage(msg["usage"]))
                seen_calls += 1
        elif kind == "result" and not seen_calls and isinstance(ev.get("usage"), dict):
            fallback.append((model or "unknown", api_usage(ev["usage"])))
    usage = {}
    for m, u in list(calls.values()) + fallback:
        add_usage(usage, m, u)
    return usage


def isolated_usage(projects, since):
    """(raw usage by served model, runs counted, runs with no usage) of the isolated runs whose summaries were
    written under the projects' .evidence at or after since (a Codex run under codex:<model>)."""
    usage, runs, bare = {}, 0, 0
    for p in projects:
        ev = Path(p) / ".evidence"
        for s in sorted(ev.rglob("*.summary.json")) if ev.is_dir() else []:
            try:
                if s.stat().st_mtime < since:
                    continue
                d = json.loads(s.read_text())
            except (OSError, ValueError):
                continue
            u = d.get("usage") if isinstance(d, dict) else None
            if not isinstance(u, dict):
                bare += 1
                continue
            model = d.get("served_model") or d.get("model") or "unknown"
            add_usage(usage, f"codex:{model}" if d.get("family") == "codex" or u.get("family") == "codex" else model, u)
            runs += 1
    return usage, runs, bare


def dollars_of(usage):
    """Dollars at list prices of the Claude usage, by this tree's spend.py; None when it has no price table."""
    try:
        scripts = str(REPO / "skills/_shared/scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import spend
        return round(sum(spend.dollars(m, u)[0] for m, u in usage.items() if not m.startswith("codex")), 4)
    except (ImportError, AttributeError):
        return None


def record_cost(ev, projects, since):
    """Write the scenario's cost.json (see the module text) and return it."""
    sessions, streams = {}, sorted(Path(ev).glob("*.jsonl"))
    for f in streams:
        for m, u in stream_usage(f).items():
            add_usage(sessions, m, u)
    runs_usage, runs, bare = isolated_usage(projects, since)
    total = {}
    for part in (sessions, runs_usage):
        for m, u in part.items():
            add_usage(total, m, u)
    total = {m: u for m, u in total.items() if any(u.values())}
    cost = {"usage": total, "models": sorted(total), "dollars": dollars_of(total),
            "tokens": sum(sum(u.values()) for u in total.values()),
            "sessions": {"streams": [f.name for f in streams], "usage": sessions},
            "isolated": {"runs": runs, "without_usage": bare, "usage": runs_usage},
            "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since)),
            "projects": [str(p) for p in projects]}
    (Path(ev) / "cost.json").write_text(json.dumps(cost, indent=2))
    return cost


def cost_line(cost):
    if not cost:
        return "cost not recorded"
    d = f"${cost['dollars']:.2f} at list prices" if cost.get("dollars") is not None else "dollars not computed"
    return (f"cost: {cost['tokens'] / 1e6:.1f}M tokens, {d}, {len(cost['sessions']['streams'])} session stream(s), "
            f"{cost['isolated']['runs']} isolated run(s); models {', '.join(cost['models']) or 'none'}")


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


IDEA3 = ("I want a small command-line reading log for myself, built in three milestones, in this order. First, I "
         "add a book by title, author, and page count, and list my books. Second, I log the pages I read on a day "
         "and see each book's progress as a percentage of its page count. Third, I see a weekly summary: pages "
         "read on each of the last seven days, and the books I finished that week. Data lives in a JSON file in "
         "the folder. If the file is unreadable it must say so and never overwrite it.")
ANSWERS3 = ("My answers to anything you need to ask: it is only for me, on this laptop, in English only, no colors "
            "needed; a book's page count is required when adding it; logging pages past the last page caps the "
            "progress at 100 percent and marks the book finished on that day; the week is the seven days ending "
            "today; no stand-ins or sample data anywhere. Plan it as exactly three milestones, one for each part "
            "above. When you play the lock back to me, my reply is the next line.\n"
            "Yes, lock it. That is the reading log I want.")
DEV3 = ("/dev {m}\n\nBuild the whole milestone, then freeze it and run the gate round. If the round asks for "
        "changes, fix them, freeze again, and run the next round, until the verdict is ACCEPT-READY or BLOCKED. "
        "Report the last verdict. Do not wait for me between steps.")
ACCEPT3 = "/gate accept {m}\n\nI have looked at the demo and it does what I asked. I accept {m}."
MILESTONES3 = ("M1", "M2", "M3")


def steps_build_gate_3():
    """The three-milestone scenario as data: --dry-run prints these steps, and the run carries out the same ones."""
    steps = [{"name": "plan", "session": "new, in a fresh folder named reading",
              "prompt": f"/plan {IDEA3}\n\n{ANSWERS3}",
              "resume": "resumed with the continue prompt until the intent is locked, at most 3 times",
              "check": "record_check, intent_lock verify, milestone_lint, and rulings pass; milestones.md plans "
                       "exactly M1, M2, and M3; no product code exists"}]
    for m in MILESTONES3:
        steps.append({"name": f"dev {m}", "session": "new", "prompt": DEV3.format(m=m),
                      "resume": f"resumed with the continue prompt until the last {m} round ends ACCEPT-READY or "
                                f"BLOCKED, at most 6 times",
                      "check": f"every {m} round has a verdict.json in which every checker ran; the last one is "
                               f"ACCEPT-READY; the rounds are recorded in rounds.json"})
        steps.append({"name": f"accept {m}", "session": "new", "prompt": ACCEPT3.format(m=m), "resume": "",
                      "check": f"milestones.md gives {m} Status: accepted"})
    steps.append({"name": "regression demos", "session": "none (reads the evidence)", "prompt": "", "resume": "",
                  "check": "rulings check passes; the last M3 round's demo result has steps for M1 and M2 (their "
                           "demo endings were replayed)"})
    return steps


def milestone_ids(project):
    f = project / "docs/project/milestones.md"
    return re.findall(r"^## (M\d+) · ", f.read_text(), re.M) if f.is_file() else []


def milestone_status(project, m):
    f = project / "docs/project/milestones.md"
    text = f.read_text() if f.is_file() else ""
    sec = re.search(rf"^## {m} · .*?(?=^## |\Z)", text, re.M | re.S)
    st = re.search(r"^Status:\s*(\S+)", sec.group(0), re.M) if sec else None
    return st.group(1) if st else None


def gate_rounds(project, m):
    """[(round, verdict, checkers that did not run)] of a milestone's finished gate rounds, in order."""
    out = []
    folder = project / ".evidence/gate" / m
    dirs = [d for d in folder.glob("r*") if re.match(r"^r\d+$", d.name)] if folder.is_dir() else []
    for d in sorted(dirs, key=lambda d: int(d.name[1:])):
        try:
            v = json.loads((d / "verdict.json").read_text())
        except (OSError, ValueError):
            continue
        out.append((d.name, v.get("verdict"), [c for c, s in (v.get("checkers") or {}).items() if s is None]))
    return out


def demo_milestones(round_dir):
    """The milestones whose demo steps a round's demo result reports (its last JSON block's steps)."""
    f = round_dir / "code-verifier-demo.result.md"
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", f.read_text(errors="replace"), re.S) if f.is_file() else []
    for b in reversed(blocks):
        try:
            return {s.get("milestone") for s in json.loads(b).get("steps") or [] if isinstance(s, dict)}
        except (ValueError, AttributeError):
            continue
    return set()


def scenario_build_gate_3(ev):
    project = fresh("build-gate-3", "reading")
    steps = steps_build_gate_3()
    result, session, code = claude(steps[0]["prompt"], project, ev / "plan.jsonl")
    for turn in range(3):
        if locked(project) or not session:
            break
        (ev / "notes.txt").open("a").write(f"resumed the plan session after its background work (turn {turn + 1})\n")
        result, _, code = claude(CONTINUE, project, ev / "plan.jsonl", resume=session)
    (ev / "plan.result.md").write_text(result)
    problems = check_record(project)
    planned = milestone_ids(project)
    if planned != list(MILESTONES3):
        problems.append(f"the plan has milestones {planned or 'none'}, not exactly M1, M2, and M3")
    if problems:
        return problems  # building on a plan that failed proves nothing
    rounds = {}
    for m in MILESTONES3:
        stream = ev / f"dev-{m}.jsonl"
        result, session, code = claude(DEV3.format(m=m), project, stream)
        for turn in range(6):
            done = gate_rounds(project, m)
            if (done and done[-1][1] in ("ACCEPT-READY", "BLOCKED")) or not session:
                break
            (ev / "notes.txt").open("a").write(f"resumed the {m} dev session after its background work "
                                               f"(turn {turn + 1})\n")
            result, _, code = claude(CONTINUE, project, stream, resume=session)
        (ev / f"dev-{m}.result.md").write_text(result)
        done = gate_rounds(project, m)
        rounds[m] = [{"round": r, "verdict": v, "not_run": missing} for r, v, missing in done]
        (ev / "rounds.json").write_text(json.dumps(rounds, indent=1))
        problems += [f"{m} {r}: {', '.join(missing)} did not run" for r, _, missing in done if missing]
        if not done:
            return problems + [f"{m}: no gate round finished (no verdict.json)"]
        if done[-1][1] != "ACCEPT-READY":
            return problems + [f"{m} ended {done[-1][1]} after {len(done)} round(s)"]
        result, _, code = claude(ACCEPT3.format(m=m), project, ev / f"accept-{m}.jsonl")
        (ev / f"accept-{m}.result.md").write_text(result)
        status = milestone_status(project, m)
        if status != "accepted":
            return problems + [f"{m} is {status or 'missing'} after the owner's acceptance words, not accepted"]
    code, out = run([PY, str(SCRIPTS / "rulings.py"), "check", str(project)])
    if code != 0:
        problems.append("rulings.py check: " + out.strip()[-300:])
    last = project / ".evidence/gate/M3" / rounds["M3"][-1]["round"]
    replayed = demo_milestones(last)
    missing = [m for m in ("M1", "M2") if m not in replayed]
    if missing:
        problems.append(f"the last M3 round's demo did not replay the demo endings of {', '.join(missing)} "
                        f"(its steps name {sorted(x for x in replayed if x) or 'no milestone'})")
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
    CURRENT["projects"].append(project)
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
    CURRENT["projects"].append(project)
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


SCENARIOS = ("plan", "build-gate", "switch", "inbox", "injected", "adopt", "capture", "build-gate-3")
NAMED_ONLY = {"build-gate-3"}  # run only when named with --only


def described(name):
    """A scenario's entry in the module text, on one line."""
    m = re.search(rf"^  {re.escape(name)}\s+(.*?)(?=^  \S|^\S|\Z)", __doc__, re.M | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def dry_run(chosen):
    for name in chosen:
        if name != "build-gate-3":
            print(f"{name}: {described(name)}")
            print("  (its steps are code; only build-gate-3 lists its steps here)")
            continue
        print(f"{name}: {len(steps_build_gate_3())} steps; each session is a headless claude -p in the project folder")
        for i, s in enumerate(steps_build_gate_3(), 1):
            print(f"  {i}. {s['name']} · session: {s['session']}")
            for j, line in enumerate(s["prompt"].splitlines()):
                lead = "     prompt: " if j == 0 else "             "
                print(lead + line if line else "")
            if s["resume"]:
                print(f"     {s['resume']}")
            print(f"     check: {s['check']}")
    print("dry run: no model was called, no folder was made, no evidence was removed")
    return 0


def main(argv):
    only = set((argv[argv.index("--only") + 1].split(",")) if "--only" in argv else [])
    unknown = sorted(only - set(SCENARIOS))
    if unknown:
        print(f"system_scenarios: unknown scenario {', '.join(unknown)} (known: {', '.join(SCENARIOS)})",
              file=sys.stderr)
        return 2
    chosen = [s for s in SCENARIOS if s in only or (not only and s not in NAMED_ONLY)]
    if "--dry-run" in argv:
        return dry_run(chosen)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    results, costs = {}, {}

    def ev_dir(name):
        d = EVIDENCE / name
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        return d

    def attempt(name, fn, *args):
        # One scenario's crash is that scenario's failure; the others still run. Its cost is recorded either way.
        ev, started = ev_dir(name), time.time()
        CURRENT["projects"] = [a for a in args if isinstance(a, Path)]
        try:
            problems = fn(ev, *args)
        except Exception as exc:
            problems = [f"the scenario itself failed: {exc.__class__.__name__}: {str(exc)[:300]}"]
        try:
            costs[name] = record_cost(ev, CURRENT["projects"], started)
        except Exception as exc:
            problems = problems + [f"its cost could not be recorded: {exc.__class__.__name__}: {str(exc)[:200]}"]
        return problems

    # --project reuses a project that an earlier run planned and built, so the scenarios that only need one
    # (switch, inbox, injected) do not pay for planning and building again.
    project = Path(argv[argv.index("--project") + 1]) if "--project" in argv else None
    if project is None and (not only or only & {"plan", "build-gate", "injected", "switch", "inbox"}):
        planned = {}

        def plan(ev):
            planned["project"], problems = scenario_plan(ev)
            return problems
        results["plan"] = attempt("plan", plan)
        project = planned.get("project")
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
    if "build-gate-3" in only:
        results["build-gate-3"] = attempt("build-gate-3", scenario_build_gate_3)
    failed = 0
    for name, problems in results.items():
        print(f"{'PASS' if not problems else 'FAIL':<5} {name:<12} {'; '.join(problems)[:600]}", flush=True)
        print(f"      {name} {cost_line(costs.get(name))}", flush=True)
        failed += bool(problems)
    print(f"system-scenarios: {'PASS' if not failed else 'FAIL'} ({len(results) - failed}/{len(results)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
