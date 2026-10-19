"""Tests for heavy.py (lock and leases) and heavy-guard.py (the PreToolUse enforcement)."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEAVY = ROOT / "skills/_shared/scripts/heavy.py"
GUARD = ROOT / "hooks/heavy-guard.py"
PY = sys.executable


class HeavyTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {**os.environ, "HEAVY_LOCK_DIR": self.tmp.name}
        for var in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "HEAVY_OWNER", "HEAVY_LOCK_HELD"):
            self.env.pop(var, None)

    def tearDown(self):
        subprocess.run([PY, str(HEAVY), "release", "--owner", "A"], env=self.env)
        subprocess.run([PY, str(HEAVY), "release", "--owner", "B"], env=self.env)
        self.tmp.cleanup()

    def heavy(self, *args, owner=None, **kw):
        extra = ["--owner", owner] if owner else []
        cmd = [PY, str(HEAVY), args[0], *extra, *args[1:]]
        return subprocess.run(cmd, capture_output=True, text=True, env=self.env, **kw)

    def bg(self, *args, owner):
        return subprocess.Popen([PY, str(HEAVY), args[0], "--owner", owner, *args[1:]], env=self.env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class HeavyLockTest(HeavyTestBase):
    def test_runs_and_returns_exit_code(self):
        self.assertEqual(self.heavy("held").returncode, 1)
        out = self.heavy("run", "--", PY, "-c", "import sys; sys.exit(3)", owner="A")
        self.assertEqual(out.returncode, 3)
        self.assertEqual(self.heavy("held").returncode, 1, "released after the command")

    def test_second_job_waits_then_busy(self):
        holder = self.bg("run", "--", PY, "-c", "import time; time.sleep(6)", owner="A")
        time.sleep(1)
        try:
            self.assertIn("held by A", self.heavy("status").stdout)
            out = self.heavy("run", "--wait", "2", "--", "echo", "should-not-run", owner="B")
            self.assertEqual(out.returncode, 75)
            self.assertNotIn("should-not-run", out.stdout)
            self.assertIn("BUSY", out.stderr)
        finally:
            holder.wait()

    def test_second_job_runs_after_first(self):
        holder = self.bg("run", "--", PY, "-c", "import time; time.sleep(2)", owner="A")
        time.sleep(0.5)
        out = self.heavy("run", "--wait", "20", "--", "echo", "ran", owner="B")
        holder.wait()
        self.assertEqual(out.returncode, 0)
        self.assertIn("ran", out.stdout)

    def test_killed_holder_leaves_no_stale_lock(self):
        holder = self.bg("run", "--", PY, "-c", "import time; time.sleep(30)", owner="A")
        time.sleep(1)
        self.assertEqual(self.heavy("held", owner="B").returncode, 0)
        holder.kill()
        holder.wait()
        time.sleep(0.5)
        self.assertEqual(self.heavy("held", owner="B").returncode, 1)

    def test_children_do_not_outlive_the_job(self):
        marker = Path(self.tmp.name) / "child.pid"
        code = (f"import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
                f"open({str(marker)!r},'w').write(str(p.pid))")
        self.heavy("run", "--", PY, "-c", code, owner="A")
        time.sleep(2)
        pid = int(marker.read_text())
        alive = True
        try:
            os.kill(pid, 0)
        except OSError:
            alive = False
        self.assertFalse(alive, "a child left running by the job must be terminated with its group")

    def test_events_log_shows_no_overlap(self):
        a = self.bg("run", "--", PY, "-c", "import time; time.sleep(1.5)", owner="A")
        time.sleep(0.2)
        self.heavy("run", "--wait", "20", "--", PY, "-c", "import time; time.sleep(0.5)", owner="B")
        a.wait()
        events = [json.loads(l) for l in (Path(self.tmp.name) / "events.log").read_text().splitlines()]
        running, peak = 0, 0
        for e in sorted(events, key=lambda e: e["t"]):
            running += 1 if e["event"] == "run-start" else -1 if e["event"] == "run-end" else 0
            peak = max(peak, running)
        self.assertEqual(peak, 1)


    def test_nested_run_reenters_instead_of_waiting(self):
        inner = f"import subprocess,sys; sys.exit(subprocess.call([sys.executable, {str(HEAVY)!r}, 'run', '--wait', '2', '--', 'echo', 'inner-ran']))"
        out = self.heavy("run", "--", PY, "-c", inner, owner="A")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("inner-ran", out.stdout)
        events = (Path(self.tmp.name) / "events.log").read_text()
        self.assertIn("run-nested", events)

    def test_forged_reentry_token_does_not_bypass(self):
        holder = self.bg("run", "--", PY, "-c", "import time; time.sleep(6)", owner="A")
        time.sleep(1)
        try:
            env = {**self.env, "HEAVY_LOCK_HELD": "B:999999"}
            out = subprocess.run([PY, str(HEAVY), "run", "--owner", "B", "--wait", "2", "--", "echo", "x"],
                                 capture_output=True, text=True, env=env)
            self.assertEqual(out.returncode, 75, "a token naming a process that does not hold the lock is ignored")
        finally:
            holder.wait()

    def test_timeout_stops_the_group(self):
        start = time.time()
        out = self.heavy("run", "--timeout", "1", "--", PY, "-c", "import time; time.sleep(30)", owner="A")
        self.assertEqual(out.returncode, 124)
        self.assertIn("TIMEOUT", out.stderr)
        self.assertLess(time.time() - start, 15)
        self.assertEqual(self.heavy("held", owner="B").returncode, 1, "lock released after a timeout")

    def test_permission_error_counts_as_alive(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("heavy_mod", HEAVY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        real = mod.os.kill

        def deny(pid, sig):
            raise PermissionError(1, "Operation not permitted")
        mod.os.kill = deny
        try:
            self.assertTrue(mod.pid_alive(12345))
        finally:
            mod.os.kill = real


class HeavyLeaseTest(HeavyTestBase):
    def test_leases_refuse_without_owner(self):
        self.assertEqual(self.heavy("lease", "browser").returncode, 2)
        self.assertEqual(self.heavy("serve", "--", "echo", "x").returncode, 2)
        self.assertEqual(self.heavy("release").returncode, 2)
        env = {**self.env, "HEAVY_OWNER": "C"}
        out = subprocess.run([PY, str(HEAVY), "lease", "browser"], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, "HEAVY_OWNER counts as an owner")
        subprocess.run([PY, str(HEAVY), "release"], env=env)
        env = {**self.env, "CODEX_THREAD_ID": "thr-9"}
        out = subprocess.run([PY, str(HEAVY), "lease", "browser"], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, "a Codex session (CODEX_THREAD_ID) counts as an owner")
        self.assertIn("thr-9", subprocess.run([PY, str(HEAVY), "status"], capture_output=True, text=True, env=env).stdout)
        subprocess.run([PY, str(HEAVY), "release"], env=env)
        both = subprocess.run([PY, str(HEAVY), "lease", "browser"], capture_output=True, text=True,
                              env={**env, "CLAUDE_CODE_SESSION_ID": "c-1"})
        self.assertEqual(both.returncode, 2, "an ambiguous session is no owner")

    def test_foreign_serve_lease_blocks_bounded_job(self):
        server = self.bg("serve", "--", PY, "-c", "import time; time.sleep(8)", owner="A")
        time.sleep(1)
        try:
            out = self.heavy("run", "--wait", "2", "--", "echo", "x", owner="B")
            self.assertEqual(out.returncode, 75)
            self.assertIn("serve lease of A", out.stderr)
        finally:
            server.terminate()
            server.wait()

    def test_owner_runs_alongside_own_server(self):
        server = self.bg("serve", "--", PY, "-c", "import time; time.sleep(8)", owner="A")
        time.sleep(1)
        try:
            out = self.heavy("run", "--wait", "3", "--", "echo", "tests-ran", owner="A")
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("tests-ran", out.stdout)
        finally:
            server.terminate()
            server.wait()

    def test_serve_lease_ends_with_process(self):
        server = self.bg("serve", "--", PY, "-c", "import time; time.sleep(1)", owner="A")
        server.wait()
        time.sleep(0.3)
        self.assertEqual(self.heavy("held", owner="B").returncode, 1)

    def test_browser_lease_and_release(self):
        self.assertEqual(self.heavy("lease", "browser", owner="A").returncode, 0)
        self.assertEqual(self.heavy("lease", "browser", owner="A").returncode, 0, "refresh by owner")
        busy = self.heavy("lease", "browser", owner="B")
        self.assertEqual(busy.returncode, 75)
        self.assertEqual(self.heavy("release", owner="A").returncode, 0)
        self.assertEqual(self.heavy("lease", "browser", owner="B").returncode, 0)

    def test_browser_lease_expires(self):
        self.assertEqual(self.heavy("lease", "browser", "--ttl", "1", owner="A").returncode, 0)
        time.sleep(1.5)
        self.assertEqual(self.heavy("lease", "browser", owner="B").returncode, 0)


# A test run's output: 300 lines, one failing line early, a traceback at the end; the error text comes from
# ERR so a test can vary it, and the exit code from CODE.
NOISY = ("import os, sys\n"
         "for i in range(300):\n"
         "    print(f'progress {i} ok')\n"
         "    if i == 10:\n"
         "        print('FAIL src/early.test.ts')\n"
         "print('Traceback (most recent call last):', file=sys.stderr)\n"
         "print(os.environ.get('ERR', 'ValueError: bad total'), file=sys.stderr)\n"
         "sys.exit(int(os.environ.get('CODE', '1')))\n")


class HeavyTailTest(HeavyTestBase):
    def setUp(self):
        super().setUp()
        self.proj = Path(self.tmp.name) / "proj"
        (self.proj / "docs/project").mkdir(parents=True)
        (self.proj / "app.py").write_text("x = 1\n")
        (self.proj / "noisy.py").write_text(NOISY)

    def run_tail(self, tail="5", cwd=None, err=None, code="1"):
        env = {**self.env, "CODE": code}
        if err:
            env["ERR"] = err
        cmd = [PY, str(HEAVY), "run", "--owner", "A", "--tail", tail, "--", PY, "noisy.py"]
        return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd or self.proj)

    def failures(self):
        path = self.proj / ".evidence/failures.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.is_file() else []

    def test_tail_prints_the_exit_code_failing_lines_and_tail_and_keeps_the_whole_log(self):
        out = self.run_tail()
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("heavy.py: exit 1", out.stdout)
        self.assertIn("12: FAIL src/early.test.ts", out.stdout, "a failing line before the tail, with its line number")
        self.assertIn("progress 299 ok", out.stdout)
        self.assertIn("ValueError: bad total", out.stdout, "standard error is part of the tail")
        self.assertNotIn("progress 100 ok", out.stdout, "the middle stays in the log")
        self.assertLess(len(out.stdout.splitlines()), 15)
        logs = list((self.proj / ".evidence/logs").glob("*-noisy-py.log"))
        self.assertEqual(len(logs), 1, list((self.proj / ".evidence/logs").iterdir()))
        self.assertIn(str(logs[0]), out.stdout)
        whole = logs[0].read_text()
        self.assertIn("progress 100 ok", whole)
        self.assertIn("Traceback (most recent call last):", whole)
        self.assertEqual(len(whole.splitlines()), 303)

    def test_a_failing_line_the_tail_shows_is_not_repeated(self):
        out = self.run_tail(tail="400")
        self.assertEqual(out.stdout.count("FAIL src/early.test.ts"), 1)
        self.assertNotIn("Failing lines before the tail", out.stdout)

    def test_from_a_subfolder_the_log_goes_to_the_project_and_outside_one_to_the_working_folder(self):
        sub = self.proj / "src"
        sub.mkdir()
        (sub / "noisy.py").write_text(NOISY)
        self.run_tail(cwd=sub)
        self.assertEqual(len(list((self.proj / ".evidence/logs").glob("*.log"))), 1)
        loose = Path(self.tmp.name) / "loose"
        loose.mkdir()
        (loose / "noisy.py").write_text(NOISY)
        out = self.run_tail(cwd=loose)
        self.assertEqual(len(list((loose / ".evidence/logs").glob("*.log"))), 1, out.stdout)
        self.assertFalse((loose / ".evidence/failures.jsonl").exists(), "no project, no signature history")
        self.assertNotIn("survived", out.stdout)

    def test_without_tail_output_passes_through_and_nothing_is_written(self):
        out = self.heavy("run", "--", PY, "noisy.py", owner="A", cwd=self.proj)
        self.assertEqual(out.returncode, 1)
        self.assertIn("progress 100 ok", out.stdout)
        self.assertIn("ValueError: bad total", out.stderr, "standard error stays standard error")
        self.assertNotIn("heavy.py: exit", out.stdout)
        self.assertFalse((self.proj / ".evidence").exists())

    def test_a_log_folder_that_cannot_be_written_still_runs_the_job_and_says_so(self):
        (self.proj / ".evidence").write_text("a file where the folder would go\n")
        out = self.run_tail()
        self.assertEqual(out.returncode, 1)
        self.assertIn("cannot keep a log", out.stderr)
        self.assertIn("progress 100 ok", out.stdout, "the output passes through in full")
        self.assertNotIn("Traceback (most recent call last):\n  File", out.stderr)

    def test_a_bad_tail_value_is_bad_usage(self):
        for value in ("many", "-3"):
            out = self.heavy("run", "--tail", value, "--", "echo", "x", owner="A", cwd=self.proj)
            self.assertEqual(out.returncode, 2, value)
            self.assertNotIn("Traceback", out.stderr)

    def test_a_failing_run_records_its_signature_and_a_passing_one_does_not(self):
        self.run_tail()
        rows = self.failures()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        for key in ("time", "signature", "command", "error", "fingerprint"):
            self.assertIn(key, row)
        self.assertEqual(row["error"], "ValueError: bad total",
                         "Jest's bare FAIL <file> header and the Traceback header name no failure, so they are "
                         "passed over")
        self.assertTrue(row["fingerprint"].startswith("product:"))
        self.assertIn("noisy.py", row["command"])
        self.run_tail(code="0")
        self.assertEqual(len(self.failures()), 1)

    def test_numbers_paths_hex_ids_and_times_do_not_change_the_signature(self):
        (self.proj / "noisy.py").write_text("import os, sys\nprint(os.environ['ERR'])\nsys.exit(1)\n")
        self.run_tail(err="Error: /tmp/run-1/a.py:12 at 2026-10-16T10:00:01Z id 3f9a2c1d")
        self.run_tail(err="Error: /var/x/run-2/a.py:40 at 2026-10-17T11:22:33Z id 0b7e44aa")
        self.run_tail(err="Error: the cache is cold")
        sigs = [r["signature"] for r in self.failures()]
        self.assertEqual(sigs[0], sigs[1])
        self.assertNotEqual(sigs[0], sigs[2])

    def test_the_same_failure_on_three_fingerprints_says_it_survived_two_fixes(self):
        first = self.run_tail()
        self.assertNotIn("survived", first.stdout)
        again = self.run_tail()
        self.assertNotIn("survived", again.stdout, "a rerun without a change is not a fix")
        (self.proj / "app.py").write_text("x = 2\n")
        self.assertNotIn("survived", self.run_tail().stdout)
        self.run_tail(code="0")  # a pass in between clears nothing
        (self.proj / "app.py").write_text("x = 3\n")
        third = self.run_tail()
        sig = self.failures()[-1]["signature"][:8]
        self.assertIn(f"This failure has survived 2 fixes (signature {sig}): write down the premise both fixes "
                      "assumed and test it before another fix.", third.stdout)
        other = self.run_tail(err="KeyError: 'total'")
        self.assertNotIn("survived", other.stdout, "a different error is a different failure")
        (self.proj / "noisy.py").write_text(NOISY.replace("FAIL src/early.test.ts", "all fine"))
        self.assertNotIn("survived", self.run_tail(err="KeyError: 'total'").stdout, "a different failure starts over")

    def test_the_history_keeps_the_last_500_records(self):
        path = self.proj / ".evidence/failures.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("".join(json.dumps({"signature": f"old{i}", "fingerprint": "product:x"}) + "\n"
                                for i in range(600)))
        self.run_tail()
        rows = self.failures()
        self.assertEqual(len(rows), 500)
        self.assertEqual(rows[0]["signature"], "old101")
        self.assertIn("noisy.py", rows[-1]["command"])

    def run_script(self, text, name="out.py"):
        (self.proj / name).write_text(text)
        cmd = [PY, str(HEAVY), "run", "--owner", "A", "--tail", "2", "--", PY, name]
        return subprocess.run(cmd, capture_output=True, text=True, env=self.env, cwd=self.proj)

    def test_three_different_pytest_failures_are_three_signatures_not_a_failure_that_survived(self):
        session = ("print('=' * 29 + ' test session starts ' + '=' * 29)\n"
                   "print('=' * 35 + ' FAILURES ' + '=' * 35)\n"
                   "print('_' * 20 + ' {t} ' + '_' * 20)\n"
                   "print('E       AssertionError: assert 1 == 2')\n"
                   "print('tests/test_app.py:7: AssertionError')\n"
                   "print('=' * 27 + ' short test summary info ' + '=' * 27)\n"
                   "print('FAILED tests/test_app.py::{t} - AssertionError: assert 1 == 2')\n"
                   "print('=' * 25 + ' 1 failed, 2 passed in 0.0{n}s ' + '=' * 25)\n"
                   "raise SystemExit(1)\n")
        outs = []
        for n, test in enumerate(("test_parse_empty", "test_parse_unicode", "test_render_header")):
            (self.proj / "app.py").write_text(f"x = {n}\n")  # a new product state each time
            outs.append(self.run_script(session.format(t=test, n=n)))
        rows = self.failures()
        self.assertEqual([r["error"] for r in rows],
                         [f"FAILED tests/test_app.py::{t} - AssertionError: assert 1 == 2"
                          for t in ("test_parse_empty", "test_parse_unicode", "test_render_header")])
        self.assertEqual(len({r["signature"] for r in rows}), 3)
        self.assertNotIn("survived", outs[-1].stdout)

    def test_without_a_summary_the_pytest_e_line_beats_the_banner(self):
        self.run_script("print('=' * 10 + ' FAILURES ' + '=' * 10)\nprint('>       raise ValueError(x)')\n"
                        "print('E       KeyError: total')\nraise SystemExit(1)\n")
        self.assertEqual(self.failures()[-1]["error"], "E       KeyError: total")

    def test_jest_file_header_is_passed_over_for_the_failing_test_name(self):
        self.run_script("print('FAIL src/a.test.ts (5.2 s)')\nprint('  \\u25cf Console')\n"
                        "print('  \\u25cf Parser \\u203a parses an empty file')\n"
                        "print('    expect(received).toBe(expected)')\nraise SystemExit(1)\n")
        self.assertEqual(self.failures()[-1]["error"], "\u25cf Parser \u203a parses an empty file")

    def test_digits_in_a_file_or_test_name_are_kept_and_counts_and_durations_are_not(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("heavy_mod", HEAVY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        n = mod.normalize
        self.assertNotEqual(n("src/other30.ts(1,1): error TS6133"), n("src/other31.ts(1,1): error TS6133"))
        self.assertNotEqual(n("error TS2322: x"), n("error TS6133: x"))
        self.assertNotEqual(n("FAILED t.py::test_x[1-2] - E"), n("FAILED t.py::test_x[3-4] - E"))
        self.assertNotEqual(n("FAILED t.py::test_v2"), n("FAILED t.py::test_v3"))
        self.assertEqual(n("src/a.ts(12,7): 1 failed in 0.02s pid 4711 at 0x7ffe12"),
                         n("src/a.ts(40,3): 9 failed in 13.5s pid 99 at 0x10a3b2"))
        self.assertEqual(n("a.test.js:12:5 (3 ms)"), n("a.test.js:80:1 (250 ms)"))

    def test_compiler_and_linter_errors_and_cross_marks_are_failing_lines(self):
        lines = ["src/auth.ts(12,7): error TS2322: Type 'string' is not assignable to type 'number'.",
                 "src/auth.ts:12:7 - error TS2322: Type 'string' is not assignable to type 'number'.",
                 "  12:7  error  'token' is assigned a value but never used  no-unused-vars",
                 "error[E0425]: cannot find value `x` in this scope",
                 "    \u2715 adds two numbers (3 ms)",
                 "\u2716 parses (1.2ms)",
                 " \u00d7 renders 2ms"]
        script = "".join(f"print({line!r})\n" for line in lines) + "".join(
            f"print('filler {i}')\n" for i in range(5)) + "raise SystemExit(2)\n"
        out = self.run_script(script)
        for i, line in enumerate(lines, 1):
            self.assertIn(f"  {i}: {line}", out.stdout, "shown even though the tail does not reach it")
        self.assertEqual(self.failures()[-1]["error"], "\u2715 adds two numbers (3 ms)",
                         "the cross mark names the failing test, so it is the signature's line")


class HeavyFastProjectTest(HeavyTestBase):
    """A fast-workflow project (a folder holding .fast/plan.md) is a project for --tail's log and failure record."""

    def setUp(self):
        super().setUp()
        self.proj = Path(self.tmp.name) / "fastproj"
        (self.proj / ".fast").mkdir(parents=True)
        (self.proj / ".fast/plan.md").write_text("# tool\n\n## Goal\nA small tool.\n")
        (self.proj / "app.py").write_text("x = 1\n")
        (self.proj / "src").mkdir()
        (self.proj / "src/noisy.py").write_text(NOISY)

    def run_tail(self, cwd):
        return subprocess.run([PY, str(HEAVY), "run", "--owner", "A", "--tail", "5", "--", PY, "noisy.py"],
                              capture_output=True, text=True, env=self.env, cwd=cwd)

    def failures(self, proj):
        path = proj / ".evidence/failures.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.is_file() else []

    def survives_two_fixes(self, cwd):
        """Fail on three product states (the first failure and two fixes); the third run's output."""
        outs = []
        for n in (1, 2, 3):
            (self.proj / "app.py").write_text(f"x = {n}\n")
            outs.append(self.run_tail(cwd))
        return outs

    def test_outside_git_the_log_and_the_survived_notice_go_to_the_fast_project(self):
        outs = self.survives_two_fixes(self.proj / "src")
        self.assertEqual(len(list((self.proj / ".evidence/logs").glob("*-noisy-py*.log"))), 3)
        self.assertFalse((self.proj / "src/.evidence").exists(), "the subfolder is not the project")
        self.assertEqual(len(self.failures(self.proj)), 3)
        self.assertNotIn("survived", outs[1].stdout)
        self.assertIn("This failure has survived 2 fixes", outs[2].stdout)

    def test_in_git_with_fast_excluded_the_project_is_the_same(self):
        subprocess.run(["git", "init", "-q", str(self.proj)], check=True)
        (self.proj / ".git/info/exclude").write_text(".fast/\n.evidence/\n")
        outs = self.survives_two_fixes(self.proj / "src")
        self.assertIn("This failure has survived 2 fixes", outs[2].stdout)
        prints = {r["fingerprint"] for r in self.failures(self.proj)}
        self.assertEqual(len(prints), 3, "each fix is a new product state")
        (self.proj / ".fast/plan.md").write_text("# tool\n\n## Goal\nA small tool, edited.\n")
        self.run_tail(self.proj / "src")
        self.assertEqual(self.failures(self.proj)[-1]["fingerprint"], self.failures(self.proj)[-2]["fingerprint"],
                         "editing the plan is not a product change")

    def test_a_full_pipeline_project_above_wins_and_fast_without_a_plan_is_no_project(self):
        outer = Path(self.tmp.name)
        (outer / "docs/project").mkdir(parents=True)
        self.run_tail(self.proj / "src")
        self.assertTrue(list((outer / ".evidence/logs").glob("*.log")), "docs/project/ is looked for first")
        self.assertFalse((self.proj / ".evidence").exists())
        lone = outer / "elsewhere"
        (lone / ".fast").mkdir(parents=True)
        (lone / "noisy.py").write_text(NOISY)
        (outer / "docs/project").rmdir()
        out = self.run_tail(lone)
        self.assertEqual(len(list((lone / ".evidence/logs").glob("*.log"))), 1, out.stdout)
        self.assertFalse((lone / ".evidence/failures.jsonl").exists(), ".fast/ without plan.md is no project")


