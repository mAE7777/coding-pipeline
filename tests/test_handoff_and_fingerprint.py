"""Tests for fingerprint.py and handoff_check.py."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/_shared/scripts"
FP = SCRIPTS / "fingerprint.py"
HC = SCRIPTS / "handoff_check.py"

BRIEF = """# Brief
## Constraints
| ID | Rule | Reason | Source | Scope | Change trigger | Status |
|---|---|---|---|---|---|---|
| C-01 | Data stays on device | privacy promise | [owner 2026-09-27] | all | owner ruling | active |
| C-02 | Old sync API | legacy | [owner 2026-09-01] | sync | replaced by C-03 | superseded by C-03 |
| C-03 | No network calls in M1 | offline first | [owner 2026-09-27] | M1 | owner ruling | active |
"""
INTENT = """# Intent
## Must not lose
- L-01 Deleting a list deletes it everywhere
- L-02 No account required
"""
STATE = """# State
## Open
- [ ] wire the export button
- [x] write the store
- [ ] add the empty state
"""


def fp(d, scope="product"):
    return subprocess.run([sys.executable, str(FP), d, "--scope", scope],
                          capture_output=True, text=True, check=True).stdout.strip()


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def project(d):
    docs = Path(d) / "docs/project"
    docs.mkdir(parents=True)
    (docs / "brief.md").write_text(BRIEF)
    (docs / "intent.md").write_text(INTENT)
    (docs / "state.md").write_text(STATE)
    (Path(d) / "app.py").write_text("print('hi')\n")
    (Path(d) / ".evidence").mkdir(exist_ok=True)
    (Path(d) / ".evidence/store.log").write_text("ok\n")
    return docs


def packet(d, **over):
    docs = Path(d) / "docs/project"
    parts = {
        "Authority": "May: build M1\nMay not: deploy",
        "Read list": "\n".join(f"- docs/project/{n} · sha256 {sha(docs / n)}"
                               for n in ("brief.md", "intent.md", "state.md")),
        "Candidate": fp(d),
        "Done": "- store written · evidence: .evidence/store.log",
        "Open": "- [ ] wire the export button\n- [ ] add the empty state",
        "In flight": "none",
        "Blockers": "none",
        "Failures": "none",
        "Carried forward": "none",
        "Constraint IDs": "C-01, C-03",
        "Must-not-lose IDs": "L-01, L-02",
        "Next step": "wire the export button",
        "Hand back": "state.md updated and a checkpoint note",
    }
    parts.update(over)
    body = "# Handoff\n\n" + "\n\n".join(f"## {k}\n{v}" for k, v in parts.items()) + "\n"
    p = Path(d) / "docs/project/handoffs/packet.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


class HandoffCarriedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        project(self.d)

    def tearDown(self):
        self.tmp.cleanup()

    def test_code_angle_brackets_are_not_placeholders(self):
        code, out = check(self.d, packet(self.d, **{"Next step": "type the store as Map<string, List> and wire it"}))
        self.assertNotIn("placeholder", out)
        code, out = check(self.d, packet(self.d, **{"Next step": "<the exact next action>"}))
        self.assertIn("placeholder", out)

    def test_parked_and_findings_must_be_carried(self):
        docs = Path(self.d) / "docs/project"
        (docs / "milestones.md").write_text("## M1 · x\nParked:\n- src/share/ · purpose: sharing · re-enable: second persona · owner: M3\n")
        (docs / "reviews").mkdir()
        (docs / "reviews/M1.findings.json").write_text(json.dumps({"M1-F04": {"summary": "slow list", "status": "logged"}}))
        code, out = check(self.d, packet(self.d))
        self.assertEqual(code, 1)
        self.assertIn("src/share/", out)
        self.assertIn("M1-F04", out)
        code, out = check(self.d, packet(self.d, **{"Carried forward": "- src/share/ parked · from: M1 parked\n- M1-F04 slow list · from: gate finding"}))
        self.assertNotIn("not carried forward", out)

    def test_missing_evidence_fails(self):
        code, out = check(self.d, packet(self.d, **{"Done": "- store written · evidence: .evidence/nope.log"}))
        self.assertEqual(code, 1)
        self.assertIn("nope.log", out)


def check(d, p):
    out = subprocess.run([sys.executable, str(HC), str(p), "--project", d], capture_output=True, text=True)
    return out.returncode, out.stdout + out.stderr


class FingerprintTest(unittest.TestCase):
    def test_stable_and_sensitive(self):
        with tempfile.TemporaryDirectory() as d:
            project(d)
            a, b = fp(d), fp(d)
            self.assertEqual(a, b)
            (Path(d) / "app.py").write_text("print('changed')\n")
            self.assertNotEqual(a, fp(d))

    def test_planning_docs_do_not_change_product_scope(self):
        with tempfile.TemporaryDirectory() as d:
            docs = project(d)
            before_product, before_all = fp(d), fp(d, "all")
            (docs / "brief.md").write_text(BRIEF + "\nextra\n")
            self.assertEqual(before_product, fp(d))
            self.assertNotEqual(before_all, fp(d, "all"))

    def test_git_untracked_contents_count(self):
        with tempfile.TemporaryDirectory() as d:
            project(d)
            subprocess.run(["git", "init", "-q", d], check=True)
            subprocess.run(["git", "-C", d, "add", "app.py"], check=True)
            subprocess.run(["git", "-C", d, "-c", "user.email=t@t", "-c", "user.name=t",
                            "commit", "-q", "-m", "init"], check=True)
            (Path(d) / "new.py").write_text("x = 1\n")
            a = fp(d)
            (Path(d) / "new.py").write_text("x = 2\n")
            self.assertNotEqual(a, fp(d), "untracked file content change must change the fingerprint")

    def test_browser_tool_output_does_not_count(self):
        with tempfile.TemporaryDirectory() as d:
            project(d)
            subprocess.run(["git", "init", "-q", d], check=True)
            a = fp(d)
            for folder in (".playwright-cli", "test-results", "web/playwright-report"):
                (Path(d) / folder).mkdir(parents=True)
                (Path(d) / folder / "page.yml").write_text("- snapshot\n")
            self.assertEqual(a, fp(d), "looking at the product must not change its fingerprint")

    def test_binary_file(self):
        with tempfile.TemporaryDirectory() as d:
            project(d)
            (Path(d) / "img.bin").write_bytes(bytes(range(256)))
            a = fp(d)
            (Path(d) / "img.bin").write_bytes(bytes(range(255)) + b"\x00")
            self.assertNotEqual(a, fp(d))


    def test_rename_and_chmod_change_it(self):
        with tempfile.TemporaryDirectory() as d:
            project(d)
            a = fp(d)
            (Path(d) / "app.py").rename(Path(d) / "main.py")
            b = fp(d)
            self.assertNotEqual(a, b, "a rename changes the fingerprint")
            (Path(d) / "main.py").chmod(0o755)
            self.assertNotEqual(b, fp(d), "making a file executable changes the fingerprint")


class HandoffCheckTest(unittest.TestCase):
    def test_complete_packet_passes(self):
        with tempfile.TemporaryDirectory() as d:
            project(d)
            code, out = check(d, packet(d))
            self.assertEqual(code, 0, out)

    def test_dropped_constraint_fails(self):
        with tempfile.TemporaryDirectory() as d:
            project(d)
            code, out = check(d, packet(d, **{"Constraint IDs": "C-01"}))
            self.assertEqual(code, 1, out)
            self.assertIn("C-03", out)

    def test_superseded_constraint_not_required(self):
        with tempfile.TemporaryDirectory() as d:
            project(d)
            code, out = check(d, packet(d))
            self.assertNotIn("C-02", out)

    def test_dropped_must_not_lose_fails(self):
        with tempfile.TemporaryDirectory() as d:
            project(d)
            code, out = check(d, packet(d, **{"Must-not-lose IDs": "L-01"}))
            self.assertEqual(code, 1, out)
            self.assertIn("L-02", out)

    def test_dropped_open_item_fails(self):
        with tempfile.TemporaryDirectory() as d:
            project(d)
            code, out = check(d, packet(d, Open="- [ ] wire the export button"))
            self.assertEqual(code, 1, out)
            self.assertIn("add the empty state", out)

    def test_stale_fingerprint_fails(self):
        with tempfile.TemporaryDirectory() as d:
            project(d)
            p = packet(d)
            (Path(d) / "app.py").write_text("print('moved on')\n")
            code, out = check(d, p)
            self.assertEqual(code, 1, out)
            self.assertIn("candidate", out)

    def test_changed_read_list_file_fails(self):
        with tempfile.TemporaryDirectory() as d:
            docs = project(d)
            p = packet(d)
            (docs / "intent.md").write_text(INTENT + "- L-03 new\n")
            code, out = check(d, p)
            self.assertEqual(code, 1, out)
            self.assertIn("changed since", out)

    def test_tbd_fails(self):
        with tempfile.TemporaryDirectory() as d:
            project(d)
            code, out = check(d, packet(d, **{"Next step": "TBD"}))
            self.assertEqual(code, 1, out)
            self.assertIn("placeholder", out)

    def test_ordinary_content_is_not_a_placeholder(self):
        with tempfile.TemporaryDirectory() as d:
            project(d)
            (Path(d) / ".evidence").mkdir(exist_ok=True)
            (Path(d) / ".evidence/parser.log").write_text("ok\n")
            pk = packet(d, **{"Open": "- [ ] remove the TODO in parser.py", "Done": "- parser · evidence: `.evidence/parser.log`."})
            code, out = check(d, pk)
            self.assertNotIn("placeholder", out)
            self.assertNotIn("does not exist", out)
            code, out = check(d, packet(d, **{"Open": "- TODO"}))
            self.assertIn("placeholder", out, "a bare TODO line is still an unfilled section")

    def test_missing_section_fails(self):
        with tempfile.TemporaryDirectory() as d:
            project(d)
            p = packet(d)
            p.write_text(p.read_text().replace("## Hand back", "## Something else"))
            code, out = check(d, p)
            self.assertEqual(code, 1, out)
            self.assertIn("Hand back", out)


if __name__ == "__main__":
    unittest.main()
