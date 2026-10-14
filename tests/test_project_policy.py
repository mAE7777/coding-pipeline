"""A project can leave formal management without finishing or repairing its record."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S = ROOT / "skills/_shared/scripts"
sys.path.insert(0, str(S))
import project_policy as policy
from fingerprint import fingerprint


class ProjectPolicyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.project = self.base / "app"
        self.project.mkdir()
        self.env = {**os.environ, "HOME": str(self.base / "home"),
                    "RELOAD_STATE_DIR": str(self.base / "reload"), "PYTHONDONTWRITEBYTECODE": "1"}
        self.env.pop("CLAUDE_PROJECT_DIR", None)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, script, *args, payload=None, **extra):
        env = {**self.env, **extra}
        return subprocess.run([sys.executable, str(script), *map(str, args)],
                              input=json.dumps(payload) if payload is not None else None,
                              capture_output=True, text=True, env=env, timeout=10)

    def old_record(self):
        rec = self.project / "docs/project"
        rec.mkdir(parents=True)
        (self.project / "app.py").write_text("answer = 42\n")
        (rec / "state.md").write_text("# State\n## Writer\ncodex session current\n"
            "## Milestone\nM1 · phase: building\n## Open\n- [ ] add export\n"
            "## Blockers\nnone\n## In flight\nnone\n")
        (rec / "intent.md").write_text("# Intent\nLocked by the owner but hash broken\n")
        (rec / "milestones.md").write_text("unreadable old milestones")
        return rec

    def test_default_off_even_with_partial_adoption_and_old_lock(self):
        rec = self.old_record()
        (self.project / "truth").mkdir()
        original = {p: p.read_bytes() for p in rec.iterdir()}
        out = self.call(S / "project_status.py", self.project, "--json")
        status = json.loads(out.stdout)
        self.assertFalse(status["managed"])
        self.assertEqual(status["next"], [])
        self.assertFalse(status["recovery"])
        self.assertEqual(original, {p: p.read_bytes() for p in rec.iterdir()})

    def test_existing_design_does_not_trigger_adoption_when_off(self):
        (self.project / "docs").mkdir()
        (self.project / "docs/design.md").write_text("Use the existing architecture.")
        out = self.call(S / "record_check.py", self.project, "--json")
        self.assertEqual(out.returncode, 0)
        self.assertEqual(json.loads(out.stdout)["kind"], "foreign-docs")
        self.assertIsNone(json.loads(out.stdout)["route"])
        policy.set_mode(self.project, True)
        on = self.call(S / "record_check.py", self.project, "--json")
        self.assertEqual(on.returncode, 3)
        self.assertEqual(json.loads(on.stdout)["route"], "/plan adopt")

    def test_on_off_are_independent_of_a_record_and_persist_in_new_process(self):
        for mode in ("on", "off"):
            out = self.call(S / "project_policy.py", mode, self.project)
            self.assertEqual(out.returncode, 0, out.stderr)
            state = json.loads(self.call(S / "project_policy.py", "status", self.project, "--json").stdout)
            self.assertEqual(state["managed"], mode == "on")
            self.assertFalse((self.project / "docs").exists())

    def test_typo_never_changes_parent_project(self):
        out = self.call(S / "project_policy.py", "off", self.project / "missing")
        self.assertEqual(out.returncode, 2)
        self.assertFalse((self.project / policy.NAME).exists())

    def test_malformed_or_missing_policy_never_enables_management(self):
        for text in ('{}', '{"version":1,"managed":"false"}', 'broken', '{"version":2,"managed":true}'):
            (self.project / policy.NAME).write_text(text)
            self.assertFalse(policy.managed(self.project))

    def test_new_session_in_either_tool_observes_off_without_adoption(self):
        self.old_record()
        policy.set_mode(self.project, False)
        for tool in ("claude", "codex"):
            out = self.call(S / "continuity.py", "session-start", "--tool", tool,
                            payload={"cwd": str(self.project), "session_id": "new"})
            context = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("workflow OFF", context)
            self.assertNotIn("/plan adopt", context)
            self.assertNotIn("$plan adopt", context)
            self.assertNotIn("lock it with the owner", context)

    def test_claim_stop_packet_recovery_and_journal_do_not_touch_old_record(self):
        rec = self.old_record()
        policy.set_mode(self.project, False)
        original = {p: p.read_bytes() for p in rec.iterdir()}
        payload = {"cwd": str(self.project), "session_id": "current", "tool_name": "Edit",
                   "tool_input": {"file_path": str(self.project / "app.py")}}
        for mode in ("claim", "stop"):
            out = self.call(S / "continuity.py", mode, "--tool", "codex", payload=payload)
            self.assertEqual(out.returncode, 0, out.stderr)
        self.call(S / "continuity.py", "packet", self.project, "--tool", "codex", "--session", "current")
        self.call(S / "continuity.py", "recover", self.project)
        self.call(S / "project_status.py", "record", self.project, "--skill", "fix", "--outcome", "fixed")
        self.assertEqual(original, {p: p.read_bytes() for p in rec.iterdir()})
        self.assertFalse((rec / "handoffs").exists())
        self.assertFalse((rec / "journal.md").exists())
        self.assertFalse((self.project / ".evidence").exists())

    def test_armed_reload_gate_stops_blocking_immediately_and_control_command_is_allowed(self):
        self.old_record()
        policy.set_mode(self.project, True)
        hook = ROOT / "hooks/reload-gate.py"
        payload = {"cwd": str(self.project), "session_id": "current", "tool_name": "Bash",
                   "tool_input": {"command": "python3 app.py"}}
        self.call(hook, "arm", payload=payload)
        self.assertIn('"deny"', self.call(hook, "guard", payload=payload).stdout)
        payload["tool_input"]["command"] = f"{sys.executable} {S / 'project_policy.py'} off {self.project}"
        self.assertEqual(self.call(hook, "guard", payload=payload).stdout, "")
        copied = self.base / "project_policy.py"
        copied.write_bytes((S / "project_policy.py").read_bytes())
        payload["tool_input"]["command"] = f"{sys.executable} {copied} off {self.project}"
        self.assertEqual(self.call(hook, "guard", payload=payload).stdout, "")
        copied.write_text("print('not the controller')")
        self.assertIn('"deny"', self.call(hook, "guard", payload=payload).stdout)
        policy.set_mode(self.project, False)
        payload["tool_input"]["command"] = "python3 app.py"
        self.assertEqual(self.call(hook, "guard", payload=payload).stdout, "")
        policy.set_mode(self.project, True)
        self.assertEqual(self.call(hook, "guard", payload=payload).stdout, "", "old gate does not revive")

    def test_a_control_command_lets_nothing_else_through_the_reload_gate(self):
        self.old_record()
        policy.set_mode(self.project, True)
        hook = ROOT / "hooks/reload-gate.py"
        payload = {"cwd": str(self.project), "session_id": "current", "tool_name": "Bash",
                   "tool_input": {"command": "python3 app.py"}}
        self.call(hook, "arm", payload=payload)
        ctl = f"{sys.executable} {S / 'project_policy.py'}"
        for tail in (f"status {self.project};touch x", "status\ntouch x", f"status {self.project} &touch x",
                     "status &touch x", 'status "$(touch x)"', "status `touch x`", "status x|tee y",
                     "status <(touch x)"):
            payload["tool_input"]["command"] = f"{ctl} {tail}"
            self.assertIn('"deny"', self.call(hook, "guard", payload=payload).stdout, tail)
        payload["tool_input"]["command"] = f"{ctl} status {self.project} --json"
        self.assertEqual(self.call(hook, "guard", payload=payload).stdout, "")

    def test_compaction_and_loaded_stop_hook_do_not_restart_an_off_project(self):
        self.old_record()
        payload = {"cwd": str(self.project), "session_id": "current"}
        for script, args in ((ROOT / "hooks/snapshot-state.py", ()),
                             (ROOT / "hooks/reload-gate.py", ("arm",)),
                             (ROOT / "skills/dev/scripts/milestone-continue.py", ("--tool", "codex"))):
            out = self.call(script, *args, payload=payload)
            self.assertEqual((out.returncode, out.stdout, out.stderr), (0, "", ""))
        self.assertFalse((self.project / ".evidence").exists())
        self.assertFalse((self.base / "reload").exists())

    def test_other_automatic_hooks_do_not_lock_or_start_checks_when_off(self):
        self.old_record()
        (self.project / "tsconfig.json").write_text("{}")
        (self.project / "app.ts").write_text("console.log('test')")
        payload = {"cwd": str(self.project), "session_id": "current", "tool_name": "Bash",
                   "tool_input": {"command": "npm run build"}}
        for name in ("heavy-guard.py", "typecheck-once.py"):
            out = self.call(ROOT / "hooks" / name, payload=payload,
                            HEAVY_LOCK_DIR=str(self.base / "machine-lock"))
            self.assertEqual((out.returncode, out.stdout, out.stderr), (0, "", ""))
        out = subprocess.run(["bash", str(ROOT / "hooks/verify-pipeline-completion.sh")],
                             input=json.dumps(payload), capture_output=True, text=True, env=self.env)
        self.assertEqual(json.loads(out.stdout), {"suppressOutput": True})
        self.assertFalse((self.base / "machine-lock").exists())

    def test_owner_lock_and_shell_gate_are_not_prerequisites_when_off(self):
        rec = self.old_record()
        out = self.call(S / "intent_lock.py", "verify", rec / "intent.md")
        self.assertEqual(out.returncode, 3)
        self.assertIn("workflow OFF", out.stderr)
        self.assertNotIn("FAIL", out.stdout)
        out = subprocess.run(["bash", str(S.parent / "gate.sh"), str(self.project)],
                             capture_output=True, text=True, env=self.env)
        self.assertEqual(out.returncode, 3)
        self.assertNotIn("FAIL", out.stdout)

    def test_inflight_isolated_checker_is_cancelled_without_result_or_descendant(self):
        import run_isolated
        policy.set_mode(self.project, True)
        stem = self.base / "checker"
        result = self.base / "result.md"
        marker = self.base / "should-not-exist"
        code = f"import time;time.sleep(2);open({str(marker)!r},'w').write('ran')"
        opts = {"project": str(self.project), "timeout": "10"}
        timer = threading.Timer(0.2, policy.set_mode, args=(self.project, False))
        timer.start()
        started = time.monotonic()
        try:
            info = run_isolated.launch("cold-reader", "claude", opts, self.project, stem,
                                      [sys.executable, "-c", code], self.env, {}, "pack", "sid", result)
        finally:
            timer.join()
        self.assertEqual(info["status"], "CANCELLED")
        self.assertLess(time.monotonic() - started, 2)
        self.assertFalse(marker.exists())
        self.assertFalse(result.exists())
        self.assertFalse(Path(str(stem) + ".jsonl").exists())

    def test_formal_runners_do_not_create_adoption_or_gate_outputs_when_off(self):
        self.old_record()
        for script, args in ((S / "adopt.py", ("inventory", self.project)),
                             (S / "gate_run.py", (self.project, "--milestone", "M1")),
                             (S / "run_isolated.py", ("cold-reader", "--project", self.project, "--dir", "auto",
                                                      "--out", self.project / ".evidence/test", "--render", "--"))):
            out = self.call(script, *args)
            self.assertEqual(out.returncode, 3, out.stdout + out.stderr)
            self.assertIn("workflow OFF", out.stderr)
        self.assertFalse((self.project / ".evidence").exists())

    def test_generated_agreement_is_conditioned_without_deleting_design(self):
        original = (ROOT / "skills/_shared/templates/AGENTS.md").read_text()
        # Reconstruct the previous generated agreement, including a user-added convention.
        begin = original.index("<!-- coding-pipeline-policy:v1 -->")
        end = original.index("- The plan, decisions", begin)
        old = original[:begin] + original[end:] + "\nCustom design: preserve offline storage.\n"
        (self.project / "AGENTS.md").write_text(old)
        policy.set_mode(self.project, False)
        current = (self.project / "AGENTS.md").read_text()
        self.assertIn("only when", current)
        self.assertIn("Custom design: preserve offline storage.", current)
        self.assertIn("- The plan, decisions", current)
        self.assertFalse(policy.migrate_agreement(self.project), "migration is idempotent")

    def test_custom_agreement_without_pipeline_signature_is_untouched(self):
        text = "# Map\n## Working agreement\nKeep the existing design.\n"
        (self.project / "AGENTS.md").write_text(text)
        policy.set_mode(self.project, False)
        self.assertEqual((self.project / "AGENTS.md").read_text(), text)

    def test_policy_changes_do_not_change_product_fingerprint(self):
        (self.project / "app.py").write_text("answer = 42\n")
        before = fingerprint(self.project)[0]
        policy.set_mode(self.project, True)
        self.assertEqual(before, fingerprint(self.project)[0])
        policy.set_mode(self.project, False)
        self.assertEqual(before, fingerprint(self.project)[0])

    def test_nested_repositories_do_not_inherit_parent_management(self):
        policy.set_mode(self.project, True)
        child = self.project / "child"
        child.mkdir()
        subprocess.run(["git", "init", "-q", str(child)], check=True)
        self.assertFalse(policy.managed(child))
        alias = self.base / "alias"
        alias.symlink_to(self.project, target_is_directory=True)
        self.assertTrue(policy.managed(alias))

    def test_worktrees_share_one_persistent_choice(self):
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        subprocess.run(["git", "-C", str(self.project), "-c", "user.name=fixture", "-c", "user.email=f@f",
                        "commit", "--allow-empty", "-qm", "fixture"], check=True)
        worktree = self.base / "worktree"
        subprocess.run(["git", "-C", str(self.project), "worktree", "add", "--detach", "-q", str(worktree)], check=True)
        policy.set_mode(self.project, True)
        self.assertTrue(policy.managed(worktree))
        policy.set_mode(worktree, False)
        self.assertFalse(policy.managed(self.project))
        self.assertEqual(policy.read(worktree)["source"], str((self.project / policy.NAME).resolve()))
        self.assertFalse((worktree / policy.NAME).exists())

    def test_running_gate_child_is_cancelled_after_switch_off(self):
        import gate_run
        policy.set_mode(self.project, True)
        gate_run.WORKFLOW_LEASE = policy.read(self.project)
        marker = self.project / "should-not-write"
        timer = threading.Timer(0.2, policy.set_mode, args=(self.project, False))
        timer.start()
        try:
            with self.assertRaises(gate_run.WorkflowOff):
                gate_run.run([sys.executable, "-c", "import time,pathlib,sys; time.sleep(3); pathlib.Path(sys.argv[1]).touch()", str(marker)])
        finally:
            timer.join()
            gate_run.WORKFLOW_LEASE = None
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