def guard(payload, env=None, cwd=None):
    payload = dict(payload)
    if not payload.get("cwd"):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".coding-pipeline.json").write_text('{"version":1,"managed":true}')
            return guard({**payload, "cwd": d}, env=env, cwd=cwd)
    (Path(payload["cwd"]) / ".coding-pipeline.json").write_text('{"version":1,"managed":true}')
    out = subprocess.run([PY, str(GUARD)], input=json.dumps(payload), capture_output=True, text=True,
                         env={**os.environ, **(env or {})}, cwd=cwd)
    if not out.stdout.strip():
        return "allow", ""
    d = json.loads(out.stdout)["hookSpecificOutput"]
    return d["permissionDecision"], d["permissionDecisionReason"]


def bash(command, **kw):
    return guard({"tool_name": "Bash", "tool_input": {"command": command}, **kw.pop("payload", {})}, **kw)


class HeavyGuardTest(unittest.TestCase):
    def test_text_passed_as_data_is_not_a_command(self):
        for cmd in ("python3 - <<'EOF'\nprint('x')\ngate.sh part names its status\nnpm test is heavy\nEOF",
                    'git commit -m "fix the parser\n\nnpm test now passes; gate.sh | clean"',
                    "echo 'a; npm test && pytest'",
                    'cat <<EOF > notes.md\npytest -q\nEOF'):
            self.assertEqual(bash(cmd)[0], "allow", cmd)

    def test_heavy_commands_inside_shell_c_are_still_seen(self):
        self.assertEqual(bash('bash -c "cd app && npm test"')[0], "deny")
        self.assertEqual(bash("python3 - <<'EOF'\nprint(1)\nEOF\nnpm test")[0], "deny",
                         "a command after the heredoc still counts")

    def test_a_script_a_shell_reads_is_commands(self):
        for cmd in ("bash <<'EOF'\nnpm test\nEOF", "sh -s <<EOF\ncd app\npytest -q\nEOF",
                    "cat <<'EOF' | bash\nnpm test\nEOF", "bash -lc 'npm test'", 'bash -l -c "pytest -q"',
                    "/bin/sh -c 'cargo test'"):
            self.assertEqual(bash(cmd)[0], "deny", cmd)

    def test_comments_and_quoted_shell_mentions_are_not_commands(self):
        for cmd in ("# npm test is heavy\necho hi", "echo hi # then npm test",
                    "echo \"run bash -c 'npm test' later\"", "git commit -m \"note: sh -c 'pytest' in CI\"",
                    "python3 - <<'EOF'\nrun(\"bash -c 'npm test'\")\nEOF"):
            self.assertEqual(bash(cmd)[0], "allow", cmd)

    def test_bounded_commands_denied_with_run_suggestion(self):
        for cmd in ("pnpm test", "npm run build", "npx tsc --noEmit", "pytest -q", "cargo test",
                    "xcodebuild -scheme App build", "cd app && pnpm test", "CI=1 npm test",
                    "python3 -m unittest discover", "bash ~/.claude/skills/_shared/gate.sh ."):
            decision, reason = bash(cmd)
            self.assertEqual(decision, "deny", cmd)
            self.assertIn("heavy.py run --owner ", reason, cmd)

    def test_servers_denied_with_serve_suggestion(self):
        for cmd in ("pnpm dev", "npm start", "npx next dev", "python3 -m http.server 8000", "uvicorn app:api"):
            decision, reason = bash(cmd)
            self.assertEqual(decision, "deny", cmd)
            self.assertIn("heavy.py serve --owner ", reason, cmd)

    def test_wrapped_and_light_commands_allowed(self):
        for cmd in (f"python3 {HEAVY} run -- pnpm test", f"python3 {HEAVY} serve -- pnpm dev", "ls -la",
                    "git status", "grep -rn test src", "cat package.json", "echo build", "npm view react version"):
            self.assertEqual(bash(cmd)[0], "allow", cmd)

    def test_compound_command_gets_the_heavy_part_only(self):
        _, reason = bash("cd app && pnpm test", payload={"session_id": "S9"})
        self.assertIn("run --owner S9 --tail 60 -- pnpm test", reason)
        self.assertIn("own call", reason)
        self.assertNotIn("bash -c", reason)

    def test_a_bounded_suggestion_bounds_its_output_and_a_server_suggestion_does_not(self):
        _, reason = bash("pytest -q", payload={"session_id": "S9"})
        self.assertIn("heavy.py run --owner S9 --tail 60 -- pytest -q", reason, "the first try is already bounded")
        suggested = reason.split("Run instead: ", 1)[1].split("  (", 1)[0]
        self.assertEqual(bash(suggested)[0], "allow", "the suggested command passes the guard as given")
        _, reason = bash("pnpm dev", payload={"session_id": "S9"})
        self.assertIn("heavy.py serve --owner S9 -- pnpm dev", reason)
        self.assertNotIn("--tail", reason)

    def test_mentioning_the_wrapper_is_not_wrapping(self):
        self.assertEqual(bash("echo heavy.py; pnpm test")[0], "deny")
        self.assertEqual(bash(f"CI=1 python3 {HEAVY} run --owner S -- pnpm test")[0], "allow")

    def test_heavy_commands_from_gate_settings(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "docs/project").mkdir(parents=True)
            (Path(d) / "docs/project/gate.md").write_text("Heavy commands: ./scripts/e2e.sh\n")
            self.assertEqual(bash("./scripts/e2e.sh --all", payload={"cwd": d})[0], "deny")

    def test_playwright_cli_takes_and_releases_the_browser_lease(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"HEAVY_LOCK_DIR": d}
            self.assertEqual(bash("playwright-cli open http://localhost:3000", env=env, payload={"session_id": "S1"})[0], "allow")
            self.assertEqual(bash("playwright-cli snapshot", env=env, payload={"session_id": "S2"})[0], "deny")
            self.assertEqual(bash("playwright-cli close", env=env, payload={"session_id": "S1"})[0], "allow")
            self.assertEqual(bash("playwright-cli open http://localhost:3000", env=env, payload={"session_id": "S2"})[0], "allow")

    def test_named_playwright_cli_session_close_releases_the_lease(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"HEAVY_LOCK_DIR": d}
            self.assertEqual(bash("playwright-cli -s=app open http://localhost:3000", env=env, payload={"session_id": "S1"})[0], "allow")
            self.assertEqual(bash("playwright-cli -s=app close", env=env, payload={"session_id": "S1"})[0], "allow")
            self.assertEqual(bash("playwright-cli --json open http://localhost:3000", env=env, payload={"session_id": "S2"})[0], "allow",
                             "the lease was released by the named-session close")
            self.assertEqual(bash("playwright-cli -s app close", env=env, payload={"session_id": "S2"})[0], "allow")
            self.assertEqual(bash("playwright-cli open http://localhost:3000", env=env, payload={"session_id": "S1"})[0], "allow")

    def test_project_extra_heavy_command(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "AGENTS.md").write_text("# map\nHeavy commands: ./scripts/e2e.sh, node scripts/gate.ts\n")
            self.assertEqual(bash("node scripts/gate.ts", payload={"cwd": d})[0], "deny")
            self.assertEqual(bash("node scripts/other.ts", payload={"cwd": d})[0], "allow")

    def test_browser_tool_lease(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"HEAVY_LOCK_DIR": d}
            first = guard({"tool_name": "mcp__plugin_playwright_playwright__browser_navigate", "session_id": "S1"}, env=env)
            self.assertEqual(first[0], "allow")
            again = guard({"tool_name": "mcp__plugin_playwright_playwright__browser_click", "session_id": "S1"}, env=env)
            self.assertEqual(again[0], "allow", "the owner refreshes its own lease")
            other = guard({"tool_name": "mcp__claude-in-chrome__navigate", "session_id": "S2"}, env=env)
            self.assertEqual(other[0], "deny")
            self.assertIn("another session", other[1])
            lease = json.loads(next((Path(d) / "leases").glob("S1-browser.json")).read_text())
            self.assertLessEqual(lease["expires"] - time.time(), 121, "a browser lease lasts two minutes, refreshed by use")
            closed = guard({"tool_name": "mcp__plugin_playwright_playwright__browser_close", "session_id": "S1"}, env=env)
            self.assertEqual(closed[0], "allow")
            self.assertEqual(guard({"tool_name": "mcp__claude-in-chrome__navigate", "session_id": "S2"}, env=env)[0], "allow",
                             "closing the browser releases the lease")

    def test_an_unwritable_lock_folder_is_a_named_block(self):
        with tempfile.TemporaryDirectory() as d:
            locked = Path(d) / "lock"
            locked.mkdir()
            locked.chmod(0o500)
            try:
                out = subprocess.run([PY, str(HEAVY), "run", "--owner", "A", "--", "echo", "RAN"], capture_output=True,
                                     text=True, env={**os.environ, "HEAVY_LOCK_DIR": str(locked)})
            finally:
                locked.chmod(0o700)
            self.assertEqual(out.returncode, 77, out.stderr)
            self.assertIn("BLOCKED: cannot open the heavy lock", out.stderr)
            self.assertNotIn("RAN", out.stdout)
            self.assertNotIn("Traceback", out.stderr)

    def test_default_lock_is_under_tmp(self):
        env = {k: v for k, v in os.environ.items() if k != "HEAVY_LOCK_DIR"}
        out = subprocess.run([PY, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import heavy; print(heavy.default_lock_dir())",
                              str(HEAVY.parent)], capture_output=True, text=True, env=env)
        self.assertEqual(out.stdout.strip(), f"/tmp/heavy-lock-{os.getuid()}")

    def test_disable_switch(self):
        self.assertEqual(bash("pnpm test", env={"HEAVY_GUARD_DISABLE": "1"})[0], "allow")


if __name__ == "__main__":
    unittest.main()
