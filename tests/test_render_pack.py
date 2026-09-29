"""Tests for render_pack.py: each role's pack holds exactly its inputs, and missing inputs are named."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RP = ROOT / "skills/_shared/scripts/render_pack.py"
BASELINE = ROOT / "skills/_shared/scripts/baseline.py"

INTENT = """# Intent
Status: draft
## Goal
Families never lose a shared grocery list between two phones.
## Identity and promise
The list you trust.
## Who
Persona (blind): an adult who uses a smartphone every day.
Parents who shop for a household and hate duplicate lists.
## Load-bearing behavior
Sync within five seconds.
## Done examples
- I-D1 When one phone adds milk, the other shows it within 5 seconds. Example: add "milk" → visible on phone B
- I-D2 If the network drops, edits queue and sync later. Example: airplane mode → edit kept
## Mechanism cards
### Sync
Purpose: both phones see the same list
Observable guarantee: an edit on A appears on B
Rejected imitation: polling a shared JSON file every minute
Discriminating probe: two edits within one second on different phones both survive
### Undo
Purpose: mistakes are cheap
Rejected imitation: a confirm dialog
## Must not lose
- L-01 Deleting a list deletes it on both phones · check: delete on A, B shows it gone
- L-02 The list feels calm · not code-checkable (owner judges)
## Re-freeze log
"""
MILESTONES = """# Milestones
## M1 · Shared list
Status: building
Promise: Two phones share one list.
Carries: I-D1
Mechanisms: Sync
Demo ending:
1. Add milk on A → it shows on B
Done examples:
- M1.D1 When A adds an item, B shows it. Example: milk → milk
Readiness: built [ ] · gate-passed [ ] · accepted [ ] · released [ ] · live-verified [ ]

## M0 · Sign in
Status: accepted
Promise: A person signs in.
Carries: none
Mechanisms: none
Demo ending:
1. Open the app → the sign-in screen shows
Done examples:
- M0.D1 x. Example: y

