#!/usr/bin/env python3
"""Level-3 harness: run each checker on planted-defect and clean fixtures through the real isolated runner.

Usage: agent_fixtures.py [--only <prefix>[,<prefix>...]] [--runs N] [--parallel K] [--installed] [--effort <level>]

Each fixture folder holds a project (a small product with its docs/project build record). The harness
copies it to a fresh work folder under ~/.gate-copies/fixtures/, prepares the checker's directory the way
the gate does (gate_copies.py review or blind copy, a verdict folder, or a documents folder), renders the
pack with render_pack.py, runs the checker with run_isolated.py (the agent file from this repository unless
--installed), and checks the checker's final JSON block against the fixture's expectations. Canary strings
planted in the project's intent and in files outside the checker's copy must never appear in its output.
Results go to <repo>/.evidence/fixtures/<name>/run-<n>/ and a table is printed. A fixture passes only if
every run passes. Exit 0 if all pass, 1 otherwise.

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


def run_one(name, spec, n, installed, effort):
    work = WORK / f"{name}-{n}-{int(time.time() * 1000) % 10**9}"
    shutil.copytree(FIX / spec["folder"], work / "project")
    project = work / "project"
    ev = REPO / ".evidence/fixtures" / name / f"run-{n}"
    if ev.exists():
        shutil.rmtree(ev)
    ev.mkdir(parents=True)
    if spec["role"] == "code-verifier" and spec.get("mode") != "demo":
        run([sys.executable, str(SCRIPTS / "baseline.py"), "record", str(project), spec.get("milestone", "M1")])
    try:
        workdir, _ = prepare(spec, project, work)
    except RuntimeError as exc:
        return name, n, [str(exc)], None
    cmd = [sys.executable, str(SCRIPTS / "run_isolated.py"), spec["role"], "--dir", str(workdir), "--out", str(ev),
           "--project", str(project), "--effort", effort]
    if spec.get("pack"):
        packed = ev / "fixture-pack.md"
        text = (project / spec["pack"]).read_text().replace("{project}", str(project))
        packed.write_text(re.sub(r"\{repo:([^}]+)\}", lambda m: (REPO / m.group(1)).read_text(), text))
        (project / spec["pack"]).unlink()
        cmd += ["--pack", str(packed)]
    else:
        render = ["--project", str(project), *spec.get("render", [])]
        render = [a.replace("{copy}", str(workdir)).replace("{project}", str(project)) for a in render]
        cmd += ["--render", *render, "--"]
    for c in spec.get("canaries", []):
        cmd += ["--canary", c]
    if spec.get("mode"):
        cmd += ["--mode", spec["mode"]]
    if spec.get("agent"):
        cmd += ["--agent-file", str(REPO / spec["agent"])]
    elif not installed:
        cmd += ["--agent-file", str(REPO / "agents" / f"{spec['role']}.md")]
    run(cmd, timeout=4000)
    stem = spec["role"] + ("-demo" if spec.get("mode") == "demo" else "")
    try:
        summary = json.loads((ev / f"{stem}.summary.json").read_text())
    except (OSError, ValueError):
        return name, n, ["no summary written"], None
    problems = []
    if summary["status"] != "OK":
        problems.append(f"runner status {summary['status']}: {summary.get('reason') or summary.get('canary_hits') or ''} "
                        f"{summary.get('stderr_tail', '')[-160:]}")
    result_text = (ev / f"{stem}.result.md").read_text() if (ev / f"{stem}.result.md").exists() else ""
    verdict = last_json(result_text, 1 if spec.get("pass2") else None)
    if spec.get("pass2") and summary.get("status") == "OK":
        render2 = ["--project", str(project), "--pass", "2"]
        cmd2 = [sys.executable, str(SCRIPTS / "run_isolated.py"), spec["role"], "--dir", str(workdir), "--out", str(ev),
                "--project", str(project), "--effort", effort, "--resume", summary["session_id"],
                "--render", *render2, "--"]
        for c in spec.get("canaries", []):
            cmd2 += ["--canary", c]
        if not installed:
            cmd2 += ["--agent-file", str(REPO / "agents" / f"{spec['role']}.md")]
        run(cmd2, timeout=4000)
        s2 = json.loads((ev / f"{stem}-pass2.summary.json").read_text()) if (ev / f"{stem}-pass2.summary.json").exists() else {}
        if s2.get("status") != "OK":
            problems.append(f"pass 2 runner status {s2.get('status')}")
        v2 = last_json((ev / f"{stem}-pass2.result.md").read_text(), 2) if (ev / f"{stem}-pass2.result.md").exists() else None
        verdict = {"pass1": verdict, "pass2": v2}
    ctx = {"summary": summary, "result": result_text}
    if spec.get("no_json"):
        problems += spec["expect"](verdict or {}, ctx)
    elif verdict is None or (spec.get("pass2") and not verdict.get("pass1")):
        problems.append("no JSON verdict block in the final message")
    else:
        (ev / "verdict.json").write_text(json.dumps(verdict, indent=2))
        problems += spec["expect"](verdict, ctx)
    if not problems:
        shutil.rmtree(work, ignore_errors=True)
    return name, n, problems, summary


def main(argv):
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    runs = int(argv[argv.index("--runs") + 1]) if "--runs" in argv else 3
    parallel = int(argv[argv.index("--parallel") + 1]) if "--parallel" in argv else 1
    effort = argv[argv.index("--effort") + 1] if "--effort" in argv else "xhigh"
    installed = "--installed" in argv
    WORK.mkdir(parents=True, exist_ok=True)
    prefixes = [x for x in (only or "").split(",") if x]
    jobs = [(name, spec, n) for name, spec in FIXTURES.items() if not prefixes or name.startswith(tuple(prefixes))
            for n in range(1, runs + 1)]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(parallel, 3))) as pool:
        futures = [pool.submit(run_one, nm, sp, n, installed, effort) for nm, sp, n in jobs]
        for fut in concurrent.futures.as_completed(futures):
            res = fut.result()
            results.append(res)
            name, n, problems, summary = res
            print(f"{'PASS' if not problems else 'FAIL':<5} {name:<34} run {n}  tools={summary.get('tool_uses') if summary else '-'}"
                  f"  {'; '.join(problems)[:300]}", flush=True)
    failed = sum(1 for r in results if r[2])
    print(f"agent-fixtures: {'PASS' if not failed else 'FAIL'} ({len(results) - failed}/{len(results)} runs passed)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
