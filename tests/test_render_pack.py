"""Tests for render_pack.py: each role's pack holds exactly its inputs, and missing inputs are named."""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RP = ROOT / "skills/_shared/scripts/render_pack.py"
BASELINE = ROOT / "skills/_shared/scripts/baseline.py"
sys.path.insert(0, str(RP.parent))
from render_pack import DIFF_BUDGET  # noqa: E402

DOT = "\u00b7"

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
    root = Path(d) / "project"  # the pack goes to a folder beside it (render): never inside a copy under review
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
    out = root.parent / "out/pack.md"
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


def section_of(text, heading):
    """The body of the pack's '## heading' section, or None."""
    marker = f"\n## {heading}\n"
    if marker not in text:
        return None
    return text.split(marker, 1)[1].split("\n## ", 1)[0]


def run_pack(root, out, *args):
    r = subprocess.run([sys.executable, str(RP), "code-verifier", "--project", str(root), "--out", str(out), *args],
                       capture_output=True, text=True)
    return r.returncode, (out.read_text() if out.exists() else r.stderr)


WIRED = ("Interfaces: ListStore (src/zz_store.py)\n\nWiring:\n"
         "| Component | Producer / trigger | Consumer | Visible effect | Failure state | Test | Status |\n"
         "|---|---|---|---|---|---|---|\n"
         "| Sync | add on A | zz_push.py | B shows it | banner | tests/test_zz_sync.py | built |\n\n")


