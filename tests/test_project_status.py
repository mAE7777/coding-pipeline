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
        (self.root / ".coding-pipeline.json").write_text('{"version":1,"managed":true}')
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
        self.assertTrue(self.status()["next"][0]["fresh"], "a new milestone is a joint: best begun in a new session")
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
        self.assertFalse(steps[0]["fresh"], "a milestone under way stays in its session")
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

    def test_a_milestone_fixed_and_frozen_again_goes_back_to_the_gate(self):
        self.record(s1="gate")
        d = self.root / ".evidence/gate/M1/r1"
        d.mkdir(parents=True)
        (d / "verdict.json").write_text(json.dumps({"round": 1, "verdict": "CHANGES", "fingerprint": "product:aaa",
                                                    "reasons": ["blocking: M1-F01 the total is wrong"]}))
        state = self.root / "docs/project/state.md"
        state.write_text(state.read_text() + "\n## Candidate\nproduct:aaa\n")
        self.assertIn("round 1's blocking findings", self.first()[1], "frozen on the same candidate: still to fix")
        state.write_text(state.read_text().replace("product:aaa", "product:bbb"))
        who, action = self.first()
        self.assertEqual((who, action), ("builder", "/gate M1"), "a new candidate after CHANGES runs the next round")

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

    def step(self, skill, arg=None, outcome="no progress"):
        cmd = [sys.executable, str(PS), "record", str(self.root), "--skill", skill, "--outcome", outcome]
        out = subprocess.run(cmd + (["--arg", arg] if arg else []), capture_output=True, text=True, env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def journal_prints(self):
        lines = (self.root / "docs/project/journal.md").read_text().splitlines()
        return [l.rsplit(" · record ", 1)[1] if " · record " in l else None for l in lines if l.startswith("- ")]

    def test_each_journal_line_carries_the_record_fingerprint_which_recording_alone_does_not_move(self):
        self.record(s1="building", phase="building")
        self.step("dev", "M1")
        self.step("fix", "M1-F01")
        prints = self.journal_prints()
        self.assertEqual(len(prints), 2)
        self.assertRegex(prints[0], r"^[0-9a-f]{8}$")
        self.assertEqual(prints[0], prints[1], "the journal and state.md's Last step are not the record moving")
        (self.root / "app.py").write_text("x = 2\n")
        self.step("dev", "M1")
        self.assertNotEqual(self.journal_prints()[-1], prints[1])

    def test_three_steps_that_repeat_without_moving_the_record_stop_for_the_owner(self):
        self.record(s1="building", phase="building")
        loop = "The last 3 steps repeated /dev M1 without changing the record. Stop and tell the owner what is " \
               "looping and what you tried."
        self.step("dev", "M1")
        self.assertNotIn("repeated", self.step("dev", "M1"))
        third = self.step("dev", "M1")
        self.assertIn(f"Next (owner): {loop}", third, "the step that closes the loop already says to stop")
        first = self.status()["next"][0]
        self.assertEqual((first["who"], first["action"]), ("owner", loop))
        self.assertEqual(self.status()["next"][1]["action"], "/dev resume", "what the record says next stays in view")
        (self.root / "app.py").write_text("x = 2\n")
        self.assertEqual(self.first(), ("builder", "/dev resume"), "a record that moved since the loop clears it")

    def test_a_moving_record_or_a_different_step_is_not_a_loop(self):
        self.record(s1="building", phase="building")
        self.step("dev", "M1")
        (self.root / "app.py").write_text("x = 2\n")
        self.step("dev", "M1")
        self.step("dev", "M1")
        self.assertNotIn("repeated", self.first()[1], "the first of the three moved the record")
        self.step("gate", "M1")
        self.step("dev", "M1")
        self.assertNotIn("repeated", self.first()[1])
        self.step("dev")
        self.assertNotIn("repeated", self.first()[1], "/dev and /dev M1 are different steps")

    def test_journal_lines_without_a_fingerprint_never_count(self):
        self.record(s1="building", phase="building")
        old = "- 2026-10-01 10:0{} UTC · dev M1 · unknown session · started · next: /dev resume (builder)\n"
        (self.root / "docs/project/journal.md").write_text("# Journal\n\n" + "".join(old.format(i) for i in range(3)))
        self.assertEqual(self.first(), ("builder", "/dev resume"))
        self.assertNotIn("repeated", self.step("dev", "M1"))
        self.assertNotIn("repeated", self.step("dev", "M1"), "two old lines and one new are not three repeats")
        self.assertIn("repeated /dev M1", self.step("dev", "M1"))


if __name__ == "__main__":
    unittest.main()
