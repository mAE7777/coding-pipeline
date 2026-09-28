"""Tests for inbox.py: input waits in the inbox and leaves only through a recorded, routed decision."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/_shared/scripts"
INBOX = SCRIPTS / "inbox.py"
SID = "99999999-2222-3333-4444-555555555555"
OWNER_SAYS = "Go with your recommendations on the export idea and the dark theme."


class InboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.project = d / "proj"
        (self.project / "docs/project").mkdir(parents=True)
        (self.project / "docs/project/decisions.md").write_text("# Decisions\n")
        self.home = d / "home"
        t = self.home / ".claude/projects/-p"
        t.mkdir(parents=True)
        (t / f"{SID}.jsonl").write_text(json.dumps({"type": "user", "uuid": "u1", "timestamp": "t1",
                                                    "message": {"content": OWNER_SAYS}}) + "\n")
        self.env = {**os.environ, "HOME": str(self.home), "CLAUDE_CODE_SESSION_ID": SID}

    def tearDown(self):
        self.tmp.cleanup()

    def run_s(self, script, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True, text=True,
                              env=self.env)

    def add(self, text, kind="idea", who="Mia (a beta user)"):
        out = self.run_s("inbox.py", "add", str(self.project), "--from", who, "--kind", kind, "--via", "email",
                         "--text", text)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return out.stdout.strip()

    def decide(self, did, iid, words, verdict, routed, owner=False):
        source = f'Source: [owner 2026-09-28] "{OWNER_SAYS}"' if owner else "Source: [proposed]"
        with open(self.project / "docs/project/decisions.md", "a") as f:
            f.write(f"\n## {did} · 2026-09-28 · Inbox {iid}\nResolves: {iid} (from Mia, 2026-09-28, via email)\n"
                    f'Item: "{words}"\nVerdict: {verdict}\nRouted: {routed}\n{source}\n')
        if owner:
            rec = self.run_s("rulings.py", "record", str(self.project), "--id", did, "--quote", OWNER_SAYS)
            self.assertEqual(rec.returncode, 0, rec.stdout)

    def check(self):
        return self.run_s("inbox.py", "check", str(self.project))

    def test_items_are_numbered_kept_verbatim_and_listed(self):
        self.assertEqual(self.add("Could the list export to CSV?\nWe paste it into a spreadsheet."), "IN-001")
        self.assertEqual(self.add("Dark theme please", kind="feedback"), "IN-002")
        text = (self.project / "docs/project/inbox.md").read_text()
        self.assertIn("> Could the list export to CSV?\n> We paste it into a spreadsheet.", text)
        self.assertIn("Next: IN-003", text)
        out = self.check()
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("2 open: IN-001, IN-002", out.stdout)

    def test_an_item_removed_by_hand_is_a_failure(self):
        self.add("Could the list export to CSV?")
        p = self.project / "docs/project/inbox.md"
        p.write_text(p.read_text().split("## IN-001")[0])
        out = self.check()
        self.assertEqual(out.returncode, 1)
        self.assertIn("IN-001 left the inbox without a decision entry", out.stdout)

    def test_an_in_contract_adoption_is_the_builders_to_make(self):
        iid = self.add("Show the item count in the header")
        self.decide("D-010", iid, "Show the item count in the header", "ADOPT",
                    "state.md Open (M1, inside its contract); decisions.md D-010")
        out = self.run_s("inbox.py", "resolve", str(self.project), iid, "--decision", "D-010")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertNotIn("IN-001", (self.project / "docs/project/inbox.md").read_text())
        out = self.check()
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("1 item(s) accounted for: 0 open, 1 resolved", out.stdout)

    def test_declining_or_changing_the_contract_needs_the_owner(self):
        a = self.add("Could the list export to CSV?")
        b = self.add("Dark theme please", kind="feedback")
        self.decide("D-011", a, "Could the list export to CSV?", "PLACE M3 · CSV export in M3",
                    "milestones.md M3 (In scope, M3.D4)")
        out = self.run_s("inbox.py", "resolve", str(self.project), a, "--decision", "D-011")
        self.assertEqual(out.returncode, 1)
        self.assertIn("changes the intent or a milestone contract", out.stdout)
        self.decide("D-012", b, "Dark theme please", "REJECT · the product is light only by the owner's standing rule",
                    "none")
        out = self.run_s("inbox.py", "resolve", str(self.project), b, "--decision", "D-012")
        self.assertEqual(out.returncode, 1)
        self.assertIn("declining or reshaping input is the owner's call", out.stdout)
        self.decide("D-013", a, "Could the list export to CSV?", "PLACE M3 · CSV export in M3",
                    "milestones.md M3 (In scope, M3.D4)", owner=True)
        self.decide("D-014", b, "Dark theme please", "REJECT · light only", "none", owner=True)
        for iid, did in ((a, "D-013"), (b, "D-014")):
            out = self.run_s("inbox.py", "resolve", str(self.project), iid, "--decision", did)
            self.assertEqual(out.returncode, 0, out.stdout)
        out = self.check()
        self.assertEqual(out.returncode, 0, "the later ruled entry supersedes the refused attempt: " + out.stdout)

    def test_the_decision_must_quote_the_item(self):
        iid = self.add("Could the list export to CSV?")
        self.decide("D-015", iid, "Export to Excel", "ADOPT", "state.md Open")
        out = self.run_s("inbox.py", "resolve", str(self.project), iid, "--decision", "D-015")
        self.assertEqual(out.returncode, 1)
        self.assertIn("but the item says", out.stdout)

    def test_resolved_but_still_listed_and_hand_numbering_fail(self):
        iid = self.add("Show the item count in the header")
        self.decide("D-016", iid, "Show the item count in the header", "ADOPT", "state.md Open")
        out = self.check()
        self.assertIn("still listed in the inbox", out.stdout)
        p = self.project / "docs/project/inbox.md"
        p.write_text(p.read_text() + "\n## IN-007 · 2026-09-28 · typed by hand\nStatus: open\n")
        self.assertIn("numbered at or past Next", self.check().stdout)

    def test_no_inbox_is_a_skip(self):
        out = self.check()
        self.assertEqual(out.returncode, 0)
        self.assertIn("SKIP", out.stdout)


if __name__ == "__main__":
    unittest.main()
