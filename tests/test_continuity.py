"""Tests for record_check.py and continuity.py (session start, writer claim, stop, packet)."""
import json
import time
import re
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S = ROOT / "skills/_shared/scripts"
RC, CONT, HC = S / "record_check.py", S / "continuity.py", S / "handoff_check.py"

STATE = """# State

Updated: 2026-09-27T10:00:00Z

## Writer
codex session aaa

## Milestone
M1 · phase: building

## Campaign
none

## Baseline
product:x

## Candidate
not frozen

## Understanding
Two phones keep one list.

## Done
- store written · evidence: .evidence/store.log

## Open
- [ ] wire the export button

## In flight
none

## Failures
none

## Blockers
none

## Next step
wire the export button
"""


def adopted(d):
    root = Path(d) / "proj"
    docs = root / "docs/project"
    docs.mkdir(parents=True)
    (docs / "intent.md").write_text("# Intent\nLocked by the owner 2026-09-27 · hash 0123456789abcdef · ruling D-001 · "
                                    "re-freezes 0\n## Goal\nx\n## Must not lose\n- L-01 keep · check: y\n## Re-freeze log\n")
    for name in ("milestones.md", "interfaces.md", "decisions.md"):
        (docs / name).write_text(f"# {name}\n")
    (docs / "brief.md").write_text("# Brief\n## Constraints\n| ID | Rule | Reason | Source | Scope | Change trigger | Status |\n"
                                   "|---|---|---|---|---|---|---|\n| C-01 | r | w | s | a | t | active |\n")
    (docs / "state.md").write_text(STATE)
    (root / "AGENTS.md").write_text("# Map\n\n## Commands\ntest: true\n")
    (root / "app.py").write_text("x = 1\n")
    (root / ".evidence").mkdir()
    (root / ".evidence/store.log").write_text("ok")
    return root


def hook(mode, payload, tool="claude", env=None):
    e = {**os.environ, **(env or {})}
    e.pop("CLAUDE_PROJECT_DIR", None)
    out = subprocess.run([sys.executable, str(CONT), mode, "--tool", tool], input=json.dumps(payload),
                         capture_output=True, text=True, env=e)
    return out.returncode, out.stdout, out.stderr


