"""Tests for inventory.py: every planted site is listed, tests are skipped, a clean tree lists nothing."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INV = ROOT / "skills/_shared/scripts/inventory.py"
FIX = ROOT / "tests/fixtures"

EXPECTED = {
    ("swallowed-error", "src/store.ts:6"),
    ("swallowed-error", "src/store.ts:12"),
    ("swallowed-error", "src/sync.py:7"),
    ("swallowed-error", "src/sync.py:14"),
    ("stand-in-import", "src/store.ts:1"),
    ("stand-in-import", "src/sync.py:1"),
    ("feature-flag", "src/store.ts:16"),
    ("unfinished", "src/store.ts:19"),
    ("unfinished", "src/store.ts:20"),
}


def run(d):
    return subprocess.run([sys.executable, str(INV), str(d)], capture_output=True, text=True)


class InventoryTest(unittest.TestCase):
    def test_every_planted_site_found(self):
        out = run(FIX / "degradation")
        self.assertEqual(out.returncode, 0)
        found = {(l.split()[0], l.split()[1]) for l in out.stdout.splitlines() if not l.startswith("inventory:")}
        self.assertEqual(found, EXPECTED, out.stdout)

    def test_wiring_surface_found(self):
        out = run(FIX / "wiring").stdout
        found = {(l.split()[0], l.split()[1]) for l in out.splitlines() if not l.startswith("inventory:")}
        for want in (("route", "src/server.ts:7"), ("route", "src/server.ts:11"), ("route", "src/api.py:7"),
                     ("model-call", "src/server.ts:12"), ("model-call", "src/api.py:13"),
                     ("event", "src/server.ts:13"), ("event", "src/server.ts:17")):
            self.assertIn(want, found, out)

    def test_test_files_skipped(self):
        self.assertNotIn("store.test.ts", run(FIX / "degradation").stdout)

    def test_snippets_stay_on_one_line(self):
        for line in run(FIX / "degradation").stdout.splitlines():
            self.assertNotIn("export async", line.split("  ", 1)[-1] if "stand-in-import" in line else "")

    def test_game_and_ui_languages_are_scanned_and_markup_is_named(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "src").mkdir()
            (Path(d) / "src/Player.cs").write_text("void Load() {\n  try { Read(); } catch (Exception e) { }\n}\n")
            (Path(d) / "src/player.gd").write_text("func _ready():\n    pass # TODO: real save\n")
            (Path(d) / "src/index.html").write_text("<html></html>\n")
            out = run(d).stdout
            self.assertIn("swallowed-error  src/Player.cs:2", out)
            self.assertIn("unfinished       src/player.gd:2", out)
            self.assertIn("not scanned (markup, styles, SQL): html 1 file(s)", out)

    def test_clean_control_lists_nothing(self):
        out = run(FIX / "clean")
        self.assertEqual(out.stdout.strip(), "inventory: no candidates")


if __name__ == "__main__":
    unittest.main()
