#!/usr/bin/env python3
"""Level-3 harness: run each checker on planted-defect and clean fixtures through the real isolated runner.

Usage: agent_fixtures.py [--only <prefix>[,<prefix>...]] [--runs N] [--parallel K] [--installed] [--effort <level>]
                         [--model <model id>]

Each fixture folder holds a project (a small product with its docs/project build record). The harness
copies it to a fresh work folder under ~/.gate-copies/fixtures/, prepares the checker's directory the way
the gate does (gate_copies.py review or blind copy, a verdict folder, or a documents folder), renders the
pack with render_pack.py, runs the checker with run_isolated.py (the agent file from this repository unless
--installed; --model <id> and --effort <level> passed on to run_isolated.py, for both passes of a two-pass
checker; without them each checker runs on its models.json route, so a routing change is what gets measured;
never with a shadow run),
and checks the checker's final JSON block against the fixture's expectations (which also see the checker's
folder, so a demo step's capture can be checked to exist). Canary strings planted in the project's intent and
in files outside the checker's copy must never appear in its output. A judge whose folder holds captures runs
with --require-read 'captures/*', as gate_run.py runs it. A fixture marked "browser" needs Playwright for
python3 (browse.py drives the page); without it the run is recorded as missed and no model is called.
Results go to <repo>/.evidence/fixtures/<name>/run-<n>/ and a table is printed. A fixture passes only if
every run passes. Exit 0 if all pass, 1 otherwise.

Each run also writes fixture-result.json beside its summaries: the fixture's kind (planted, clean, other), the
problems and their count, the runner status, the served models, the raw token usage by served model, and its
dollars at list prices (by this tree's spend.py; null when it has no price table). A run whose summary says
escalated: true fails: a retry on another model never rescues the model under test. The problem count is the
number of problems the expectation reported (a runner status other than OK is one of them); a run that gave
no verdict of its own (no summary, no verdict block, or escalated) missed everything, so it counts one plus
every problem its expectation finds in an empty verdict. evolve.py pools these counts (repro:route).

A fixture with a "base" (a folder beside it) starts from that folder, the product as the milestone found it, and
its own folder is copied over it; a review fixture's milestone baseline is recorded in between, so its pack shows
the fixture's own change since the milestone started (without a base the baseline is the fixture as it is: no
change). A re-verify fixture ("mode": "reverify") names its focused round's scope.json ("scope", a file in the
fixture, as regate_scope.py writes it): the harness points the scope's delta_patch and since.snapshot at the run's
copy of the project (absolute paths, as a gate round's are) and renders with --mode reverify --scope <that file>
({scope} in its render arguments); it runs on the code-verifier.reverify route, under the code-verifier.* stem.

A probe fixture (role "probe") measures how a model follows a pipeline text rather than how a checker judges:
its pack embeds files of the pipeline under test with {repo:<path>} (read from this repository, so each
version is measured with its own text and the same question), and its agent file is named by the fixture's
"agent" (a path in this repository; probes are never installed).
"""
import concurrent.futures
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "skills/_shared/scripts"
FIX = REPO / "tests/fixtures/agents"
WORK = Path.home() / ".gate-copies/fixtures"
sys.path.insert(0, str(REPO / "tests"))
from fixture_expectations import FIXTURES  # noqa: E402


def last_json(text, want_pass=None):
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text or "", flags=re.S)
    parsed = []
    for b in blocks:
        try:
            parsed.append(json.loads(b))
        except ValueError:
            continue
    if want_pass is not None:
        own = [p for p in parsed if p.get("pass") == want_pass]
        if own:
            return own[-1]
    return parsed[-1] if parsed else None


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def reviews(spec):
    """True for a code-verifier review fixture (not demo, not re-verify): its pack shows the change since the
    milestone baseline."""
    return spec["role"] == "code-verifier" and spec.get("mode") not in ("demo", "reverify")