class ReviewChangeTest(unittest.TestCase):
    """Review mode: every changed file listed, hunks within the budget, the full patch beside the pack."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = project(self.tmp.name)
        ms = self.root / "docs/project/milestones.md"
        ms.write_text(MILESTONES.replace("Readiness:", WIRED + "Readiness:", 1))
        subprocess.run([sys.executable, str(BASELINE), "record", str(self.root), "M1"], capture_output=True, check=True)
        self.ev = self.root.parent / "ev"
        self.out = self.ev / "code-verifier.pack.md"
        self.patch = self.ev / "code-verifier.change.patch"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, files):
        for rel, text in files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            (p.write_bytes if isinstance(text, bytes) else p.write_text)(text)

    def test_a_large_change_is_listed_whole_inlined_within_the_budget_and_patched_in_full(self):
        big = {f"src/aa_code{i}.py": "".join(f"value_{i}_{j} = {j}  # filler to make the hunk large\n"
                                             for j in range(150)) for i in range(8)}
        self.write({**big, "app.py": "x = 2\n",
                    "src/zz_store.py": "class ListStore:\n    pass\n",
                    "src/zz_push.py": "def push(item):\n    return item\n",
                    "tests/test_zz_sync.py": "def test_sync():\n    assert True\n",
                    "tests/test_other.py": "def test_other():\n    assert True\n",
                    "package-lock.json": '{"lockfile-marker": true}\n',
                    "web/bundle.min.js": "var generatedMarker=1;\n",
                    "img.png": b"\x89PNG\r\n\x1a\n\0\0binary"})
        code, text = run_pack(self.root, self.out, "--milestone", "M1")
        self.assertEqual(code, 0, text)
        change = section_of(text, "Change since the milestone started")
        table = change.split("```diff", 1)[0]
        for rel in [*big, "app.py", "src/zz_store.py", "src/zz_push.py", "tests/test_zz_sync.py",
                    "tests/test_other.py", "package-lock.json", "web/bundle.min.js", "img.png"]:
            self.assertIn(rel, table, f"every changed file is listed: {rel}")
        inlined = re.search(r"^```diff\n(.*?)^```$", change, flags=re.M | re.S).group(1)
        patch = self.patch.read_text()
        largest_hunk = max(len(h.encode()) for h in re.split(r"(?m)^(?=@@ )", patch))
        self.assertLessEqual(len(inlined.encode()), DIFF_BUDGET + largest_hunk, "the inlined hunks keep to the budget")
        self.assertGreater(len(patch.encode()), DIFF_BUDGET, "the change is larger than the budget")
        heads = re.findall(r"^\+\+\+ b/(\S+)", inlined, flags=re.M)
        self.assertEqual(heads[:3], ["src/zz_push.py", "src/zz_store.py", "tests/test_zz_sync.py"],
                         "the files the Wiring table and Interfaces line name come first, code before tests")
        self.assertEqual(heads[3], "app.py", "then other code")
        self.assertRegex(table, r"src/aa_code\d\.py .*not inlined: read it in the full patch")
        self.assertRegex(table, r"package-lock\.json .*lockfile +listed only \(lockfile\)")
        self.assertRegex(table, r"web/bundle\.min\.js .*generated +listed only \(generated\)")
        self.assertRegex(table, r"img\.png .*binary +listed only \(binary\)")
        self.assertNotIn("lockfile-marker", text, "a lockfile is listed, never inlined")
        self.assertNotIn("generatedMarker", text)
        self.assertIn(f"The full patch: {self.patch.resolve()}. Read it with the Read tool; it is outside the copy "
                      "under review.", change)
        for rel, body in big.items():
            self.assertIn(f"+++ b/{rel}", patch)
            self.assertIn("".join(f"+{line}\n" for line in body.splitlines()), patch, f"{rel} is whole in the patch")
        self.assertIn('+{"lockfile-marker": true}', patch, "the full patch has every text file")
        self.assertIn("Binary files /dev/null and b/img.png differ", patch)
        sha = hashlib.sha256(self.patch.read_bytes()).hexdigest()
        self.assertIn(f"- {self.patch.resolve()} {DOT} sha256 {sha}", text, "the patch is in the manifest")

    def test_the_patch_never_lands_inside_the_copy(self):
        self.write({"app.py": "x = 2\n"})
        copy = self.ev
        code, text = run_pack(self.root, self.out, "--milestone", "M1", "--copy", str(copy))
        self.assertEqual(code, 2, text)
        self.assertIn("inside the copy under review", text)
        self.assertFalse(self.patch.exists())

    def test_no_change_leaves_no_patch_and_clears_a_stale_one(self):
        self.ev.mkdir(parents=True)
        self.patch.write_text("--- a/old\n+++ b/old\n")
        code, text = run_pack(self.root, self.out, "--milestone", "M1")
        self.assertEqual(code, 0, text)
        self.assertIn("no product file changed", text)
        self.assertFalse(self.patch.exists(), "a patch from an earlier render is never read as this change")

    def test_layer1_results_are_rendered_and_a_missing_file_is_named(self):
        layer1 = self.ev / "layer1.json"
        self.ev.mkdir(parents=True)
        layer1.write_text(json.dumps({
            "status": "PASS", "extra": {"tolerated": True},
            "checks": [{"name": "gate.sh", "status": "PASS", "exit": 0, "log": "/x/layer1-gate-sh.log"},
                       {"name": "test suite", "status": "SKIP", "exit": 0, "log": "/x/l.log",
                        "reason": "no 'test:' line in AGENTS.md Commands", "seconds": 3}],
            "for_reviewer": [{"milestone": "M0", "id": "M0.C1", "what": "the sign-in probe",
                              "why": "it needs a browser"}]}))
        code, text = run_pack(self.root, self.out, "--milestone", "M1", "--layer1", str(layer1))
        self.assertEqual(code, 0, text)
        body = section_of(text, "Deterministic layer (already run by the gate; do not run these again)")
        self.assertIsNotNone(body, text[:2000])
        self.assertIn("- gate.sh: PASS, exit 0", body)
        self.assertIn("- test suite: SKIP, exit 0 (no 'test:' line in AGENTS.md Commands)", body)
        self.assertIn("### Not run by the gate: check these yourself", body)
        self.assertIn("- M0 M0.C1: the sign-in probe (why the gate did not run it: it needs a browser)", body)
        self.assertNotIn("layer1-gate-sh.log", body, "compact: no log paths the reviewer cannot read")
        self.assertIn(f"{layer1} {DOT} sha256", text)
        code, text = run_pack(self.root, self.out, "--milestone", "M1", "--layer1", str(self.ev / "nope.json"))
        self.assertEqual(code, 1)
        self.assertIn("NOT PROVIDED", section_of(text, "Deterministic layer (already run by the gate; do not run "
                                                       "these again)"))
        code, text = run_pack(self.root, self.out, "--milestone", "M1")
        self.assertNotIn("Deterministic layer", text, "no --layer1, no section")

    def test_the_structure_lens_is_in_review_packs_only_and_stays_small(self):
        code, text = run_pack(self.root, self.out, "--milestone", "M1")
        self.assertEqual(code, 0, text)
        lens = section_of(text, "Structure lens (finding class structure)")
        self.assertIsNotNone(lens)
        self.assertIn("code judo", lens)
        self.assertIn("Comments that stay", lens)
        self.assertIn("MUST KILL", lens)
        size = len(("## Structure lens (finding class structure)\n" + lens).encode())
        self.assertLess(size, 10000, f"the lens section grew to {size} bytes; it is paid for in every review run")
        code, text = run_pack(self.root, self.out, "--milestone", "M1", "--mode", "demo")
        self.assertEqual(code, 0, text)
        self.assertNotIn("Structure lens", text, "the demo checks behavior, not structure")

    def test_a_missing_lens_is_named(self):
        # The scripts installed without skills/code-craft beside them: the lens folder is found from the script's place.
        scripts = self.root.parent / "install/skills/_shared/scripts"
        shutil.copytree(RP.parent, scripts, ignore=shutil.ignore_patterns("__pycache__"))
        r = subprocess.run([sys.executable, "-B", str(scripts / "render_pack.py"), "code-verifier", "--project",
                            str(self.root), "--milestone", "M1", "--out", str(self.out)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stderr)
        lens = section_of(self.out.read_text(), "Structure lens (finding class structure)")
        self.assertIn("NOT PROVIDED: the structure lens", lens)
        self.assertIn("code-craft/review/code-quality-review.md", lens)


SCOPE_DELTA = """diff --git a/src/a.py b/src/a.py
index 1111111..2222222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1,2 +1,2 @@
 def delete(item):