class RecordCheckTest(unittest.TestCase):
    def kind(self, root):
        return json.loads(subprocess.run([sys.executable, str(RC), str(root), "--json"], capture_output=True,
                                         text=True).stdout)["kind"]

    def test_kinds(self):
        with tempfile.TemporaryDirectory() as d:
            root = adopted(d)
            self.assertEqual(self.kind(root), "complete")
            (root / "docs/project/brief.md").unlink()
            self.assertEqual(self.kind(root), "partial")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "slices.md").write_text("# Slices\n")
            (Path(d) / "a.py").write_text("")
            self.assertEqual(self.kind(d), "legacy-v2")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "docs").mkdir()
            (Path(d) / "docs/architecture.md").write_text("layers")
            (Path(d) / "a.py").write_text("")
            self.assertEqual(self.kind(d), "foreign-docs")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.py").write_text("")
            self.assertEqual(self.kind(d), "none")
            r = subprocess.run([sys.executable, str(RC), d], capture_output=True, text=True)
            self.assertEqual(r.returncode, 3)
            self.assertIn("/plan adopt", r.stdout)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.kind(d), "empty")

    def test_every_code_language_counts_and_a_cut_scan_is_not_empty(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "scripts").mkdir()
            (Path(d) / "scripts/fetch.mjs").write_text("export const x = 1\n")
            self.assertEqual(self.kind(d), "none", ".mjs scripts are code")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "assets").mkdir()
            for i in range(30):
                (Path(d) / f"assets/{i}.png").write_bytes(b"x")
            out = subprocess.run([sys.executable, "-c", "import sys, json; sys.path.insert(0, sys.argv[1]); import record_check as r; "
                                  "r.scan.__defaults__ = (10, 10.0); print(json.dumps(r.classify(sys.argv[2])))", str(S), d],
                                 capture_output=True, text=True)
            info = json.loads(out.stdout)
            self.assertEqual(info["kind"], "inconclusive", info)
            self.assertFalse(info["scan_complete"])

    def test_a_venture_project_at_the_build_is_new_work_not_an_adoption(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for rel in ("truth/brief.md", "truth/decisions.md", "truth/validation-plan.md", "narrative/story.md",
                        "blueprint-trail.md", "solution-concept.md", "idea-stage-status.md", "design/design-notes.md",
                        "vnv/plan-review.md"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("# helm\n")
            self.assertEqual(self.kind(root), "empty")
            (root / "app.py").write_text("print(1)\n")
            self.assertEqual(self.kind(root), "none", "code with no build record still needs adoption")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "design").mkdir()
            (Path(d) / "design/design-notes.md").write_text("notes")
            self.assertEqual(self.kind(d), "foreign-docs", "outside a venture project a design folder is foreign docs")


class LocalOnlyTest(unittest.TestCase):
    def test_standard_set_written_once_to_the_local_exclude_file(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            lo = S / "local_only.py"
            out = subprocess.run([sys.executable, str(lo), d], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            exclude = (Path(d) / ".git/info/exclude").read_text()
            for pat in ("/docs/project/state.md", "/.evidence/", "/AGENTS.md", "/CLAUDE.md", "/docs/project/.gate-canary-*"):
                self.assertIn(pat, exclude)
            again = subprocess.run([sys.executable, str(lo), d], capture_output=True, text=True)
            self.assertIn("nothing (all present)", again.stdout)
            self.assertFalse((Path(d) / ".gitignore").exists(), "never .gitignore")
            (Path(d) / "AGENTS.md").write_text("# map\n")
            status = subprocess.run(["git", "-C", d, "status", "--porcelain"], capture_output=True, text=True).stdout
            self.assertNotIn("AGENTS.md", status)

    def test_outside_a_repository(self):
        with tempfile.TemporaryDirectory() as d:
            out = subprocess.run([sys.executable, str(S / "local_only.py"), d], capture_output=True, text=True)
            self.assertEqual(out.returncode, 1)


class ContinuityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = adopted(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_unadopted_project_is_routed_to_adoption(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".git").mkdir()
            (Path(d) / "main.go").write_text("package main\n")
            code, out, _ = hook("session-start", {"session_id": "s1", "cwd": d})
            self.assertIn("/plan adopt", json.loads(out)["hookSpecificOutput"]["additionalContext"])
            code, out, _ = hook("session-start", {"session_id": "s1", "cwd": d}, tool="codex")
            self.assertIn("$plan adopt", out)

    def test_packet_reads_the_tool_and_session_from_the_environment(self):
        base = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")}
        r = subprocess.run([sys.executable, str(CONT), "packet", str(self.root)], capture_output=True, text=True,
                           env={**base, "CODEX_THREAD_ID": "thr-77"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("codex session thr-77", (self.root / "docs/project/handoffs/latest.md").read_text())
        r = subprocess.run([sys.executable, str(CONT), "packet", str(self.root)], capture_output=True, text=True,
                           env=base)
        self.assertEqual(r.returncode, 2, "no session variable: refuse instead of writing a made-up writer")
        self.assertIn("cannot tell which session", r.stderr)
        r = subprocess.run([sys.executable, str(CONT), "packet", str(self.root)], capture_output=True, text=True,
                           env={**base, "CODEX_THREAD_ID": "t", "CLAUDE_CODE_SESSION_ID": "c"})
        self.assertEqual(r.returncode, 2)
        self.assertIn("ambiguous", r.stderr)

    def test_a_codex_session_cut_off_by_its_usage_limit_is_recovered(self):
        home = Path(self.tmp.name) / "home"
        subprocess.run([sys.executable, str(CONT), "packet", str(self.root), "--tool", "claude", "--session", "c-old"],
                       check=True, capture_output=True, env={**os.environ, "HOME": str(home)})
        packet = self.root / "docs/project/handoffs/latest.md"
        written = re.search(r"^Written: (\S+)", packet.read_text(), re.M).group(1)
        os.utime(packet, (time.time() - 600, time.time() - 600))
        (self.root / "app.py").write_text("x = 2  # half-finished export\n")
        rollout = home / ".codex/sessions/2026/09/28/rollout-2026-09-28T10-00-00-thr-42.jsonl"
        rollout.parent.mkdir(parents=True)
        later = "2099-01-01T00:00:00.000Z"
        rollout.write_text("\n".join(json.dumps(x) for x in [
            {"type": "session_meta", "timestamp": written, "payload": {"id": "thr-42", "cwd": str(self.root)}},
            {"type": "event_msg", "timestamp": "2000-01-01T00:00:00Z", "payload": {"type": "user_message", "message": "an old instruction"}},
            {"type": "event_msg", "timestamp": later, "payload": {"type": "user_message",
                                                                 "message": "keep the export as CSV, not JSON, that's final"}},
            {"type": "event_msg", "timestamp": later, "payload": {"type": "agent_message",
                                                                 "message": "Switching the export writer to CSV now."}},
            {"type": "event_msg", "timestamp": later, "payload": {"type": "error", "message": "You've hit your usage limit."}},
        ]) + "\n")
        code, out, _ = hook("session-start", {"session_id": "c-new", "cwd": str(self.root)}, env={"HOME": str(home)})
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("codex session thr-42", ctx)
        self.assertIn('"keep the export as CSV, not JSON, that\'s final"', ctx, "the owner's words arrive verbatim")
        self.assertNotIn("an old instruction", ctx, "only what came after the last handoff note")
        self.assertIn("Switching the export writer to CSV now.", ctx)
        self.assertIn("--session codex:thr-42", ctx, "the words can be proven from the Codex transcript")
        self.assertIn("app.py", ctx)

    def test_a_clean_handoff_adds_no_recovery(self):
        home = Path(self.tmp.name) / "home2"
        rollout = home / ".codex/sessions/2026/09/28/rollout-x-thr-7.jsonl"
        rollout.parent.mkdir(parents=True)
        rollout.write_text(json.dumps({"type": "session_meta", "payload": {"id": "thr-7", "cwd": str(self.root)}}) + "\n")
        os.utime(rollout, (time.time() - 600, time.time() - 600))
        subprocess.run([sys.executable, str(CONT), "packet", str(self.root), "--tool", "codex", "--session", "thr-7"],
                       check=True, capture_output=True, env={**os.environ, "HOME": str(home)})
        code, out, _ = hook("session-start", {"session_id": "c-new", "cwd": str(self.root)}, env={"HOME": str(home)})
        self.assertNotIn("Work after the last handoff note", out)

    def test_takeover_context_from_the_other_tool(self):
        subprocess.run([sys.executable, str(CONT), "packet", str(self.root), "--tool", "codex", "--session", "aaa"],
                       check=True, capture_output=True)
        (self.root / "app.py").write_text("x = 2\n")
        code, out, _ = hook("session-start", {"session_id": "bbb", "cwd": str(self.root)})
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Last writer: codex session aaa", ctx)
        self.assertIn("wire the export button", ctx)
        self.assertIn("app.py", ctx, "files changed since the other writer's note are named")

    def test_same_writer_gets_no_takeover_text(self):
        code, out, _ = hook("session-start", {"session_id": "aaa", "cwd": str(self.root)}, tool="codex")
        self.assertNotIn("Last writer", out)

    def test_claim_rewrites_writer_once_and_logs(self):
        payload = {"session_id": "bbb", "cwd": str(self.root), "tool_name": "Edit",
                   "tool_input": {"file_path": str(self.root / "app.py")}}
        hook("claim", payload)
        state = (self.root / "docs/project/state.md").read_text()
        self.assertIn("## Writer\nclaude session bbb\n", state)
        self.assertIn("claude session bbb took over from codex session aaa",
                      (self.root / "docs/project/handoffs/log.md").read_text())
        hook("claim", payload)
        self.assertEqual((self.root / "docs/project/handoffs/log.md").read_text().count("took over"), 1)

    def test_codex_apply_patch_claims_the_writer_role(self):
        patch = "*** Begin Patch\n*** Update File: app.py\n@@\n-x = 1\n+x = 3\n*** End Patch\n"
        hook("claim", {"session_id": "cdx1", "cwd": str(self.root), "tool_name": "apply_patch",
                       "tool_input": {"command": patch}}, tool="codex")
        self.assertIn("## Writer\ncodex session cdx1\n", (self.root / "docs/project/state.md").read_text())

    def test_a_session_that_comes_back_takes_the_role_back(self):
        edit = lambda sid: {"session_id": sid, "cwd": str(self.root), "tool_name": "Edit",
                            "tool_input": {"file_path": str(self.root / "app.py")}}
        hook("claim", edit("AAA"))
        patch = "*** Begin Patch\n*** Update File: app.py\n@@\n-x = 1\n+x = 4\n*** End Patch\n"
        hook("claim", {"session_id": "BBB", "cwd": str(self.root), "tool_name": "apply_patch",
                       "tool_input": {"command": patch}}, tool="codex")
        self.assertIn("## Writer\ncodex session BBB\n", (self.root / "docs/project/state.md").read_text())
        hook("claim", edit("AAA"))
        self.assertIn("## Writer\nclaude session AAA\n", (self.root / "docs/project/state.md").read_text(),
                      "Claude, then Codex, then the same Claude session: the writer role comes back")
        hook("stop", {"session_id": "AAA", "cwd": str(self.root)})
        self.assertIn("claude session AAA", (self.root / "docs/project/handoffs/latest.md").read_text())

    def test_a_session_started_in_a_parent_folder_still_claims_and_hands_off(self):
        parent = str(self.root.parent)
        hook("claim", {"session_id": "par1", "cwd": parent, "tool_name": "Edit",
                       "tool_input": {"file_path": str(self.root / "app.py")}})
        self.assertIn("## Writer\nclaude session par1\n", (self.root / "docs/project/state.md").read_text())
        patch = f"*** Begin Patch\n*** Update File: {self.root.name}/app.py\n@@\n-x = 1\n+x = 5\n*** End Patch\n"
        hook("claim", {"session_id": "par2", "cwd": parent, "tool_name": "apply_patch",
                       "tool_input": {"command": patch}}, tool="codex")
        self.assertIn("## Writer\ncodex session par2\n", (self.root / "docs/project/state.md").read_text())
        code, out, err = hook("stop", {"session_id": "par2", "cwd": parent}, tool="codex")
        self.assertEqual(code, 0, err)
        self.assertIn("codex session par2", (self.root / "docs/project/handoffs/latest.md").read_text())

    def test_open_inbox_items_are_named_at_session_start(self):
        subprocess.run([sys.executable, str(CONT.parent / "inbox.py"), "add", str(self.root), "--from", "Sam",
                        "--kind", "idea", "--text", "Show the longest streak too"], check=True, capture_output=True)
        code, out, _ = hook("session-start", {"session_id": "aaa", "cwd": str(self.root)}, tool="codex")
        context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Inbox: 1 open item(s)", context)
        self.assertIn("$inbox review", context)
        self.assertIn("Next (", context)
        self.assertIn("computed from the record", context)

    def test_claim_ignores_reads_and_outside_files(self):
        hook("claim", {"session_id": "ccc", "cwd": str(self.root), "tool_name": "Read", "tool_input": {}})
        hook("claim", {"session_id": "ccc", "cwd": str(self.root), "tool_name": "Write",
                       "tool_input": {"file_path": "/tmp/elsewhere.txt"}})
        self.assertIn("codex session aaa", (self.root / "docs/project/state.md").read_text())

    def test_stop_writes_a_packet_that_passes_the_check(self):
        hook("claim", {"session_id": "bbb", "cwd": str(self.root), "tool_name": "Write",
                       "tool_input": {"file_path": str(self.root / "app.py")}})
        code, out, err = hook("stop", {"session_id": "bbb", "cwd": str(self.root)})
        self.assertEqual(code, 0, err)
        packet = self.root / "docs/project/handoffs/latest.md"
        self.assertTrue(packet.exists())
        r = subprocess.run([sys.executable, str(HC), str(packet), "--project", str(self.root)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_stop_holds_once_when_code_moved_but_state_did_not(self):
        hook("claim", {"session_id": "bbb", "cwd": str(self.root), "tool_name": "Write",
                       "tool_input": {"file_path": str(self.root / "app.py")}})
        hook("stop", {"session_id": "bbb", "cwd": str(self.root)})
        (self.root / "app.py").write_text("x = 3\n")
        code, out, _ = hook("stop", {"session_id": "bbb", "cwd": str(self.root)})
        self.assertEqual(json.loads(out)["decision"], "block")
        (self.root / "app.py").write_text("x = 4\n")
        code, out, _ = hook("stop", {"session_id": "bbb", "cwd": str(self.root), "stop_hook_active": True})
        self.assertEqual(out.strip(), "", "never holds twice in a row")

    def test_stop_by_a_non_writer_does_nothing(self):
        code, out, _ = hook("stop", {"session_id": "zzz", "cwd": str(self.root)})
        self.assertFalse((self.root / "docs/project/handoffs/latest.md").exists())

    def test_internal_error_is_visible(self):
        intent = self.root / "docs/project/intent.md"
        intent.chmod(0o000)
        try:
            code, out, _ = hook("session-start", {"session_id": "bbb", "cwd": str(self.root),
                                                  "hook_event_name": "SessionStart"})
        finally:
            intent.chmod(0o644)
        self.assertEqual(code, 0, "a hook error never breaks the session")
        self.assertIn("internal error", json.loads(out)["systemMessage"])


if __name__ == "__main__":
    unittest.main()
