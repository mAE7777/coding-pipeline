import csv
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATEMENTS = ROOT / "tests/statements"
RULES = "coffee -> food\nfreshmart -> food\nshell -> travel\ntransit -> travel\nrent -> rent\n"


def tally(folder, *args):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-m", "tally", *args], cwd=folder, capture_output=True, text=True, env=env)


def exported(folder):
    return list(csv.reader(io.StringIO(tally(folder, "export").stdout)))[1:]


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "rules.txt").write_text(RULES)

    def tearDown(self):
        self.tmp.cleanup()

    def statement(self, name, text):
        path = self.dir / name
        path.write_text(text)
        return str(path)

    def test_a_northbank_statement_records_its_spending_by_rule(self):
        out = tally(self.dir, "import", str(STATEMENTS / "northbank-2026-09.csv"))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "imported 4 expense(s) from the northbank statement "
                                             "(0 already recorded, 1 income line(s) skipped)")
        self.assertEqual(exported(self.dir), [["2026-09-02", "food", "3.50"], ["2026-09-05", "travel", "61.20"],
                                              ["2026-09-12", "food", "48.75"], ["2026-09-20", "food", "3.50"]])
        self.assertEqual(tally(self.dir, "total", "food").stdout.strip(), "Total food: 55.75")

    def test_each_bank_dialect_is_read(self):
        tally(self.dir, "import", str(STATEMENTS / "riverside-2026-09.csv"))
        tally(self.dir, "import", str(STATEMENTS / "mono-2026-09.csv"))
        self.assertEqual(exported(self.dir), [["2026-09-01", "rent", "1,250.00"],
                                              ["2026-09-18", "uncategorized", "89.90"],
                                              ["2026-09-04", "travel", "2.90"],
                                              ["2026-09-11", "uncategorized", "11.50"]])

    def test_the_same_statement_twice_records_nothing_more(self):
        path = str(STATEMENTS / "northbank-2026-09.csv")
        tally(self.dir, "import", path)
        again = tally(self.dir, "import", path)
        self.assertEqual(again.stdout.strip(), "imported 0 expense(s) from the northbank statement "
                                               "(4 already recorded, 1 income line(s) skipped)")
        self.assertEqual(len(exported(self.dir)), 4)

    def test_an_overlapping_statement_adds_only_its_new_lines(self):
        tally(self.dir, "import", str(STATEMENTS / "northbank-2026-09.csv"))
        later = self.statement("later.csv", "Date,Description,Amount\n20/09/2026,CORNER COFFEE HOUSE,-3.50\n"
                                            "01/10/2026,SHELL STATION 114,-58.00\n")
        out = tally(self.dir, "import", later)
        self.assertIn("imported 1 expense(s)", out.stdout)
        self.assertIn("(1 already recorded", out.stdout)
        self.assertEqual(exported(self.dir)[-1], ["2026-10-01", "travel", "58.00"])

    def test_an_expense_added_by_hand_is_never_taken_for_a_statement_line(self):
        tally(self.dir, "add", "food", "3.50", "--on", "2026-09-02")
        tally(self.dir, "import", str(STATEMENTS / "northbank-2026-09.csv"))
        self.assertEqual(len(exported(self.dir)), 5)

    def test_a_bad_line_stops_the_import_and_is_named(self):
        tally(self.dir, "add", "food", "1", "--on", "2026-09-01")
        bad = self.statement("bad.csv", "Date,Description,Amount\n02/09/2026,CORNER COFFEE HOUSE,-3.50\n"
                                        "31/09/2026,SHELL STATION 114,-61.20\n")
        out = tally(self.dir, "import", bad)
        self.assertEqual(out.returncode, 2)
        self.assertIn("bad.csv line 3: Date '31/09/2026' is not a date like 03/09/2026", out.stderr)
        self.assertIn("nothing was recorded", out.stderr)
        self.assertEqual(len(exported(self.dir)), 1)

    def test_lines_that_are_not_spending_or_income_are_refused(self):
        for text, why in (("Date,Description,Amount\n02/09/2026,COFFEE,abc\n", "is not an amount"),
                          ("Date,Description,Amount\n02/09/2026,,-3.50\n", "Description is empty"),
                          ("Date,Description,Amount\n02/09/2026,COFFEE\n", "2 fields"),
                          ("Transaction Date;Payee;Debit;Credit\n2026-09-01;Rent;5,00;1,00\n", "exactly one of"),
                          ('"Booking date","Counterparty","Amount (EUR)","Type"\n"04.09.2026","Transit","2.90","out"\n',
                           "is neither")):
            with self.subTest(why):
                out = tally(self.dir, "import", self.statement("s.csv", text))
                self.assertEqual(out.returncode, 2)
                self.assertIn("s.csv line 2: ", out.stderr)
                self.assertIn(why, out.stderr)
        self.assertFalse((self.dir / "expenses.json").exists())

    def test_an_unknown_bank_is_refused(self):
        out = tally(self.dir, "import", self.statement("other.csv", "When,What,How much\n"))
        self.assertEqual(out.returncode, 2)
        self.assertIn("not a header tally knows", out.stderr)

    def test_a_bad_rule_is_named_and_nothing_is_recorded(self):
        (self.dir / "rules.txt").write_text("coffee -> food\ncoffee food\n")
        out = tally(self.dir, "import", str(STATEMENTS / "northbank-2026-09.csv"))
        self.assertEqual(out.returncode, 2)
        self.assertIn("rules.txt line 2", out.stderr)
        self.assertFalse((self.dir / "expenses.json").exists())

    def test_a_dry_run_shows_and_records_nothing(self):
        out = tally(self.dir, "import", "--dry-run", str(STATEMENTS / "mono-2026-09.csv"))
        self.assertIn("would add 2.90 to travel on 2026-09-04 (Berlin Transit)", out.stdout)
        self.assertIn("would import 2 expense(s)", out.stdout)
        self.assertFalse((self.dir / "expenses.json").exists())

    def test_an_unreadable_data_file_is_refused_and_kept(self):
        data = self.dir / "expenses.json"
        data.write_text("{broken")
        out = tally(self.dir, "import", str(STATEMENTS / "northbank-2026-09.csv"))
        self.assertEqual(out.returncode, 2)
        self.assertEqual(data.read_text(), "{broken")


if __name__ == "__main__":
    unittest.main()
