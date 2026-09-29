"""Tests for spend.py: a phase's spend is measured from what actually ran, and only the owner raises its cap."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/_shared/scripts"
SPEND = SCRIPTS / "spend.py"
SID = "77777777-2222-3333-4444-555555555555"
sys.path.insert(0, str(SCRIPTS))
import spend  # noqa: E402


def call(ts, cwd, mid, out=1000, cache_read=0, cache_write=0):
    return json.dumps({"type": "assistant", "timestamp": ts, "cwd": cwd, "message": {"id": mid, "usage": {
        "input_tokens": 0, "output_tokens": out, "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_write}}})


class SpendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.home, self.project = d / "home", d / "work/proj"
        self.project.mkdir(parents=True)
        self.env = {**os.environ, "HOME": str(self.home), "CLAUDE_CODE_SESSION_ID": SID}
        self.projects = self.home / ".claude/projects"

    def tearDown(self):
        self.tmp.cleanup()

    def spend(self, *args):
        return subprocess.run([sys.executable, str(SPEND), *args], capture_output=True, text=True, env=self.env)

    def transcript(self, folder, name, lines):
        f = self.projects / folder / f"{name}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join(lines) + "\n")
        return f

    def start(self, cap="10"):
        r = self.spend("start", str(self.project), "--phase", "adopt", "--cap", cap)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads((self.project / ".evidence/spend/active.json").read_text())["started"]

    def test_what_counts(self):
        started = self.start()
        key = spend.claude_folder_key(self.project)
        after, before = "2099-01-01T00:00:00Z", "2000-01-01T00:00:00Z"
        # This project's own conversation, a helper it started, and a call from before the phase.
        main = self.transcript(key, "s1", [call(before, str(self.project), "m0", out=10**9),
                                           call(after, str(self.project), "m1", out=1000),
                                           call(after, str(self.project), "m1", out=1000)])
        (main.parent / "s1/subagents").mkdir(parents=True)
        (main.parent / "s1/subagents/a.jsonl").write_text(call(after, str(self.project), "h1", cache_read=100000) + "\n")
        # A conversation from a parent folder working inside the project, and one working elsewhere.
        self.transcript("-parent", "s2", [call(after, str(self.project / "src"), "p1", out=2000)])
        self.transcript("-other", "s3", [call(after, "/somewhere/else", "o1", out=10**8)])
        # Isolated runs: one with usage recorded, an older one whose stream holds it, and a Codex one.
        ev = self.project / ".evidence/capture/extract-1"
        ev.mkdir(parents=True)
        (ev / "cold-reader.summary.json").write_text(json.dumps({"usage": {"output": 3000, "cache_write": 8000}}))
        old = self.project / ".evidence/capture/extract-2"
        old.mkdir(parents=True)
        (old / "cold-reader.summary.json").write_text(json.dumps({"status": "OK"}))
        (old / "cold-reader.jsonl").write_text(json.dumps({"type": "result", "usage": {"output_tokens": 1000}}) + "\n")
        cx = self.project / ".evidence/gate/M1/r1"
        cx.mkdir(parents=True)
        (cx / "code-verifier.summary.json").write_text(json.dumps({"family": "codex", "usage": {"output": 500000}}))
        # A Codex conversation in the project (its turns' token counts), and one elsewhere.
        rollouts = self.home / ".codex/sessions/2099/01/01"
        rollouts.mkdir(parents=True)
        turn = lambda ts: json.dumps({"timestamp": ts, "type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": 1000, "cached_input_tokens": 800, "output_tokens": 100}}}})
        (rollouts / "rollout-a.jsonl").write_text("\n".join([
            json.dumps({"type": "session_meta", "payload": {"cwd": str(self.project)}}), turn(before), turn(after)]) + "\n")
        (rollouts / "rollout-b.jsonl").write_text("\n".join([
            json.dumps({"type": "session_meta", "payload": {"cwd": "/somewhere/else"}}), turn(after)]) + "\n")
        home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        try:
            m = spend.measure(self.project, spend.parse_time(started))
        finally:
            os.environ["HOME"] = home
        # conversations: the main call, the helper's call, and the parent folder's call (1000 + 1000 + 2000 output,
        # x5) and the helper's 100000 cache reads (x0.1); the repeated message id counts once
        self.assertEqual(m["conversations"], 4000 * 5 + 100000 * 0.1)
        self.assertEqual(m["isolated"], 3000 * 5 + 8000 * 1.25 + 1000 * 5)
        # the Codex run, and the one Codex turn after the start: 200 uncached input, 800 cached, 100 output
        self.assertEqual(m["codex"], 500000 * 5 + 200 + 800 * 0.1 + 100 * 5, "Codex is shown apart: its own allowance")
        self.assertEqual(m["runs"], 3)

    def test_over_the_cap_stops_and_only_the_owner_raises_it(self):
        self.start(cap="0.000001")
        ev = self.project / ".evidence/capture/extract-1"
        ev.mkdir(parents=True)
        (ev / "cold-reader.summary.json").write_text(json.dumps({"usage": {"output": 100000}}))
        r = self.spend("status", str(self.project))
        self.assertEqual(r.returncode, 1)
        self.assertIn("OVER THE CAP", r.stdout)
        r = self.spend("raise", str(self.project), "--cap", "15", "--quote", "Go up to fifteen percent.")
        self.assertEqual(r.returncode, 1, "words the owner never typed raise nothing")
        self.transcript("-p", SID, [json.dumps({"type": "user", "uuid": "u1", "timestamp": "t",
                                                "message": {"content": "Go up to fifteen percent."}})])
        r = self.spend("raise", str(self.project), "--cap", "15", "--quote", "Go up to fifteen percent.")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.spend("status", str(self.project)).returncode, 0)
        r = self.spend("stop", str(self.project))
        self.assertEqual(r.returncode, 0)
        self.assertFalse((self.project / ".evidence/spend/active.json").exists())
        closed = list((self.project / ".evidence/spend").glob("adopt-*.json"))
        self.assertEqual(len(closed), 1)
        self.assertEqual(json.loads(closed[0].read_text())["raises"][0]["quote"], "Go up to fifteen percent.")

    def test_estimate_and_calibrate(self):
        src = self.project / "docs/project/sources/SRC-1-notes"
        src.mkdir(parents=True)
        (src / "meta.json").write_text(json.dumps({"id": "SRC-1", "kind": "doc"}))
        (src / "transcript.md").write_text("x" * 400000)
        r = self.spend("estimate", str(self.project))
        self.assertIn("1 source(s) to read, about 100k tokens", r.stdout)
        ev = self.project / ".evidence/capture/extract-1"
        ev.mkdir(parents=True)
        (ev / "cold-reader.summary.json").write_text(json.dumps({"usage": {"output": 1_000_000}}))
        r = self.spend("calibrate", "10", str(self.project))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads((self.home / ".claude/.pipeline-budget.json").read_text())["weekly_units"], 50_000_000)


if __name__ == "__main__":
    unittest.main()
