"""Tests for install.py against a throwaway home folder."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.py"


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        claude = self.home / ".claude"
        (claude / "skills/qa").mkdir(parents=True)
        (claude / "skills/qa/SKILL.md").write_text("old qa\n")
        (claude / "skills/plan/references").mkdir(parents=True)
        (claude / "skills/plan/references/interrogation.md").write_text("old reference\n")
        (claude / "skills/plan/brain.md").write_text("the owner's notes\n")
        (claude / "skills/plan/friction.log").write_text("log\n")
        (claude / "skills/_shared/scripts").mkdir(parents=True)
        (claude / "skills/_shared/scripts/someone_elses.py").write_text("keep me\n")
        (claude / "agents").mkdir(parents=True)
        (claude / "agents/task-implementer.md").write_text("old agent\n")
        hooks = {"hooks": {"PreToolUse": [{"hooks": [{"command": c}]} for c in (
            "python3 heavy-guard.py", "python3 reload-gate.py guard", "python3 continuity.py claim")],
            "PostToolUse": [{"hooks": [{"command": "python3 reload-gate.py track"}]}],
            "SessionStart": [{"hooks": [{"command": "python3 reload-gate.py arm"}, {"command": "python3 continuity.py session-start"}]}],
            "PreCompact": [{"hooks": [{"command": "python3 snapshot-state.py"}]}],
            "Stop": [{"hooks": [{"command": "python3 typecheck-once.py"}, {"command": "python3 continuity.py stop"},
                              {"command": "~/.claude/hooks/verify-pipeline-completion.sh"}]}]}}
        (claude / "settings.json").write_text(json.dumps(hooks))

    def tearDown(self):
        self.tmp.cleanup()

    def run_i(self, cmd):
        return subprocess.run([sys.executable, str(INSTALL), cmd, "--home", str(self.home)], capture_output=True, text=True)

    def test_check_fails_before_install(self):
        out = self.run_i("check")
        self.assertEqual(out.returncode, 1)
        self.assertIn("retired skill still loads", out.stdout)
        self.assertIn("retired agent still loads", out.stdout)

    def test_apply_installs_archives_and_keeps_the_owners_files(self):
        out = self.run_i("apply")
        claude = self.home / ".claude"
        self.assertTrue((claude / "skills/gate/SKILL.md").exists())
        self.assertTrue((claude / "agents/gate-judge.md").exists())
        self.assertTrue((claude / "skills/_shared/scripts/run_isolated.py").exists())
        self.assertFalse((claude / "skills/qa").exists())
        self.assertTrue(any((claude / "_archived-skills").glob("qa-*")))
        self.assertFalse((claude / "agents/task-implementer.md").exists())
        self.assertFalse((claude / "skills/plan/references/interrogation.md").exists(), "a stale reference is removed")
        self.assertTrue((claude / "skills/plan/friction.log").exists(), "the owner's log is kept")
        self.assertTrue((claude / "skills/_shared/scripts/someone_elses.py").exists(), "other shared files untouched")
        self.assertTrue((claude / ".pipeline-install.json").exists())
        self.assertNotIn("FAIL   install     differs", out.stdout)
        self.assertNotIn("missing:", out.stdout)

    def test_check_catches_a_modified_install(self):
        self.run_i("apply")
        (self.home / ".claude/skills/gate/SKILL.md").write_text("edited by hand\n")
        out = self.run_i("check")
        self.assertIn("differs from the repository", out.stdout)

    def test_check_catches_shadows_and_codex_leftovers(self):
        self.run_i("apply")
        shadow = self.home / "Projects/lab/app/.claude/skills/dev"
        shadow.mkdir(parents=True)
        (self.home / ".agents/skills/qa").mkdir(parents=True)
        out = self.run_i("check")
        self.assertIn("project-level skill shadows ours", out.stdout)
        self.assertIn("Codex still offers a retired skill", out.stdout)

    def test_codex_conversion_must_match_the_installed_files(self):
        self.run_i("apply")
        package = self.home / "pkg/skills"
        for name in ("plan",):
            (package / name).mkdir(parents=True)
        (self.home / ".agents/skills").mkdir(parents=True)
        (self.home / ".agents/skills/plan").symlink_to(package / "plan")
        installed = self.home / ".claude/skills/plan/SKILL.md"
        import hashlib
        good = hashlib.sha256(installed.read_bytes()).hexdigest()
        (self.home / "pkg/source-manifest.sha256").write_text(f"{'0' * 64}  skills/plan/SKILL.md\n")
        out = self.run_i("check")
        self.assertIn("converted from older versions of 1 file(s) (skills/plan/SKILL.md)", out.stdout)
        self.assertIn("does not carry", out.stdout)
        self.assertIn("skills/", out.stdout.split("does not carry", 1)[1])
        self.assertNotIn("hooks/heavy-guard.py", out.stdout.split("does not carry", 1)[1], "hooks run from ~/.claude")
        (self.home / "pkg/source-manifest.sha256").write_text(f"{good}  skills/plan/SKILL.md\n")
        self.assertNotIn("converted from older versions", self.run_i("check").stdout)

    def test_a_live_edit_stops_apply_until_ported_or_overwritten(self):
        self.run_i("apply")
        gate = self.home / ".claude/skills/gate/SKILL.md"
        gate.write_text("an edit made under ~/.claude\n")
        # the repository has moved on too, so apply wants to update this file
        manifest = json.loads((self.home / ".claude/.pipeline-install.json").read_text())
        manifest["files"][str(gate)] = "0" * 64
        (self.home / ".claude/.pipeline-install.json").write_text(json.dumps(manifest))
        out = self.run_i("apply")
        self.assertEqual(out.returncode, 1)
        self.assertIn("changed or added under ~/.claude since the last install", out.stdout)
        self.assertEqual(gate.read_text(), "an edit made under ~/.claude\n", "nothing was overwritten")
        out = subprocess.run([sys.executable, str(INSTALL), "apply", "--home", str(self.home), "--overwrite-live-edits"],
                             capture_output=True, text=True)
        self.assertNotEqual(gate.read_text(), "an edit made under ~/.claude\n")
        backups = list((self.home / ".claude/_backups").glob("pipeline-install-*/skills/gate/SKILL.md"))
        self.assertTrue(backups and backups[-1].read_text() == "an edit made under ~/.claude\n", "the edit was backed up")

    def test_a_file_added_inside_an_installed_skill_stops_apply(self):
        self.run_i("apply")
        added = self.home / ".claude/skills/gate/references/my-notes.md"
        added.write_text("written by hand after the install\n")
        out = self.run_i("apply")
        self.assertEqual(out.returncode, 1)
        self.assertIn(f"since the last install: {added}", out.stdout)
        self.assertTrue(added.exists(), "nothing was removed")
        (self.home / ".claude/skills/gate/friction.log").write_text("a note the owner keeps\n")
        added.unlink()
        again = self.run_i("apply")
        self.assertEqual(again.returncode, 0, "brain.md, friction.log, and tests/ stay the owner's: " + again.stdout[-600:])

    def test_unapproved_codex_hooks_are_noted(self):
        (self.home / ".codex").mkdir()
        (self.home / ".codex/hooks.json").write_text('{"hooks": {"Stop": [{"hooks": [{"command": "python3 continuity.py stop --tool codex"}]}]}}')
        (self.home / ".codex/config.toml").write_text('model = "x"\n')
        out = self.run_i("check")
        self.assertIn("none are recorded in ~/.codex/config.toml yet", out.stdout)

    def test_unregistered_hook_is_named(self):
        (self.home / ".claude/settings.json").write_text(json.dumps({"hooks": {}}))
        out = self.run_i("check")
        self.assertIn("hook not registered in settings.json: heavy-guard.py", out.stdout)

    def test_missing_tools_are_named(self):
        bare = self.home / "bin"
        bare.mkdir()
        (bare / "claude").write_text("#!/bin/sh\necho '2.1.100 (Claude Code)'\n")
        (bare / "claude").chmod(0o755)
        out = subprocess.run([sys.executable, str(INSTALL), "check", "--home", str(self.home)], capture_output=True,
                             text=True, env={"PATH": str(bare), "HOME": str(self.home)})
        self.assertIn("required tool not installed: playwright-cli", out.stdout)
        self.assertIn("older than 2.1.283", out.stdout)
        self.assertIn("checkers' browser is not ready", out.stdout)
        self.assertIn("optional tool codex: not installed", out.stdout)


if __name__ == "__main__":
    unittest.main()
