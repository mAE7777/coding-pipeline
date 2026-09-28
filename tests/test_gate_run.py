"""End-to-end test of gate_run.py with a stand-in `claude` (a test fixture, never product code)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/_shared/scripts"
SID = "33333333-2222-3333-4444-555555555555"

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import glob, json, os, sys
args = sys.argv[1:]
role = args[args.index("--agent") + 1]
pack = sys.stdin.read()
mode = os.environ.get("FAKE_MODE", "clean")
tools = 1
text = "done"
if role == "code-verifier" and pack.startswith("# Demo pack"):
    steps = [{"milestone": "M1", "step": 1, "expected": "1. milk", "observed": "1. milk", "status": "HOLDS"}]
    text = "Demo ran.\n```json\n" + json.dumps({"mode": "demo", "steps": steps}) + "\n```"
elif role == "code-verifier":
    review = {"mode": "review", "verdict": "PASS", "done_examples": [{"id": "I-D1", "status": "HOLDS"}],
              "must_not_lose": [{"id": "L-01", "status": "HOLDS"}], "mechanisms": [], "wiring": [], "findings": [],
              "not_run": []}
    text = "Reviewed.\n```json\n" + json.dumps(review) + "\n```"
elif role == "gate-judge":
    verdict = {"verdict": "ACCEPT-READY", "intent_diff": [{"id": "I-D1", "status": "HOLDS", "evidence": "q"},
               {"id": "M1.D1", "status": "HOLDS", "evidence": "q"}, {"id": "MECH-Store", "status": "HOLDS", "evidence": "q"},
               {"id": "L-01", "status": "HOLDS", "evidence": "q"}], "blocking": [], "logged": [], "not_run": [],
               "resolved": []}
    text = "Judgment.\n```json\n" + json.dumps(verdict) + "\n```"
    tools = 0
elif role == "loyal-evaluator" and mode == "escape":
    hits = glob.glob(os.environ["FAKE_PROJECT"] + "/docs/project/.gate-canary-*.md")
    text = "I looked around: " + (open(hits[0]).read() if hits else "nothing")
print(json.dumps({"type": "system", "subtype": "init", "session_id": "fake-" + role, "model": "fake", "tools": []}))
for _ in range(tools):
    print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}))
print(json.dumps({"type": "result", "result": text, "num_turns": 2, "is_error": False, "permission_denials": []}))
'''

INTENT = """# Intent

Status: draft

## Goal
Keep one short to-do list in a terminal.

## Identity and promise
A list you can trust.

## Who
Persona (blind): an adult comfortable with a command line.
Someone who keeps a few chores in mind.

## Load-bearing behavior
Adding an item shows it at once.

## Done examples
- I-D1 When an item is added, it is printed back. Example: add milk → "1. milk"

## Mechanism cards
### Store
Purpose: items survive.
Observable guarantee: the item is printed.
Rejected imitation: a constant list.
Discriminating probe: add two different items.

## Must not lose
- L-01 Items are never reordered · check: add a then b, see a before b

## Design intent
none

## Assumptions
- A-01 one user · signed 2026-09-27

## Re-freeze log
"""
MILESTONES = """# Milestones

## M1 · Add and show
Status: gate
Promise: A person adds an item and sees it.
Carries: I-D1
Mechanisms: Store

Demo ending:
1. Run the add command with milk → it prints 1. milk

In scope:
- add and show

Named non-goals:
- sync (reason: one device)

Parked:
- none

Done examples:
- M1.D1 When milk is added, it prints. Example: add milk → "1. milk"

Checkpoints:
- none

Interfaces: none

Steal: none

Wiring:
| Component | Producer / trigger | Consumer | Visible effect | Failure state | Test | Status |
|---|---|---|---|---|---|---|
| add command | the command line | the store | the printed list | an error line | test_app.py | proven |

AI evals: none

