"""Tests for the PreCompact snapshot and the post-compaction reload gate."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "hooks/snapshot-state.py"
GATE = ROOT / "hooks/reload-gate.py"
STATE = "# State\n## Milestone\nM2 · phase: building\n## Open\n- [ ] add export\n## Blockers\nnone\n## Next step\nadd export\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self.tmp.name) / "proj"
        self.docs = self.proj / "docs/project"
        self.docs.mkdir(parents=True)
        self.env = {**os.environ, "RELOAD_STATE_DIR": str(Path(self.tmp.name) / "reload")}

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, script, mode=None, **payload):
        payload = {"cwd": str(self.proj), "session_id": "s1", **payload}
        args = [sys.executable, str(script)] + ([mode] if mode else [])
        return subprocess.run(args, input=json.dumps(payload), capture_output=True, text=True, env=self.env)

    def decision(self, out):
        if not out.stdout.strip():
            return "allow"
        return json.loads(out.stdout)["hookSpecificOutput"].get("permissionDecision", "allow")


class SnapshotTest(Base):
    def test_snapshot_written_with_state_excerpt(self):
        (self.docs / "state.md").write_text(STATE)
        out = self.call(SNAP, trigger="auto")
        self.assertEqual(out.returncode, 0, out.stderr)
        snaps = list((self.proj / ".evidence/compact").glob("*.md"))
        self.assertEqual(len(snaps), 1)
        body = snaps[0].read_text()
        for expected in ("M2 · phase: building", "- [ ] add export", "state.md sha256:"):
            self.assertIn(expected, body)

    def test_snapshot_from_a_subfolder(self):
        (self.docs / "state.md").write_text(STATE)
        (self.proj / "src/deep").mkdir(parents=True)
        out = self.call(SNAP, cwd=str(self.proj / "src/deep"), trigger="auto")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len(list((self.proj / ".evidence/compact").glob("*.md"))), 1, "a cd into a subfolder still snapshots")

    def test_snapshot_no_state_is_no_op(self):
        self.assertEqual(self.call(SNAP).returncode, 0)
        self.assertFalse((self.proj / ".evidence").exists())


class ReloadGateTest(Base):
    def setUp(self):
        super().setUp()
        for n in ("state.md", "intent.md", "milestones.md"):
            (self.docs / n).write_text(STATE)
        (self.proj / "app.py").write_text("x = 1\n")

    def test_arm_injects_directive(self):
        self.call(SNAP)
        out = self.call(GATE, "arm", source="compact")
        ctx = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("docs/project/state.md, then docs/project/intent.md", ctx)
        self.assertIn(".evidence/compact/", ctx)

    def test_writes_blocked_until_all_required_read(self):
        self.call(GATE, "arm")
        write = {"tool_input": {"file_path": str(self.proj / "app.py")}}
        self.assertEqual(self.decision(self.call(GATE, "guard", **write)), "deny")
        for n in ("state.md", "intent.md"):
            self.call(GATE, "track", tool_input={"file_path": str(self.docs / n)})
        self.assertEqual(self.decision(self.call(GATE, "guard", **write)), "deny", "milestones.md still unread")
        self.call(GATE, "track", tool_input={"file_path": str(self.docs / "milestones.md")})
        self.assertEqual(self.decision(self.call(GATE, "guard", **write)), "allow")

    def test_writes_outside_project_not_blocked(self):
        self.call(GATE, "arm")
        out = self.call(GATE, "guard", tool_input={"file_path": str(Path(self.tmp.name) / "elsewhere.txt")})
        self.assertEqual(self.decision(out), "allow")

    def test_other_session_not_blocked(self):
        self.call(GATE, "arm")
        out = self.call(GATE, "guard", session_id="s2", tool_input={"file_path": str(self.proj / "app.py")})
        self.assertEqual(self.decision(out), "allow")

    def test_not_armed_means_no_block(self):
        out = self.call(GATE, "guard", tool_input={"file_path": str(self.proj / "app.py")})
        self.assertEqual(self.decision(out), "allow")

    def test_shell_writes_blocked_and_shell_reads_allowed_while_armed(self):
        self.call(GATE, "arm")
        for cmd in ("echo x > app.py", "sed -i '' 's/1/2/' app.py", "python3 fix.py", "cat a | tee b",
                    "git checkout -- app.py", "rm app.py", "sort -o app.py app.py", "uniq notes.txt app.py",
                    "tree -o app.py"):
            self.assertEqual(self.decision(self.call(GATE, "guard", tool_name="Bash", tool_input={"command": cmd})),
                             "deny", cmd)
        for cmd in ("git status --short", "cat docs/project/state.md", "grep -n Open docs/project/state.md | head -3",
                    "sed -n 1,20p app.py", "ls -la"):
            self.assertEqual(self.decision(self.call(GATE, "guard", tool_name="Bash", tool_input={"command": cmd})),
                             "allow", cmd)

    def test_shell_reads_count_as_rereading(self):
        self.call(GATE, "arm")
        for n in ("state.md", "intent.md", "milestones.md"):
            self.call(GATE, "track", tool_name="Bash", tool_input={"command": f"cat docs/project/{n}"})
        write = {"tool_input": {"file_path": str(self.proj / "app.py")}}
        self.assertEqual(self.decision(self.call(GATE, "guard", **write)), "allow")

    def test_naming_a_file_without_printing_it_is_not_reading_it(self):
        self.call(GATE, "arm")
        for n in ("state.md", "intent.md", "milestones.md"):
            for cmd in (f"ls docs/project/{n}", f"wc -l docs/project/{n}", f"grep -c Open docs/project/{n}"):
                self.call(GATE, "track", tool_name="Bash", tool_input={"command": cmd})
        write = {"tool_input": {"file_path": str(self.proj / "app.py")}}
        self.assertEqual(self.decision(self.call(GATE, "guard", **write)), "deny")
        for n in ("state.md", "intent.md", "milestones.md"):
            self.call(GATE, "track", tool_name="Bash", tool_input={"command": f"ls docs/project && sed -n 1,400p docs/project/{n}"})
        self.assertEqual(self.decision(self.call(GATE, "guard", **write)), "allow")

    def test_a_subfolder_cwd_does_not_disarm(self):
        self.call(GATE, "arm")
        sub = self.proj / "src"
        sub.mkdir()
        out = self.call(GATE, "guard", cwd=str(sub), tool_input={"file_path": str(self.proj / "app.py")})
        self.assertEqual(self.decision(out), "deny")

    def test_codex_apply_patch_is_guarded(self):
        self.call(GATE, "arm")
        patch = "*** Begin Patch\n*** Update File: app.py\n@@\n-x = 1\n+x = 2\n*** End Patch\n"
        self.assertEqual(self.decision(self.call(GATE, "guard", tool_name="apply_patch", tool_input={"patch": patch})), "deny")
        outside = "*** Begin Patch\n*** Add File: /tmp/elsewhere.txt\n+hi\n*** End Patch\n"
        self.assertEqual(self.decision(self.call(GATE, "guard", tool_name="apply_patch", tool_input={"patch": outside})), "allow")
        # Codex's real payload: the patch arrives in tool_input.command
        self.assertEqual(self.decision(self.call(GATE, "guard", tool_name="apply_patch", tool_input={"command": patch})), "deny")
        self.assertEqual(self.decision(self.call(GATE, "guard", tool_name="apply_patch", tool_input={"command": "garbled"})),
                         "deny", "a patch with no readable target fails closed while armed")

    def test_project_without_state_is_silent(self):
        (self.docs / "state.md").unlink()
        self.assertEqual(self.call(GATE, "arm").stdout.strip(), "")

    def test_bad_mode(self):
        self.assertEqual(subprocess.run([sys.executable, str(GATE), "nope"], input="{}", text=True,
                                        capture_output=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
