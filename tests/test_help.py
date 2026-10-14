"""Asking a pipeline script how to use it is a request, not a mistake: the usage and exit 0."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# evolve.py is the judge of pipeline changes; a change to it is the owner's ruling, so it is not covered here.
SCRIPTS = [ROOT / "install.py"] + sorted(p for p in (ROOT / "skills/_shared/scripts").glob("*.py")
                                        if "print(__doc__" in p.read_text() and p.name != "evolve.py")


class HelpTest(unittest.TestCase):
    def test_every_script_answers_help_with_its_usage_and_success(self):
        self.assertGreater(len(SCRIPTS), 20)
        for script in SCRIPTS:
            for args in (["--help"], ["-h"]):
                out = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, timeout=60)
                self.assertEqual(out.returncode, 0, f"{script.name} {args[0]}: {out.stderr[-300:]}")
                self.assertIn("Usage", out.stdout, f"{script.name} {args[0]} prints its usage")

    def test_help_after_a_subcommand(self):
        for script, sub in (("rulings.py", "record"), ("inbox.py", "add"), ("project_status.py", "record")):
            out = subprocess.run([sys.executable, str(ROOT / "skills/_shared/scripts" / script), sub, "--help"],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, f"{script} {sub} --help: {out.stderr[-300:]}")
            self.assertIn("Usage", out.stdout)


if __name__ == "__main__":
    unittest.main()
