import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app.py"


def tally(d, *args):
    return subprocess.run([sys.executable, str(APP), *args], cwd=d, capture_output=True, text=True)


class TallyTest(unittest.TestCase):
    def test_add_says_what_it_added(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("added 5.00 to food", tally(d, "add", "food", "5").stdout)

    def test_total_sums_only_its_category(self):
        with tempfile.TemporaryDirectory() as d:
            for category, value in (("food", "5"), ("travel", "40"), ("food", "7.5")):
                tally(d, "add", category, value)
            self.assertEqual(tally(d, "total", "food").stdout.strip(), "Total food: 12.50")
            self.assertEqual(tally(d, "total", "travel").stdout.strip(), "Total travel: 40.00")

    def test_fresh_folder_has_no_expenses(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(tally(d, "total", "food").stdout.strip(), "Total food: 0.00")
            self.assertEqual(tally(d, "export").stdout.strip(), "category,amount")

    def test_unreadable_file_is_refused_and_kept(self):
        variants = {"broken": b"{broken", "empty": b"", "not utf-8": b"\xff\xfe", "not a list": b"{}",
                    "bad amount": b'[{"category": "food", "amount": NaN}]'}
        for label, raw in variants.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as d:
                data = Path(d) / "expenses.json"
                data.write_bytes(raw)
                for args in (("add", "food", "1"), ("total", "food"), ("export",)):
                    out = tally(d, *args)
                    self.assertEqual(out.returncode, 2, (label, args, out.stderr))
                    self.assertIn("cannot read expenses.json", out.stderr)
                self.assertEqual(data.read_bytes(), raw)

    def test_links_that_cannot_be_followed_are_refused_and_kept(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "expenses.json"
            os.symlink("expenses.json", data)
            self.assertEqual(tally(d, "add", "food", "1").returncode, 2, "a link loop")
            self.assertTrue(data.is_symlink())
            data.unlink()
            os.symlink("missing/real.json", data)
            self.assertEqual(tally(d, "total", "food").returncode, 2, "a dangling link")
            self.assertEqual(tally(d, "add", "food", "1").returncode, 2, "a dangling link")
            self.assertTrue(data.is_symlink())

    def test_save_writes_through_a_link_and_keeps_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            real = Path(d) / "real.json"
            real.write_text("[]")
            real.chmod(0o644)
            os.symlink("real.json", Path(d) / "expenses.json")
            tally(d, "add", "food", "5")
            self.assertTrue((Path(d) / "expenses.json").is_symlink())
            self.assertEqual(json.loads(real.read_text()), [{"category": "food", "amount": 5.0}])
            self.assertEqual(real.stat().st_mode & 0o777, 0o644)

    def test_export_is_valid_csv_and_safe_in_a_spreadsheet(self):
        with tempfile.TemporaryDirectory() as d:
            for category in ("eat, out", 'say "hi"', "=SUM(A1)"):
                tally(d, "add", category, "2")
            rows = list(csv.reader(io.StringIO(tally(d, "export").stdout)))
            self.assertEqual(rows, [["category", "amount"], ["eat, out", "2.00"], ['say "hi"', "2.00"],
                                    ["'=SUM(A1)", "2.00"]])

    def test_bad_amounts_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            for bad in ("-5", "nan", "inf", "abc", "1e400", "2000000000"):
                self.assertEqual(tally(d, "add", "food", bad).returncode, 2, bad)
            self.assertFalse((Path(d) / "expenses.json").exists())

    def test_amounts_are_kept_in_cents(self):
        with tempfile.TemporaryDirectory() as d:
            for _ in range(3):
                self.assertIn("added 0.00 to c", tally(d, "add", "c", "0.004").stdout)
            self.assertEqual(tally(d, "total", "c").stdout.strip(), "Total c: 0.00")
            self.assertIn("added 0.00 to z", tally(d, "add", "z", "-0").stdout)

    def test_read_only_folder_reports_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as d:
            tally(d, "add", "food", "5")
            os.chmod(d, 0o555)
            try:
                self.assertEqual(tally(d, "total", "food").stdout.strip(), "Total food: 5.00")
                out = tally(d, "add", "food", "1")
                self.assertEqual(out.returncode, 2)
                self.assertNotIn("Traceback", out.stderr)
            finally:
                os.chmod(d, 0o755)
            self.assertEqual(tally(d, "total", "food").stdout.strip(), "Total food: 5.00")


if __name__ == "__main__":
    unittest.main()
