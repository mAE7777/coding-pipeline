"""Tests for settings_patch.py: exact additions, the two removals, idempotence, everything else untouched."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "settings_patch.py"

BEFORE = {"theme": "light", "env": {"KEEP": "1"},
          "hooks": {"PreToolUse": [{"matcher": "Write|Edit", "hooks": [{"type": "command", "command": "~/.claude/hooks/guard-truth-reload.sh"}]}],
                    "PostToolUse": [{"matcher": "Write|Edit", "hooks": [
                        {"type": "command", "command": "~/.claude/hooks/scan-written-code.sh"},
                        {"type": "command", "command": "~/.claude/hooks/suggest-compact.sh"}]},
                        {"matcher": "Edit", "hooks": [{"type": "command", "command": "~/.claude/hooks/post-edit-typecheck.sh"}]}]}}


class SettingsPatchTest(unittest.TestCase):
    def test_apply_is_exact_and_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".claude/settings.json"
            p.parent.mkdir()
            p.write_text(json.dumps(BEFORE))
            subprocess.run([sys.executable, str(PATCH), "--apply", "--home", d], check=True, capture_output=True)
            after = json.loads(p.read_text())
            text = json.dumps(after)
            self.assertNotIn("suggest-compact", text)
            self.assertNotIn("post-edit-typecheck", text)
            self.assertIn("scan-written-code", text)
            self.assertIn("guard-truth-reload", text)
            for cmd in ("heavy-guard.py", "reload-gate.py arm", "reload-gate.py track", "reload-gate.py guard",
                        "snapshot-state.py", "typecheck-once.py", "continuity.py session-start", "continuity.py claim",
                        "continuity.py stop", "verify-pipeline-completion.sh"):
                self.assertEqual(text.count(cmd), 1, cmd)
            self.assertEqual(after["theme"], "light")
            self.assertEqual(after["env"]["KEEP"], "1")
            self.assertEqual(after["env"]["CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"], "5")
            self.assertTrue(list(p.parent.glob("settings.json.bak-*")), "a backup was written")
            again = subprocess.run([sys.executable, str(PATCH), "--home", d], capture_output=True, text=True)
            self.assertIn("already has every pipeline entry", again.stdout)


class CodexHooksPatchTest(unittest.TestCase):
    def test_codex_hooks_added_once_and_existing_kept(self):
        codex_patch = ROOT / "codex_hooks_patch.py"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".codex/hooks.json"
            p.parent.mkdir()
            p.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine.sh"}]}]}}))
            subprocess.run([sys.executable, str(codex_patch), "--apply", "--home", d], check=True, capture_output=True)
            text = p.read_text()
            self.assertIn("mine.sh", text)
            for cmd in ("continuity.py session-start --tool codex", "continuity.py claim --tool codex",
                        "continuity.py stop --tool codex", "milestone-continue.py --tool codex", "heavy-guard.py"):
                self.assertEqual(text.count(cmd), 1, cmd)
            again = subprocess.run([sys.executable, str(codex_patch), "--home", d], capture_output=True, text=True)
            self.assertIn("already has every pipeline entry", again.stdout)


if __name__ == "__main__":
    unittest.main()