-    local_only(item)
+    sync_delete(item)
diff --git a/tests/test_a.py b/tests/test_a.py
new file mode 100644
--- /dev/null
+++ b/tests/test_a.py
@@ -0,0 +1,3 @@
+def test_delete():
+    -- the line above starts a removed-looking text
+    assert sync_delete
"""


class ReverifyTest(unittest.TestCase):
    """The focused re-verify pack: the open findings, the delta since the earlier candidate, never the whole change."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = project(self.tmp.name)
        subprocess.run([sys.executable, str(BASELINE), "record", str(self.root), "M1"], capture_output=True, check=True)
        (self.root / "app.py").write_text("x = 2\n")  # changed since the baseline; the last full review saw it
        self.ev = self.root.parent / "ev"
        self.ev.mkdir()
        self.out = self.ev / "code-verifier.pack.md"
        self.delta = self.ev / "delta.patch"
        self.delta.write_text(SCOPE_DELTA)
        self.layer1 = self.ev / "layer1.json"
        self.layer1.write_text(json.dumps({"status": "PASS", "checks": [{"name": "gate.sh", "status": "PASS",
                                                                          "exit": 0}]}))

    def tearDown(self):
        self.tmp.cleanup()

    def scope(self, name="scope.json", **over):
        doc = {"scope": "focused", "milestone": "M1", "kind": "changes",
               "since": {"round": 2, "fingerprint": "product:0123456789abcdef", "snapshot": "/nowhere"},
               "changed_files": [{"path": "src/a.py", "status": "modified", "added": 1, "removed": 1},
                                 {"path": "tests/test_a.py", "status": "added", "added": 3, "removed": 0}],
               "changed_lines": 5, "delta_patch": str(self.delta),
               "findings": [{"id": "F-3", "summary": "a delete stays on one phone", "class": "correctness",
                             "severity": "blocking", "files": ["src/a.py"], "where": "src/a.py:2",
                             "fixed_when": "a delete on A is gone on B within 5 seconds"}],
               "fixes": [], "carried": {"loyal-evaluator": "product:0123456789abcdef"},
               "reasons": ["every changed file is named in an open finding or is a test"], "unknown": [1, 2]}
        doc.update(over)
        path = self.ev / name
        path.write_text(json.dumps(doc))
        return path

    def render(self, scope, *more):
        return run_pack(self.root, self.out, "--mode", "reverify", "--milestone", "M1", "--copy",
                        str(self.root.parent / "copy"), "--scope", str(scope), *more)

    def test_findings_and_the_delta_without_the_whole_change(self):
        code, text = self.render(self.scope(), "--layer1", str(self.layer1))
        self.assertEqual(code, 0, text)
        self.assertIn("Re-verify pack: M1", text)
        self.assertIn("Promise: Two phones share one list.", text)
        self.assertIn("I-D1 When one phone adds milk", text)
        self.assertIn("Rejected imitation: polling", text)
        findings = section_of(text, "Findings to re-verify (every finding blocking since the last full round, open "
                                    "or fixed)")
        self.assertIn("- F-3 [correctness, blocking] a delete stays on one phone\n  status: open", findings)
        self.assertIn("fixed when: a delete on A is gone on B within 5 seconds", findings)
        self.assertIn("files: src/a.py", findings)
        delta = section_of(text, "Change since round 2's candidate")
        self.assertIn("+    sync_delete(item)", delta, "the delta is inlined")
        self.assertRegex(delta, r"modified  src/a\.py +\+1 -1 +code +inlined")
        self.assertRegex(delta, r"added     tests/test_a\.py +\+3 -0 +test +inlined")
        self.assertIn("+    -- the line above starts a removed-looking text", delta)
        self.assertNotIn("Change since the milestone started", text, "the last full review covered that")
        self.assertNotIn("x = 1", text, "no hunk of the change since the baseline")
        patch = self.ev / "code-verifier.change.patch"
        self.assertEqual(patch.read_text(), SCOPE_DELTA, "the full delta sits beside the pack")
        self.assertIn(f"The full patch: {patch.resolve()}.", delta)
        self.assertIn("- gate.sh: PASS, exit 0", section_of(text, "Deterministic layer (already run by the gate; do "
                                                                  "not run these again)"))
        self.assertIn("run: python3 -m app", text)
        self.assertIsNotNone(section_of(text, "Structure lens (finding class structure)"))
        self.assertIn(f"{self.ev / 'scope.json'} {DOT} sha256", text)

    def test_a_hotfix_shows_its_fix_log_entries(self):
        scope = self.scope(kind="hotfix", findings=[], fixes=[{
            "id": "F-007", "title": "Delete did not sync", "symptom": "B still shows milk",
            "reproduction": "python3 -m unittest tests.test_a", "change": "BUILDER-ACCOUNT of how it works"}])
        code, text = self.render(scope)
        self.assertEqual(code, 0, text)
        fix = section_of(text, "The fix to re-verify (fix-log entries)")
        self.assertIn("- F-007 Delete did not sync", fix)
        self.assertIn("symptom: B still shows milk", fix)
        self.assertIn("reproduction: python3 -m unittest tests.test_a", fix)
        self.assertNotIn("BUILDER-ACCOUNT", text, "the builder's account of the fix stays out (D8); the delta shows it")

    def test_a_fixed_finding_is_checked_again(self):
        fixed = {"id": "F-2", "status": "fixed", "fixed_round": 3, "summary": "a blank name is accepted",
                 "class": "correctness", "severity": "high", "files": ["src/a.py"], "fixed_when": "a blank name exits 2"}
        scope = self.scope(findings=[{**self.scope_doc_finding(), "status": "open"}, fixed])
        code, text = self.render(scope)
        self.assertEqual(code, 0, text)
        findings = section_of(text, "Findings to re-verify (every finding blocking since the last full round, open "
                                    "or fixed)")
        self.assertIn("- F-2 [correctness, high] a blank name is accepted\n  status: fixed in round 3: check it "
                      "again, a later change can undo a fix", findings)
        self.assertIn("fixed when: a blank name exits 2", findings)

    def scope_doc_finding(self):
        return {"id": "F-3", "summary": "a delete stays on one phone", "class": "correctness", "severity": "blocking",
                "files": ["src/a.py"], "where": "src/a.py:2", "fixed_when": "a delete on A is gone on B within 5 seconds"}

    def test_a_hotfix_reviews_the_change_since_the_accepted_candidate(self):
        hotfix = self.ev / "reverify-delta.patch"
        hotfix.write_text(SCOPE_DELTA.split("diff --git a/tests/test_a.py")[0])
        scope = self.scope(kind="hotfix", fixes=[{"id": "F-007", "title": "Delete did not sync"}], reverify={
            "since": {"round": 4, "fingerprint": "product:fedcba9876543210", "snapshot": "/accepted"},
            "changed_files": [{"path": "src/a.py", "status": "modified", "added": 1, "removed": 1}],
            "changed_lines": 2, "delta_patch": str(hotfix)})
        code, text = self.render(scope)
        self.assertEqual(code, 0, text)
        self.assertIn("Re-verify pack: M1 (focused hotfix, since the accepted candidate of round 4)", text)
        delta = section_of(text, "Change since the accepted candidate (round 4)")
        self.assertIn("1 file(s) changed", delta)
        self.assertNotIn("tests/test_a.py", delta, "the hotfix's own delta, not the whole change since round 2")
        self.assertEqual((self.ev / "code-verifier.change.patch").read_text(), hotfix.read_text())
        self.assertIn("- F-3 [correctness, blocking]", section_of(
            text, "Findings to re-verify (every finding blocking since the last full round, open or fixed)"),
            "a hotfix re-checks the findings since the last full round too")

    def test_a_bad_scope_is_refused(self):
        for scope, why in ((self.scope("full.json", scope="full"), "not 'focused'"),
                           (self.ev / "absent.json", "cannot read"),
                           (self.scope("m2.json", milestone="M2"), "is for M2")):
            code, text = self.render(scope)
            self.assertEqual(code, 2, text)
            self.assertIn(why, text)
        code, text = run_pack(self.root, self.out, "--mode", "reverify", "--milestone", "M1")
        self.assertEqual(code, 2, text)
        self.assertIn("needs --scope", text)

    def test_a_missing_delta_patch_is_named(self):
        code, text = self.render(self.scope(delta_patch=str(self.ev / "gone.patch")))
        self.assertEqual(code, 1, text)
        self.assertIn("NOT PROVIDED: the delta patch", text)
        self.assertFalse((self.ev / "code-verifier.change.patch").exists())


