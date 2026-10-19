import json
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


class BudgetTest(unittest.TestCase):
    def test_a_budget_is_kept_and_setting_it_again_replaces_it(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(tally(d, "budget", "food", "100").stdout.strip(), "budget for food: 100.00 a month")
            tally(d, "budget", "food", "80")
            self.assertEqual(json.loads((Path(d) / "budgets.json").read_text()), {"food": 8000})

    def test_status_shows_each_budgeted_category_against_its_budget(self):
        with tempfile.TemporaryDirectory() as d:
            for category, amount, day in (("food", "5", "2026-09-03"), ("travel", "40", "2026-09-10"),
                                          ("food", "7.50", "2026-09-20")):
                tally(d, "add", category, amount, "--on", day)
            tally(d, "budget", "food", "100")
            self.assertEqual(tally(d, "status", "2026-09").stdout.splitlines(), ["food 12.50 of 100.00"])

    def test_status_without_budgets_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(tally(d, "status", "2026-09").stdout.strip(), "no budgets yet")

    def test_a_month_is_yyyy_mm(self):
        with tempfile.TemporaryDirectory() as d:
            out = tally(d, "status", "2026-9")
            self.assertEqual(out.returncode, 2)
            self.assertIn("not a month", out.stderr)

    def test_an_unreadable_budgets_file_is_refused_and_kept(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "budgets.json"
            for raw in ("{broken", "[]", '{"food": -1}'):
                data.write_text(raw)
                for args in (("budget", "food", "1"), ("status", "2026-09")):
                    out = tally(d, *args)
                    self.assertEqual(out.returncode, 2, (raw, args))
                    self.assertIn("cannot read budgets.json", out.stderr)
                self.assertEqual(data.read_text(), raw)


if __name__ == "__main__":
    unittest.main()
