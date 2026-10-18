"""Tests for typecheck-once.py using a fake npx on PATH."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks/typecheck-once.py"

FAKE_NPX = """#!/bin/bash
echo "called" >> "$FAKE_LOG"
if [ "$FAKE_MODE" = broken ]; then
  echo "npm ERR! could not determine executable to run"
  exit 1
fi
echo "src/a.ts(1,7): error TS2322: Type 'string' is not assignable to type 'number'."
echo "src/untouched.ts(2,1): error TS1005: ';' expected."
exit 2
"""


class TypecheckOnceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.proj = d / "proj"
        (self.proj / "src").mkdir(parents=True)
        (self.proj / ".coding-pipeline.json").write_text('{"version":1,"managed":true}')
        (self.proj / "tsconfig.json").write_text("{}")
        (self.proj / "src/a.ts").write_text("const x: number = 1;\n")
        (self.proj / "src/untouched.ts").write_text("export {};\n")
        subprocess.run(["git", "init", "-q", str(self.proj)], check=True)
        subprocess.run(["git", "-C", str(self.proj), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.proj), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "-m", "init"], check=True)
        bindir = d / "bin"
        bindir.mkdir()
        npx = bindir / "npx"
        npx.write_text(FAKE_NPX)
        npx.chmod(npx.stat().st_mode | stat.S_IEXEC)
        self.log = d / "npx.log"
        self.env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_LOG": str(self.log),
                    "HEAVY_LOCK_DIR": str(d / "lock")}
        self.session = "tc-" + uuid.uuid4().hex

    def tearDown(self):
        self.tmp.cleanup()
        (Path(tempfile.gettempdir()) / f"typecheck-once-{self.session}").unlink(missing_ok=True)

    def begin(self):
        """The session's first stop, on a clean tree: it records the time and says nothing."""
        code, out = self.stop()
        self.assertEqual((code, out.strip()), (0, ""))

    def stop(self, cwd=None, env=None, **extra):
        payload = {"cwd": str(cwd or self.proj), "session_id": self.session, "hook_event_name": "Stop", **extra}
        out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                             text=True, env={**self.env, **(env or {})})
        return out.returncode, out.stdout

    def calls(self):
        return self.log.read_text().count("called") if self.log.exists() else 0

    def test_no_change_no_run(self):
        code, out = self.stop()
        self.assertEqual((code, out.strip(), self.calls()), (0, "", 0))

    def test_errors_in_changed_files_go_to_the_model_and_the_rest_to_the_owner(self):
        self.begin()
        time.sleep(1.1)
        (self.proj / "src/a.ts").write_text("const x: number = 'a';\n")
        code, out = self.stop()
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "Stop")
        context = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("src/a.ts(1,7): error TS2322", context)
        self.assertNotIn("untouched.ts", context, "errors elsewhere are never sent to the model")
        self.assertNotIn("decision", result, "the hook never blocks the stop")
        note = result["systemMessage"]
        self.assertIn("1 error(s) in files changed this turn were sent to the model", note)
        self.assertIn("1 error(s) in files not changed this turn", note)
        self.assertIn("src/untouched.ts", note)
        self.assertEqual(self.calls(), 1)
        code, out = self.stop()
        self.assertEqual(self.calls(), 1, "no new change since the last run: no second tsc")

    def test_a_turn_that_already_continued_for_a_stop_hook_only_tells_the_owner(self):
        self.begin()
        time.sleep(1.1)
        (self.proj / "src/a.ts").write_text("const x: number = 'a';\n")
        code, out = self.stop(stop_hook_active=True)
        result = json.loads(out)
        self.assertNotIn("hookSpecificOutput", result, "nothing goes to the model, so it can never loop")
        self.assertIn("src/a.ts(1,7): error TS2322", result["systemMessage"])
        self.assertIn("not sent to the model again", result["systemMessage"])

    def test_errors_only_in_other_files_are_a_summary_for_the_owner(self):
        self.begin()
        time.sleep(1.1)
        (self.proj / "src/b.ts").write_text("export const y = 2;\n")
        code, out = self.stop()
        result = json.loads(out)
        self.assertNotIn("hookSpecificOutput", result)
        self.assertIn("2 error(s) in files not changed this turn", result["systemMessage"])

    def test_not_run_stays_a_message_to_the_owner(self):
        time.sleep(1.1)
        (self.proj / "src/a.ts").write_text("const x: number = 'c';\n")
        code, out = self.stop(env={"FAKE_MODE": "broken"})
        result = json.loads(out)
        self.assertEqual(list(result), ["systemMessage"])
        self.assertIn("Typecheck NOT_RUN: tsc could not run", result["systemMessage"])

    def test_a_subfolder_session_still_typechecks(self):
        self.begin()
        time.sleep(1.1)
        (self.proj / "src/a.ts").write_text("const x: number = 'b';\n")
        code, out = self.stop(cwd=self.proj / "src")
        self.assertIn("src/a.ts", json.loads(out)["hookSpecificOutput"]["additionalContext"])

    def test_outside_git_uses_file_times(self):
        import shutil
        shutil.rmtree(self.proj / ".git")
        code, out = self.stop()
        self.assertIn("src/a.ts", json.loads(out)["systemMessage"], "first run outside git sees every file")
        self.assertEqual(self.calls(), 1)
        time.sleep(1.1)
        (self.proj / "src/a.ts").write_text("const x: number = 'd';\n")
        code, out = self.stop()
        self.assertIn("src/a.ts", json.loads(out)["hookSpecificOutput"]["additionalContext"],
                      "a file changed after the first stop is this turn's work")
        self.assertNotIn("untouched.ts", json.loads(out)["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.calls(), 2)

    def test_the_first_stop_reports_errors_already_there_to_the_owner_only(self):
        (self.proj / "src/a.ts").write_text("const x: number = 'old';\n")  # left uncommitted before the session
        old = time.time() - 86400
        os.utime(self.proj / "src/a.ts", (old, old))
        code, out = self.stop()
        result = json.loads(out)
        self.assertNotIn("hookSpecificOutput", result,
                         "nothing is known to be this turn's, so nothing goes to the model")
        self.assertIn("first stop", result["systemMessage"])
        self.assertIn("src/a.ts(1,7): error TS2322", result["systemMessage"])
        self.assertTrue((Path(tempfile.gettempdir()) / f"typecheck-once-{self.session}").exists(), "stamp written")
        code, out = self.stop()
        self.assertEqual((out.strip(), self.calls()), ("", 1), "the next stop measures from the first one")

    def leftovers(self):
        hook = ROOT / "hooks/verify-pipeline-completion.sh"
        out = subprocess.run(["bash", str(hook)], input=json.dumps({"cwd": str(self.proj)}), capture_output=True,
                             text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_debug_leftover_hook(self):
        (self.proj / "src/app.ts").write_text("console.log('here')\n")
        self.assertIn("console.log/debugger found in src/app.ts", self.leftovers()["systemMessage"])
        (self.proj / "src/app.ts").write_text("export const x = 1\n")
        self.assertEqual(self.leftovers(), {"suppressOutput": True})

    def test_debug_leftovers_count_only_lines_added_in_the_working_tree(self):
        (self.proj / "src/old.ts").write_text("export function f() {\n  console.log('committed long ago')\n}\n")
        subprocess.run(["git", "-C", str(self.proj), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.proj), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "-m", "old"], check=True)
        (self.proj / "src/old.ts").write_text("export function f() {\n  console.log('committed long ago')\n}\n"
                                              "export const g = 2\n")
        self.assertEqual(self.leftovers(), {"suppressOutput": True}, "an old line in a modified file is not this work")
        (self.proj / "src/old.ts").write_text("export function f() {\n  console.log('committed long ago')\n}\n"
                                              "export const g = 2\ndebugger\n")
        msg = self.leftovers()["systemMessage"]
        self.assertIn("console.log/debugger found in src/old.ts", msg)
        self.assertIn("5:debugger", msg, "the added line, with its line number")
        self.assertNotIn("committed long ago", msg)
        self.assertNotIn("hookSpecificOutput", self.leftovers(), "it informs the owner; it never makes the model go on")
        subprocess.run(["git", "-C", str(self.proj), "add", "src/old.ts"], check=True)
        self.assertIn("5:debugger", self.leftovers()["systemMessage"], "a staged line is still this work")
        (self.proj / "src/new.spec.ts").write_text("console.log('a test may log')\n")
        self.assertNotIn("new.spec.ts", self.leftovers()["systemMessage"])

    def test_debug_leftovers_are_found_whatever_the_diff_prefix_config(self):
        (self.proj / "src/a.ts").write_text("const x: number = 1;\nconsole.log('debug')\n")
        for key in ("diff.mnemonicPrefix", "diff.noprefix"):
            subprocess.run(["git", "-C", str(self.proj), "config", key, "true"], check=True)
            self.assertIn("2:console.log('debug')", self.leftovers().get("systemMessage", ""), key)
            subprocess.run(["git", "-C", str(self.proj), "config", "--unset", key], check=True)

    def test_not_a_ts_project_no_op(self):
        (self.proj / "tsconfig.json").unlink()
        (self.proj / "src/a.ts").write_text("changed\n")
        self.assertEqual(self.stop()[1].strip(), "")
        self.assertEqual(self.calls(), 0)


if __name__ == "__main__":
    unittest.main()
