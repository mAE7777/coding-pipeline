"""Tests for evolve.py: the harvest finds the pipeline's own trouble and nothing else, and a change is kept only
when the rule fixed in advance says it is better, the isolated review accepts it, and the owner ruled where
they must."""
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
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


OPUS, SONNET = "claude-opus-5-5", "claude-sonnet-5-5"


def per_run(passes, output=100_000, model=OPUS, problems=None, items=6):
    """A fixture's stored run records: each run's raw usage (output tokens) by its served model, never a cost, and
    the planted items it checked (six: five runs of one planted fixture reach the route rule's floor of 30)."""
    return [{"run": i + 1, "pass": p, "problems": problems[i] if problems else (0 if p else 1), "escalated": False,
             "status": "OK", "items": items,
             "usage": {model: {"input": 0, "cache_write": 0, "cache_read": 0, "output": output}}}
            for i, p in enumerate(passes)]


def fixtures(kinds=None, **runs):
    """A fixtures measurement as bench stores it: {fixture name with _ for -: run records}."""
    runs = {k.replace("_", "-"): v for k, v in runs.items()}
    return {"fixtures": {k: [r["pass"] for r in v] for k, v in runs.items()}, "per_run": runs,
            "kinds": {k.replace("_", "-"): v for k, v in (kinds or {}).items()}}


