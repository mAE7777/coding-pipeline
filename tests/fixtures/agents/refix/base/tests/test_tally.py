import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def tally(folder, *args):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-m", "tally", *args], cwd=folder, capture_output=True, text=True, env=env)


class TallyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_says_what_it_recorded(self):
        out = tally(self.dir, "add", "food", "5", "--on", "2026-09-03")
        self.assertEqual(out.stdout.strip(), "added 5.00 to food on 2026-09-03")

    def test_total_sums_only_its_category(self):
        for category, amount in (("food", "5"), ("travel", "40"), ("food", "7.5")):
            tally(self.dir, "add", category, amount)
        self.assertEqual(tally(self.dir, "total", "food").stdout.strip(), "Total food: 12.50")
        self.assertEqual(tally(self.dir, "total", "rent").stdout.strip(), "Total rent: 0.00")

    def test_bad_input_is_refused_and_nothing_is_recorded(self):
        for args in (("food", "abc"), ("food", "nan"), ("food", "5", "--on", "2026-02-30")):
            out = tally(self.dir, "add", *args)
            self.assertEqual(out.returncode, 2, args)
            self.assertTrue(out.stderr.startswith("error: "), out.stderr)
        self.assertFalse((Path(self.dir) / "expenses.json").exists())

    def test_export_prints_a_header_and_every_expense(self):
        tally(self.dir, "add", "food", "5", "--on", "2026-09-03")
        tally(self.dir, "add", "travel", "40", "--on", "2026-09-10")
        self.assertEqual(tally(self.dir, "export").stdout,
                         "day,category,amount\n2026-09-03,food,5.00\n2026-09-10,travel,40.00\n")

    def test_archive_writes_only_that_months_expenses(self):
        tally(self.dir, "add", "food", "5", "--on", "2026-09-03")
        tally(self.dir, "add", "food", "3", "--on", "2026-10-01")
        out = tally(self.dir, "archive", "2026-09")
        self.assertEqual(out.stdout.strip(), "archived 1 expense(s) to archive/2026-09.csv")
        text = (Path(self.dir) / "archive/2026-09.csv").read_text()
        self.assertIn("2026-09-03,food,5.00", text)
        self.assertNotIn("2026-10", text)
        self.assertEqual(tally(self.dir, "archive", "2026-13").returncode, 2)


if __name__ == "__main__":
    unittest.main()
