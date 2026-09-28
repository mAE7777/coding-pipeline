"""Tests for intent_lock.py."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "skills/_shared/scripts/intent_lock.py"
RULINGS = ROOT / "skills/_shared/scripts/rulings.py"
SID = "99999999-2222-3333-4444-555555555555"

INTENT = """# Intent

Status: draft

## Goal
Two people who share a household keep one grocery list that stays the same on both phones.

## Identity and promise
The shared list you can trust.
Before: two lists drift apart. After: one list.

## Who
Persona (blind): an adult who uses a smartphone every day and installs apps from the store.
Parents juggling errands.

## Load-bearing behavior
An edit on one phone appears on the other within five seconds, and deletions win over stale edits.

## Done examples
- I-D1 When one phone adds milk, the other shows milk within five seconds. Example: add "milk" on A → B lists "milk"
- I-D2 If the network drops, the list says offline and queues the edit. Example: airplane mode, add "eggs" → "offline, 1 pending"

## Mechanism cards
### Sync
Purpose: both phones agree.
Observable guarantee: same list on both within five seconds.
Rejected imitation: polling every minute.
Discriminating probe: add on A, read B after five seconds.

## Must not lose
- L-01 A deleted item never comes back · check: delete on A, stale edit on B, item stays deleted
- L-02 The list feels calm · not code-checkable (the owner judges it at acceptance)

## Design intent
One screen.

## Assumptions
- A-01 Two phones only · signed 2026-09-27

## Re-freeze log
"""


class IntentLockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "proj"
        (self.project / "docs/project").mkdir(parents=True)
        self.intent = self.project / "docs/project/intent.md"
        self.intent.write_text(INTENT)
        self.home = Path(self.tmp.name) / "home"
        t = self.home / ".claude/projects/-p"
        t.mkdir(parents=True)
        (t / f"{SID}.jsonl").write_text("\n".join(json.dumps(x) for x in [
            {"type": "user", "uuid": "u1", "message": {"content": "Locked. That is the thing I want built."}},
            {"type": "user", "uuid": "u2", "message": {"content": "yes, replace I-D2 with the retry version"}},
        ]) + "\n")
        self.env = {**os.environ, "HOME": str(self.home), "CLAUDE_CODE_SESSION_ID": SID}

    def tearDown(self):
        self.tmp.cleanup()

    def run_l(self, *args):
        return subprocess.run([sys.executable, str(LOCK), *args], capture_output=True, text=True, env=self.env)

    def record(self, did, quote, title="Lock intent"):
        with open(self.project / "docs/project/decisions.md", "a") as f:
            f.write(f'\n## {did} · 2026-09-27 · {title}\nSource: [owner 2026-09-27] "{quote}"\n')
        return subprocess.run([sys.executable, str(RULINGS), "record", str(self.project), "--id", did, "--quote", quote],
                              capture_output=True, text=True, env=self.env)

    def test_lint_passes_a_complete_intent(self):
        out = self.run_l("lint", str(self.intent))
        self.assertEqual(out.returncode, 0, out.stdout)

    def test_lint_catches_a_persona_that_names_the_purpose(self):
        self.intent.write_text(INTENT.replace("installs apps from the store", "shares a grocery list"))
        out = self.run_l("lint", str(self.intent))
        self.assertEqual(out.returncode, 1)
        self.assertIn("grocery", out.stdout)

    def test_lint_reads_a_chinese_persona(self):
        zh = INTENT.replace("Two people who share a household keep one grocery list that stays the same on both phones.",
                            "帮在纽约租房的中国留学生看懂租约里的隐藏费用。").replace(
            "Persona (blind): an adult who uses a smartphone every day and installs apps from the store.",
            "Persona (blind): 在纽约租房的中国留学生，想看懂租约里的隐藏费用")
        self.intent.write_text(zh)
        out = self.run_l("lint", str(self.intent))
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("shares purpose words", out.stdout)
        ok = zh.replace("Persona (blind): 在纽约租房的中国留学生，想看懂租约里的隐藏费用", "Persona (blind): 每天用手机的成年人")
        self.intent.write_text(ok)
        self.assertNotIn("shares purpose words", self.run_l("lint", str(self.intent)).stdout)

    def test_lint_catches_unchecked_must_not_lose(self):
        self.intent.write_text(INTENT.replace(" · check: delete on A, stale edit on B, item stays deleted", ""))
        self.assertEqual(self.run_l("lint", str(self.intent)).returncode, 1)

    def test_stamp_requires_a_proven_ruling(self):
        with open(self.project / "docs/project/decisions.md", "w") as f:
            f.write('# Decisions\n\n## D-001 · 2026-09-27 · Lock intent\nSource: [owner 2026-09-27] "lock it"\n')
        self.assertEqual(self.run_l("stamp", str(self.intent), "--ruling", "D-001").returncode, 1,
                         "an owner line without proof cannot lock")
        self.assertEqual(self.record("D-002", "That is the thing I want built.").returncode, 0)
        out = self.run_l("stamp", str(self.intent), "--ruling", "D-002")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertRegex(self.intent.read_text(), r"Locked by the owner \d{4}-\d{2}-\d{2} · hash [0-9a-f]{16} · ruling D-002")
        self.assertEqual(self.run_l("verify", str(self.intent)).returncode, 0)

    def test_edit_after_lock_fails_verify(self):
        self.record("D-002", "That is the thing I want built.")
        self.run_l("stamp", str(self.intent), "--ruling", "D-002")
        self.intent.write_text(self.intent.read_text().replace("within five seconds, and", "eventually, and"))
        out = self.run_l("verify", str(self.intent))
        self.assertEqual(out.returncode, 1)
        self.assertIn("changed after the lock", out.stdout)

    def test_refreeze_changes_effective_intent_not_the_hash(self):
        self.record("D-002", "That is the thing I want built.")
        self.run_l("stamp", str(self.intent), "--ruling", "D-002")
        self.record("D-003", "yes, replace I-D2 with the retry version", "Re-freeze I-D2")
        text = self.intent.read_text().replace("re-freezes 0", "re-freezes 1")
        text += ("### RF-1 · 2026-09-27 · D-003\n"
                 "Supersedes I-D2 with I-D2a: If the network drops, edits retry until they land. Example: x → y\n"
                 "Drops L-02 (reason: the owner folded it into acceptance)\n")
        self.intent.write_text(text)
        out = self.run_l("verify", str(self.intent))
        self.assertEqual(out.returncode, 0, out.stdout)
        eff = json.loads(self.run_l("effective", str(self.intent)).stdout)
        self.assertIn("I-D2a", eff["done_examples"])
        self.assertNotIn("I-D2", eff["done_examples"])
        self.assertNotIn("L-02", eff["must_not_lose"])
        self.assertEqual(eff["mechanisms"], ["Sync"])
        self.assertTrue(eff["persona_blind"].startswith("an adult"))

    def test_unproven_refreeze_fails(self):
        self.record("D-002", "That is the thing I want built.")
        self.run_l("stamp", str(self.intent), "--ruling", "D-002")
        text = self.intent.read_text().replace("re-freezes 0", "re-freezes 1")
        text += "### RF-1 · 2026-09-27 · D-004\nAdds I-D3: something. Example: a → b\n"
        self.intent.write_text(text)
        self.assertEqual(self.run_l("verify", str(self.intent)).returncode, 1)


if __name__ == "__main__":
    unittest.main()
