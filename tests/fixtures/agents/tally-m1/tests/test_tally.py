import csv
import io
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


class AddAndTotalTest(unittest.TestCase):
    def test_add_says_what_it_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            out = tally(d, "add", "food", "5", "--on", "2026-09-03")
            self.assertEqual(out.stdout.strip(), "added 5.00 to food on 2026-09-03")

    def test_total_sums_only_its_category(self):
        with tempfile.TemporaryDirectory() as d:
            for category, amount in (("food", "5"), ("travel", "40"), ("food", "7.5")):
                tally(d, "add", category, amount)
            self.assertEqual(tally(d, "total", "food").stdout.strip(), "Total food: 12.50")
            self.assertEqual(tally(d, "total", "travel").stdout.strip(), "Total travel: 40.00")
            self.assertEqual(tally(d, "total", "rent").stdout.strip(), "Total rent: 0.00")

    def test_amounts_are_kept_in_cents_and_shown_with_separators(self):
        with tempfile.TemporaryDirectory() as d:
            tally(d, "add", "rent", "1,250")
            tally(d, "add", "rent", "0.005")
            self.assertEqual(tally(d, "total", "rent").stdout.strip(), "Total rent: 1,250.01")

    def test_bad_input_is_refused_and_nothing_is_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            for args in (("food", "-5"), ("food", "abc"), ("food", "nan"), ("food", "1e12"),
                         ("food", "5", "--on", "2026-02-30"), ("food", "5", "--on", "yesterday")):
                out = tally(d, "add", *args)
                self.assertEqual(out.returncode, 2, args)
                self.assertTrue(out.stderr.startswith("error: "), out.stderr)
            self.assertFalse((Path(d) / "expenses.json").exists())


class DataFileTest(unittest.TestCase):
    def test_an_unreadable_file_is_refused_and_kept(self):
        for raw in (b"{broken", b"", b"\xff\xfe", b"{}", b'[{"day": "2026-09-03", "category": "food", "cents": 1.5}]'):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as d:
                data = Path(d) / "expenses.json"
                data.write_bytes(raw)
                for args in (("add", "food", "1"), ("total", "food"), ("export",)):
                    out = tally(d, *args)
                    self.assertEqual(out.returncode, 2, args)
                    self.assertIn("cannot read expenses.json", out.stderr)
                self.assertEqual(data.read_bytes(), raw)

    def test_a_failed_save_keeps_the_old_file(self):
        with tempfile.TemporaryDirectory() as d:
            tally(d, "add", "food", "5")
            os.chmod(d, 0o555)
            try:
                out = tally(d, "add", "food", "1")
            finally:
                os.chmod(d, 0o755)
            if os.geteuid() != 0:  # root writes anyway
                self.assertEqual(out.returncode, 2)
                self.assertIn("nothing was recorded", out.stderr)
            self.assertNotIn("Traceback", out.stderr)


class ExportTest(unittest.TestCase):
    def test_export_is_valid_csv_and_safe_in_a_spreadsheet(self):
        with tempfile.TemporaryDirectory() as d:
            for category in ("eat, out", 'say "hi"', "=SUM(A1)"):
                tally(d, "add", category, "2", "--on", "2026-09-03")
            rows = list(csv.reader(io.StringIO(tally(d, "export").stdout)))
            self.assertEqual(rows, [["day", "category", "amount"], ["2026-09-03", "eat, out", "2.00"],
                                    ["2026-09-03", 'say "hi"', "2.00"], ["2026-09-03", "'=SUM(A1)", "2.00"]])


if __name__ == "__main__":
    unittest.main()
