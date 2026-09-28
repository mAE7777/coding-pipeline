"""Tests for the /dev Stop hook (milestone-continue.py)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "skills/dev/scripts/milestone-continue.py"

STATE = """# State
Updated: {updated}

## Writer
claude session {writer}

## Milestone
M1 · phase: {phase}

## Campaign
{campaign}

## Open
{open}

## In flight
{inflight}

## Blockers
{blockers}
"""


class MilestoneContinueTest(unittest.TestCase):
    def setUp(self):
        self.session = "test-" + uuid.uuid4().hex
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, phase="building", open_items="- [ ] wire export\n- [x] store", blockers="none", writer=None,
              campaign="none", inflight="none", updated="2026-09-27T10:00:00Z"):
        p = Path(self.d) / "docs/project"
        p.mkdir(parents=True, exist_ok=True)
        (p / "state.md").write_text(STATE.format(phase=phase, open=open_items, blockers=blockers,
                                                 writer=writer or self.session, campaign=campaign,
                                                 inflight=inflight, updated=updated))

    def stop(self, active=False, cwd=None, **extra):
        payload = {"session_id": self.session, "cwd": cwd or self.d, "hook_event_name": "Stop",
                   "stop_hook_active": active, **extra}
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                             text=True, env=env)
        return out.returncode, out.stdout, out.stderr

    def test_holds_with_open_items(self):
        self.write()
        code, _, err = self.stop()
        self.assertEqual(code, 2)
        self.assertIn("wire export", err)

    def test_allows_when_blocker_recorded(self):
        self.write(blockers="- need the Stripe test key · owner: user · unblock: key in env")
        self.assertEqual(self.stop()[0], 0)

    def test_allows_when_nothing_open(self):
        self.write(open_items="- [x] everything")
        self.assertEqual(self.stop()[0], 0)

    def test_gate_phase_is_inactive_outside_a_campaign(self):
        self.write(phase="gate")
        self.assertEqual(self.stop()[0], 0)
        self.write(phase="gate", campaign="M1-M3 · D-004")
        self.assertEqual(self.stop()[0], 2, "an authorized campaign keeps going through its gates")

    def test_no_state_file_is_a_no_op(self):
        self.assertEqual(self.stop()[0], 0)

    def test_streak_cap_and_timestamps_are_not_progress(self):
        self.write()
        codes = []
        for i in range(4):
            self.write(updated=f"2026-09-27T10:0{i}:00Z")
            codes.append(self.stop(active=(i > 0))[0])
        self.assertEqual(codes, [2, 2, 2, 0], "rewriting only the timestamp is not progress")

    def test_progress_resets_the_streak(self):
        self.write()
        self.assertEqual([self.stop(active=(i > 0))[0] for i in range(3)], [2, 2, 2])
        self.write(open_items="- [ ] wire export\n- [x] store\n- [x] empty state")
        self.assertEqual(self.stop(active=True)[0], 2)

    def test_session_cap(self):
        for i in range(25):
            self.write(open_items=f"- [ ] wire export\n- [x] step {i}")
            self.assertEqual(self.stop(active=True)[0], 2)
        self.write(open_items="- [ ] wire export\n- [x] step 99")
        code, out, _ = self.stop(active=True)
        self.assertEqual(code, 0)
        self.assertIn("25 automatic continuations", out)

    def test_other_writer_is_ignored(self):
        self.write(writer="aaaaaaaa-1111-2222-3333-444444444444")
        self.assertEqual(self.stop()[0], 0)

    def test_in_flight_work_allows_the_stop(self):
        self.write(inflight="- npm run build in the background (shell b1)")
        self.assertEqual(self.stop()[0], 0)

    def test_a_question_to_the_owner_ends_the_turn(self):
        self.write()
        self.assertEqual(self.stop(last_assistant_message="Two readings of the sync rule. Which one do you want?")[0], 0)
        self.assertEqual(self.stop(last_assistant_message="Wired the store. Moving on.")[0], 2)

    def test_the_owners_pause_ends_the_run(self):
        self.write()
        transcript = Path(self.d) / "session.jsonl"

        def says(text, kind="human"):
            transcript.write_text("\n".join(json.dumps(x) for x in [
                {"type": "user", "uuid": "u1", "message": {"content": "build M1"}},
                {"type": "attachment", "uuid": "q1", "attachment": {"type": "queued_command", "commandMode": "prompt",
                                                                    "origin": {"kind": kind}, "prompt": text}}]) + "\n")
        says("先停一下，我看看")
        self.assertEqual(self.stop(transcript_path=str(transcript))[0], 0, "a Chinese pause lets the stop through")
        says("wait, I want to look at the export first")
        self.assertEqual(self.stop(transcript_path=str(transcript))[0], 0)
        says("looks good, keep going")
        self.assertEqual(self.stop(transcript_path=str(transcript))[0], 2)
        says("stop and wait for me", kind="peer")
        self.assertEqual(self.stop(transcript_path=str(transcript))[0], 2, "an agent's words are not the owner's pause")

    def test_found_from_a_subfolder(self):
        self.write()
        sub = Path(self.d) / "packages/web/src"
        sub.mkdir(parents=True)
        self.assertEqual(self.stop(cwd=str(sub))[0], 2)

    def test_codex_writer_with_tool_flag(self):
        p = Path(self.d) / "docs/project/state.md"
        self.write()
        p.write_text(p.read_text().replace(f"claude session {self.session}", f"codex session {self.session}"))
        self.assertEqual(self.stop()[0], 0, "a Claude registration ignores a Codex writer")
        payload = {"session_id": self.session, "cwd": self.d, "hook_event_name": "Stop", "stop_hook_active": False}
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        out = subprocess.run([sys.executable, str(HOOK), "--tool", "codex"], input=json.dumps(payload),
                             capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 2)

    def test_bad_json_allows(self):
        out = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)


if __name__ == "__main__":
    unittest.main()
