"""Tests for project_status.py: where a project stands and what comes next, from the record alone."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS = ROOT / "skills/_shared/scripts/project_status.py"
INBOX = ROOT / "skills/_shared/scripts/inbox.py"
MS = """# Milestones
## M1 · Add and list
Status: {s1}
Readiness: built [x] · gate-passed [{g1}] · accepted [ ] · released [ ] · live-verified [ ]

## M2 · Streaks
Status: {s2}
Readiness: built [ ] · gate-passed [ ] · accepted [ ] · released [{r2}] · live-verified [ ]
"""
STATE = """# State

## Writer
claude session aaa

## Milestone
M1 · phase: {phase}

## Open
- [ ] wire the list command

## In flight
{flight}

## Blockers
{blockers}

## Next step
continue
"""


class ProjectStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.root.mkdir()
        self.env = {**os.environ, "HOME": str(Path(self.tmp.name) / "home")}
        for k in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"):
            self.env.pop(k, None)

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, s1="planned", g1=" ", s2="planned", r2=" ", phase="idle", flight="none", blockers="none",
               locked=True):
        rec = self.root / "docs/project"
        rec.mkdir(parents=True, exist_ok=True)
        (rec / "intent.md").write_text("# Intent\n" + ("Locked by the owner 2026-09-28 · hash abc · ruling D-001\n"
                                                        if locked else "Status: draft\n"))
        (rec / "milestones.md").write_text(MS.format(s1=s1, g1=g1, s2=s2, r2=r2))
        (rec / "state.md").write_text(STATE.format(phase=phase, flight=flight, blockers=blockers))
        for name in ("brief.md", "interfaces.md", "decisions.md"):
            (rec / name).write_text(f"# {name}\n")
        (self.root / "AGENTS.md").write_text("# Map\n\n## Commands\ntest: true\n")
        (self.root / "app.py").write_text("x = 1\n")

    def verdict(self, mid, rnd, verdict, reasons=()):
        d = self.root / f".evidence/gate/{mid}/r{rnd}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "verdict.json").write_text(json.dumps({"round": rnd, "verdict": verdict, "reasons": list(reasons)}))

    def status(self):
        out = subprocess.run([sys.executable, str(PS), str(self.root), "--json"], capture_output=True, text=True,
                             env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def first(self):
        n = self.status()["next"][0]
        return n["who"], n["action"]

    def test_an_empty_folder_asks_the_owner_for_the_idea(self):
        who, action = self.first()
        self.assertEqual(who, "owner")
        self.assertIn("/plan", action)

    def test_code_without_a_record_is_adopted(self):
        (self.root / "main.go").write_text("package main\n")
        self.assertEqual(self.first(), ("builder", "/plan adopt"))

    def test_an_unlocked_plan_is_finished_then_locked_by_the_owner(self):
        self.record(locked=False)
        steps = self.status()["next"]
        self.assertTrue(steps[0]["action"].startswith("/plan"))
        self.assertEqual(steps[1]["who"], "owner")

    def test_the_next_milestone_is_built_after_the_inbox_is_weighed(self):
        self.record()
        self.assertEqual(self.first(), ("builder", "/dev M1"))
        subprocess.run([sys.executable, str(INBOX), "add", str(self.root), "--from", "Sam", "--kind", "idea",
                        "--text", "Show the longest streak"], check=True, capture_output=True)
        steps = self.status()["next"]
        self.assertEqual([s["action"] for s in steps[:2]], ["/inbox review", "/dev M1"])

    def test_mid_milestone_inbox_items_stay_in_view(self):
        self.record(s1="building", phase="building")
        subprocess.run([sys.executable, str(INBOX), "add", str(self.root), "--from", "Sam", "--kind", "idea",
                        "--text", "Show the longest streak"], check=True, capture_output=True)
        steps = self.status()["next"]
        self.assertEqual(steps[0]["action"], "/dev resume")
        self.assertIn("IN-001", steps[-1]["why"])

    def test_a_gate_passed_candidate_waits_for_the_owner(self):
        self.record(s1="gate", g1="x")
        self.verdict("M1", 1, "ACCEPT-READY")
        who, action = self.first()
        self.assertEqual(who, "owner")
        self.assertIn("/gate accept M1", action)

    def test_gate_findings_inconclusive_and_blocked_rounds(self):
        self.record(s1="changes")
        self.verdict("M1", 2, "CHANGES", ["blocking: M1-F02 the export drops rows"])
        who, action = self.first()
        self.assertEqual(who, "builder")
        self.assertIn("round 2's blocking findings", action)
        self.record(s1="gate")
        self.verdict("M1", 3, "INCONCLUSIVE", ["code-verifier: ERROR"])
        self.assertIn("inconclusive", self.first()[1])
        self.verdict("M1", 4, "BLOCKED", ["needs the owner: M1-F05"])
        self.assertEqual(self.first()[0], "owner")

    def test_a_blocker_goes_to_the_owner(self):
        self.record(blockers="the payment keys · owner · add them to the vault")
        who, action = self.first()
        self.assertEqual((who, action), ("owner", "clear the blocker"))

    def test_wait_only_on_a_round_that_is_really_running(self):
        self.record(s1="gate", flight="gate round 1 (background)")
        lock = self.root / ".evidence/gate/round.running"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(f"{os.getpid()} M1")
        self.assertEqual(self.first()[0], "wait")
        lock.write_text("999999 M1")
        steps = self.status()["next"]
        self.assertEqual(steps[0]["who"], "builder", "a dead round's stale note is checked, not waited on")
        self.assertIn("in flight", steps[0]["action"])
        self.assertEqual(steps[1]["action"], "/gate M1")

    def test_a_release_is_the_owners_call(self):
        self.record(s1="accepted", s2="accepted")
        who, action = self.first()
        self.assertEqual(who, "owner")
        self.assertIn("/deploy", action)

    def test_every_step_is_recorded_with_what_comes_next(self):
        self.record()
        out = subprocess.run([sys.executable, str(PS), "record", str(self.root), "--skill", "plan", "--outcome",
                              "intent locked, 2 milestones"], capture_output=True, text=True, env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("Next (builder): /dev M1", out.stdout)
        journal = (self.root / "docs/project/journal.md").read_text()
        self.assertIn("· plan · unknown session · intent locked, 2 milestones · next: /dev M1 (builder)", journal)
        state = (self.root / "docs/project/state.md").read_text()
        self.assertIn("## Last step\nplan · ", state)
        subprocess.run([sys.executable, str(PS), "record", str(self.root), "--skill", "dev", "--arg", "M1",
                        "--outcome", "started"], capture_output=True, text=True, env=self.env)
        state = (self.root / "docs/project/state.md").read_text()
        self.assertEqual(state.count("## Last step"), 1)
        self.assertIn("## Last step\ndev M1 · ", state)
        self.assertEqual(self.status()["last_step"].split(" · ")[0], "dev M1")


if __name__ == "__main__":
    unittest.main()
