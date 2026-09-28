"""Tests for adopt.py: inventory, the coverage ledger, command runs, and the completeness check."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADOPT = ROOT / "skills/_shared/scripts/adopt.py"


def unadopted(d):
    root = Path(d) / "proj"
    files = {
        "README.md": "# Lists\nShare grocery lists between phones. Supports offline mode.\n",
        "docs/architecture.md": "# Architecture\nA store and a sync loop.\n",
        "slices.md": "# Slices\n- S1 add items\n",
        "src/app.py": "def add(items, x):\n    items.append(x)\n    return items\n",
        "src/export.py": "def export(items):\n    return ','.join(items)\n",
        "tests/test_app.py": "from src.app import add\n\ndef test_add():\n    assert add([], 'a') == ['a']\n",
        "package-lock.json": "{}\n",
        "dist/bundle.min.js": "x\n",
        "logo.png": "PNG",
    }
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "start"],
                   check=True)
    return root


class AdoptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = unadopted(self.tmp.name)
        self.env = {**os.environ, "HEAVY_LOCK_DIR": str(Path(self.tmp.name) / "lock"), "HEAVY_OWNER": "t"}
        self.env.pop("HEAVY_LOCK_HELD", None)

    def tearDown(self):
        self.tmp.cleanup()

    def adopt(self, *args):
        return subprocess.run([sys.executable, str(ADOPT), *args, str(self.root)], capture_output=True, text=True,
                              env=self.env)

    def test_inventory_classifies_and_plans(self):
        out = self.adopt("inventory")
        self.assertEqual(out.returncode, 0, out.stderr)
        d = self.root / "docs/project/research/adoption"
        inv = json.loads((d / "inventory.json").read_text())
        classes = {r["path"]: r["class"] for r in inv["files"]}
        self.assertEqual(classes["src/app.py"], "code")
        self.assertEqual(classes["tests/test_app.py"], "test")
        self.assertEqual(classes["README.md"], "doc")
        self.assertEqual(classes["slices.md"], "legacy-record")
        self.assertEqual(classes["package-lock.json"], "lockfile")
        self.assertEqual(classes["logo.png"], "binary")
        ledger = (d / "coverage.md").read_text()
        self.assertIn("| src/app.py | code | 3 | todo |", ledger)
        self.assertIn("skipped (lockfile)", ledger)
        self.assertNotIn("| package-lock.json |", ledger, "pre-accounted files are grouped, not read")
        self.assertIn("docs/architecture.md", (d / "reading-plan.md").read_text())
        self.assertEqual(inv["git"]["commits"], "1")

    def test_check_fails_until_everything_is_accounted_and_built(self):
        self.adopt("inventory")
        out = self.adopt("check")
        self.assertEqual(out.returncode, 1)
        for must in ("not accounted for yet", "docs/project/intent.md is missing", "never run"):
            self.assertIn(must, out.stdout)

    def import_documents(self):
        """The real flow: each document becomes a capture source, organized in a dossier quoting it verbatim."""
        capture = ROOT / "skills/_shared/scripts/capture.py"
        units, n, ids = [], 0, {}
        for doc in ("README.md", "docs/architecture.md"):
            out = subprocess.run([sys.executable, str(capture), "add", str(self.root), str(self.root / doc), "--kind", "doc"],
                                 capture_output=True, text=True, env=self.env)
            self.assertEqual(out.returncode, 0, out.stderr)
            src = out.stdout.split()[0]
            ids[doc] = src
            folder = next((self.root / "docs/project/sources").glob(f"{src}-*"))
            for line in (folder / "turns.jsonl").read_text().splitlines():
                turn = json.loads(line)
                n += 1
                line_text = turn["text"].strip().splitlines()[-1]
                units.append(f"- S-{n:03d} · product · document · current · {src} {turn['id']}\n  {line_text[:40]}\n"
                             f"  > \"{line_text}\" ({src} {turn['id']})")
        (self.root / "docs/project/sources/dossier.md").write_text(
            "# Dossier: lists\nStatus: exploring\nSources: " + ", ".join(ids.values()) + "\n\n## Where it stands\nAs the "
            "documents say.\n\n## Units\n" + "\n".join(units) + "\n")
        return ids

    def complete(self, doc_status="read"):
        d = self.root / "docs/project/research/adoption"
        ids = self.import_documents() if doc_status == "read" else {}
        ledger = (d / "coverage.md").read_text()
        for doc in ("README.md", "docs/architecture.md"):
            ledger = re.sub(rf"\| ({re.escape(doc)}) \| doc \| (\d+) \| todo \| \|",
                            lambda m: f"| {m.group(1)} | doc | {m.group(2)} | {doc_status} | {ids.get(doc, '')} |", ledger)
        ledger = ledger.replace("| slices.md | legacy-record | 2 | todo |", "| slices.md | legacy-record | 2 | superseded (milestones.md) |")
        ledger = ledger.replace("| todo |", "| read |")
        (d / "coverage.md").write_text(ledger)
        rec = self.root / "docs/project"
        (rec / "intent.md").write_text("# Intent\nStatus: draft\n## Done examples\n"
                                       "- I-D1 Adding an item keeps it. Example: add a → [a] [code src/app.py:1]\n")
        for f in ("brief.md", "interfaces.md", "decisions.md", "state.md", "gate.md"):
            (rec / f).write_text(f"# {f}\n")
        (rec / "milestones.md").write_text("# Milestones\n## M0 · As found\nStatus: gate\n")
        (self.root / "AGENTS.md").write_text("# Map\n\n## Commands\ntest: python3 -m pytest -q tests\nbuild: true\n")
        (self.root / "slices.md").write_text("> SUPERSEDED 2026-09-27: replaced by docs/project/milestones.md\n# Slices\n")

    def test_complete_adoption_passes(self):
        self.adopt("inventory")
        self.complete()
        self.adopt("commands")
        results = json.loads((self.root / ".evidence/adoption/commands.json").read_text())
        self.assertIn(results["build"]["status"], ("PASS", "FAIL"))
        out = self.adopt("check")
        self.assertEqual(out.returncode, 0, out.stdout)

    def test_missing_m0_fails(self):
        self.adopt("inventory")
        self.complete()
        self.adopt("commands")
        (self.root / "docs/project/milestones.md").write_text("# Milestones\n## M1 · Next\nStatus: planned\n")
        self.assertIn("no M0", self.adopt("check").stdout)

    def test_documents_cannot_be_skimmed(self):
        self.adopt("inventory")
        self.complete(doc_status="outlined (long)")
        self.adopt("commands")
        out = self.adopt("check")
        self.assertEqual(out.returncode, 1)
        self.assertIn("a document must be read", out.stdout)

    def test_a_removed_ledger_row_or_an_uncited_read_fails(self):
        self.adopt("inventory")
        self.complete()
        self.adopt("commands")
        self.assertEqual(self.adopt("check").returncode, 0)
        ledger = self.root / "docs/project/research/adoption/coverage.md"
        text = ledger.read_text()
        ledger.write_text("\n".join(l for l in text.splitlines() if not l.startswith("| src/export.py |")) + "\n")
        out = self.adopt("check")
        self.assertIn("src/export.py: in the inventory but has no ledger row", out.stdout)
        ledger.write_text(re.sub(r"(\| README\.md \| doc \| \d+ \| read \|) SRC-\d+ \|", r"\1 |", text))
        self.assertIn("README.md: marked read, but its note cites no imported source", self.adopt("check").stdout)

    def test_unlabeled_reconstruction_and_unmarked_legacy_fail(self):
        self.adopt("inventory")
        self.complete()
        self.adopt("commands")
        (self.root / "docs/project/intent.md").write_text("# Intent\n## Done examples\n- I-D1 Adding keeps it. Example: a → [a]\n")
        (self.root / "slices.md").write_text("# Slices\n")
        out = self.adopt("check")
        self.assertIn("without an evidence label", out.stdout)
        self.assertIn("not marked", out.stdout)


if __name__ == "__main__":
    unittest.main()
