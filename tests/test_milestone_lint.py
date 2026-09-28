"""Tests for milestone_lint.py: a clean file passes, each planted defect fails."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINT = ROOT / "skills/_shared/scripts/milestone_lint.py"
RULINGS = ROOT / "skills/_shared/scripts/rulings.py"
SID = "77777777-2222-3333-4444-555555555555"

GOOD = """# Milestones

## M1 · Save a list
Status: building
Promise: A signed-in person can save a shopping list and find it again tomorrow.
Carries: I-D1
Mechanisms: none

Demo ending:
1. Sign in as a new user → the empty state offers "Create a list"
2. Create "Groceries" with two items → both items show, in order
3. Reload the page → the list is still there

In scope:
- create, rename, and delete a list

Named non-goals:
- sharing lists (reason: no second persona in this product yet)

Parked:
- none

Done examples:
- M1.D1 When a user saves a list, it survives a reload. Example: "Groceries" with milk, eggs → same list after reload
- M1.D2 If the save fails, the user sees "Not saved, retry". Example: server returns 500 → banner shown, draft kept

Checkpoints:
- M1.C1 storage schema · why here: every screen reads it · check: `pytest tests/test_store.py`

Interfaces: ListStore port (interfaces.md#liststore)

Wiring:
| Component | Producer / trigger | Consumer | Visible effect | Failure state | Test | Status |
|---|---|---|---|---|---|---|
| save route | form submit | ListStore | list shown | banner | tests/test_save.py | built |

AI evals: none

Readiness: built [ ] · gate-passed [ ] · accepted [ ] · released [ ] · live-verified [ ]
Real-use needs: none
"""


def run(text, extra=("--no-history",), cwd=None, name="milestones.md"):
    with tempfile.TemporaryDirectory() as d:
        p = Path(cwd or d) / name
        p.write_text(text, encoding="utf-8")
        out = subprocess.run([sys.executable, str(LINT), str(p), *extra],
                             capture_output=True, text=True)
        return out.returncode, out.stdout + out.stderr


class MilestoneLintTest(unittest.TestCase):
    def test_clean_file_passes(self):
        code, out = run(GOOD)
        self.assertEqual(code, 0, out)
        self.assertIn("PASS", out)

    def test_missing_demo_fails(self):
        bad = GOOD.replace("1. Sign in as a new user", "Sign in as a new user").replace(
            "2. Create", "Create").replace("3. Reload", "Reload")
        code, out = run(bad)
        self.assertEqual(code, 1, out)
        self.assertIn("demo ending", out)

    def test_missing_done_examples_fails(self):
        bad = GOOD.replace("M1.D1", "D1").replace("M1.D2", "D2")
        code, out = run(bad)
        self.assertEqual(code, 1, out)
        self.assertIn("done examples", out)

    def test_later_is_not_a_state(self):
        bad = GOOD.replace("- create, rename, and delete a list", "- create now, sharing later")
        code, out = run(bad)
        self.assertEqual(code, 1, out)
        self.assertIn("not a state", out)

    def test_parked_without_reenable_fails(self):
        bad = GOOD.replace("Parked:\n- none", "Parked:\n- src/share/ · purpose: sharing")
        code, out = run(bad)
        self.assertEqual(code, 1, out)
        self.assertIn("re-enable", out)

    def test_non_goal_without_reason_fails(self):
        bad = GOOD.replace("(reason: no second persona in this product yet)", "")
        code, out = run(bad)
        self.assertEqual(code, 1, out)
        self.assertIn("without a reason", out)

    def test_bad_status_fails(self):
        code, out = run(GOOD.replace("Status: building", "Status: almost"))
        self.assertEqual(code, 1, out)

    def test_duplicate_id_fails(self):
        code, out = run(GOOD + "\n" + GOOD.split("# Milestones\n", 1)[1])
        self.assertEqual(code, 1, out)
        self.assertIn("more than once", out)

    def test_foreign_done_id_fails(self):
        code, out = run(GOOD.replace("M1.D2", "M2.D2"))
        self.assertEqual(code, 1, out)
        self.assertIn("belongs to M2", out)

    CLOSURE = ("\n## Idea-anchor closure\n| Item | What it is | Where it lives |\n|---|---|---|\n"
               "| K1 | text input | IN-MILESTONE @M1 |\n"
               "| K2 | voice input | named non-goal (no audio hardware in scope) |\n"
               "| K3 | payments | contract-blocked @C-07 |\n")

    def test_closure_fourth_bucket_fails(self):
        code, out = run(GOOD + self.CLOSURE.replace("named non-goal (no audio hardware in scope)", "later"))
        self.assertEqual(code, 1, out)
        self.assertIn("K2", out)

    def test_closure_three_buckets_pass(self):
        code, out = run(GOOD + self.CLOSURE)
        self.assertEqual(code, 0, out)

    def test_closure_pointing_at_missing_milestone_fails(self):
        code, out = run(GOOD + self.CLOSURE.replace("IN-MILESTONE @M1", "IN-MILESTONE @M4"))
        self.assertEqual(code, 1, out)
        self.assertIn("M4", out)

    def test_venture_heading_and_anchor_and_parts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "docs/project").mkdir(parents=True)
            (root / "truth").mkdir()
            (root / "truth/idea-anchor.md").write_text("| K1 | a |\n| K2 | b |\n| K3 | c |\n| K4 | d |\n")
            (root / "truth/blueprint.md").write_text("| Node | State |\n|---|---|\n**P9** helm's progress table, not parts\n")
            (root / "blueprint-sync.md").write_text("**P1** sync\n**P2** share\n")
            text = GOOD.replace("Mechanisms: none", "Mechanisms: none\nParts: [P1]") + \
                self.CLOSURE.replace("## Idea-anchor closure", "## idea-anchor reconciliation")
            p = root / "docs/project/milestones.md"
            p.write_text(text)
            out = subprocess.run([sys.executable, str(LINT), str(p), "--no-history"], capture_output=True, text=True)
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("K4 is in the idea anchor", out.stdout)
            self.assertIn("P2 is in the blueprint", out.stdout)
            self.assertNotIn("P9", out.stdout, "truth/blueprint.md is never the composition blueprint")

    def test_anchor_keys_are_the_anchors_own(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "docs/project").mkdir(parents=True)
            (root / "truth").mkdir()
            (root / "truth/idea-anchor.md").write_text(
                "| # | Point |\n|---|---|\n| P1 | fork a life |\n| P2 | daily mail |\n\n"
                "| # | Point |\n|---|---|\n| R-P1 | a stand-in self |\n| R-P10 | divergence is fine |\n")
            closure = ("\n## idea-anchor 对账\n| # | 要点 | State |\n|---|---|---|\n"
                       "| P1 | fork a life | IN-MILESTONE @M1 |\n| P2 | daily mail | named non-goal (not this candidate) |\n"
                       "| R-P1 | a stand-in self | IN-MILESTONE @M1 |\n")
            p = root / "docs/project/milestones.md"
            p.write_text(GOOD + closure)
            out = subprocess.run([sys.executable, str(LINT), str(p), "--no-history"], capture_output=True, text=True)
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("R-P10 is in the idea anchor", out.stdout)
            self.assertNotIn("R-P1 is in", out.stdout)
            p.write_text(GOOD + closure + "| R-P10 | divergence is fine | IN-MILESTONE @M1 |\n")
            out = subprocess.run([sys.executable, str(LINT), str(p), "--no-history"], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stdout)

    def test_several_blueprints_need_a_named_one(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "docs/project").mkdir(parents=True)
            (root / "blueprint-a.md").write_text("**P1** one\n")
            (root / "blueprint-b.md").write_text("**P1** one\n**P2** two\n")
            p = root / "docs/project/milestones.md"
            p.write_text(GOOD.replace("Mechanisms: none", "Mechanisms: none\nParts: [P1]"))
            out = subprocess.run([sys.executable, str(LINT), str(p), "--no-history"], capture_output=True, text=True)
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("several composition blueprints", out.stdout)
            (root / "docs/project/gate.md").write_text("Blueprint: blueprint-a.md\n")
            out = subprocess.run([sys.executable, str(LINT), str(p), "--no-history"], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stdout)
            (root / "docs/project/gate.md").write_text("Blueprint: blueprint-b.md\n")
            out = subprocess.run([sys.executable, str(LINT), str(p), "--no-history"], capture_output=True, text=True)
            self.assertIn("P2 is in the blueprint", out.stdout)
            (root / "docs/project/gate.md").write_text("Blueprint: blueprint-c.md\n")
            out = subprocess.run([sys.executable, str(LINT), str(p), "--no-history"], capture_output=True, text=True)
            self.assertIn("which does not exist", out.stdout)

    def test_wiring_status_rules(self):
        code, out = run(GOOD.replace("| built |", "| done |"))
        self.assertEqual(code, 1, out)
        self.assertIn("status 'done'", out)
        code, out = run(GOOD.replace("Status: building", "Status: gate"))
        self.assertEqual(code, 1, out)
        self.assertIn("proven or parked", out)
        code, out = run(GOOD.replace("Status: building", "Status: gate").replace("| built |", "| proven |"))
        self.assertEqual(code, 0, out)

    def test_missing_mechanisms_line_fails(self):
        code, out = run(GOOD.replace("Mechanisms: none\n", ""))
        self.assertEqual(code, 1, out)
        self.assertIn("Mechanisms", out)

    def _git_repo(self, d, text):
        subprocess.run(["git", "init", "-q", d], check=True)
        p = Path(d) / "milestones.md"
        p.write_text(text, encoding="utf-8")
        subprocess.run(["git", "-C", d, "add", "milestones.md"], check=True)
        subprocess.run(["git", "-C", d, "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "-m", "init"], check=True)
        return p

    def test_history_removed_id_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._git_repo(d, GOOD)
            p.write_text(GOOD.replace("- M1.D2", "- (removed)").replace("M1.D2", ""), encoding="utf-8")
            out = subprocess.run([sys.executable, str(LINT), str(p)], capture_output=True, text=True)
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("M1.D2 existed at HEAD", out.stdout)

    def test_history_unchanged_passes(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._git_repo(d, GOOD)
            out = subprocess.run([sys.executable, str(LINT), str(p)], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stdout)

    def test_missing_carries_fails(self):
        code, out = run(GOOD.replace("Carries: I-D1\n", ""))
        self.assertEqual(code, 1, out)
        self.assertIn("Carries", out)

    def test_carries_without_ids_fails(self):
        code, out = run(GOOD.replace("Carries: I-D1", "Carries: the saving feature"))
        self.assertEqual(code, 1, out)

    def test_released_is_not_a_status(self):
        code, out = run(GOOD.replace("Status: building", "Status: released"))
        self.assertEqual(code, 1, out)

    def _with_intent(self, milestones, intent):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "intent.md").write_text(intent, encoding="utf-8")
            p = Path(d) / "milestones.md"
            p.write_text(milestones, encoding="utf-8")
            out = subprocess.run([sys.executable, str(LINT), str(p), "--no-history"], capture_output=True, text=True)
            return out.returncode, out.stdout

    def test_mechanism_names_must_be_cards(self):
        intent = "## Done examples\n- I-D1 save\n## Mechanism cards\n### Sync\nPurpose: x\n## Must not lose\n"
        code, out = self._with_intent(GOOD.replace("Mechanisms: none", "Mechanisms: Sync"), intent)
        self.assertEqual(code, 0, out)
        code, out = self._with_intent(GOOD.replace("Mechanisms: none", "Mechanisms: Magic merge"), intent)
        self.assertEqual(code, 1, out)
        self.assertIn("Magic merge", out)

    def test_refrozen_example_counts(self):
        intent = ("## Done examples\n- I-D1 save\n- I-D2 old\n## Mechanism cards\n## Must not lose\n"
                  "## Re-freeze log\n### RF-1 · 2026-09-27 · D-003\nSupersedes I-D2 with I-D2a: new. Example: a → b\n")
        code, out = self._with_intent(GOOD.replace("Carries: I-D1", "Carries: I-D1, I-D2a"), intent)
        self.assertEqual(code, 0, out)

    def test_uncarried_intent_example_fails(self):
        intent = "## Done examples\n- I-D1 save\n- I-D2 share\n"
        code, out = self._with_intent(GOOD, intent)
        self.assertEqual(code, 1, out)
        self.assertIn("I-D2", out)

    def test_uncarried_but_named_non_goal_passes(self):
        intent = "## Done examples\n- I-D1 save\n- I-D2 share\n"
        m = GOOD.replace("- sharing lists (reason:", "- I-D2 sharing lists (reason:")
        code, out = self._with_intent(m, intent)
        self.assertEqual(code, 0, out)

    def test_carried_nonexistent_example_fails(self):
        code, out = self._with_intent(GOOD.replace("Carries: I-D1", "Carries: I-D1, I-D9"), "## Done examples\n- I-D1 save\n")
        self.assertEqual(code, 1, out)
        self.assertIn("I-D9", out)

    def _accept_project(self, d, milestones_text, quotes):
        root = Path(d)
        (root / "docs/project").mkdir(parents=True)
        home = root / "home"
        t = home / ".claude/projects/-p"
        t.mkdir(parents=True)
        (t / f"{SID}.jsonl").write_text("\n".join(json.dumps({"type": "user", "uuid": f"u{i}", "message": {"content": q}})
                                                 for i, q in enumerate(quotes)) + "\n")
        env = {**os.environ, "HOME": str(home), "CLAUDE_CODE_SESSION_ID": SID}
        p = root / "docs/project/milestones.md"
        p.write_text(milestones_text)
        return root, p, env

    def _decide(self, root, env, did, body, quote):
        with open(root / "docs/project/decisions.md", "a") as f:
            f.write(f'\n## {did} · 2026-09-27 · decision\n{body}\nSource: [owner 2026-09-27] "{quote}"\n')
        subprocess.run([sys.executable, str(RULINGS), "record", str(root), "--id", did, "--quote", quote],
                       capture_output=True, env=env, check=True)

    def _lint(self, p, env):
        return subprocess.run([sys.executable, str(LINT), str(p), "--no-history"], capture_output=True, text=True, env=env)

    def test_accepted_needs_a_proven_acceptance(self):
        accepted = GOOD.replace("Status: building", "Status: accepted").replace("| built |", "| proven |")
        with tempfile.TemporaryDirectory() as d:
            root, p, env = self._accept_project(d, accepted, ["yes accept M1, it works"])
            out = self._lint(p, env)
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("without an owner acceptance", out.stdout)
            h = subprocess.run([sys.executable, str(LINT), str(p), "--contract-hash", "M1"], capture_output=True,
                               text=True).stdout.strip()
            self._decide(root, env, "D-005", f"Accept M1 · contract {h} · fingerprint product:x · review reviews/M1.md",
                         "yes accept M1, it works")
            out = self._lint(p, env)
            self.assertEqual(out.returncode, 0, out.stdout)

    def test_acceptance_names_the_candidate_that_passed(self):
        accepted = GOOD.replace("Status: building", "Status: accepted").replace("| built |", "| proven |")
        with tempfile.TemporaryDirectory() as d:
            root, p, env = self._accept_project(d, accepted, ["yes accept M1, it works"])
            h = subprocess.run([sys.executable, str(LINT), str(p), "--contract-hash", "M1"], capture_output=True,
                               text=True).stdout.strip()
            self._decide(root, env, "D-005", f"Accept M1 · contract {h} · fingerprint product:old", "yes accept M1, it works")
            for n, (verdict, fp) in enumerate([("ACCEPT-READY", "product:old"), ("CHANGES", "product:mid"),
                                               ("ACCEPT-READY", "product:new")], 1):
                (root / f".evidence/gate/M1/r{n}").mkdir(parents=True)
                (root / f".evidence/gate/M1/r{n}/verdict.json").write_text(json.dumps({"verdict": verdict, "fingerprint": fp}))
            out = self._lint(p, env)
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("latest ACCEPT-READY round of M1 checked product:new", out.stdout)

    def test_contract_change_after_acceptance(self):
        accepted = GOOD.replace("Status: building", "Status: accepted").replace("| built |", "| proven |")
        with tempfile.TemporaryDirectory() as d:
            root, p, env = self._accept_project(d, accepted, ["yes accept M1, it works", "ok, drop the tomorrow part"])
            h = subprocess.run([sys.executable, str(LINT), str(p), "--contract-hash", "M1"], capture_output=True,
                               text=True).stdout.strip()
            self._decide(root, env, "D-005", f"Accept M1 · contract {h} · fingerprint product:x", "yes accept M1, it works")
            p.write_text(accepted.replace("find it again tomorrow", "find it again"))
            out = self._lint(p, env)
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("contract changed after acceptance", out.stdout)
            self._decide(root, env, "D-006", "Supersede M1 promise", "ok, drop the tomorrow part")
            p.write_text(accepted.replace("find it again tomorrow", "find it again").replace(
                "Carries: I-D1", "Carries: I-D1\nSuperseded: D-006"))
            out = self._lint(p, env)
            self.assertEqual(out.returncode, 0, out.stdout)
            self.assertIn("superseded by D-006", out.stdout)

    def test_contract_test_must_exist_at_gate(self):
        at_gate = GOOD.replace("Status: building", "Status: gate").replace("| built |", "| proven |")
        with tempfile.TemporaryDirectory() as d:
            root, p, env = self._accept_project(d, at_gate, [])
            (root / "docs/project/interfaces.md").write_text("### ListStore\nContract test: tests/contract_store.py (owned by M1)\n")
            out = self._lint(p, env)
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("contract_store.py does not exist", out.stdout)
            (root / "tests").mkdir()
            (root / "tests/contract_store.py").write_text("")
            self.assertEqual(self._lint(p, env).returncode, 0)

    def test_bad_invocation(self):
        out = subprocess.run([sys.executable, str(LINT), "/nonexistent/m.md"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)


if __name__ == "__main__":
    unittest.main()