DEMO_MILESTONES = f"""# Milestones
## M1 {DOT} Sign in
Status: accepted
Promise: A person signs in.
Carries: none
Mechanisms: none
Demo ending:
1. Open the app, the sign-in screen shows
Done examples:
- M1.D1 x. Example: y

## M2 {DOT} Lists
Status: changes
Promise: Lists exist.
Carries: none
Mechanisms: none
Demo ending:
1. Make a list, it shows in the sidebar
Done examples:
- M2.D1 x. Example: y
Readiness: built [x] {DOT} gate-passed [x] {DOT} accepted [ ] {DOT} released [ ] {DOT} live-verified [ ]

## M3 {DOT} Share
Status: building
Promise: Share a list.
Carries: none
Mechanisms: none
Demo ending:
1. Share a list, phone B shows it
Done examples:
- M3.D1 x. Example: y

## M4 {DOT} Offline
Status: planned
Promise: Offline edits sync later.
Carries: none
Mechanisms: none
"""


class DemoScopeTest(unittest.TestCase):
    """Demo mode replays an earlier ending only when the current change can reach it (plan 6.3)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = project(self.tmp.name)
        (self.root / "docs/project/milestones.md").write_text(DEMO_MILESTONES)
        (self.root / "src").mkdir()
        for name in ("a", "b", "c", "login"):
            (self.root / f"src/{name}.py").write_text(f"{name} = 1\n")
        subprocess.run([sys.executable, str(BASELINE), "record", str(self.root), "M3"], capture_output=True, check=True)
        reviews = self.root / "docs/project/reviews"
        reviews.mkdir()
        (reviews / "M1.changed.txt").write_text("# M1: files changed since its baseline, at fingerprint product:1\n"
                                                "src/a.py\nsrc/login.py\n")
        (reviews / "M2.changed.txt").write_text("# M2: files changed since its baseline, at fingerprint product:2\n"
                                                "src/b.py\n")
        self.out = self.root.parent / "ev/code-verifier-demo.pack.md"

    def tearDown(self):
        self.tmp.cleanup()

    def demo(self, *flags):
        code, text = run_pack(self.root, self.out, "--milestone", "M3", "--mode", "demo", *flags)
        self.assertEqual(code, 0, text)
        return text

    def record(self):
        return json.loads((self.out.parent / "code-verifier-demo.regression.json").read_text())

    def test_replay_all_replays_every_ending_and_the_record_says_so(self):
        text = self.demo()
        self.assertEqual(self.record(), {"milestone": "M3", "replay_all": False, "all_replayed": False, "replayed": [],
                                         "not_replayed": [
            {"milestone": "M1", "why": "none of its 2 changed files changed since the M3 baseline"},
            {"milestone": "M2", "why": "none of its 1 changed files changed since the M3 baseline"}]})
        text = self.demo("--replay-all")
        for m in ("M1", "M2"):
            self.assertIn(f"### {m}\n(replayed: --replay-all: a release replays every earlier ending)", text)
        self.assertIsNone(section_of(text, "Regression demo endings not replayed"))
        rec = self.record()
        self.assertEqual((rec["replay_all"], rec["all_replayed"], [r["milestone"] for r in rec["replayed"]],
                          rec["not_replayed"]), (True, True, ["M1", "M2"], []))

    def test_an_ending_whose_file_was_renamed_replays(self):
        # M2 renamed M1's src/login.py before M3 started; M3 changes the renamed file, which no list names.
        shutil.rmtree(self.root / ".evidence")
        (self.root / "src/login.py").rename(self.root / "src/signin.py")
        subprocess.run([sys.executable, str(BASELINE), "record", str(self.root), "M3"], capture_output=True, check=True)
        (self.root / "src/signin.py").write_text("login = 2\n")
        text = self.demo()
        self.assertIn("### M1\n(replayed: src/login.py, among its 2 changed files, no longer exists (renamed or "
                      "deleted since), so the link to where its behavior lives is lost)", text)
        self.assertIn("- M2: not replayed", text)

    def test_an_ending_replays_when_the_change_touches_its_files_and_the_rest_are_listed(self):
        (self.root / "src/a.py").write_text("a = 2\n")
        (self.root / "src/c.py").write_text("c = 2\n")
        text = self.demo()
        self.assertIn("Share a list, phone B shows it", text)
        self.assertIn("### M1\n(replayed: src/a.py changed since the M3 baseline and is among its 2 changed files)\n"
                      "1. Open the app", text)
        self.assertNotIn("### M2", text)
        self.assertNotIn("Make a list", text)
        self.assertIn("- M2: not replayed: none of its 1 changed files changed since the M3 baseline",
                      section_of(text, "Regression demo endings not replayed"))
        self.assertNotIn("Offline", text)

    def test_a_missing_list_replays_the_ending(self):
        (self.root / "docs/project/reviews/M2.changed.txt").unlink()
        text = self.demo()
        self.assertIn("### M2\n(replayed: its list of changed files (docs/project/reviews/M2.changed.txt) is "
                      "missing or unreadable)", text)
        self.assertIn("- M1: not replayed: none of its 2 changed files", text, "nothing changed since the baseline")

    def test_a_manifest_change_replays_every_ending(self):
        (self.root / "package.json").write_text('{"dependencies": {}}\n')
        text = self.demo()
        for m in ("M1", "M2"):
            self.assertIn(f"### {m}\n(replayed: the change touches package.json (dependency manifest), which can "
                          "affect every milestone)", text)
        self.assertIsNone(section_of(text, "Regression demo endings not replayed"))

    def test_without_a_baseline_every_ending_replays(self):
        shutil.rmtree(self.root / ".evidence")
        text = self.demo()
        for m in ("M1", "M2"):
            self.assertIn(f"### {m}\n(replayed: the change since the M3 baseline cannot be computed", text)

    def test_the_final_milestone_replays_every_ending(self):
        ms = self.root / "docs/project/milestones.md"
        ms.write_text(DEMO_MILESTONES.replace("Status: planned", "Status: dropped"))
        text = self.demo()
        for m in ("M1", "M2"):
            self.assertIn(f"### {m}\n(replayed: this is the final milestone, which replays every earlier ending)",
                          text)
        self.assertIsNone(section_of(text, "Regression demo endings not replayed"))


if __name__ == "__main__":
    unittest.main()
