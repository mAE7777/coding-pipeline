"""A project paused mid-milestone under the pipeline as it was at 587f48c keeps working after an update.

tests/fixtures/compat-587f48c/ was made with the 587f48c scripts, never edited by hand: its docs/project record
and AGENTS.md are the 587f48c templates filled in (the trailing idea-anchor example dropped, as a planner does
without an anchor), the intent locked by that intent_lock.py with a ruling proven by that rulings.py, the M1
baseline recorded by that baseline.py (no .head file), and one gate round run by that gate_run.py with the
stand-in claude of tests/test_gate_run.py ending CHANGES (M1-F01, in the old findings ledger, without files). Then
the builder fixed it and froze again: Status gate and a new Candidate, ready for round 2. The round keeps its
results, summaries, logs, and verdict; the rendered packs, agent definitions, sandbox settings, and raw streams
were left out, and the folders it was made in read as /Users/owner/... . In the old layout there is no
candidate.txt, no full-candidate snapshot, and no scope.json.

Each test runs today's scripts on a copy: milestone_lint, record_check, reentry_digest, project_status (and its
record), regate_scope decide (full, with the reason), and gate_run.py with the stand-in claude, which must reach
a verdict, outside git and inside a git checkout whose exclude file is the one 587f48c's local_only.py wrote. The
round also proves the run registry: gate_run.py and each run_isolated.py are registered while they run, and
nothing is left after the round or after a stopped one.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/_shared/scripts"
FIXTURE = ROOT / "tests/fixtures/compat-587f48c"
sys.path.insert(0, str(ROOT / "tests"))
sys.dont_write_bytecode = True
from test_gate_run import FAKE_CLAUDE, SID  # noqa: E402

# Each stand-in run writes down the run registry as it finds it, and can be told to take its time.
ANCHOR = "pack = sys.stdin.read()\n"
WATCH = ANCHOR + '''if os.environ.get("REGISTRY_DIR"):
    _runs = sorted(glob.glob(os.path.join(os.environ["REGISTRY_DIR"], "*.json")))
    with open(os.environ["REGISTRY_LOG"], "a") as _f:
        _f.write(json.dumps([json.load(open(p)) for p in _runs]) + "\\n")
import time as _time
_time.sleep(float(os.environ.get("FAKE_SLEEP") or 0))
'''
# The exclude file 587f48c's local_only.py wrote (its standard local-only set).
OLD_LOCAL_ONLY = ["/docs/project/brief.md", "/docs/project/state.md", "/docs/project/gate.md",
                  "/docs/project/handoffs/", "/docs/project/journal.md", "/docs/project/reviews/",
                  "/docs/project/research/", "/docs/project/sources/", "/docs/project/.gate-canary-*", "/.evidence/",
                  "/.playwright-cli/", "/AGENTS.md", "/CLAUDE.md"]
GIT_ENV = {"GIT_AUTHOR_NAME": "owner", "GIT_AUTHOR_EMAIL": "owner@example.com", "GIT_COMMITTER_NAME": "owner",
           "GIT_COMMITTER_EMAIL": "owner@example.com", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class CompatTest(unittest.TestCase):
    def setUp(self):
        self.assertIn(ANCHOR, FAKE_CLAUDE, "the stand-in claude still reads its pack this way")
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.proj = d / "proj"
        shutil.copytree(FIXTURE, self.proj, symlinks=True)
        self.home = d / "home"
        self.home.mkdir()
        bindir = d / "bin"
        bindir.mkdir()
        (bindir / "claude").write_text(FAKE_CLAUDE.replace(ANCHOR, WATCH, 1))
        (bindir / "claude").chmod(0o755)
        self.runs = self.home / ".claude/.pipeline-runs"
        self.registry_log = d / "registry.log"
        self.env = {**os.environ, **GIT_ENV, "HOME": str(self.home), "CLAUDE_CODE_SESSION_ID": SID,
                    "HEAVY_LOCK_DIR": str(d / "lock"), "PATH": f"{bindir}:{os.environ['PATH']}",
                    "FAKE_PROJECT": str(self.proj), "PYTHONDONTWRITEBYTECODE": "1", "REGISTRY_DIR": str(self.runs),
                    "REGISTRY_LOG": str(self.registry_log)}
        for k in ("HEAVY_LOCK_HELD", "HEAVY_OWNER", "CODEX_THREAD_ID"):
            self.env.pop(k, None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, name, *args, timeout=120):
        return subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args)], capture_output=True, text=True,
                              env=self.env, timeout=timeout)

    def gate(self, **extra):
        return subprocess.run([sys.executable, str(SCRIPTS / "gate_run.py"), str(self.proj), "--milestone", "M1",
                               "--family", "claude", "--agents-dir", str(ROOT / "agents")], capture_output=True,
                              text=True, env={**self.env, **extra}, timeout=600)

    def make_git_checkout(self):
        def git(*args):
            subprocess.run(["git", *args], cwd=self.proj, env=self.env, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        (self.proj / ".git/info/exclude").write_text("\n".join(OLD_LOCAL_ONLY) + "\n")
        git("add", "-A")
        git("commit", "-q", "-m", "add and show")

    def test_the_fixture_is_in_the_old_layout(self):
        ev = self.proj / ".evidence"
        self.assertTrue((ev / "baseline-M1.txt").is_file() and (ev / "baseline/M1").is_dir())
        self.assertFalse((ev / "baseline-M1.head").exists(), "587f48c's baseline.py wrote no .head file")
        self.assertEqual(json.loads((ev / "gate/M1/r1/verdict.json").read_text())["verdict"], "CHANGES")
        for new in ("gate/M1/r1/candidate.txt", "gate/M1/r1/scope.json", "gate/M1/full-candidate",
                    "gate/M1/full-candidate.json"):
            self.assertFalse((ev / new).exists(), new)
        ledger = json.loads((self.proj / "docs/project/reviews/M1.findings.json").read_text())
        self.assertNotIn("files", ledger["M1-F01"], "the old ledger names no files")
        state = (self.proj / "docs/project/state.md").read_text()
        self.assertNotIn("## Eliminated approaches", state, "587f48c's state.md template had no such section")
        fp = self.run_script("fingerprint.py", self.proj).stdout.split()[0]
        self.assertIn(f"## Candidate\n{fp}\n", state, "frozen for round 2")

    def test_the_record_scripts_read_the_old_record(self):
        lint = self.run_script("milestone_lint.py", self.proj)
        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
        record = self.run_script("record_check.py", self.proj, "--json")
        self.assertEqual(record.returncode, 0, record.stderr)
        self.assertEqual(json.loads(record.stdout)["kind"], "complete")
        digest = self.run_script("reentry_digest.py", self.proj)
        self.assertEqual(digest.returncode, 0, digest.stderr)
        self.assertIn("## docs/project/state.md \u00b7 Eliminated approaches\nnone recorded", digest.stdout)
        self.assertIn("## docs/project/milestones.md \u00b7 M1 \u00b7 Add and show", digest.stdout)
        status = self.run_script("project_status.py", self.proj)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("M1 gate (round 1 CHANGES)", status.stdout)
        journal = self.proj / "docs/project/journal.md"
        old_lines = journal.read_text().count("\n- ")
        rec = self.run_script("project_status.py", "record", self.proj, "--skill", "dev", "--arg", "M1 resume",
                              "--outcome", "picked up after the update")
        self.assertEqual(rec.returncode, 0, rec.stdout + rec.stderr)
        text = journal.read_text()
        self.assertEqual(text.count("\n- "), old_lines + 1)
        self.assertRegex(text.splitlines()[-1], " \u00b7 record [0-9a-f]{8,}$", "the new line carries the fingerprint")
        self.assertIn("dev M1 resume", (self.proj / "docs/project/state.md").read_text())

    def test_regate_scope_decides_full_with_the_reason(self):
        out = Path(self.tmp.name) / "scope.json"
        r = self.run_script("regate_scope.py", "decide", self.proj, "--milestone", "M1", "--round", "2", "--out", out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        scope = json.loads(out.read_text())
        self.assertEqual(scope["scope"], "full")
        self.assertTrue(r.stdout.startswith("full: "), r.stdout)
        reasons = " ".join(scope["reasons"])
        self.assertIn("snapshot missing", reasons, "the old layout kept no snapshot of the full round")
        self.assertIn("carried evidence unusable", reasons)

    def check_round(self, out):
        ev = self.proj / ".evidence/gate/M1/r2"
        self.assertTrue((ev / "verdict.json").is_file(), out.stdout[-2000:] + out.stderr[-1000:])
        verdict = json.loads((ev / "verdict.json").read_text())
        self.assertNotEqual(verdict["verdict"], "ERROR", json.dumps(verdict)[:1500])
        self.assertEqual(verdict["verdict"], "ACCEPT-READY", json.dumps(verdict, indent=1)[:2500])
        self.assertEqual(out.returncode, 0, out.stderr[-1000:])
        progress = (ev / "progress.log").read_text()
        self.assertIn("scope: full round (changes): ", progress)
        self.assertIn("snapshot missing", progress)
        self.assertTrue((ev / "candidate.txt").is_file(), "the new layout starts with this round")
        return ev

    def check_registry(self, gate_pid):
        seen = [json.loads(line) for line in self.registry_log.read_text().splitlines()]
        self.assertTrue(seen, "the stand-in ran")
        project = str(self.proj.resolve())
        for entries in seen:
            scripts = {(e["script"], e["project"]) for e in entries}
            self.assertIn(("gate_run.py", project), scripts, "the round is registered while each checker runs")
            self.assertIn(("run_isolated.py", project), scripts)
            self.assertIn(gate_pid, [e["pid"] for e in entries if e["script"] == "gate_run.py"])
        self.assertEqual(list(self.runs.glob("*.json")), [], "nothing is left after the round")

    def test_a_gate_round_reaches_a_verdict(self):
        proc = subprocess.Popen([sys.executable, str(SCRIPTS / "gate_run.py"), str(self.proj), "--milestone", "M1",
                                 "--family", "claude", "--agents-dir", str(ROOT / "agents")],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        stdout, stderr = proc.communicate(timeout=600)
        out = subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
        self.check_round(out)
        self.check_registry(proc.pid)
        ledger = json.loads((self.proj / "docs/project/reviews/M1.findings.json").read_text())
        self.assertIn("M1-F01", ledger, "the old ledger is kept")

    def test_a_gate_round_in_a_git_checkout(self):
        self.make_git_checkout()
        ev = self.check_round(self.gate())
        gate_sh = (ev / "layer1-gate-sh.log").read_text()
        self.assertIn("commit messages not checked: the M1 baseline records no git commit", gate_sh,
                      "a baseline without its commit takes the cautious path")
        self.assertIn("RESULT: PASS", gate_sh)

    def test_a_stopped_round_leaves_no_registry_entry(self):
        proc = subprocess.Popen([sys.executable, str(SCRIPTS / "gate_run.py"), str(self.proj), "--milestone", "M1",
                                 "--family", "claude", "--agents-dir", str(ROOT / "agents")],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env={**self.env, "FAKE_SLEEP": "120"})
        try:
            deadline = time.time() + 120
            while time.time() < deadline and not (self.registry_log.is_file() and self.registry_log.read_text()):
                time.sleep(0.1)
            self.assertTrue(self.registry_log.is_file(), "the first checker started")
            self.assertEqual(len(list(self.runs.glob("*.json"))), 2, "the round and its checker")
        finally:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=60)
        self.assertEqual(list(self.runs.glob("*.json")), [], "a stopped round and its checker both leave")


if __name__ == "__main__":
    unittest.main()
