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

    def stop(self):
        payload = {"cwd": str(self.proj), "session_id": self.session, "hook_event_name": "Stop"}
        out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                             text=True, env=self.env)
        return out.returncode, out.stdout

    def calls(self):
        return self.log.read_text().count("called") if self.log.exists() else 0

    def test_no_change_no_run(self):
        code, out = self.stop()
        self.assertEqual((code, out.strip(), self.calls()), (0, "", 0))

    def test_change_runs_once_and_reports_only_changed_files(self):
        time.sleep(1.1)
        (self.proj / "src/a.ts").write_text("const x: number = 'a';\n")
        code, out = self.stop()
        self.assertEqual(code, 0)
        msg = json.loads(out)["systemMessage"]
        self.assertIn("src/a.ts", msg)
        self.assertNotIn("untouched.ts", msg)
        self.assertEqual(self.calls(), 1)
        code, out = self.stop()
        self.assertEqual(self.calls(), 1, "no new change since the last run: no second tsc")

    def test_a_subfolder_session_still_typechecks(self):
        time.sleep(1.1)
        (self.proj / "src/a.ts").write_text("const x: number = 'b';\n")
        payload = {"cwd": str(self.proj / "src"), "session_id": self.session, "hook_event_name": "Stop"}
        out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                             text=True, env=self.env)
        self.assertIn("src/a.ts", json.loads(out.stdout)["systemMessage"])

    def test_outside_git_uses_file_times(self):
        import shutil
        shutil.rmtree(self.proj / ".git")
        code, out = self.stop()
        self.assertIn("src/a.ts", json.loads(out)["systemMessage"], "first run outside git sees the changed file")
        self.assertEqual(self.calls(), 1)

    def test_debug_leftover_hook(self):
        hook = ROOT / "hooks/verify-pipeline-completion.sh"
        (self.proj / "src/app.ts").write_text("console.log('here')\n")
        out = subprocess.run(["bash", str(hook)], input=json.dumps({"cwd": str(self.proj)}), capture_output=True, text=True)
        self.assertIn("console.log/debugger found in src/app.ts", json.loads(out.stdout)["systemMessage"])
        (self.proj / "src/app.ts").write_text("export const x = 1\n")
        out = subprocess.run(["bash", str(hook)], input=json.dumps({"cwd": str(self.proj)}), capture_output=True, text=True)
        self.assertEqual(json.loads(out.stdout), {"suppressOutput": True})

    def test_not_a_ts_project_no_op(self):
        (self.proj / "tsconfig.json").unlink()
        (self.proj / "src/a.ts").write_text("changed\n")
        self.assertEqual(self.stop()[1].strip(), "")
        self.assertEqual(self.calls(), 0)


if __name__ == "__main__":
    unittest.main()
