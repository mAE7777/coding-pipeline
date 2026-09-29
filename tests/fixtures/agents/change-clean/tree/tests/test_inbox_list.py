import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/_shared/scripts/inbox_list.py"
SAMPLE = """# Inbox

- IN-001 · Sam: Drop the CSV export from M2.
- IN-002 · Priya: The share link should expire after a week.
- IN-003 · Leo: Add a dark theme.
"""


class InboxList(unittest.TestCase):
    def run_list(self, text):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "inbox.md"
            f.write_text(text, encoding="utf-8")
            return subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)

    def test_list_shows_every_item(self):
        r = self.run_list(SAMPLE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("IN-"), 3)

    def test_words_are_kept_verbatim(self):
        r = self.run_list(SAMPLE)
        self.assertIn("IN-002 · Priya: The share link should expire after a week.", r.stdout)

    def test_words_with_a_colon_are_listed_whole(self):
        r = self.run_list(SAMPLE + "- IN-004 · Maya: Idea: keep the dates when exporting.\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("IN-004 · Maya: Idea: keep the dates when exporting.", r.stdout)
        self.assertEqual(r.stdout.count("IN-"), 4)


if __name__ == "__main__":
    unittest.main()
