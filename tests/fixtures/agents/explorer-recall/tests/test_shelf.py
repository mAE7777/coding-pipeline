import datetime
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shelf.export import safe_cell  # noqa: E402
from shelf.models import BadIsbn, Book, Loan, normalize_isbn  # noqa: E402


def shelf(d, *args):
    env = dict(os.environ, SHELF_DATA=str(Path(d) / "loans.json"), PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, "-m", "shelf", *args], cwd=d, env=env, capture_output=True, text=True)


class ShelfTest(unittest.TestCase):
    def test_isbn_check_digit(self):
        self.assertEqual(normalize_isbn("0-306-40615-2"), "0306406152")
        with self.assertRaises(BadIsbn):
            normalize_isbn("0-306-40615-3")

    def test_overdue_only_after_the_due_date(self):
        loan = Loan(Book("Dune"), "Sam", datetime.date(2026, 10, 1), datetime.date(2026, 10, 22))
        self.assertFalse(loan.is_overdue(datetime.date(2026, 10, 22)))
        self.assertTrue(loan.is_overdue(datetime.date(2026, 10, 23)))

    def test_formula_cells_are_text(self):
        self.assertEqual(safe_cell("=SUM(A1)"), "'=SUM(A1)")

    def test_lend_and_return(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("lent Dune to Sam", shelf(d, "lend", "Dune", "Sam").stdout)
            self.assertIn("Dune is back from Sam", shelf(d, "return", "Dune").stdout)
            self.assertEqual(shelf(d, "list").stdout, "")

    def test_a_damaged_file_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "loans.json").write_text("{damaged")
            out = shelf(d, "list")
            self.assertEqual(out.returncode, 2)
            self.assertEqual((Path(d) / "loans.json").read_text(), "{damaged")


if __name__ == "__main__":
    unittest.main()