Readiness: built [x] · gate-passed [ ] · accepted [ ] · released [ ] · live-verified [ ]
Real-use needs: none
"""


def make_project(d, test_cmd="python3 -c \"print('tests ok')\""):
    root = Path(d) / "proj"
    docs = root / "docs/project"
    docs.mkdir(parents=True)
    (root / "app.py").write_text("items = []\n")
    (root / "AGENTS.md").write_text(f"# Map\n\n## Commands\ntest: {test_cmd}\nrun: python3 app.py\n")
    (docs / "intent.md").write_text(INTENT)
    (docs / "milestones.md").write_text(MILESTONES)
    (docs / "decisions.md").write_text('# Decisions\n\n## D-001 · 2026-09-27 · Lock intent\nLock intent\n'
                                       'Source: [owner 2026-09-27] "yes, lock it, that is the list I want"\n')
    return root


class GateRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.home = d / "home"
        t = self.home / ".claude/projects/-p"
        t.mkdir(parents=True)
        (t / f"{SID}.jsonl").write_text(json.dumps({"type": "user", "uuid": "u1", "message": {
            "content": "yes, lock it, that is the list I want"}}) + "\n")
        self.bin = d / "bin"
        self.bin.mkdir()
        (self.bin / "claude").write_text(FAKE_CLAUDE)
        os.chmod(self.bin / "claude", 0o755)
        self.env = {**os.environ, "HOME": str(self.home), "CLAUDE_CODE_SESSION_ID": SID,
                    "HEAVY_LOCK_DIR": str(d / "lock"), "PATH": f"{self.bin}:{os.environ['PATH']}"}
        for k in ("HEAVY_LOCK_HELD", "HEAVY_OWNER"):
            self.env.pop(k, None)

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self, **kw):
        root = make_project(self.tmp.name, **kw)
        self.env["FAKE_PROJECT"] = str(root)
        subprocess.run([sys.executable, str(SCRIPTS / "rulings.py"), "record", str(root), "--id", "D-001", "--quote",
                        "yes, lock it, that is the list I want"], env=self.env, check=True, capture_output=True)
        out = subprocess.run([sys.executable, str(SCRIPTS / "intent_lock.py"), "stamp", str(root / "docs/project/intent.md"),
                              "--ruling", "D-001"], env=self.env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout)
        subprocess.run([sys.executable, str(SCRIPTS / "baseline.py"), "record", str(root), "M1"], env=self.env,
                       check=True, capture_output=True)
        fp = subprocess.run([sys.executable, str(SCRIPTS / "fingerprint.py"), str(root)], capture_output=True,
                            text=True).stdout.split()[0]
        (root / "docs/project/state.md").write_text(f"# State\n\n## Understanding\nAdd and show.\n\n## Candidate\n{fp}\n")
        return root

    def gate(self, root, mode="clean", family=("--family", "claude"), extra_env=None):
        env = {**self.env, "FAKE_MODE": mode, **(extra_env or {})}
        out = subprocess.run([sys.executable, str(SCRIPTS / "gate_run.py"), str(root), "--milestone", "M1",
                              *family, "--agents-dir", str(ROOT / "agents")],
                             capture_output=True, text=True, env=env, timeout=600)
        ev = sorted((root / ".evidence/gate/M1").glob("r*"))
        verdict = json.loads((ev[-1] / "verdict.json").read_text()) if ev and (ev[-1] / "verdict.json").exists() else None
        return out, verdict, (ev[-1] if ev else None)

    def test_clean_round_reaches_accept_ready(self):
        root = self.prepare()
        out, verdict, ev = self.gate(root)
        self.assertIsNotNone(verdict, out.stdout[-2000:] + out.stderr[-1000:])
        self.assertEqual(verdict["verdict"], "ACCEPT-READY", json.dumps(verdict, indent=1) + out.stdout[-1500:])
        self.assertTrue((ev / "layer1.json").exists())
        self.assertEqual(list((self.home / ".gate-copies").glob("*/review")), [], "copies are deleted after the round")
        self.assertEqual(list((root / "docs/project").glob(".gate-canary-*")), [], "the canary is removed")
        self.assertIn("gate-passed [x]", (root / "docs/project/milestones.md").read_text())

    def test_a_codex_builder_gets_its_review_from_claude(self):
        root = self.prepare()
        env = {k: v for k, v in self.env.items() if k != "CLAUDE_CODE_SESSION_ID"}
        self.env = env
        out, verdict, ev = self.gate(root, family=(), extra_env={"CODEX_THREAD_ID": "builder-thread"})
        self.assertIsNotNone(verdict, out.stdout[-2000:] + out.stderr[-1000:])
        summary = json.loads((ev / "code-verifier.summary.json").read_text())
        self.assertEqual(summary["family"], "claude", "the other family than the Codex builder")
        self.assertFalse(summary.get("family_switch"), "choosing the other family is not a switch")

    def test_a_stale_round_lock_is_removed_and_a_live_one_refuses(self):
        root = self.prepare()
        lock = root / ".evidence/gate/round.running"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("999999 M2")
        (root / "docs/project/.gate-canary-deadbeef.md").write_text("CANARY-OLD\n")
        out, verdict, ev = self.gate(root)
        self.assertIn("removed a stale round lock (999999 M2)", out.stderr)
        self.assertIsNotNone(verdict, out.stderr[-800:])
        self.assertFalse((root / "docs/project/.gate-canary-deadbeef.md").exists(), "a dead round's canary is removed")
        lock.write_text("")
        os.utime(lock, (0, 0))
        out, verdict, _ = self.gate(root)
        self.assertIn("removed a stale round lock (empty)", out.stderr, "an old empty lock is from a dead round")
        lock.write_text(f"{os.getpid()} M2")
        out, _, _ = self.gate(root)
        self.assertIn("already running in this project (M2", out.stderr)
        lock.unlink()

    def test_a_test_suite_exiting_75_by_itself_is_a_failure_not_a_busy_machine(self):
        root = self.prepare(test_cmd="python3 -c \"import sys; sys.exit(75)\"")
        out, verdict, ev = self.gate(root)
        self.assertEqual(verdict["verdict"], "CHANGES", out.stdout[-1500:])
        checks = json.loads((ev / "layer1.json").read_text())["checks"]
        self.assertEqual([c["status"] for c in checks if c["name"] == "test suite"], ["FAIL"])

    def test_failing_tests_stop_before_model_review(self):
        root = self.prepare(test_cmd="python3 -c \"import sys; sys.exit(3)\"")
        out, verdict, ev = self.gate(root)
        self.assertEqual(verdict["verdict"], "CHANGES", out.stdout[-1500:])
        self.assertFalse((ev / "code-verifier.summary.json").exists(), "no model review after a deterministic FAIL")

    def test_not_frozen_refuses(self):
        root = self.prepare()
        (root / "app.py").write_text("items = ['changed after the freeze']\n")
        out, verdict, ev = self.gate(root)
        self.assertEqual(out.returncode, 1)
        self.assertIn("not frozen", out.stderr)

    def test_intent_only_runs_on_the_live_tree(self):
        root = self.prepare()
        (root / "app.py").write_text("items = ['mid-build change']\n")
        env = {**self.env, "FAKE_MODE": "clean"}
        out = subprocess.run([sys.executable, str(SCRIPTS / "gate_run.py"), str(root), "--milestone", "M1",
                              "--intent-only", "--agents-dir", str(ROOT / "agents")],
                             capture_output=True, text=True, env=env, timeout=600)
        ev = sorted((root / ".evidence/loyal/M1").glob("r*"))[-1]
        verdict = json.loads((ev / "verdict.json").read_text())
        self.assertEqual(verdict["verdict"], "ACCEPT-READY", out.stdout[-1500:])
        self.assertFalse((ev / "code-verifier.summary.json").exists(), "no code review in an intent check")
        self.assertIn("intent check r1", (root / "docs/project/reviews/intent-ledger.md").read_text())
        self.assertIn("Status: gate", (root / "docs/project/milestones.md").read_text(), "status untouched")

    def test_escape_to_the_real_project_is_a_leak(self):
        root = self.prepare()
        out, verdict, ev = self.gate(root, mode="escape")
        self.assertEqual(verdict["verdict"], "INCONCLUSIVE", out.stdout[-1500:])
        self.assertEqual(json.loads((ev / "loyal-evaluator.summary.json").read_text())["status"], "LEAK")


if __name__ == "__main__":
    unittest.main()
