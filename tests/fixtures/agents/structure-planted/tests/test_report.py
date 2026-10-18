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


class ReportTest(unittest.TestCase):
    def test_an_empty_folder_has_no_expenses_yet(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(tally(d, "report").stdout.strip(), "no expenses yet")

    def test_each_month_and_category_oldest_month_first(self):
        with tempfile.TemporaryDirectory() as d:
            for category, amount, day in (("food", "3", "2026-10-01"), ("food", "5", "2026-09-03"),
                                          ("travel", "40", "2026-09-10"), ("food", "7.50", "2026-09-20")):
                tally(d, "add", category, amount, "--on", day)
            self.assertEqual(tally(d, "report").stdout.splitlines(),
                             ["2026-09 food 12.50", "2026-09 travel 40.00", "2026-10 food 3.00"])

    def test_amounts_show_as_everywhere_else(self):
        with tempfile.TemporaryDirectory() as d:
            tally(d, "add", "rent", "1250", "--on", "2026-10-01")
            tally(d, "add", "food", "0.99", "--on", "2026-10-02")
            self.assertEqual(tally(d, "report").stdout.splitlines(), ["2026-10 food 0.99", "2026-10 rent 1,250.00"])
            self.assertEqual(tally(d, "total", "rent").stdout.strip(), "Total rent: 1,250.00")

    def test_an_unreadable_file_is_refused_and_kept(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "expenses.json"
            data.write_text("{broken")
            out = tally(d, "report")
            self.assertEqual(out.returncode, 2)
            self.assertIn("cannot read expenses.json", out.stderr)
            self.assertEqual(data.read_text(), "{broken")


if __name__ == "__main__":
    unittest.main()