def scenario(status, output=None, model=OPUS):
    m = {"scenarios": {"build-gate": status}}
    if output is not None:
        m["cost"] = {"build-gate": {"usage": {model: {"input": 0, "cache_write": 0, "cache_read": 0, "output": output}}}}
    return m


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
        self.store(self.base, suite, fixtures(gate_judge_planted=per_run([True, True, True])))
        self.store(self.head, suite, fixtures(gate_judge_planted=per_run([True, False, True])))
        self.assertEqual(self.verdict([suite])[0], "WORSE")
        self.store(self.head, suite, fixtures(gate_judge_planted=per_run([True, True])))
        self.assertEqual(self.verdict([suite])[0], "INCOMPARABLE")
        self.store(self.head, suite, fixtures(gate_judge_planted=per_run([True, True, True])),
                   env={"python": "3", "os": "x", "claude": "2", "codex": "absent"})
        # the head's only measurement in the first environment still has two runs; the one in a new environment
        # has no partner at base
        self.assertEqual(self.verdict([suite])[0], "INCOMPARABLE")
        self.assertEqual(self.verdict(["fixtures:cold-reader"])[0], "INCOMPARABLE")

    def test_cost_is_measured_too(self):
        suite = "fixtures:cold-reader"
        runs = [True, True, True]
        self.store(self.base, suite, fixtures(cold_reader_clear=per_run(runs, 100e3)))
        self.store(self.head, suite, fixtures(cold_reader_clear=per_run(runs, 120e3)))
        self.assertNotEqual(self.verdict([suite])[0], "WORSE", "a fifth more is inside run-to-run noise")
        self.store(self.head, suite, fixtures(cold_reader_clear=per_run(runs, 140e3)))
        verdict, reasons, _ = self.verdict([suite])
        self.assertEqual(verdict, "WORSE")
        self.assertIn("costs more: $2.00 -> $2.80 a run (500k -> 700k units)", " ".join(reasons))
        repro = "repro:cost:fixtures:cold-reader"
        self.store(self.base, repro, fixtures(cold_reader_clear=per_run(runs, 100e3)))
        self.store(self.head, repro, fixtures(cold_reader_clear=per_run(runs, 70e3)))
        self.assertEqual(self.verdict([repro])[0], "BETTER", "cheaper by more than a fifth, passing as often")
        self.store(self.head, repro, fixtures(cold_reader_clear=per_run([True, False, True], 50e3)))
        self.assertEqual(self.verdict([repro])[0], "SAME", "cheaper but worse is not an improvement")

    def test_cost_is_computed_at_compare_time_from_raw_usage(self):
        import spend
        repro = "repro:cost:fixtures:cold-reader"
        runs = [True, True, True]
        # More tokens on a cheaper model: the units rise, the dollars fall by a quarter.
        for suite in (repro, "fixtures:cold-reader"):
            self.store(self.base, suite, fixtures(cold_reader_clear=per_run(runs, 100e3, OPUS)))
            self.store(self.head, suite, fixtures(cold_reader_clear=per_run(runs, 150e3, SONNET)))
        self.assertEqual(self.verdict(["fixtures:cold-reader"])[0], "SAME", "cheaper is not worse")
        verdict, reasons, rows = self.verdict([repro])
        self.assertEqual(verdict, "BETTER", reasons)
        self.assertIn("$2.00 -> $1.50 a run (500k -> 750k units)", reasons[0])
        stored = json.dumps([json.loads(f.read_text()) for f in (evolve.HOME / "benchmarks").rglob("*.json")])
        self.assertNotIn("dollars", stored)
        # A price change after the measurements applies to both sides alike, when comparing.
        saved = spend.PRICES[SONNET]
        spend.PRICES[SONNET] = {**saved, "output": 30.00}
        try:
            verdict, reasons, _ = self.verdict([repro])
            self.assertEqual(verdict, "SAME")
            self.assertIn("$2.00 -> $4.50 a run", reasons[0])
            self.assertEqual(self.verdict([repro.replace("repro:cost:", "")])[0], "WORSE")
        finally:
            spend.PRICES[SONNET] = saved

    def test_an_old_measurement_without_raw_usage_is_not_compared_silently(self):
        suite = "fixtures:cold-reader"
        old = {"fixtures": {"cold-reader-clear": [True, True, True]}, "units": {"cold-reader-clear": [100e3] * 3}}
        new = fixtures(cold_reader_clear=per_run([True, True, True], 100e3))
        self.store(self.base, suite, old)
        self.store(self.head, suite, new)
        verdict, reasons, _ = self.verdict([suite])
        self.assertEqual(verdict, "INCOMPARABLE")
        self.assertIn("fixture cold-reader-clear: cost not comparable: the base's stored measurements hold no raw "
                      "usage", reasons[0])
        self.assertIn("--again", reasons[0])
        # Measured again on both sides, the cost comes from the measurements that hold raw usage.
        self.store(self.base, suite, None, measurements=[old, new])
        self.store(self.head, suite, None, measurements=[new, new])
        self.assertEqual(self.verdict([suite])[0], "SAME")
        # Scenarios alike.
        self.store(self.base, "scenario:build-gate", scenario("PASS"))
        self.store(self.head, "scenario:build-gate", scenario("PASS", 1e6))
        verdict, reasons, _ = self.verdict(["scenario:build-gate"])
        self.assertEqual(verdict, "INCOMPARABLE")
        self.assertIn("scenario build-gate: cost not comparable", reasons[0])

    def routed(self, before, after):
        """Two commits on this test's repository whose diff is the routing table."""
        table = self.repo / "skills/_shared/models.json"
        table.parent.mkdir(parents=True, exist_ok=True)
        shas = []
        for content in (before, after):
            table.write_text(json.dumps(content))
            git(self.repo, "add", "-A")
            git(self.repo, "commit", "-qm", "routing")
            shas.append(git(self.repo, "rev-parse", "HEAD"))
        return shas

    def test_a_routing_change_is_compared_across_the_models_it_moves_to(self):
        suite = "fixtures:cold-reader"
        env = {"python": "3", "os": "x", "claude": "1", "codex": "absent"}
        runs = [True, True, True]
        self.store(self.base, suite, fixtures(cold_reader_clear=per_run(runs, 100e3, OPUS)), env={**env, "models": [OPUS]})
        self.store(self.head, suite, fixtures(cold_reader_clear=per_run(runs, 100e3, SONNET)),
                   env={**env, "models": [SONNET]})
        verdict, reasons, _ = self.verdict([suite])
        self.assertEqual(verdict, "INCOMPARABLE", "the change does not touch the routing table")
        self.assertIn("only the served models differ", reasons[0])
        before = {"version": 1, "roles": {"gate-judge": {"model": OPUS, "effort": "xhigh"},
                                          "cold-reader": {"model": OPUS, "effort": "xhigh"}}}
        after = {"version": 1, "roles": {"gate-judge": {"model": OPUS, "effort": "xhigh"},
                                         "cold-reader": {"model": SONNET, "effort": "high"}}}
        self.base, self.head = self.routed(before, after)
        self.store(self.base, suite, fixtures(cold_reader_clear=per_run(runs, 100e3, OPUS)), env={**env, "models": [OPUS]})
        self.store(self.head, suite, fixtures(cold_reader_clear=per_run(runs, 100e3, SONNET)),
                   env={**env, "models": [SONNET]})
        verdict, reasons, rows = self.verdict([suite])
        self.assertEqual(verdict, "SAME", reasons)
        self.assertEqual(rows[0]["suite"], "model routing changed")
        self.assertEqual(rows[0]["routes"], [{"route": "roles.cold-reader", "before": f"model {OPUS}, effort xhigh",
                                              "after": f"model {SONNET}, effort high"}])
        # Only the served models are left out of the match: another Claude Code version still does not pair.
        other = "fixtures:cold-reader-clear"
        self.store(self.base, other, fixtures(cold_reader_clear=per_run(runs, 100e3, OPUS)), env={**env, "models": [OPUS]})
        self.store(self.head, other, fixtures(cold_reader_clear=per_run(runs, 100e3, SONNET)),
                   env={**env, "claude": "2", "models": [SONNET]})
        self.assertEqual(self.verdict([other])[0], "INCOMPARABLE")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            evolve.cmd_compare([self.base, self.head, "--suites", suite])
        self.assertIn(f"model routing changed (skills/_shared/models.json): roles.cold-reader: model {OPUS}, effort "
                      f"xhigh -> model {SONNET}, effort high", out.getvalue())

    def route(self, base_runs, head_runs, kinds=None):
        suite = "repro:route:fixtures:gate-judge"
        kinds = kinds if kinds is not None else {"gate_judge_planted": "planted", "gate_judge_clean": "clean"}
        self.store(self.base, suite, fixtures(kinds, **base_runs))
        self.store(self.head, suite, fixtures(kinds, **head_runs))
        return self.verdict([suite])

    def test_the_route_rule_pools_planted_problems_and_holds_every_clean_run(self):
        five = [True] * 5
        base = {"gate_judge_planted": per_run([False, True, False, True, True], problems=[1, 0, 2, 0, 0]),
                "gate_judge_clean": per_run(five)}
        cheaper = {"gate_judge_planted": per_run([True, False, True, False, True], model=SONNET, problems=[0, 2, 0, 1, 0]),
                   "gate_judge_clean": per_run(five, model=SONNET)}
        verdict, reasons, _ = self.route(base, cheaper)
        self.assertEqual(verdict, "BETTER", reasons)
        self.assertIn("planted problems 3 at base, 3 at head; clean runs passing at head 5/5; $2.00 -> $1.00 a run "
                      "(0.50 of base, at most 0.80)", reasons[0])
        # More problems pooled over the planted runs: the cheaper model misses more.
        worse = {**cheaper, "gate_judge_planted": per_run([True, False, False, False, True], model=SONNET,
                                                         problems=[0, 2, 1, 1, 0])}
        verdict, reasons, _ = self.route(base, worse)
        self.assertEqual(verdict, "SAME")
        self.assertIn("planted problems 3 at base, 4 at head", reasons[0])
        # One false block on a clean fixture.
        verdict, reasons, _ = self.route(base, {**cheaper, "gate_judge_clean": per_run([True] * 4 + [False], model=SONNET)})
        self.assertEqual(verdict, "SAME")
        self.assertIn("clean runs passing at head 4/5", reasons[0])
        # Not cheaper by a fifth.
        verdict, reasons, _ = self.route(base, {k: per_run([r["pass"] for r in v], 90e3, OPUS, [r["problems"] for r in v])
                                                for k, v in cheaper.items()})
        self.assertEqual(verdict, "SAME")
        self.assertIn("$2.00 -> $1.80 a run (0.90 of base", reasons[0])
        # A planted fixture alone cannot show the routing raises no false block.
        verdict, reasons, _ = self.route({"gate_judge_planted": base["gate_judge_planted"]},
                                         {"gate_judge_planted": cheaper["gate_judge_planted"]})
        self.assertEqual(verdict, "SAME")
        self.assertIn("0 clean fixture(s)", reasons[0])

    def test_the_route_rule_needs_kinds_counts_and_equal_runs(self):
        five = [True] * 5
        base = {"gate_judge_planted": per_run(five), "gate_judge_clean": per_run(five)}
        head = {"gate_judge_planted": per_run(five, model=SONNET), "gate_judge_clean": per_run(five, model=SONNET)}
        verdict, reasons, _ = self.route(base, {**head, "gate_judge_planted": per_run([True] * 4, model=SONNET)})
        self.assertEqual(verdict, "INCOMPARABLE")
        self.assertIn("fixture gate-judge-planted: 5 runs at base, 4 at head", " ".join(reasons))
        verdict, reasons, _ = self.route(base, head, kinds={})
        self.assertEqual(verdict, "INCOMPARABLE")
        self.assertIn("has no kind", reasons[0])
        uncounted = per_run(five, model=SONNET)
        uncounted[2]["problems"] = None
        verdict, reasons, _ = self.route(base, {**head, "gate_judge_planted": uncounted})
        self.assertEqual(verdict, "INCOMPARABLE")
        self.assertIn("records no problem count", reasons[0])
        # A probe among them keeps the ordinary rule: passing less often is worse.
        kinds = {"gate_judge_planted": "planted", "gate_judge_clean": "clean", "gate_judge_probe": "other"}
        verdict, reasons, _ = self.route({**base, "gate_judge_probe": per_run(five)},
                                         {**head, "gate_judge_probe": per_run([True, False] + [True] * 3, model=SONNET)},
                                         kinds)
        self.assertEqual(verdict, "WORSE")
        self.assertIn("fixture gate-judge-probe (other): 5/5 at base, 4/5 at head", reasons[0])
        # Old measurements, with no run records, cannot show it.
        self.store(self.base, "repro:route:fixtures:gate-judge", {"fixtures": {"gate-judge-planted": five}})
        verdict, reasons, _ = self.verdict(["repro:route:fixtures:gate-judge"])
        self.assertEqual(verdict, "INCOMPARABLE")
        self.assertIn("--again", " ".join(reasons))

    def test_the_route_rule_needs_thirty_planted_item_trials_a_side(self):
        one = {"gate_judge_planted": per_run([True]), "gate_judge_clean": per_run([True])}
        cheap = {"gate_judge_planted": per_run([True], model=SONNET), "gate_judge_clean": per_run([True], model=SONNET)}
        verdict, reasons, _ = self.route(one, cheap)
        self.assertEqual(verdict, "INCOMPARABLE")
        self.assertIn("6 planted item-trials at base and 6 at head (6 planted item(s) a run, 1 run(s)); the rule needs "
                      "at least 30 on each side: bench both sides with --runs 5 to reach it", reasons[0])
        # Records from before the count was written cannot show it.
        old = per_run([True] * 5)
        for r in old:
            del r["items"]
        verdict, reasons, _ = self.route({**one, "gate_judge_planted": old, "gate_judge_clean": per_run([True] * 5)},
                                         {"gate_judge_planted": per_run([True] * 5, model=SONNET),
                                          "gate_judge_clean": per_run([True] * 5, model=SONNET)})
        self.assertEqual(verdict, "INCOMPARABLE")
        self.assertIn("records no count of the planted items it checked", reasons[0])

    def test_a_cost_rule_with_no_priced_usage_at_base_cannot_judge(self):
        def unpriced(runs):
            for r in runs:
                r["usage"] = {}
            return runs
        five = [True] * 5
        verdict, reasons, _ = self.route({"gate_judge_planted": unpriced(per_run(five)),
                                          "gate_judge_clean": unpriced(per_run(five))},
                                         {"gate_judge_planted": unpriced(per_run(five)),
                                          "gate_judge_clean": unpriced(per_run(five))})
        self.assertEqual(verdict, "INCOMPARABLE", "$0 <= 0.8 x $0 is no saving")
        self.assertIn("no priced usage at base ($0.00 a run)", reasons[0])
        suite = "repro:cost:fixtures:gate-judge"
        self.store(self.base, suite, fixtures(None, gate_judge_clean=unpriced(per_run(five))))
        self.store(self.head, suite, fixtures(None, gate_judge_clean=unpriced(per_run(five))))
        verdict, reasons, _ = self.verdict([suite])
        self.assertEqual(verdict, "INCOMPARABLE")
        self.assertIn("fixture gate-judge-clean: no priced usage at base", " ".join(reasons))
        repro = "repro:cost:scenario:build-gate"
        self.store(self.base, repro, scenario("PASS", 0))
        self.store(self.head, repro, scenario("PASS", 0))
        verdict, reasons, _ = self.verdict([repro])
        self.assertEqual(verdict, "INCOMPARABLE")
        self.assertIn("scenario build-gate: no priced usage at base", reasons[0])

    def test_served_models_leave_the_match_only_when_the_diff_is_the_routing_table(self):
        suite = "fixtures:cold-reader"
        env = {"python": "3", "os": "x", "claude": "1", "codex": "absent"}
        before = {"version": 1, "roles": {"cold-reader": {"model": OPUS, "effort": "xhigh"}}}
        after = {"version": 1, "roles": {"cold-reader": {"model": SONNET, "effort": "high"}}}

        def compare_with(extra):
            base, head = self.routed(before, after)
            for rel, text in extra.items():
                (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (self.repo / rel).write_text(text)
            git(self.repo, "add", "-A")
            git(self.repo, "commit", "-qm", "routing and more")
            self.base, self.head = base, git(self.repo, "rev-parse", "HEAD")
            runs = [True, True, True]
            self.store(self.base, suite, fixtures(cold_reader_clear=per_run(runs, 100e3, OPUS)),
                       env={**env, "models": [OPUS]})
            self.store(self.head, suite, fixtures(cold_reader_clear=per_run(runs, 100e3, SONNET)),
                       env={**env, "models": [SONNET]})
            return self.verdict([suite])

        verdict, reasons, rows = compare_with({"docs/routing-note.md": "why\n", "NOTES.md": "x\n"})
        self.assertEqual(verdict, "SAME", reasons)
        verdict, reasons, rows = compare_with({"skills/_shared/scripts/run_isolated_extra.py": "x = 1\n"})
        self.assertEqual(verdict, "INCOMPARABLE", "code changed beside the table: the models stay in the match")
        self.assertIn("touches more than skills/_shared/models.json and documents", reasons[0])
        self.assertEqual(rows[0]["suite"], "model routing changed", "the routes that moved are still shown")
        verdict, reasons, _ = compare_with({"skills/gate/notes.md": "an instruction\n"})
        self.assertEqual(verdict, "INCOMPARABLE", "a .md file under skills/ is the pipeline's own text")

    def test_scenarios_record_cost(self):
        suite = "scenario:build-gate"
        self.store(self.base, suite, scenario("PASS", 1e6))  # $20.00 on Opus
        self.store(self.head, suite, scenario("PASS", 1.2e6))
        self.assertEqual(self.verdict([suite])[0], "SAME", "a fifth more is inside run-to-run noise")
        self.store(self.head, suite, scenario("PASS", 1.3e6))
        verdict, reasons, rows = self.verdict([suite])
        self.assertEqual(verdict, "WORSE")
        self.assertIn("scenario build-gate costs more: $20.00 -> $26.00 a run", reasons[0])
        self.assertEqual(rows[0]["head"], "build-gate PASS $26.00")
        # A scenario that failed at base stopped early: its cost is no measure of a full run.
        self.store(self.base, suite, scenario("FAIL", 0.2e6))
        self.assertEqual(self.verdict([suite])[0], "SAME")
        repro = "repro:cost:scenario:build-gate"
        self.store(self.base, repro, scenario("PASS", 1e6))
        self.store(self.head, repro, scenario("PASS", 1.5e6, SONNET))  # $15.00
        verdict, reasons, _ = self.verdict([repro])
        self.assertEqual(verdict, "BETTER", reasons)
        self.assertIn("scenario build-gate cost: $20.00 -> $15.00 a run", reasons[0])
        self.store(self.head, repro, scenario("FAIL", 0.5e6, SONNET))
        self.assertEqual(self.verdict([repro])[0], "SAME", "cheaper but failing is not an improvement")
        self.store(self.head, repro, scenario("PASS", 1.7e6, SONNET))  # $17.00, a cut of only 15 percent
        self.assertEqual(self.verdict([repro])[0], "SAME")

    def test_a_stochastic_reproduction(self):
        suite = "repro:fixtures:probe-inbox"
        self.store(self.base, suite, fixtures(probe_inbox=per_run([True, False, True])))
        self.store(self.head, suite, fixtures(probe_inbox=per_run([True, True, True])))
        self.assertEqual(self.verdict([suite])[0], "BETTER")
        self.store(self.base, suite, fixtures(probe_inbox=per_run([True, True, True])))
        self.assertEqual(self.verdict([suite])[0], "SAME")
        self.store(self.base, suite, None, measurements=[fixtures(probe_inbox=per_run([True, True, False])),
                                                         fixtures(probe_inbox=per_run([True, True, True]))])
        self.store(self.head, suite, None, measurements=[fixtures(probe_inbox=per_run([True, True, True])),
                                                         fixtures(probe_inbox=per_run([True, True, True]))])
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

    def test_a_failure_reason_leaves_out_what_differs_from_run_to_run(self):
        # Two runs of one reproduction whose message names the commits of that run.
        a = {"outcome": "fail", "tail": "Traceback (most recent call last):\nAssertionError: 1 != 0 : FAIL   evolve      "
             "CHG-0001: the review was of f4d86f1469c6, the branch is at b38da9e6c76a: review again\n\n"
             "Ran 1 test in 2.1s\n\nFAILED (failures=1)\n"}
        b = {**a, "tail": a["tail"].replace("f4d86f1469c6", "660d818a6f5a").replace("b38da9e6c76a", "47c3cdf3e004")}
        self.assertEqual(evolve.reason_of(a), evolve.reason_of(b))
        self.assertNotEqual(evolve.reason_of(a), evolve.reason_of({"outcome": "crash", "tail": "KeyError: 'x'\n"}))
        self.assertEqual(evolve.reason_of({"fixtures": {"probe-inbox": [False, True], "other": [True]}}),
                         "fixtures failing: probe-inbox")
        self.assertEqual(evolve.reason_of({"scenarios": {"adopt": "FAIL", "plan": "PASS"}}), "scenarios failing: adopt")
        # Two different failed comparisons stay different.
        self.assertNotEqual(evolve.reason_of({"outcome": "fail", "error": "AssertionError: 'the review was of another commit' != 'ok'"}),
                            evolve.reason_of({"outcome": "fail", "error": "AssertionError: 'a KeyError in the ledger reader' != 'ok'"}))
        # A long message pushes the exception line out of the stored tail; the full output's line is kept apart.
        out = ("F\n" + "=" * 70 + "\nFAIL: test_x (t.T.test_x)\n" + "-" * 70 + "\nTraceback (most recent call last):\n"
               "  File \"t.py\", line 3, in test_x\n    self.assertEqual(r.returncode, 0, r.stdout)\n"
               "AssertionError: 1 != 0 : PASS   first line of a long report\n" + "PASS   another line\n" * 200 +
               "\n" + "-" * 70 + "\nRan 1 test in 0.1s\n\nFAILED (failures=1)\n")
        self.assertEqual(evolve.error_line(out), "AssertionError: 1 != 0 : PASS   first line of a long report")
        self.assertIsNone(evolve.reason_of({"outcome": "fail", "tail": out[-1500:]}), "a reason that cannot be told")
        self.assertEqual(evolve.reason_of({"outcome": "fail", "error": evolve.error_line(out), "tail": out[-1500:]}),
                         "fail: AssertionError: <n> != <n> : PASS first line of a long report")

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


FAKE_FIXTURES = '''import json, os, sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
want = os.environ.get("PIPELINE_MODELS_IGNORE_OVERRIDE")
for n in (1, 2):
    ev = root / ".evidence/fixtures/gate-judge-planted" / f"run-{n}"
    ev.mkdir(parents=True)
    (ev / "gate-judge.summary.json").write_text(json.dumps({"status": "OK", "model": "claude-sonnet-5-5",
        "usage": {"input": 10, "cache_write": 0, "cache_read": 1000, "output": 500 * n}}))
    (ev / "fixture-result.json").write_text(json.dumps({"kind": "planted", "pass": n == 1, "problem_count": n - 1,
        "items": 4, "escalated": False, "status": "OK", "dollars": 99}))
    print(("PASS" if n == 1 and want == "1" else "FAIL") + f"  gate-judge-planted  run {n}  override={want}")
'''
FAKE_SCENARIOS = '''import json, os
from pathlib import Path
ev = Path(__file__).resolve().parents[1] / ".evidence/system/build-gate"
ev.mkdir(parents=True)
(ev / "cost.json").write_text(json.dumps({"usage": {"claude-opus-5-5": {"input": 1, "cache_write": 2, "cache_read": 3,
    "output": 4}, "codex:gpt-x": {"input": 5, "cache_write": 0, "cache_read": 0, "output": 6}}, "dollars": 99}))
print("PASS  build-gate" if os.environ.get("PIPELINE_MODELS_IGNORE_OVERRIDE") == "1" else "FAIL  build-gate")
print("      build-gate cost: ...")
'''


class Instrument(unittest.TestCase):
    """What bench reads from the fixture and scenario harnesses, and what they record, without any model."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_bench_reads_raw_usage_and_the_runs_records_with_the_override_ignored(self):
        tree = self.d / "tree"
        (tree / "tests").mkdir(parents=True)
        (tree / "tests/agent_fixtures.py").write_text(FAKE_FIXTURES)
        (tree / "tests/system_scenarios.py").write_text(FAKE_SCENARIOS)
        saved = os.environ.pop("PIPELINE_MODELS_IGNORE_OVERRIDE", None)
        try:
            m = evolve.measure(tree, "repro:route:fixtures:gate-judge", 2)
            s = evolve.measure(tree, "scenario:build-gate", 1)
        finally:
            if saved is not None:
                os.environ["PIPELINE_MODELS_IGNORE_OVERRIDE"] = saved
        self.assertEqual(m["fixtures"], {"gate-judge-planted": [True, False]}, "the suite ran with the override ignored")
        self.assertEqual(m["kinds"], {"gate-judge-planted": "planted"})
        self.assertEqual(m["models"], [SONNET])
        runs = m["per_run"]["gate-judge-planted"]
        self.assertEqual([(r["run"], r["problems"], r["pass"]) for r in runs], [(1, 0, True), (2, 1, False)])
        self.assertEqual([r["items"] for r in runs], [4, 4], "the planted items each run checked")
        self.assertEqual(runs[1]["usage"], {SONNET: {"input": 10, "cache_write": 0, "cache_read": 1000, "output": 1000}})
        self.assertNotIn("dollars", json.dumps(m), "raw usage is stored, never a cost")
        self.assertEqual(s["scenarios"], {"build-gate": "PASS"})
        self.assertEqual(s["models"], [OPUS, "codex:gpt-x"])
        self.assertEqual(s["cost"]["build-gate"]["usage"][OPUS]["output"], 4)
        self.assertNotIn("dollars", json.dumps(s))
        u, d, codex = evolve.run_cost(s["cost"]["build-gate"]["usage"])
        self.assertEqual(codex, 11, "Codex tokens are counted apart")
        self.assertAlmostEqual(d, (1 * 4 + 2 * 5 + 3 * 0.2 + 4 * 20) / 1e6)

    def fixture_run(self, *summaries):
        ev = self.d / f"run-{len(list(self.d.iterdir()))}"
        ev.mkdir()
        for name, s in summaries:
            (ev / f"{name}.summary.json").write_text(json.dumps(s))
        return ev

    def test_a_fixture_run_records_usage_cost_problems_and_escalation(self):
        sys.path.insert(0, str(ROOT / "tests"))
        import agent_fixtures
        from fixture_expectations import FIXTURES
        spec = FIXTURES["gate-judge-planted"]
        self.assertEqual(spec["kind"], "planted")
        self.assertEqual({s["kind"] for s in FIXTURES.values()}, {"planted", "clean", "other"})
        self.assertEqual(FIXTURES["probe-inbox"]["kind"], "other")
        misses = len(spec["expect"]({}, {"summary": {}, "result": ""}))
        self.assertGreater(misses, 1)
        usage = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 1_000_000}
        ev = self.fixture_run(("gate-judge", {"status": "OK", "model": SONNET, "usage": usage}),
                              ("code-verifier", {"status": "OK", "family": "codex", "model": "gpt-x", "usage": usage}))
        _, _, problems, _, rec = agent_fixtures.record("gate-judge-planted", spec, 1, ev, ["not caught: x"], True,
                                                       {"status": "OK"})
        self.assertEqual((rec["kind"], rec["pass"], rec["problem_count"], rec["escalated"]), ("planted", False, 1, False))
        self.assertEqual(rec["items"], misses, "a planted run checks every item an empty verdict misses")
        clean = agent_fixtures.record("gate-judge-clean", FIXTURES["gate-judge-clean"], 1, self.fixture_run(), [], True,
                                      {"status": "OK"})[4]
        self.assertEqual(clean["items"], 0, "a clean control plants nothing")
        self.assertEqual(rec["usage"][SONNET]["output"], 1_000_000)
        self.assertIn("codex:gpt-x", rec["usage"])
        self.assertEqual(rec["dollars"], 10.0, "Sonnet's output price; Codex is never priced")
        self.assertEqual(json.loads((ev / "fixture-result.json").read_text())["problem_count"], 1)
        # A run escalated to another model fails, and counts as missing everything, whatever the retry found.
        ev = self.fixture_run(("gate-judge", {"status": "OK", "model": OPUS, "escalated": True, "usage": usage}))
        _, _, problems, _, rec = agent_fixtures.record("gate-judge-planted", spec, 2, ev, [], True, {"status": "OK"})
        self.assertFalse(rec["pass"])
        self.assertIn("escalated", problems[-1])
        self.assertEqual(rec["problem_count"], 1 + misses)
        # A run with no verdict of its own missed everything too.
        ev = self.fixture_run(("gate-judge", {"status": "ERROR", "model": SONNET}))
        rec = agent_fixtures.record("gate-judge-planted", spec, 3, ev, ["runner status ERROR", "no JSON verdict block"],
                                    False, {"status": "ERROR"})[4]
        self.assertEqual(rec["problem_count"], 1 + misses)
        self.assertEqual(rec["usage"], {})

    def test_a_scenario_records_its_sessions_and_the_runs_they_caused(self):
        sys.path.insert(0, str(ROOT / "tests"))
        import system_scenarios as sc
        ev, project = self.d / "ev", self.d / "project"
        ev.mkdir()
        call = lambda mid, out, model=None: json.dumps({"type": "assistant", "message": {
            "id": mid, **({"model": model} if model else {}), "usage": {"input_tokens": 1, "output_tokens": out}}})
        (ev / "dev.jsonl").write_text("\n".join([
            json.dumps({"type": "system", "subtype": "init", "model": OPUS, "session_id": "s1"}),
            call("m1", 10), call("m1", 30),  # one call, streamed twice: its latest usage counts once
            call("m2", 100, SONNET),
            json.dumps({"type": "result", "usage": {"output_tokens": 999}}),  # its calls are counted already
            json.dumps({"type": "system", "subtype": "init", "model": OPUS, "session_id": "s1"}),
            json.dumps({"type": "result", "usage": {"input_tokens": 5, "output_tokens": 7}}),  # a turn with no calls
        ]) + "\n")
        since = time.time() - 100
        runs = project / ".evidence/gate/M1/r1"
        runs.mkdir(parents=True)
        (runs / "gate-judge.summary.json").write_text(json.dumps({"served_model": SONNET, "model": OPUS,
                                                                  "usage": {"output": 1000}}))
        (runs / "code-verifier.summary.json").write_text(json.dumps({"family": "codex", "model": "gpt-x",
                                                                     "usage": {"output": 50}}))
        (runs / "loyal-evaluator.summary.json").write_text(json.dumps({"status": "BLOCKED"}))
        old = runs / "old.summary.json"
        old.write_text(json.dumps({"model": OPUS, "usage": {"output": 10**9}}))
        os.utime(old, (since - 50, since - 50))
        cost = sc.record_cost(ev, [project], since)
        self.assertEqual(cost["usage"], {
            OPUS: {"input": 6, "cache_write": 0, "cache_read": 0, "output": 37},
            SONNET: {"input": 1, "cache_write": 0, "cache_read": 0, "output": 1100},
            "codex:gpt-x": {"input": 0, "cache_write": 0, "cache_read": 0, "output": 50}})
        self.assertEqual((cost["isolated"]["runs"], cost["isolated"]["without_usage"]), (2, 1))
        self.assertAlmostEqual(cost["dollars"], round((6 * 4 + 37 * 20 + 1 * 2 + 1100 * 10) / 1e6, 4))
        self.assertEqual(json.loads((ev / "cost.json").read_text())["usage"], cost["usage"])
        self.assertIn("isolated run(s); models claude-opus-5-5, claude-sonnet-5-5, codex:gpt-x", sc.cost_line(cost))

    def test_the_three_milestone_scenario_has_a_dry_run(self):
        home = self.d / "home"
        home.mkdir()
        env = {**os.environ, "HOME": str(home), "PATH": "/usr/bin:/bin"}  # no claude to call
        r = subprocess.run([sys.executable, str(ROOT / "tests/system_scenarios.py"), "--only", "build-gate-3", "--dry-run"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for want in ("/plan I want a small command-line reading log", "/dev M2", "/gate accept M3",
                     "I accept M3.", "replayed", "no model was called"):
            self.assertIn(want, r.stdout)
        self.assertEqual(list(home.iterdir()), [], "a dry run makes no folder")
        r = subprocess.run([sys.executable, str(ROOT / "tests/system_scenarios.py"), "--only", "build-gate-4", "--dry-run"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown scenario build-gate-4", r.stderr)


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
# The same test, failing at the base with a message that differs on every run, as real failure messages often do.
TEST_HEAD_VARYING = TEST_HEAD.replace("""        self.assertEqual(calc.mean([]), 0.0)""", """        try:
            got = calc.mean([])
        except ZeroDivisionError:
            raise AssertionError("the mean of nothing crashed in run " + __import__("os").urandom(6).hex())
        self.assertEqual(got, 0.0)""")
REPRO = "repro:test:tests/test_calc.py::Calc.test_mean_of_nothing"
NOTE = "docé.md"  # git quotes such a name unless asked not to
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

    def review(self, status="OK", **over):
        out = self.ledger / "changes/CHG-0001-review"
        out.mkdir(parents=True, exist_ok=True)
        (out / "meta.json").write_text(json.dumps({"head": self.head}))
        v = {"verdict": "ACCEPT", "kind": "fix", "kind_ok": True, "root_cause": {"status": "FIXED"},
             "reproduction": {"status": "FAITHFUL"}, "session_workaround": {"status": "WEIGHED"},
             "checks_weakened": [], "findings": [], **over}
        (out / "change-reviewer.result.md").write_text("Summary.\n\n```json\n" + json.dumps(v) + "\n```\n")
        (out / "change-reviewer.summary.json").write_text(json.dumps({"status": status, "tool_uses": 4}))

    def fingerprint(self, base, head):
        """What a review covers, computed with git the same way the judge does: the change's own diff byte for byte
        with full blob ids but without its hunk line numbers, and each file it touches (renames split, names
        unquoted) as it was at the base."""
        diff = subprocess.run(["git", "-C", str(self.repo), "diff", "--no-renames", "--no-ext-diff", "--no-textconv",
                               "--full-index", f"{base}..{head}"], capture_output=True, text=True).stdout
        kept = [re.sub(r"^@@ -\d+(,\d+)? \+\d+(,\d+)? @@", "@@", l) for l in diff.splitlines()]
        names = subprocess.run(["git", "-C", str(self.repo), "diff", "--no-renames", "--name-only", "-z",
                                f"{base}..{head}"], capture_output=True, text=True).stdout
        return {"diff_sha256": __import__("hashlib").sha256("\n".join(kept).encode()).hexdigest(),
                "touched": {f: self.blob(base, f) for f in names.split("\0") if f}}

    def amend_branch(self, files):
        git(self.repo, "switch", "-q", "evolve/chg-0001")
        for rel, content in files.items():
            (self.repo / rel).write_bytes(content if isinstance(content, bytes) else content.encode())
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--amend", "--no-edit")
        self.head = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "switch", "-q", "main")

    def in_repo(self, fn, *args):
        """Call an evolve function against this test's repository and ledger, as the command would."""
        saved, saved_home = os.environ.get("PIPELINE_REPO"), evolve.HOME
        os.environ["PIPELINE_REPO"], evolve.HOME = str(self.repo), self.ledger
        try:
            return fn(*args)
        finally:
            evolve.HOME = saved_home
            os.environ.pop("PIPELINE_REPO") if saved is None else os.environ.__setitem__("PIPELINE_REPO", saved)

    def blob(self, ref, path):
        r = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "--verify", "--quiet", f"{ref}:{path}"],
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""

    def rebase_onto_new_main(self, rel, text):
        git(self.repo, "switch", "-q", "main")
        (self.repo / rel).write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "meanwhile on main")
        self.base = git(self.repo, "rev-parse", "HEAD")
        r = subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@example.com",
                            "rebase", "-q", "main", "evolve/chg-0001"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, "the rebase itself must succeed: " + r.stdout + r.stderr)
        self.head = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "switch", "-q", "main")
        record = self.ledger / "changes/CHG-0001.md"
        record.write_text(re.sub(r"^Base: .*$", f"Base: {self.base}", record.read_text(), count=1, flags=re.M))

    def test_a_rebase_that_leaves_the_change_as_it_was_keeps_its_review(self):
        self.amend_branch({"tests/test_calc.py": TEST_HEAD_VARYING})
        self.bench_both()
        self.change()
        self.review()
        # What this version's review writes beside its result, or, before reviews carried a fingerprint, the head alone.
        meta = self.ledger / "changes/CHG-0001-review/meta.json"
        record = {"base": self.base, "head": self.head}
        if hasattr(evolve, "review_record"):
            pack = self.ledger / "changes/CHG-0001-review/pack.md"
            pack.write_text("the pack\n")
            record = self.in_repo(evolve.review_record, self.base, self.head, [REPRO], pack)
            self.assertIn("<id>", record["repro_failures"][REPRO])
        meta.write_text(json.dumps(record))
        self.rebase_onto_new_main("notes.txt", "an unrelated file\n")
        self.bench_both()
        r = run("record", "CHG-0001", env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_a_review_does_not_follow_a_change_whose_ground_or_diff_moved(self):
        self.bench_both()
        self.change()
        self.review()
        meta = self.ledger / "changes/CHG-0001-review/meta.json"
        meta.write_text(json.dumps({"base": self.base, "head": self.head, **self.fingerprint(self.base, self.head)}))
        # A file the change touches changed underneath it: the reviewer never saw that combination.
        self.rebase_onto_new_main("tests/test_calc.py", '"""The mean of a report."""\n' + TEST_BASE)
        self.bench_both()
        r = run("record", "CHG-0001", env=self.env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("tests/test_calc.py changed underneath it", r.stdout)
        # The change's own diff changed: a different change.
        meta.write_text(json.dumps({"base": self.base, "head": self.head, **self.fingerprint(self.base, self.head)}))
        git(self.repo, "switch", "-q", "evolve/chg-0001")
        (self.repo / "calc.py").write_text((self.repo / "calc.py").read_text().replace("else 0.0", "else 0"))
        git(self.repo, "commit", "-qam", "a different answer")
        self.head = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "switch", "-q", "main")
        r = run("record", "CHG-0001", env=self.env)
        self.assertIn("the change's own diff is different", r.stdout)

    def judge(self, meta, suites=()):
        return self.in_repo(evolve.review_covers, meta, self.base, self.head, suites)

    def test_whitespace_renames_and_a_new_failure_all_void_a_review(self):
        meta = {"head": "0" * 40, **self.fingerprint(self.base, self.head)}
        self.assertEqual(self.judge(meta), (True, ""))
        # Only the indentation changes: in Python that is another program.
        git(self.repo, "switch", "-q", "evolve/chg-0001")
        (self.repo / "calc.py").write_text((self.repo / "calc.py").read_text().replace("    return", "\treturn"))
        git(self.repo, "commit", "-qam", "tabs")
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(self.judge(meta), (False, "the change's own diff is different"))
        # A rename: the old path is part of the ground the review stood on.
        git(self.repo, "mv", "calc.py", "stats.py")
        git(self.repo, "commit", "-qm", "rename")
        self.head = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "switch", "-q", "main")
        meta = {"head": "0" * 40, **self.fingerprint(self.base, self.head)}
        self.assertIn("calc.py", meta["touched"])
        # A reason that cannot be told never passes for the same one: the base was never measured.
        meta["repro_failures"] = {REPRO: "error: error: ValueError: something else"}
        self.assertEqual(self.judge(meta, [REPRO]), (False, f"the new base was never measured on {REPRO}: bench it first"))
        # Measured, it fails for another reason than the review saw.
        r = run("bench", self.base, "--suites", REPRO, "--instrument", "evolve/chg-0001", env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        covered, why = self.judge(meta, [REPRO])
        self.assertFalse(covered)
        self.assertIn("fails at the new base for another reason", why)
        # A review that recorded no reason for a reproduction does not cover it either.
        meta["repro_failures"] = {}
        self.assertEqual(self.judge(meta, [REPRO]),
                         (False, f"the review holds no failure reason for the reproduction {REPRO}"))

    def test_a_binary_file_or_an_unusual_name_is_seen(self):
        self.change()
        (self.repo / NOTE).write_text("one\n\n\n\n\n\n\ntwo\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "a note")
        git(self.repo, "switch", "-q", "evolve/chg-0001")
        git(self.repo, "rebase", "-q", "main")
        git(self.repo, "switch", "-q", "main")
        self.base = git(self.repo, "rev-parse", "main")
        self.amend_branch({"data.bin": b"\x00\x01\x02 one", NOTE: "one, edited\n\n\n\n\n\n\ntwo\n"})
        meta = {"head": "0" * 40, **self.fingerprint(self.base, self.head)}
        self.assertIn(NOTE, meta["touched"])
        self.assertTrue(meta["touched"][NOTE], "a non-ASCII path is looked up at the base")
        self.assertEqual(self.judge(meta), (True, ""))
        # A binary file's content changed after the review: git's diff shows no text, only its blob id.
        self.amend_branch({"data.bin": b"\x00\x01\x02 two"})
        self.assertEqual(self.judge(meta), (False, "the change's own diff is different"))
        # A file with a non-ASCII name changed underneath, far from the change's own lines.
        self.amend_branch({"data.bin": b"\x00\x01\x02 one"})
        self.assertEqual(self.judge(meta), (True, ""))
        self.rebase_onto_new_main(NOTE, "one\n\n\n\n\n\n\ntwo, edited on main\n")
        self.assertEqual(self.judge(meta), (False, f"{NOTE} changed underneath it"))

    def test_the_judge_fingerprints_what_it_reviews(self):
        fp = self.in_repo(evolve.fingerprint, self.base, self.head)
        self.assertEqual({k: fp[k] for k in ("diff_sha256", "touched")}, self.fingerprint(self.base, self.head))
        self.assertEqual(sorted(fp["touched"]), ["calc.py", "tests/test_calc.py"])

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

    def test_a_review_counts_only_from_a_reviewer_run_marked_ok(self):
        self.bench_both()
        self.change()
        self.review(status="INCONCLUSIVE")  # an ACCEPT with every field set, from a run that used no tool
        summary = self.ledger / "changes/CHG-0001-review/change-reviewer.summary.json"
        summary.write_text(json.dumps({"status": "INCONCLUSIVE", "tool_uses": 0}))
        r = run("record", "CHG-0001", env=self.env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("the change reviewer's run is INCONCLUSIVE (0 tool use(s)), not OK", r.stdout)
        summary.write_text(json.dumps({"status": "LEAK", "reason": "a canary appeared"}))
        self.assertIn("is LEAK (a canary appeared)", run("record", "CHG-0001", env=self.env).stdout)
        summary.unlink()
        self.assertIn("left no readable change-reviewer.summary.json", run("record", "CHG-0001", env=self.env).stdout)
        self.review()
        r = run("record", "CHG-0001", env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_review_refuses_a_reviewer_run_that_is_not_ok(self):
        from unittest import mock
        self.bench_both()
        self.change()
        real = subprocess.run
        accept = {"verdict": "ACCEPT", "kind": "fix", "kind_ok": True, "root_cause": {"status": "FIXED"},
                  "reproduction": {"status": "FAITHFUL"}, "session_workaround": {"status": "WEIGHED"},
                  "checks_weakened": [], "findings": []}

        def stand_in(status):
            def fake(cmd, *args, **kw):
                if any(str(c).endswith("run_isolated.py") for c in cmd):
                    out = Path(cmd[cmd.index("--out") + 1])
                    (out / "change-reviewer.summary.json").write_text(json.dumps({"status": status, "tool_uses": 0}))
                    (out / "change-reviewer.result.md").write_text("```json\n" + json.dumps(accept) + "\n```\n")
                    return subprocess.CompletedProcess(cmd, 0, "", "")
                return real(cmd, *args, **kw)
            return fake

        for status, code in (("INCONCLUSIVE", 1), ("OK", 0)):
            printed = io.StringIO()
            with mock.patch.dict(os.environ, {"HOME": str(self.home)}), \
                    mock.patch.object(evolve.subprocess, "run", side_effect=stand_in(status)), \
                    contextlib.redirect_stdout(printed):
                self.assertEqual(self.in_repo(evolve.cmd_review, ["CHG-0001"]), code, printed.getvalue())
            if code:
                self.assertIn("the change reviewer's run is INCONCLUSIVE (0 tool use(s)), not OK", printed.getvalue())

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
