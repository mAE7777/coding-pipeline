import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app.py"


class TallyTest(unittest.TestCase):
    def test_add_says_what_it_added(self):
        with tempfile.TemporaryDirectory() as d:
            out = subprocess.run([sys.executable, str(APP), "add", "food", "5"], cwd=d, capture_output=True, text=True)
            self.assertIn("added 5.00 to food", out.stdout)


if __name__ == "__main__":
    unittest.main()
