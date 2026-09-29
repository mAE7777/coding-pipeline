"""Tests for evolve.py: the harvest finds the pipeline's own trouble and nothing else, and a change is kept only
when the rule fixed in advance says it is better, the isolated review accepts it, and the owner ruled where
they must."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/_shared/scripts"
EVOLVE = SCRIPTS / "evolve.py"
SID = "88888888-2222-3333-4444-555555555555"
sys.path.insert(0, str(SCRIPTS))
import evolve  # noqa: E402


def entry(**e):
    return json.dumps(e)


def tool(tid, name, inp, uuid):
    return entry(type="assistant", uuid=uuid, timestamp="t",
                 message={"content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]})


def result(tid, text, uuid, is_error=False):
    return entry(type="user", uuid=uuid, timestamp="t", message={"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": is_error}]})


def typed(text, uuid):
    return entry(type="user", uuid=uuid, timestamp="t", message={"content": text})


GATE = "python3 ~/.claude/skills/_shared/scripts/gate_run.py . M1"
CLAUDE_SESSION = [
    typed("build M1 please", "u0"),
    tool("s1", "Skill", {"skill": "gate"}, "a0"),
    tool("t1", "Bash", {"command": GATE}, "a1"),
    result("t1", "FAIL   layer1      tests failed\nFAIL   layer1      lint failed\nFAIL   layer1      types failed\n"
                 "PASS   other       ok", "r1", True),
    tool("t2", "Bash", {"command": GATE}, "a2"),
    result("t2", "FAIL   layer1      tests failed\nFAIL   layer1      lint failed", "r2", True),
    tool("t3", "Read", {"file_path": "/x/skills/_shared/scripts/gate_report.py"}, "a3"),
    result("t3", "FAIL   gate        INCONCLUSIVE-IN-SOURCE\nverdict: ERROR", "r3"),
    tool("t4", "Bash", {"command": "grep -n FAIL ~/.claude/skills/_shared/scripts/gate_run.py"}, "a4"),
    result("t4", "BLOCKED  grepped-line   from source", "r4"),
    tool("t5", "Bash", {"command": "npm test"}, "a5"),
    result("t5", "Exit code 1\nFAIL  src/app.test.ts\nTraceback (most recent call last):\nValueError: PROJECT-OWN",
           "r5", True),
    tool("t6", "Bash", {"command": "pytest"}, "a6"),
    result("t6", "PreToolUse:Bash hook error: [heavy-guard]: Blocked: 'pytest' is a heavy local job.", "r6", True),
    tool("t7", "Bash", {"command": "python3 ~/.claude/skills/_shared/scripts/inbox.py list ."}, "a7"),
    result("t7", "Traceback (most recent call last):\n  File \"inbox.py\", line 3, in <module>\nKeyError: 'Status'",
           "r7", True),
    entry(type="user", uuid="c1", timestamp="t", isCompactSummary=True, message={"content": "summary"}),
    typed("why did the gate stop again? that is wrong", "u1"),
    tool("t8", "Bash", {"command": "test -f ~/.claude/skills/_shared/scripts/x.py"}, "a8"),
    result("t8", "Exit code 1", "r8", True),
]
# Codex runs its own copies of the pipeline's scripts.
CAPTURE = "python3 ~/.agents/skills/_shared/scripts/capture.py check ."
CODEX_SESSION = [
    entry(type="event_msg", timestamp="t", payload={"type": "user_message", "message": "the capture still misses turns, why?"}),
    entry(type="response_item", timestamp="t", payload={"type": "function_call", "call_id": "c1", "name": "exec_command",
                                                        "arguments": json.dumps({"cmd": CAPTURE})}),
    entry(type="event_msg", timestamp="t", payload={"type": "item_completed", "item": {
        "type": "CommandExecution", "command": ["bash", "-lc", CAPTURE], "exit_code": 1,
        "aggregated_output": "FAIL   capture     turn T12 unaccounted"}}),
    entry(type="response_item", timestamp="t", payload={"type": "function_call_output", "call_id": "c1",
                                                        "output": "FAIL   capture     turn T12 unaccounted"}),
    entry(type="event_msg", timestamp="t", payload={"type": "item_completed", "item": {
        "command": ["bash", "-lc", "rg FAIL ~/.claude/skills/_shared/scripts"], "exit_code": 1,
        "aggregated_output": "READ-ONLY-NOISE"}}),
    entry(type="compacted", timestamp="t", payload={"message": ""}),
]


def run(*args, env, cwd=None):
    return subprocess.run([sys.executable, str(EVOLVE), *args], capture_output=True, text=True, env=env, cwd=cwd)


def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com",
                        "-c", "commit.gpgsign=false", *args], capture_output=True, text=True)
    return r.stdout.strip()


class Harvest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.ledger = d / "ledger"
        self.env = {**os.environ, "PIPELINE_EVOLUTION_HOME": str(self.ledger), "HOME": str(d / "home")}
        self.claude = d / "claude.jsonl"
        self.claude.write_text("\n".join(CLAUDE_SESSION) + "\n")
        self.codex = d / "codex.jsonl"
        self.codex.write_text("\n".join(CODEX_SESSION) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def harvest(self, path):
        r = run("harvest", "--transcript", str(path), env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = next((self.ledger / "harvests").glob(f"*-{path.stem[-12:]}"))
        return json.loads((out / "candidates.json").read_text()), (out / "candidates.md").read_text(), out

    def test_claude_session_keeps_pipeline_events_only(self):
        data, md, _ = self.harvest(self.claude)
        kinds = sorted(g["kind"] for g in data["candidates"])
        self.assertEqual(kinds, ["compaction", "hook-block", "owner-pushback", "retried-failure", "status-fail",
                                 "traceback"])
        status = next(g for g in data["candidates"] if g["kind"] == "status-fail")
        self.assertEqual(status["count"], 2, "two runs of one check are one signature; each run's lines one event")
        self.assertIn("3 lines", status["excerpt"])
        tb = next(g for g in data["candidates"] if g["kind"] == "traceback")
        self.assertIn("KeyError", tb["signature"])
        self.assertIn("inbox.py", tb["signature"])
        self.assertEqual(data["skills"], ["gate"])
        for noise in ("INCONCLUSIVE-IN-SOURCE", "grepped-line", "PROJECT-OWN", "src/app.test.ts"):
            self.assertNotIn(noise, md)

    def test_codex_session(self):
        data, md, _ = self.harvest(self.codex)
        kinds = sorted(g["kind"] for g in data["candidates"])
        self.assertEqual(kinds, ["compaction", "owner-pushback", "status-fail", "tool-error"])
        self.assertNotIn("READ-ONLY-NOISE", md)

    def test_known_incident_gets_one_occurrence_per_transcript_and_a_fixed_one_is_a_regression(self):
        data, _, out = self.harvest(self.claude)
        tb = next(g for g in data["candidates"] if g["kind"] == "traceback")
        r = run("new-incident", "--title", "inbox listing crashes", "--kind", "defect", "--where", "inbox.py",
                "--signature", tb["signature"], "--harvest", str(out), "--candidate", str(tb["n"]), env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        inc = self.ledger / "incidents/INC-0001.md"
        self.assertIn("KeyError: 'Status'", inc.read_text())
        self.harvest(self.claude)
        self.harvest(self.claude)
        occurrences = evolve.section(inc.read_text(), "Occurrences")
        self.assertEqual(occurrences.count(str(self.claude)), 1, occurrences)
        inc.write_text(inc.read_text().replace("Status: open", "Status: fixed (CHG-0001)"))
        _, md, _ = self.harvest(self.claude)
        self.assertIn("REGRESSIONS", md)
        self.assertIn("INC-0001", md)
        r = run("similar", "inbox listing crashes", env=self.env)
        self.assertIn("INC-0001", r.stdout)


class Ledger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.tmp.name) / "ledger"
        (self.ledger / "incidents").mkdir(parents=True)
        self.env = {**os.environ, "PIPELINE_EVOLUTION_HOME": str(self.ledger), "PIPELINE_REPO": str(ROOT)}

    def tearDown(self):
        self.tmp.cleanup()

    def incident(self, n, status, repro="<the suite>", kind="defect"):
        (self.ledger / f"incidents/INC-{n:04d}.md").write_text(
            f"# INC-{n:04d} · t\n\nStatus: {status}\nKind: {kind}\nWhere: x\nSignature: s{n}\n\n## Reproduction\n{repro}\n")

    def test_check_refuses_an_incoherent_ledger(self):
        self.incident(1, "maybe")
        self.incident(2, "confirmed")
        self.incident(3, "environment")
        self.incident(4, "duplicate (INC-0099)")
        self.incident(5, "fixed")
        self.incident(6, "open", kind="bug")
        r = run("check", env=self.env)
        self.assertEqual(r.returncode, 1)
        for want in ("INC-0001: unknown status", "INC-0002: confirmed, but the Reproduction", "INC-0003: environment needs",
                     "INC-0004: a duplicate must name", "INC-0005: fixed without naming", "INC-0006: unknown kind"):
            self.assertIn(want, r.stdout)

    def test_check_passes_a_coherent_ledger(self):
        self.incident(1, "open")
        self.incident(2, "confirmed", repro="repro:test:tests/test_x.py::T.test_y fails at base")
        self.incident(3, "not-pipeline (the design skill)")
        self.incident(4, "duplicate (INC-0001)")
        self.incident(5, "not-reproduced", repro="tried a unit test on the stop hook; the hook behaves")
        # A repository of its own: a copy of this one (a benchmark's export) has no git history to ask.
        repo = Path(self.tmp.name) / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        (repo / "a.txt").write_text("a\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "a")
        head = git(repo, "rev-parse", "main")
        self.env["PIPELINE_REPO"] = str(repo)
        self.incident(6, f"resolved ({head[:12]} · the owner's direct order; unit tests and three fixture runs)")
        r = run("check", env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.incident(6, "resolved (0000000000 · a commit that does not exist on main)")
        self.assertIn("not on main", run("check", env=self.env).stdout)
        r = run("status", env=self.env)
        self.assertIn("INC-0001", r.stdout)
        self.assertNotIn("INC-0003", r.stdout)


class Rule(unittest.TestCase):
    """compare, fed stored measurements directly."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.repo = d / "repo"
        (self.repo / "tests").mkdir(parents=True)
        (self.repo / "tests/test_a.py").write_text("x = 1\n")
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "a.py").write_text("y = 2\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "head")
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.saved = (evolve.HOME, os.environ.get("PIPELINE_REPO"))
        evolve.HOME = d / "ledger"
        os.environ["PIPELINE_REPO"] = str(self.repo)

    def tearDown(self):
        evolve.HOME = self.saved[0]
        if self.saved[1] is None:
            os.environ.pop("PIPELINE_REPO", None)
        else:
            os.environ["PIPELINE_REPO"] = self.saved[1]
        self.tmp.cleanup()

    def store(self, sha, suite, measurement, env=None, measurements=None):
        env = env or {"python": "3", "os": "x", "claude": "1", "codex": "absent"}
        data = {"suite": suite, "commit": sha, "env": env, "measurements": measurements or [measurement]}
        f = evolve.HOME / "benchmarks" / sha[:12] / \
            f"{evolve.suite_key(suite)}__{evolve.instrument_key(suite, self.head)}__{evolve.env_key(env)}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data))

    def selftest(self, sha, rows, tests=None):
        self.store(sha, "selftest", {"suites": rows, "tests": tests or {"test_a": 3}})

    def verdict(self, suites):
        return evolve.compare(self.base, self.head, suites, self.head)

    def test_better_needs_every_reproduction_to_flip_and_nothing_worse(self):
        repro = "repro:test:tests/test_a.py::T.test_b"
        self.selftest(self.base, {"test_a": "PASS"})
        self.selftest(self.head, {"test_a": "PASS"}, {"test_a": 4})
        self.store(self.base, repro, {"outcome": "crash"})
        self.store(self.head, repro, {"outcome": "pass"})
        self.assertEqual(self.verdict(["selftest", repro])[0], "BETTER")

    def test_a_reproduction_that_cannot_show_the_problem_is_not_one(self):
        repro = "repro:test:tests/test_a.py::T.test_b"
        self.selftest(self.base, {"test_a": "PASS"})
        self.selftest(self.head, {"test_a": "PASS"})
        for base_outcome in ("missing-name", "pass", "error"):
            self.store(self.base, repro, {"outcome": base_outcome})
            self.store(self.head, repro, {"outcome": "pass"})
            verdict, reasons, _ = self.verdict(["selftest", repro])
            self.assertEqual(verdict, "SAME", base_outcome)
        self.assertEqual(self.verdict(["selftest"])[0], "SAME")

    def test_worse(self):
        repro = "repro:test:tests/test_a.py::T.test_b"
        self.store(self.base, repro, {"outcome": "fail"})
        self.store(self.head, repro, {"outcome": "pass"})
        self.selftest(self.base, {"test_a": "PASS", "test_b": "PASS"})
        self.selftest(self.head, {"test_a": "PASS", "test_b": "FAIL"})
        verdict, reasons, _ = self.verdict(["selftest", repro])
        self.assertEqual(verdict, "WORSE")
        self.assertIn("test_b", reasons[0])
        self.selftest(self.head, {"test_a": "PASS", "test_b": "PASS"}, {"test_a": 2})
        verdict, reasons, _ = self.verdict(["selftest", repro])
        self.assertEqual(verdict, "WORSE")
        self.assertIn("tests removed", " ".join(reasons))

    def test_fixtures_compare_shares_of_equal_runs_in_one_environment(self):
        suite = "fixtures:gate-judge"
        self.store(self.base, suite, {"fixtures": {"gate-judge-planted": [True, True, True]}})
        self.store(self.head, suite, {"fixtures": {"gate-judge-planted": [True, False, True]}})
        self.assertEqual(self.verdict([suite])[0], "WORSE")
        self.store(self.head, suite, {"fixtures": {"gate-judge-planted": [True, True]}})
        self.assertEqual(self.verdict([suite])[0], "INCOMPARABLE")
        self.store(self.head, suite, {"fixtures": {"gate-judge-planted": [True, True, True]}},
                   env={"python": "3", "os": "x", "claude": "2", "codex": "absent"})
        # the head's only measurement in the first environment still has two runs; the one in a new environment
        # has no partner at base
        self.assertEqual(self.verdict([suite])[0], "INCOMPARABLE")
        self.assertEqual(self.verdict(["fixtures:cold-reader"])[0], "INCOMPARABLE")

    def test_cost_is_measured_too(self):
        suite = "fixtures:cold-reader"
        runs = [True, True, True]
        self.store(self.base, suite, {"fixtures": {"cold-reader-clear": runs}, "units": {"cold-reader-clear": [100e3] * 3}})
        self.store(self.head, suite, {"fixtures": {"cold-reader-clear": runs}, "units": {"cold-reader-clear": [120e3] * 3}})
        self.assertNotEqual(self.verdict([suite])[0], "WORSE", "a fifth more is inside run-to-run noise")
        self.store(self.head, suite, {"fixtures": {"cold-reader-clear": runs}, "units": {"cold-reader-clear": [140e3] * 3}})
        verdict, reasons, _ = self.verdict([suite])
        self.assertEqual(verdict, "WORSE")
        self.assertIn("costs more", " ".join(reasons))
        repro = "repro:cost:fixtures:cold-reader"
        self.store(self.base, repro, {"fixtures": {"cold-reader-clear": runs}, "units": {"cold-reader-clear": [100e3] * 3}})
        self.store(self.head, repro, {"fixtures": {"cold-reader-clear": runs}, "units": {"cold-reader-clear": [70e3] * 3}})
        self.assertEqual(self.verdict([repro])[0], "BETTER", "cheaper by more than a fifth, passing as often")
        self.store(self.head, repro, {"fixtures": {"cold-reader-clear": [True, False, True]},
                                      "units": {"cold-reader-clear": [50e3] * 3}})
        self.assertEqual(self.verdict([repro])[0], "SAME", "cheaper but worse is not an improvement")

    def test_a_stochastic_reproduction(self):
        suite = "repro:fixtures:probe-inbox"
        self.store(self.base, suite, {"fixtures": {"probe-inbox": [True, False, True]}})
        self.store(self.head, suite, {"fixtures": {"probe-inbox": [True, True, True]}})
        self.assertEqual(self.verdict([suite])[0], "BETTER")
        self.store(self.base, suite, {"fixtures": {"probe-inbox": [True, True, True]}})
        self.assertEqual(self.verdict([suite])[0], "SAME")
        self.store(self.base, suite, None, measurements=[{"fixtures": {"probe-inbox": [True, True, False]}},
                                                         {"fixtures": {"probe-inbox": [True, True, True]}}])
        self.store(self.head, suite, None, measurements=[{"fixtures": {"probe-inbox": [True, True, True]}},
                                                         {"fixtures": {"probe-inbox": [True, True, True]}}])
        self.assertEqual(self.verdict([suite])[0], "BETTER", "pooled: base 5/6, head 6/6")

    def test_pushback_in_either_language(self):
        self.assertTrue(evolve.PUSHBACK.search("\u4e3a\u4ec0\u4e48\u4f60\u73b0\u5728\u5728\u6539helm\uff1f"))
        self.assertTrue(evolve.PUSHBACK.search("that is wrong"))
        self.assertFalse(evolve.PUSHBACK.search("\u597d\u7684\uff0c\u7ee7\u7eed"))

    def test_test_outcomes(self):
        ok = "..\n----------------------------------------------------------------------\nRan 2 tests in 0.1s\n\nOK\n"
        self.assertEqual(evolve.unittest_outcome(0, ok), "pass")
        self.assertEqual(evolve.unittest_outcome(0, "Ran 0 tests in 0.0s\n\nOK\n"), "error")
        self.assertEqual(evolve.unittest_outcome(1, "AssertionError: 1 != 0\nRan 1 test\n\nFAILED (failures=1)\n"), "fail")
        self.assertEqual(evolve.unittest_outcome(1, "ZeroDivisionError: division by zero\nRan 1 test\n\nFAILED (errors=1)\n"),
                         "crash")
        self.assertEqual(evolve.unittest_outcome(
            1, "AttributeError: module 'calc' has no attribute 'safe_mean'\nRan 1 test\n\nFAILED (errors=1)\n"), "missing-name")
        self.assertEqual(evolve.unittest_outcome(1, "ImportError: cannot import name 'x' from 'y'\n"), "missing-name")
        self.assertEqual(evolve.unittest_outcome(
            1, "AttributeError: 'NoneType' object has no attribute 'x'\nRan 1 test\n\nFAILED (errors=1)\n"), "crash")

    def test_a_verdict_with_a_raw_control_character_is_read(self):
        # A reviewer quoting command output can leave a raw tab or newline inside a JSON string; the verdict stands.
        text = 'Summary.\n```json\n{"verdict": "ACCEPT", "evidence": "ran\ttests\nall passed"}\n```\n'
        self.assertEqual((evolve.last_json(text) or {}).get("verdict"), "ACCEPT")
        self.assertIsNone(evolve.last_json("```json\n{not json}\n```"), "what is not JSON still reads as no verdict")
        # Only the last block is the verdict: a draft ACCEPT never stands in for a final block that does not parse.
        draft_then_broken = ('```json\n{"verdict": "ACCEPT", "note": "draft\nline"}\n```\nOn reflection:\n'
                             '```json\n{"verdict": "CHANGES", "why": "a \\q bad escape"}\n```\n')
        verdict, why = evolve.read_verdict(draft_then_broken)
        self.assertIsNone(verdict)
        self.assertIn("last json block does not parse", why)
        self.assertEqual(evolve.last_json('```json\n{"verdict": "ACCEPT"}\n```\n```json\n{"verdict": "CHANGES"}\n```'),
                         {"verdict": "CHANGES"})

    def test_review_fields_decide_not_the_headline(self):
        good = {"verdict": "ACCEPT", "kind": "fix", "kind_ok": True, "root_cause": {"status": "FIXED"},
                "reproduction": {"status": "FAITHFUL"}, "session_workaround": {"status": "WEIGHED"},
                "checks_weakened": [], "findings": [{"id": "R01", "severity": "low", "summary": "nit"}]}
        self.assertEqual(evolve.review_problems(good), [])
        for bad in ({"root_cause": {"status": "SYMPTOM-ONLY"}}, {"reproduction": {"status": "TAUTOLOGICAL"}},
                    {"checks_weakened": [{"where": "tests/t.py:4", "what": "assertEqual became assertGreaterEqual"}]},
                    {"kind_ok": False}, {"session_workaround": {"status": "WAVED-AWAY"}},
                    {"findings": [{"id": "R02", "class": "silent-path", "severity": "medium", "summary": "skips"}]}):
            self.assertTrue(evolve.review_problems({**good, **bad}), bad)
        self.assertTrue(evolve.review_problems(None))


SELFTEST = """#!/bin/bash
HERE="$(cd "$(dirname "$0")" && pwd)"
FAILS=0
for t in "$HERE"/test_*.py; do
  if python3 "$t" >/dev/null 2>&1; then echo "PASS   $(basename "$t" .py)"; else echo "FAIL   $(basename "$t" .py)"; FAILS=$((FAILS+1)); fi
done
[ $FAILS -eq 0 ]
"""
TEST_BASE = """import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import calc


class Calc(unittest.TestCase):
    def test_mean(self):
        self.assertEqual(calc.mean([1, 2, 3]), 2)


if __name__ == "__main__":
    unittest.main()
"""
TEST_HEAD = TEST_BASE.replace("""

if __name__""", """
    def test_mean_of_nothing(self):
        self.assertEqual(calc.mean([]), 0.0)


if __name__""")
REPRO = "repro:test:tests/test_calc.py::Calc.test_mean_of_nothing"
SUITES = f"selftest;{REPRO}"


class Loop(unittest.TestCase):
    """bench, compare, record, and check on a small repository, end to end."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.repo, self.ledger, self.home = d / "repo", d / "ledger", d / "home"
        (self.repo / "tests").mkdir(parents=True)
        self.home.mkdir()
        (self.repo / "tests/pipeline-selftest.sh").write_text(SELFTEST)
        (self.repo / "tests/test_calc.py").write_text(TEST_BASE)
        (self.repo / "calc.py").write_text("def mean(xs):\n    return sum(xs) / len(xs)\n")
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "mean")
        self.base = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "switch", "-qc", "evolve/chg-0001")
        (self.repo / "tests/test_calc.py").write_text(TEST_HEAD)
        (self.repo / "calc.py").write_text("def mean(xs):\n    return sum(xs) / len(xs) if xs else 0.0\n")
        git(self.repo, "commit", "-qam", "the mean of nothing is zero")
        self.head = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "switch", "-q", "main")
        # no claude or codex on PATH: the environment is recorded as absent, and the test stays offline
        self.env = {**os.environ, "PIPELINE_EVOLUTION_HOME": str(self.ledger), "PIPELINE_REPO": str(self.repo),
                    "HOME": str(self.home), "PATH": "/usr/bin:/bin"}

    def tearDown(self):
        self.tmp.cleanup()

    def bench_both(self):
        r = run("bench", self.base, "--suites", SUITES, "--instrument", "evolve/chg-0001", env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = run("bench", "evolve/chg-0001", "--suites", SUITES, env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def change(self, kind="fix", owner="not needed (a fix)"):
        (self.ledger / "incidents").mkdir(parents=True, exist_ok=True)
        (self.ledger / "incidents/INC-0001.md").write_text(
            "# INC-0001 · the mean of an empty list crashes\n\nStatus: confirmed\nKind: defect\nWhere: calc.py\n"
            f"Signature: traceback: ZeroDivisionError\n\n## Reproduction\n{REPRO}\n")
        (self.ledger / "changes").mkdir(parents=True, exist_ok=True)
        (self.ledger / "changes/CHG-0001.md").write_text(
            f"# CHG-0001 · the mean of nothing is zero\n\nIncidents: INC-0001\nKind: {kind}\nBase: {self.base}\n"
            f"Branch: evolve/chg-0001\nSuites: {SUITES}\n\n## Root cause\ncalc.py:2 divides by len(xs)\n\n"
            "## Options\n- A, the session's workaround: guard at each call site\n- B: return 0.0 for no values\n\n"
            "Chosen: B, one place\nSession workaround: generalized\n\n## Review\nResult: x\n\n"
            f"## Owner\nRuling: {owner}\n")

    def review(self, **over):
        out = self.ledger / "changes/CHG-0001-review"
        out.mkdir(parents=True, exist_ok=True)
        (out / "meta.json").write_text(json.dumps({"head": self.head}))
        v = {"verdict": "ACCEPT", "kind": "fix", "kind_ok": True, "root_cause": {"status": "FIXED"},
             "reproduction": {"status": "FAITHFUL"}, "session_workaround": {"status": "WEIGHED"},
             "checks_weakened": [], "findings": [], **over}
        (out / "change-reviewer.result.md").write_text("Summary.\n\n```json\n" + json.dumps(v) + "\n```\n")

    def test_a_proven_change(self):
        self.bench_both()
        r = run("bench", self.base, "--suites", SUITES, "--instrument", "evolve/chg-0001", env=self.env)
        self.assertIn("stored, reused", r.stdout, "a measurement is never taken twice")
        r = run("compare", self.base, "evolve/chg-0001", "--suites", SUITES, env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("BETTER", r.stdout)
        self.assertIn("base crash, head pass", r.stdout)
        self.change()
        r = run("record", "CHG-0001", env=self.env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not accept it", r.stdout)
        self.review(root_cause={"status": "SYMPTOM-ONLY"})
        r = run("record", "CHG-0001", env=self.env)
        self.assertIn("root cause SYMPTOM-ONLY", r.stdout)
        self.review()
        r = run("record", "CHG-0001", env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("Status: fixed (CHG-0001)", (self.ledger / "incidents/INC-0001.md").read_text())
        r = run("check", env=self.env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not merged into main", r.stdout)
        git(self.repo, "merge", "-q", "--ff-only", "evolve/chg-0001")
        r = run("check", env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_an_owner_kind_needs_the_owners_words(self):
        self.bench_both()
        self.change(kind="rule-change", owner='[owner 2026-09-29] "Make the mean of nothing zero." · session ' + SID)
        self.review(kind="rule-change")
        r = run("record", "CHG-0001", env=self.env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no transcript", r.stdout)
        t = self.home / ".claude/projects/-p"
        t.mkdir(parents=True)
        (t / f"{SID}.jsonl").write_text(json.dumps({"type": "user", "uuid": "u1", "timestamp": "t1",
                                                    "message": {"content": "Make the mean of nothing zero."}}) + "\n")
        r = run("record", "CHG-0001", env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_a_worse_change_is_refused(self):
        git(self.repo, "switch", "-q", "evolve/chg-0001")
        (self.repo / "tests/test_other.py").write_text("import unittest\n\n\nclass O(unittest.TestCase):\n"
                                                       "    def test_o(self):\n        self.fail('broken')\n\n\n"
                                                       "unittest.main()\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "a test that fails")
        self.head = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "switch", "-q", "main")
        self.bench_both()
        r = run("compare", self.base, "evolve/chg-0001", "--suites", SUITES, env=self.env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("WORSE", r.stdout)
        self.assertIn("test_other", r.stdout)

    def test_touchmap(self):
        (self.repo / "agents").mkdir()
        (self.repo / "agents/gate-judge.md").write_text("judge\n")
        (self.repo / "skills/inbox").mkdir(parents=True)
        (self.repo / "skills/inbox/SKILL.md").write_text("inbox\n")
        (self.repo / "tests/fixtures/agents/probe-inbox").mkdir(parents=True)
        (self.repo / "tests/fixtures/agents/probe-inbox/probe-pack.md").write_text("{repo:skills/inbox/SKILL.md}\n")
        (self.repo / "tests/fixture_expectations.py").write_text(
            'FIXTURES = {\n    "probe-inbox": {"role": "probe", "folder": "probe-inbox", "dir": "folder"},\n}\n')
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "more")
        a = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "agents/gate-judge.md").write_text("judge, clearer\n")
        (self.repo / "skills/inbox/SKILL.md").write_text("inbox, clearer\n")
        git(self.repo, "commit", "-qam", "clearer")
        r = run("touchmap", a, "HEAD", env=self.env)
        self.assertIn("required: selftest;fixtures:gate-judge,probe-inbox", r.stdout)
        self.assertIn("scenario:inbox", r.stdout)


if __name__ == "__main__":
    unittest.main()