def point_scope(spec, project):
    """A re-verify fixture's scope.json with delta_patch and since.snapshot made absolute paths in this copy of the
    project (a gate round's scope names its own evidence folder); returns the scope file's path."""
    path = project / spec["scope"]
    scope = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(scope.get("delta_patch"), str) and not Path(scope["delta_patch"]).is_absolute():
        scope["delta_patch"] = str(project / scope["delta_patch"])
    since = scope.get("since")
    if isinstance(since, dict) and isinstance(since.get("snapshot"), str) and not Path(since["snapshot"]).is_absolute():
        since["snapshot"] = str(project / since["snapshot"])
    path.write_text(json.dumps(scope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def make_project(spec, work):
    """The run's copy of the fixture's project, at <work>/project: its base first when it names one, then its own
    folder over it; a review fixture's milestone baseline recorded after the base (or, without one, after the
    copy), and a re-verify fixture's scope pointed at this copy."""
    project = Path(work) / "project"
    mid = spec.get("milestone", "M1")
    record = [sys.executable, str(SCRIPTS / "baseline.py"), "record", str(project), mid]
    if spec.get("base"):
        shutil.copytree(FIX / spec["base"], project)
        if reviews(spec):
            run(record)
        shutil.copytree(FIX / spec["folder"], project, dirs_exist_ok=True)
    else:
        shutil.copytree(FIX / spec["folder"], project)
        if reviews(spec):
            run(record)
    if spec.get("scope"):
        point_scope(spec, project)
    return project


def prepare(spec, project, work):
    """Return (checker dir, render args, extra run args)."""
    kind = spec["dir"]
    if kind in ("review", "blind", "demo"):
        r = run([sys.executable, str(SCRIPTS / "gate_copies.py"), "make", str(project), "--dest", str(work / "copies"),
                 "--milestone", spec.get("milestone", "M1")])
        info = json.loads(r.stdout[r.stdout.index("{"):]) if "{" in r.stdout else {}
        if not info.get(kind):
            raise RuntimeError("copies failed: " + (r.stdout + r.stderr)[-400:])
        return Path(info[kind]["path"]), info
    target = work / "folder"
    target.mkdir()
    for rel in spec.get("files", []):
        src, _, dst_rel = rel.partition("=>")
        dst = target / (dst_rel or Path(src).name)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(project / src, dst)
    return target, {}


def render_args(spec, project, workdir):
    """The render_pack.py arguments (after the role) of a fixture without a pack of its own."""
    render = ["--project", str(project), *spec.get("render", [])]
    scope = str(project / spec["scope"]) if spec.get("scope") else "{scope}"
    return [a.replace("{copy}", str(workdir)).replace("{project}", str(project)).replace("{scope}", scope)
            for a in render]


def embedded_pack(spec, project):
    """The text of a fixture's own pack, with {project} and every {repo:<path>} (a file of this repository) filled."""
    text = (project / spec["pack"]).read_text().replace("{project}", str(project))
    return re.sub(r"\{repo:([^}]+)\}", lambda m: (REPO / m.group(1)).read_text(), text)


def judge_captures(spec, workdir):
    """--require-read for a judge whose folder holds captures, as gate_run.py passes it: a judge that never opens
    one is INCONCLUSIVE."""
    caps = Path(workdir) / "captures"
    has = spec["role"] == "gate-judge" and caps.is_dir() and any(p.is_file() for p in caps.iterdir())
    return ["--require-read", "captures/*"] if has else []


def browser_missing():
    """Why browse.py cannot start a browser on this machine (no Playwright for python3), or None."""
    r = run(["python3", "-c", "import playwright.sync_api"])
    return None if r.returncode == 0 else "this machine has no Playwright for python3, so browse.py cannot start a " \
                                          "browser (pip install playwright; python3 -m playwright install chromium)"


def run_usage(ev):
    """(raw usage by served model, served models, escalated) over every summary of one run (both passes): each
    summary's usage under its served model (served_model, else model, else "unknown"; a Codex run's under
    codex:<model>)."""
    usage, models, escalated = {}, set(), False
    for f in sorted(Path(ev).glob("*.summary.json")):
        try:
            s = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        model = s.get("served_model") or s.get("model") or "unknown"
        models.add(model)
        escalated = escalated or s.get("escalated") is True
        u = s.get("usage")
        if not isinstance(u, dict):
            continue
        key = f"codex:{model}" if s.get("family") == "codex" or u.get("family") == "codex" else model
        acc = usage.setdefault(key, {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0})
        for k in acc:
            acc[k] += u.get(k) or 0
    return usage, sorted(models), escalated


def dollars_of(usage):
    """Dollars at list prices of a run's Claude usage, by this tree's spend.py; None when its spend.py has no price
    table (an older pipeline). For the reader only: evolve.py computes cost from the raw usage itself."""
    try:
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        import spend
        return round(sum(spend.dollars(m, u)[0] for m, u in usage.items() if not m.startswith("codex")), 4)
    except (ImportError, AttributeError):
        return None


def problem_count(spec, problems, judged, ctx):
    """The run's problems as evolve.py pools them: what the expectation reported, or, for a run that gave no
    verdict of its own, one plus every problem the expectation finds in an empty verdict (it missed them all)."""
    if judged or spec.get("no_json"):
        return len(problems)
    return 1 + len(spec["expect"]({}, ctx))


def record(name, spec, n, ev, problems, judged, summary, result_text=""):
    """Write the run's fixture-result.json and return (name, run, problems, summary, record)."""
    usage, models, escalated = run_usage(ev)
    if escalated:
        problems = problems + ["escalated: the run was retried on another model, and a retried run fails (the retry "
                               "never rescues the model under test)"]
        judged = False
    rec = {"fixture": name, "run": n, "kind": spec.get("kind", "other"), "pass": not problems, "problems": problems,
           "problem_count": problem_count(spec, problems, judged, {"summary": summary or {}, "result": result_text}),
           "status": (summary or {}).get("status"), "escalated": escalated, "served_models": models, "usage": usage,
           "dollars": dollars_of(usage)}
    (Path(ev) / "fixture-result.json").write_text(json.dumps(rec, indent=2))
    return name, n, problems, summary, rec


def run_one(name, spec, n, installed, effort, model=None):
    work = WORK / f"{name}-{n}-{int(time.time() * 1000) % 10**9}"
    ev = REPO / ".evidence/fixtures" / name / f"run-{n}"
    if ev.exists():
        shutil.rmtree(ev)
    ev.mkdir(parents=True)
    no_browser = spec.get("browser") and browser_missing()
    if no_browser:  # a run that cannot drive the page is a miss, never a paid run
        return record(name, spec, n, ev, [no_browser], False, None)
    project = make_project(spec, work)
    try:
        workdir, _ = prepare(spec, project, work)
    except RuntimeError as exc:
        return record(name, spec, n, ev, [str(exc)], False, None)
    # No shadow runs here (a fixture measures one setting), and the route's effort unless --effort was given, so
    # an effort change in models.json is measured like a model change.
    cmd = [sys.executable, str(SCRIPTS / "run_isolated.py"), spec["role"], "--dir", str(workdir), "--out", str(ev),
           "--project", str(project), "--no-shadow"] + (["--effort", effort] if effort else [])
    if spec.get("pack"):
        packed = ev / "fixture-pack.md"
        packed.write_text(embedded_pack(spec, project))
        (project / spec["pack"]).unlink()
        cmd += ["--pack", str(packed)]
    else:
        cmd += ["--render", *render_args(spec, project, workdir), "--"]
    for c in spec.get("canaries", []):
        cmd += ["--canary", c]
    cmd += judge_captures(spec, workdir)
    if spec.get("mode"):
        cmd += ["--mode", spec["mode"]]
    if spec.get("agent"):
        cmd += ["--agent-file", str(REPO / spec["agent"])]
    elif not installed:
        cmd += ["--agent-file", str(REPO / "agents" / f"{spec['role']}.md")]
    if model:
        cmd += ["--model", model]
    run(cmd, timeout=4000)
    stem = spec["role"] + ("-demo" if spec.get("mode") == "demo" else "")
    try:
        summary = json.loads((ev / f"{stem}.summary.json").read_text())
    except (OSError, ValueError):
        return record(name, spec, n, ev, ["no summary written"], False, None)
    problems = []
    if summary["status"] != "OK":
        problems.append(f"runner status {summary['status']}: {summary.get('reason') or summary.get('canary_hits') or ''} "
                        f"{summary.get('stderr_tail', '')[-160:]}")
    result_text = (ev / f"{stem}.result.md").read_text() if (ev / f"{stem}.result.md").exists() else ""
    verdict = last_json(result_text, 1 if spec.get("pass2") else None)
    if spec.get("pass2") and summary.get("status") == "OK":
        render2 = ["--project", str(project), "--pass", "2"]
        cmd2 = [sys.executable, str(SCRIPTS / "run_isolated.py"), spec["role"], "--dir", str(workdir), "--out", str(ev),
                "--project", str(project), "--no-shadow"] + (["--effort", effort] if effort else []) + [
                "--resume", summary["session_id"],
                "--render", *render2, "--"]
        for c in spec.get("canaries", []):
            cmd2 += ["--canary", c]
        if not installed:
            cmd2 += ["--agent-file", str(REPO / "agents" / f"{spec['role']}.md")]
        if model:
            cmd2 += ["--model", model]  # a resumed pass stays on its first pass's model
        run(cmd2, timeout=4000)
        s2 = json.loads((ev / f"{stem}-pass2.summary.json").read_text()) if (ev / f"{stem}-pass2.summary.json").exists() else {}
        if s2.get("status") != "OK":
            problems.append(f"pass 2 runner status {s2.get('status')}")
        v2 = last_json((ev / f"{stem}-pass2.result.md").read_text(), 2) if (ev / f"{stem}-pass2.result.md").exists() else None
        verdict = {"pass1": verdict, "pass2": v2}
    ctx = {"summary": summary, "result": result_text, "dir": str(workdir)}  # dir: the checker's folder (its captures)
    judged = True
    if spec.get("no_json"):
        problems += spec["expect"](verdict or {}, ctx)
    elif verdict is None or (spec.get("pass2") and not verdict.get("pass1")):
        problems.append("no JSON verdict block in the final message")
        judged = False
    else:
        (ev / "verdict.json").write_text(json.dumps(verdict, indent=2))
        problems += spec["expect"](verdict, ctx)
    out = record(name, spec, n, ev, problems, judged, summary, result_text)
    if not out[2]:
        shutil.rmtree(work, ignore_errors=True)
    return out


def main(argv):
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    runs = int(argv[argv.index("--runs") + 1]) if "--runs" in argv else 3
    parallel = int(argv[argv.index("--parallel") + 1]) if "--parallel" in argv else 1
    effort = argv[argv.index("--effort") + 1] if "--effort" in argv else None  # None: the route's effort
    model = argv[argv.index("--model") + 1] if "--model" in argv[:-1] else None
    if "--model" in argv and not model:
        print("agent_fixtures: --model takes a model id, such as claude-sonnet-5-5", file=sys.stderr)
        return 2
    installed = "--installed" in argv
    WORK.mkdir(parents=True, exist_ok=True)
    prefixes = [x for x in (only or "").split(",") if x]
    jobs = [(name, spec, n) for name, spec in FIXTURES.items() if not prefixes or name.startswith(tuple(prefixes))
            for n in range(1, runs + 1)]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(parallel, 3))) as pool:
        futures = [pool.submit(run_one, nm, sp, n, installed, effort, model) for nm, sp, n in jobs]
        for fut in concurrent.futures.as_completed(futures):
            res = fut.result()
            results.append(res)
            name, n, problems, summary, rec = res
            cost = f"${rec['dollars']:.2f}" if rec["dollars"] is not None else "$-"
            print(f"{'PASS' if not problems else 'FAIL':<5} {name:<34} run {n}  tools={summary.get('tool_uses') if summary else '-'}"
                  f"  problems={rec['problem_count']}  {cost}  model={','.join(rec['served_models']) or '-'}"
                  f"  {'; '.join(problems)[:300]}", flush=True)
    failed = sum(1 for r in results if r[2])
    print(f"agent-fixtures: {'PASS' if not failed else 'FAIL'} ({len(results) - failed}/{len(results)} runs passed)")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--help" in sys.argv[1:] or sys.argv[1:] == ["-h"]:
        print(__doc__.strip())  # asked for, so not an error; never a run of every fixture
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