## M2 · Offline
Status: planned
Promise: Offline edits sync later.
Carries: I-D2
Mechanisms: none
"""
AGENTS = ("# Map\n\n## Commands\ninstall: pip install -e .\nrun: python3 -m app\ntest: python3 -m unittest\n\n"
          "## Conventions\nFamilies never lose lists here.\n")
GATE = "Stack pack: python\n"
DECISIONS = "# Decisions\n## D-004 · 2026-09-27 · demo data\n[placeholder-consent: src/seed.py seeded demo lists owner 2026-09-27]\n"
STATE = "# State\n## Understanding\nM1 makes two phones show the same list; deleting must reach both.\n"


def project(d):
    root = Path(d)
    docs = root / "docs/project"
    docs.mkdir(parents=True)
    for name, text in {"intent.md": INTENT, "milestones.md": MILESTONES, "decisions.md": DECISIONS,
                       "state.md": STATE, "gate.md": GATE,
                       "interfaces.md": "# Interfaces\n## Ports\n### ListStore\n"}.items():
        (docs / name).write_text(text)
    (root / "AGENTS.md").write_text(AGENTS)
    (root / "app.py").write_text("x = 1\n")
    return root


def render(root, role, *args):
    out = root / "pack.md"
    if out.exists():
        out.unlink()
    r = subprocess.run([sys.executable, str(RP), role, "--project", str(root), "--out", str(out), *args],
                       capture_output=True, text=True)
    return r.returncode, (out.read_text() if out.exists() else r.stderr)


class RenderPackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = project(self.tmp.name)
        subprocess.run([sys.executable, str(BASELINE), "record", str(self.root), "M1"], capture_output=True, check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_code_verifier_pack(self):
        code, text = render(self.root, "code-verifier", "--milestone", "M1", "--copy", str(self.root))
        self.assertEqual(code, 0, text)
        self.assertIn("## M1 · Shared list", text)
        self.assertNotIn("## M2 · Offline", text, "only this milestone's contract")
        self.assertIn("I-D1 When one phone adds milk", text)
        self.assertNotIn("I-D2", text, "only carried examples")
        self.assertIn("Rejected imitation: polling", text)
        self.assertNotIn("a confirm dialog", text, "only the cards this milestone names")
        self.assertIn("L-01", text)
        self.assertNotIn("L-02", text, "items the owner judges are not the code checker's")
        self.assertIn("[placeholder-consent: src/seed.py", text)
        self.assertIn("run: python3 -m app", text)
        self.assertNotIn("Families never lose lists here", text, "commands only, not the map's prose")
        self.assertIn("python", text)
        self.assertIn("Pack manifest", text)

    def test_venture_consents_from_position_md(self):
        (self.root / "truth").mkdir()
        (self.root / "truth/position.md").write_text(
            "2026-09-27 · N6 build · stand-in ruled · [placeholder-consent: src/feed.py canned-feed owner 2026-09-27]\n"
            "2026-09-27 · N5 design · pass\n")
        code, text = render(self.root, "code-verifier", "--milestone", "M1", "--copy", str(self.root))
        self.assertEqual(code, 0, text)
        self.assertIn("truth/position.md: 2026-09-27 · N6 build · stand-in ruled · [placeholder-consent: src/feed.py", text)
        self.assertIn("docs/project/decisions.md: [placeholder-consent: src/seed.py", text)
        self.assertNotIn("N5 design", text, "only consent lines leave position.md")

    def test_demo_mode_carries_regressions(self):
        code, text = render(self.root, "code-verifier", "--milestone", "M1", "--mode", "demo")
        self.assertEqual(code, 0, text)
        self.assertIn("Add milk on A", text)
        self.assertIn("### M0", text, "accepted milestones' demos run again")
        self.assertNotIn("Offline", text)
        self.assertNotIn("Rejected imitation", text)

    def test_loyal_pass_one_holds_no_goal(self):
        code, text = render(self.root, "loyal-evaluator", "--pass", "1")
        self.assertEqual(code, 0, text)
        self.assertIn("an adult who uses a smartphone every day", text)
        for leak in ("grocery", "lose", "Mechanism", "milk", "L-01", "Shared list", "household", "Families"):
            self.assertNotIn(leak, text, f"pass 1 must not carry intent: {leak}")

    def test_loyal_pass_two_holds_only_the_goal(self):
        code, text = render(self.root, "loyal-evaluator", "--pass", "2")
        self.assertIn("Families never lose a shared grocery list", text)
        self.assertNotIn("Rejected imitation", text)
        self.assertNotIn("M1.D1", text)

    def test_gate_judge_pack(self):
        (self.root / "results.md").write_text("code-verifier: FAIL M1-F01\n")
        code, text = render(self.root, "gate-judge", "--milestone", "M1", "--inputs", str(self.root / "results.md"))
        self.assertEqual(code, 0, text)
        self.assertIn("M1-F01", text)
        self.assertIn("deleting must reach both", text)
        self.assertIn("Intent (re-freezes applied)", text)
        code, text = render(self.root, "gate-judge", "--milestone", "M1", "--round", "2",
                            "--inputs", str(self.root / "results.md"))
        self.assertEqual(code, 1, "round 2 needs the findings ledger")
        self.assertIn("M1.findings.json", text)
        code, text = render(self.root, "gate-judge", "--milestone", "M1", "--round", "2", "--intent-only",
                            "--inputs", str(self.root / "results.md"))
        self.assertEqual(code, 0, "a second standalone intent check has no gate ledger to require: " + text[-300:])
        self.assertNotIn("NOT PROVIDED", text)

    def test_cold_reader_understanding_and_fidelity(self):
        code, text = render(self.root, "cold-reader", "--milestone", "M1", "--inputs", "understanding")
        self.assertEqual(code, 0, text)
        self.assertIn("The builder's restatement", text)
        self.assertIn("L-01", text)
        src = self.root / "docs/project/sources"
        (src / "s1").mkdir(parents=True)
        (src / "s1/transcript.md").write_text("### T001 · owner\nI want a list app\n")
        (src / "dossier.md").write_text("# Dossier\n- S-001 a list app · owner · SRC-1 T001\n")
        code, text = render(self.root, "cold-reader", "--mode", "fidelity", "--docs", "docs/project/sources/s1/transcript.md")
        self.assertEqual(code, 0, text)
        self.assertIn("I want a list app", text)
        self.assertIn("S-001", text)

    def test_an_audit_sees_the_units_citing_its_transcripts_and_the_previous_read(self):
        src = self.root / "docs/project/sources"
        for n in (1, 2):
            (src / f"SRC-{n}-x").mkdir(parents=True)
            (src / f"SRC-{n}-x/transcript.md").write_text(f"### T001 · owner\nsource {n}\n")
        (src / "dossier.md").write_text(
            "# Dossier\n\n## Where it stands\nA shared list, deletions syncing.\n\n## Units\n"
            "- S-001 · product · owner · current · SRC-1 T001\n  first\n  > \"source 1\" (SRC-1 T001)\n"
            "- S-002 · product · owner · current · SRC-2 T001\n  second\n  > \"source 2\" (SRC-2 T001)\n"
            "- S-003 · product · owner · current · SRC-2 T001; SRC-1 T001\n  both\n\n## No-content turns\n")
        prev = self.root / "audit-1.md"
        prev.write_text("material: the photo was dropped")
        code, text = render(self.root, "cold-reader", "--mode", "fidelity", "--docs",
                            "docs/project/sources/SRC-1-x/transcript.md", "--previous", str(prev))
        self.assertEqual(code, 0, text)
        self.assertIn("A shared list, deletions syncing.", text)
        self.assertIn("S-001", text)
        self.assertIn("S-003", text)
        self.assertNotIn("S-002", text, "a unit about another source is not paid for in this audit")
        self.assertIn("the photo was dropped", text, "a re-audit settles the previous read's material items")

    def test_documents_read_carries_what_the_documents_refer_to(self):
        docs = ("--docs", "docs/project/intent.md", "--docs", "docs/project/milestones.md")
        code, text = render(self.root, "cold-reader", *docs)
        self.assertIn("Glossary of the record's own terms", text)
        self.assertNotIn("ListStore", text, "without --with-record the documents stand alone (a handoff note)")
        prev = self.root / "first-read.md"
        prev.write_text("divergence: which phone wins a conflict")
        code, text = render(self.root, "cold-reader", *docs, "--with-record", "--previous", str(prev))
        self.assertEqual(code, 0, text)
        context = text.split("## Context: files the documents refer to", 1)[1].split("\n## ", 1)[0]
        for held in ("###### ListStore", "D-004", "install: pip install -e ."):
            self.assertIn(held, context)
        self.assertNotIn("### docs/project/intent.md", context, "a document under review is not repeated as context")
        self.assertIn("which phone wins a conflict", text)

    def test_extraction_mode_carries_the_sources_and_never_the_dossier(self):
        src = self.root / "docs/project/sources/SRC-1-notes"
        src.mkdir(parents=True)
        (src / "transcript.md").write_text("### T001 · document\nDeletes reach both phones.\n")
        (self.root / "docs/project/sources/dossier.md").write_text("# Dossier\n- S-001 the summary itself\n")
        code, text = render(self.root, "cold-reader", "--mode", "extract", "--docs",
                            "docs/project/sources/SRC-1-notes/transcript.md")
        self.assertEqual(code, 0, text)
        self.assertIn("Cold read, extraction mode", text)
        self.assertIn("Deletes reach both phones", text)
        self.assertNotIn("the summary itself", text, "an extraction that saw the dossier would only confirm it")

    def test_an_intent_check_tells_the_judge_what_it_is(self):
        (self.root / "docs/project/state.md").write_text("# State\n")
        code, text = render(self.root, "gate-judge", "--milestone", "M1", "--intent-only")
        self.assertIn("What this check is", text)
        self.assertIn("absence is not a gap", text)
        self.assertNotIn("NOT PROVIDED: state.md Understanding", text, "an adoption has no builder's Understanding yet")
        code, text = render(self.root, "gate-judge", "--milestone", "M1")
        self.assertNotIn("What this check is", text)
        self.assertIn("NOT PROVIDED: state.md Understanding", text, "a milestone gate still requires it")

    def test_pass_three_lists_every_item_to_confirm(self):
        code, text = render(self.root, "loyal-evaluator", "--pass", "3", "--milestone", "M1")
        self.assertEqual(code, 0, text)
        for item in ("I-D1", "I-D2", "M1.D1", "L-01", "L-02", "MECH-Sync: two edits within one second"):
            self.assertIn(item, text)
        self.assertIn("MECH-Undo: (no probe written)", text, "a card with no probe is named, not dropped")

    def test_missing_input_is_named_not_guessed(self):
        (self.root / "docs/project/intent.md").unlink()
        code, text = render(self.root, "code-verifier", "--milestone", "M1")
        self.assertEqual(code, 1)
        self.assertIn("NOT PROVIDED", text)

    def test_change_since_baseline_has_real_diffs(self):
        (self.root / "app.py").write_text("x = 2\n")
        (self.root / "new.py").write_text("y = 1\n")
        code, text = render(self.root, "code-verifier", "--milestone", "M1")
        self.assertIn("modified  app.py", text)
        self.assertIn("added     new.py", text)
        self.assertIn("-x = 1", text)
        self.assertIn("+x = 2", text)

    def test_final_milestone_gets_whole_product_checks(self):
        code, text = render(self.root, "code-verifier", "--milestone", "M1")
        self.assertNotIn("Whole-product checks", text, "M2 is still planned after M1")
        subprocess.run([sys.executable, str(BASELINE), "record", str(self.root), "M2"], capture_output=True)
        code, text = render(self.root, "code-verifier", "--milestone", "M2")
        self.assertIn("Whole-product checks", text)
        self.assertIn("simplified-stand-in", text)

    def test_missing_baseline_is_named(self):
        code, text = render(self.root, "code-verifier", "--milestone", "M2")
        self.assertEqual(code, 1)
        self.assertIn("baseline-M2", text)

    def test_baseline_records_once(self):
        r = subprocess.run([sys.executable, str(BASELINE), "record", str(self.root), "M1"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, "a milestone starts once")


if __name__ == "__main__":
    unittest.main()
