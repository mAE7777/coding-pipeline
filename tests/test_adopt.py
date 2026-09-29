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

    def capture(self, *args):
        out = subprocess.run([sys.executable, str(ROOT / "skills/_shared/scripts/capture.py"), *args], capture_output=True,
                             text=True, env=self.env)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return out.stdout

    def read_everything(self):
        """The real flow: the whole inventory and the history become sources; the dossier accounts for every unit (a
        unit per document section, the history read with nothing more to keep, the code mapped); an independent
        extraction and an audit that finds nothing material; every unit lands in the record."""
        self.capture("add", str(self.root), "--inventory")
        self.capture("add", str(self.root), "--git-log")
        sources = self.root / "docs/project/sources"
        units, skip, closure, points, n = [], [], [], [], 0
        for meta_path in sorted(sources.glob("SRC-*/meta.json")):
            meta = json.loads(meta_path.read_text())
            src = meta["id"]
            for line in (meta_path.parent / "turns.jsonl").read_text().splitlines():
                turn = json.loads(line)
                if turn["role"] == "document":
                    n += 1
                    text = turn["text"].strip().splitlines()[-1]
                    units.append(f"- S-{n:03d} · product · document · current · {src} {turn['id']}\n  {text[:40]}\n"
                                 f"  > \"{text}\" ({src} {turn['id']})")
                    closure.append(f"| S-{n:03d} | {text[:20]} | intent (Goal) |")
                    points.append({"refs": [f"{src} {turn['id']}"], "quote": text})
                else:
                    skip.append(f"{src} {turn['id']}")
        (sources / "dossier.md").write_text("# Dossier\n\n## Units\n" + "\n".join(units) + "\n\n## No-content turns\n"
                                            + ", ".join(skip).replace(", SRC", "; SRC") + "\n")
        ex = self.root / ".evidence/capture/extract-1"
        ex.mkdir(parents=True)
        (ex / "cold-reader.pack.md").write_text("".join(f"## Document: docs/project/sources/{m.parent.name}/transcript.md\n"
                                                        for m in sorted(sources.glob("SRC-*/meta.json"))))
        (ex / "cold-reader.result.md").write_text("```json\n" + json.dumps({"points": points}) + "\n```\n")
        self.assertIn("0 not carried", self.capture("reconcile", str(self.root), str(ex / "cold-reader.result.md")))
        au = self.root / ".evidence/capture/audit-1"
        au.mkdir(parents=True)
        (au / "cold-reader.pack.md").write_text((ex / "cold-reader.pack.md").read_text().replace("Document", "Transcript"))
        (au / "cold-reader.result.md").write_text("```json\n" + json.dumps({"fidelity": []}) + "\n```\n")
        self.assertIn("0 material", self.capture("audit", str(self.root), str(au / "cold-reader.result.md")))
        return closure

    def characterize(self, rows=None, discrepancies="", blocking=None):
        """Stand in for gate_run.py --intent-only on M0: a verdict on the current draft and the judge's rows."""
        import hashlib
        d = self.root / ".evidence/loyal/M0/r1"
        d.mkdir(parents=True, exist_ok=True)
        intent = (self.root / "docs/project/intent.md").read_bytes()
        rows = rows or [{"id": "I-D1", "status": "HOLDS"}]
        verdict = "BLOCKED" if blocking else ("ACCEPT-READY" if all(r["status"] == "HOLDS" for r in rows) else "CHANGES")
        (d / "verdict.json").write_text(json.dumps({"verdict": verdict, "intent_sha": hashlib.sha256(intent).hexdigest()}))
        (d / "gate-judge.result.md").write_text("```json\n" + json.dumps({"intent_diff": rows, "blocking": blocking or []})
                                                + "\n```\n")
        if discrepancies:
            with open(self.root / "docs/project/brief.md", "a") as f:
                f.write("\n## Discrepancies\n" + discrepancies + "\n")

    def complete(self, doc_status=None):
        closure = self.read_everything()
        d = self.root / "docs/project/research/adoption"
        ledger = (d / "coverage.md").read_text()
        if doc_status:
            ledger = re.sub(r"\| (README\.md) \| doc \| (\d+) \| captured \|", rf"| \1 | doc | \2 | {doc_status} |", ledger)
        ledger = re.sub(r"\| slices\.md \| legacy-record \| (\d+) \| \w+ \| [^|]* \|",
                        r"| slices.md | legacy-record | \1 | superseded (milestones.md) | |", ledger)
        (d / "coverage.md").write_text(ledger)
        rec = self.root / "docs/project"
        (rec / "intent.md").write_text("# Intent\nStatus: draft\n## Done examples\n"
                                       "- I-D1 Adding an item keeps it. Example: add a → [a] [code src/app.py:1]\n"
                                       "## Must not lose\n- L-01 Items are never dropped [code src/app.py:2]\n")
        for f in ("interfaces.md", "decisions.md", "state.md", "gate.md"):
            (rec / f).write_text(f"# {f}\n")
        (rec / "brief.md").write_text("# Brief\n## Source closure\n| Unit | What | Where it lands |\n|---|---|---|\n"
                                      + "\n".join(closure) + "\n")
        (rec / "milestones.md").write_text("# Milestones\n## M0 · As found\nStatus: gate\n")
        (self.root / "AGENTS.md").write_text("# Map\n\n## Commands\ntest: python3 -m pytest -q tests\nbuild: true\n")
        (self.root / "slices.md").write_text("> SUPERSEDED 2026-09-27: replaced by docs/project/milestones.md\n# Slices\n")
        self.characterize()

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

    def test_documents_and_code_cannot_be_skimmed(self):
        self.adopt("inventory")
        self.complete(doc_status="outlined (long)")
        self.adopt("commands")
        out = self.adopt("check")
        self.assertEqual(out.returncode, 1)
        self.assertIn("a document must be read or captured", out.stdout)
        ledger = self.root / "docs/project/research/adoption/coverage.md"
        text = re.sub(r"\| (src/export\.py) \| code \| (\d+) \| mapped \(code map\) \| [^|]* \|",
                      r"| \1 | code | \2 | outlined (small) | |", ledger.read_text())
        self.assertNotEqual(text, ledger.read_text())
        ledger.write_text(text)
        self.assertIn("code and tests are mapped", self.adopt("check").stdout)

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
        ledger.write_text(re.sub(r"(\| README\.md \| doc \| \d+ \| captured \|) SRC-\d+ \|", r"\1 |", text))
        self.assertIn("README.md: marked captured, but its note cites no imported source", self.adopt("check").stdout)

    def test_history_closure_and_characterization_are_required(self):
        self.adopt("inventory")
        self.complete()
        self.adopt("commands")
        self.assertEqual(self.adopt("check").returncode, 0, self.adopt("check").stdout)
        brief = self.root / "docs/project/brief.md"
        full = brief.read_text()
        brief.write_text(full.rsplit("\n", 2)[0] + "\n")
        self.assertIn("does not land in the record", self.adopt("check").stdout, "a point read but lost fails")
        brief.write_text(full)
        with open(self.root / "docs/project/intent.md", "a") as f:
            f.write("- I-D2 Export joins items. Example: [a,b] → a,b [code src/export.py:2]\n")
        self.assertIn("changed after the latest characterization", self.adopt("check").stdout)
        self.characterize(rows=[{"id": "I-D1", "status": "HOLDS"}, {"id": "EXTRA-1", "status": "EXTRA"}])
        self.assertIn("EXTRA-1 EXTRA, which brief.md's ## Discrepancies does not list", self.adopt("check").stdout)
        self.characterize(rows=[{"id": "I-D1", "status": "HOLDS"}, {"id": "EXTRA-1", "status": "EXTRA"}],
                          discrepancies="- EXTRA-1 the code exports to CSV; no document mentions it · owner (keep it?)")
        self.assertEqual(self.adopt("check").returncode, 0, self.adopt("check").stdout)

    def test_a_repository_without_commits_has_no_history_to_read(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            out = subprocess.run([sys.executable, str(ADOPT), "check", d], capture_output=True, text=True, env=self.env)
            self.assertNotIn("commit history was not read", out.stdout)

    def test_what_only_the_owner_can_settle_goes_on_the_discrepancy_list(self):
        self.adopt("inventory")
        self.complete()
        self.adopt("commands")
        ask = [{"id": "M0-F01", "summary": "delete promises a restore that does not exist", "needs_owner": True}]
        self.characterize(blocking=ask)
        self.assertIn("raised M0-F01", self.adopt("check").stdout)
        self.characterize(blocking=ask, discrepancies="- M0-F01 delete's help promises restore · owner (build it or fix the text?)")
        self.assertEqual(self.adopt("check").returncode, 0, self.adopt("check").stdout)

    def test_the_history_must_be_read(self):
        self.adopt("inventory")
        self.complete()
        self.adopt("commands")
        history = next(m.parent for m in (self.root / "docs/project/sources").glob("SRC-*/meta.json")
                       if json.loads(m.read_text())["kind"] == "git-history")
        meta = json.loads((history / "meta.json").read_text())
        meta["kind"] = "doc"
        (history / "meta.json").write_text(json.dumps(meta))
        self.assertIn("the commit history was not read", self.adopt("check").stdout)

    def test_unlabeled_reconstruction_and_unmarked_legacy_fail(self):
        self.adopt("inventory")
        self.complete()
        self.adopt("commands")
        (self.root / "docs/project/intent.md").write_text("# Intent\n## Done examples\n- I-D1 Adding keeps it. Example: a → [a]\n"
                                                          "## Must not lose\n- L-01 Items are never dropped\n")
        (self.root / "slices.md").write_text("# Slices\n")
        out = self.adopt("check")
        self.assertIn("without an evidence label: - I-D1", out.stdout)
        self.assertIn("without an evidence label: - L-01", out.stdout)
        self.assertIn("not marked", out.stdout)


if __name__ == "__main__":
    unittest.main()
