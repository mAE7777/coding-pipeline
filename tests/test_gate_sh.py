"""Tests for gate.sh's modes: the check run, --fingerprint, --inventory, and bad options."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "skills/_shared/gate.sh"
FIX = ROOT / "tests/fixtures"


def gate(*args):
    return subprocess.run(["bash", str(GATE), *args], capture_output=True, text=True, timeout=300)


class GateShTest(unittest.TestCase):
    def test_fingerprint_matches_script(self):
        a = gate("--fingerprint", str(FIX / "clean")).stdout.strip()
        b = subprocess.run([sys.executable, str(ROOT / "skills/_shared/scripts/fingerprint.py"),
                            str(FIX / "clean")], capture_output=True, text=True).stdout.strip()
        self.assertTrue(a.startswith("product:"), a)
        self.assertEqual(a, b)

    def test_inventory_mode(self):
        out = gate("--inventory", str(FIX / "degradation"))
        self.assertEqual(out.returncode, 0)
        self.assertIn("swallowed-error", out.stdout)

    def test_bad_option(self):
        self.assertEqual(gate("--nope").returncode, 2)

    def test_check_run_names_every_skip(self):
        out = gate(str(FIX / "clean"))
        self.assertIn("RESULT:", out.stdout)
        for line in out.stdout.splitlines():
            if line.startswith("SKIP"):
                self.assertGreater(len(line.split(None, 2)[-1]), 5, f"a SKIP must say why: {line}")

    def test_secret_is_a_fail(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            key = "AKIA" + "ABCDEFGHIJKLMNOP"
            (Path(d) / "config.py").write_text(f"AWS = '{key}'\n")
            out = gate(d)
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("FAIL   secrets", out.stdout)

    def test_tooling_names_in_committed_record_fail(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            docs = Path(d) / "docs/project"
            docs.mkdir(parents=True)
            (docs / "decisions.md").write_text("## D-001\nDecided after the code-verifier run in /gate.\n")
            (docs / "state.md").write_text("local notes about /dev and heavy.py\n")
            subprocess.run(["git", "init", "-q", d], check=True)
            subprocess.run(["git", "-C", d, "add", "docs/project/decisions.md"], check=True)
            out = gate(d)
            self.assertIn("FAIL   pipeline-traces", out.stdout)
            self.assertIn("decisions.md", out.stdout)
            self.assertNotIn("state.md", out.stdout.split("pipeline-traces", 1)[1].splitlines()[0],
                             "local-only files may name the tooling")
            (docs / "decisions.md").write_text("## D-001\nDecided after the review.\n")
            out = gate(d)
            self.assertIn("PASS   pipeline-traces", out.stdout)
            (docs / "interfaces.md").write_text("## API\n- POST /capture stores a photo\n- GET /plan returns the week\n"
                                                "The extension talks to Claude Code through a subagent.\n")
            subprocess.run(["git", "-C", d, "add", "docs/project/interfaces.md"], check=True)
            out = gate(d)
            self.assertIn("PASS   pipeline-traces", out.stdout, "product routes and product words are not tooling")
            (docs / "decisions.md").write_text("## D-002\nAccepted after /gate M1 and /plan adopt.\n")
            out = gate(d)
            self.assertIn("FAIL   pipeline-traces", out.stdout)


if __name__ == "__main__":
    unittest.main()
