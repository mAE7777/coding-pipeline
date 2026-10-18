"""Unit tests for run_isolated.py (no model calls): settings, command shape, stream parsing, statuses."""
import http.server
import importlib.util
import json
import os
import socketserver
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RI = ROOT / "skills/_shared/scripts/run_isolated.py"
AGENTS = ROOT / "agents"
spec = importlib.util.spec_from_file_location("run_isolated", RI)
ri = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ri)
HOME = Path.home()


class SettingsTest(unittest.TestCase):
    def test_bash_role_fence(self):
        cfg = ri.settings("loyal-evaluator", Path("/tmp/copy"), [], "/real/lab/project")
        sb = cfg["sandbox"]
        self.assertTrue(sb["enabled"])
        self.assertFalse(sb["allowUnsandboxedCommands"])
        self.assertTrue(sb["failIfUnavailable"])
        deny = sb["filesystem"]["denyRead"]
        for must in (str(HOME), "/real/lab/project", "/Volumes"):
            self.assertIn(must, deny)
        self.assertNotIn("/real/lab", deny, "the parent is covered by the home deny; denying it could fence off the copy")
        allow = sb["filesystem"]["allowRead"]
        self.assertIn("/tmp/copy", allow)
        self.assertNotIn(str(HOME / ".claude"), allow)
        self.assertNotIn(str(HOME / "Projects"), allow)
        self.assertEqual(sb["filesystem"]["allowWrite"][0:1] != [], True)
        self.assertIn("/tmp/copy", sb["filesystem"]["allowWrite"])
        net = sb["network"]
        self.assertTrue(net["strictAllowlist"])
        self.assertTrue(net["allowLocalBinding"])
        self.assertEqual(sorted(net["allowedDomains"]), sorted(ri.LOCAL_HOSTS))
        self.assertIn("Bash", cfg["permissions"]["allow"])
        self.assertTrue(any(c.endswith("--root /tmp/copy *") for c in sb.get("excludedCommands", [])),
                        "browse.py is exempt only when pinned to this copy")
        self.assertEqual(cfg["hooks"]["PreToolUse"][0]["matcher"], "Bash")
        self.assertIn("Read(//real/lab/project/**)", cfg["permissions"]["deny"])

    def test_a_deny_never_covers_the_checkers_own_folder(self):
        cfg = ri.settings("code-verifier", Path("/work/copies/abc/review"), ["/work"], "/work/project")
        self.assertNotIn("/work", cfg["sandbox"]["filesystem"]["denyRead"])
        self.assertIn("/work/project", cfg["sandbox"]["filesystem"]["denyRead"])

    def test_read_only_roles_get_no_shell_or_exemption(self):
        for role in ("gate-judge", "cold-reader"):
            cfg = ri.settings(role, Path("/tmp/verdict"))
            self.assertNotIn("Bash", cfg["permissions"]["allow"])
            self.assertNotIn("excludedCommands", cfg["sandbox"])
            self.assertNotIn("hooks", cfg)

    def test_writer_role_writes_only_in_copy(self):
        cfg = ri.settings("code-verifier", Path("/tmp/copy"))
        self.assertIn("Write(//tmp/copy/**)", cfg["permissions"]["allow"])
        self.assertFalse(any(r.startswith("Write(") and "/tmp/copy" not in r for r in cfg["permissions"]["allow"]))

    def test_extra_network_and_reads(self):
        cfg = ri.settings("code-verifier", Path("/tmp/copy"), network=["registry.npmjs.org"], allow_read=["/opt/sdk"])
        self.assertIn("registry.npmjs.org", cfg["sandbox"]["network"]["allowedDomains"])
        self.assertIn("/opt/sdk", cfg["sandbox"]["filesystem"]["allowRead"])

    def test_min_tools_per_role(self):
        self.assertEqual(ri.MIN_TOOLS["cold-reader"], 0)
        self.assertEqual(ri.MIN_TOOLS["loyal-evaluator"], 1)

    def test_codex_profile_fences_reads(self):
        prof = ri.codex_profile(Path("/tmp/copy"), Path("/tmp/codex-home"), [], Path("/tmp/private"))
        self.assertIn(f'(deny file-read* (subpath "{HOME}")', prof)
        self.assertIn('(allow file-read* (subpath "/tmp/copy"))', prof)
        self.assertIn("(deny file-write*)", prof)
        self.assertNotIn(f'(allow file-write* (subpath "{HOME / ".volta"}"))', prof, "global Node tools stay read-only")
        self.assertNotIn(str(HOME / ".codex/sessions"), prof)
        self.assertIn(f'(allow file-read* (subpath "{ri.HERE}"))', prof, "the runner's scripts (heavy.py, browse.py) are readable")

    def test_codex_can_resolve_its_own_paths_but_not_list_home(self):
        home = HOME / ".gate-copies/codex-home-x"
        prof = ri.codex_profile(Path("/tmp/copy"), home, [], Path("/tmp/private"))
        for above in (HOME, HOME / ".gate-copies"):
            self.assertIn(f'(allow file-read-metadata (literal "{above}"))', prof)
        self.assertNotIn(f'(allow file-read* (literal "{HOME}"))', prof)
        self.assertNotIn(f'(allow file-read* (subpath "{HOME}"))', prof)

    def test_codex_profile_fences_writes_and_network(self):
        prof = ri.codex_profile(Path("/tmp/copy"), Path("/tmp/codex-home"), [], Path("/tmp/private"))
        self.assertIn("(deny file-write*)", prof)
        self.assertNotIn(f'(deny file-write* (subpath "{HOME}"))', prof, "writes are denied everywhere, not only in home")
        self.assertIn("(deny network-outbound)", prof)
        self.assertIn('(allow network-outbound (remote tcp "*:443"))', prof)

    def test_real_codex_usage_limit_output_means_unavailable(self):
        lines = (ROOT / "tests/fixtures/codex-usage-limit.jsonl").read_text().splitlines()
        info = ri.parse_codex_stream(lines)
        self.assertEqual(ri.codex_unavailable(info), "usage limit")
        self.assertEqual(ri.codex_unavailable({"errors": []}, "Error: you've hit your usage limit"), "usage limit")

    def test_documented_cold_read_command_renders(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "proj"
            (proj / "docs/project").mkdir(parents=True)
            (proj / ".coding-pipeline.json").write_text('{"version":1,"managed":true}')
            for name in ("intent", "brief", "milestones"):
                (proj / f"docs/project/{name}.md").write_text(f"# {name}\nsome text\n")
            out = subprocess.run([sys.executable, str(RI), "cold-reader", "--dir", "auto", "--out", str(proj / ".evidence/plan"),
                                  "--project", str(proj), "--render", "--docs", "docs/project/intent.md", "--docs",
                                  "docs/project/brief.md", "--docs", "docs/project/milestones.md", "--", "--dry-run"],
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("DRY_RUN", out.stdout)

    def test_a_phase_over_its_budget_cap_starts_no_run(self):
        with tempfile.TemporaryDirectory() as d:
            proj, home = Path(d) / "proj", Path(d) / "home"
            (proj / "docs/project").mkdir(parents=True)
            (proj / ".coding-pipeline.json").write_text('{"version":1,"managed":true}')
            (proj / "docs/project/intent.md").write_text("# intent\nsome text\n")
            env = {**os.environ, "HOME": str(home)}
            subprocess.run([sys.executable, str(RI.parent / "spend.py"), "start", str(proj), "--phase", "adopt",
                            "--cap", "0.000001"], capture_output=True, text=True, env=env, check=True)
            ran = proj / ".evidence/capture/extract-1"
            ran.mkdir(parents=True)
            (ran / "cold-reader.summary.json").write_text(json.dumps({"usage": {"output": 100000}}))
            out = subprocess.run([sys.executable, str(RI), "cold-reader", "--dir", "auto", "--out", str(proj / ".evidence/plan"),
                                  "--project", str(proj), "--render", "--docs", "docs/project/intent.md", "--", "--dry-run"],
                                 capture_output=True, text=True, env=env)
            self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
            self.assertIn("BLOCKED", out.stdout)
            self.assertIn("budget", out.stdout)
            self.assertEqual(list((home / ".gate-copies").glob("tmp-*")) if (home / ".gate-copies").is_dir() else [], [],
                             "the private folder made for the run is removed")

    def test_auto_folder_is_removed_when_the_pack_cannot_render(self):
        before = set((HOME / ".gate-copies").glob("tmp-*")) if (HOME / ".gate-copies").is_dir() else set()
        with tempfile.TemporaryDirectory() as d:
            out = subprocess.run([sys.executable, str(RI), "cold-reader", "--dir", "auto", "--out", str(Path(d) / "ev"),
                                  "--render", "--docs", "missing.md", "--", "--dry-run"], capture_output=True, text=True)
            self.assertEqual(out.returncode, 1)
        after = set((HOME / ".gate-copies").glob("tmp-*")) if (HOME / ".gate-copies").is_dir() else set()
        self.assertEqual(after - before, set(), "no temp folder left behind")

    def test_a_server_serving_the_project_from_elsewhere_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "proj"
            proj.mkdir()
            srv = subprocess.Popen([sys.executable, "-m", "http.server", "0", "--bind", "127.0.0.1", "--directory", str(proj)],
                                   cwd="/", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                hits = []
                for _ in range(30):
                    hits = ri.project_servers(str(proj))
                    if hits:
                        break
                    time.sleep(0.2)
                self.assertTrue(hits, "a server started in / but serving the project must be found")
            finally:
                srv.terminate()
                srv.wait()

    def test_builder_session_variables_never_reach_a_checker(self):
        env = {**os.environ, "CODEX_THREAD_ID": "builder-thread"}
        code, info = dry("loyal-evaluator", env=env)
        self.assertEqual(code, 0, info)
        self.assertFalse(info["env_codex_thread_passed"])
        if ri.shutil.which("codex"):
            code, info = dry("code-verifier", "--family", "codex", env=env)
            self.assertFalse(info["env_codex_thread_passed"])
            self.assertFalse(info["env_session_id_passed"])


class AgentAndPackTest(unittest.TestCase):
    def test_agent_passed_inline_from_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "a.json"
            path, sha = ri.agents_json("cold-reader", str(AGENTS / "cold-reader.md"), out)
            data = json.loads(out.read_text())
            self.assertIn("cold-reader", data)
            self.assertTrue(data["cold-reader"]["description"])
            self.assertNotIn("---", data["cold-reader"]["prompt"][:5], "frontmatter is not part of the prompt")
            self.assertEqual(len(sha), 64)

    def test_each_shipped_agent_cuts_to_its_route(self):
        """The prompt each checker route gets from the shipped agent file holds its own mode's instructions and no
        other mode's; a role whose routes have no mode carries no mode block (it would reach no run)."""
        import models  # run_isolated.py put its own folder on the path
        own = {"code-verifier.review": ("## Review", "class `structure`", "Deterministic layer"),
               "code-verifier.reverify": ("## Review", "## Re-verify mode"),
               "code-verifier.demo": ("## Demo", ".demo-captures/"),
               "cold-reader.documents": ("## Documents mode",),
               "cold-reader.reread": ("## Documents mode", "## Re-read"),
               "cold-reader.understanding": ("## Understanding mode",),
               "cold-reader.extract": ("## Extraction mode",),
               "cold-reader.fidelity": ("## Fidelity mode",),
               "cold-reader.refidelity": ("## Fidelity mode", "## Re-audit")}
        headings = {h for want in own.values() for h in want if h.startswith("## ")}
        for route in models.CHECKER_ROUTES:
            role = route.split(".", 1)[0]
            if role == "probe":
                continue
            _, meta, body = ri.read_agent(role, str(AGENTS / f"{role}.md"), sorted(models.section_names(route)))
            self.assertNotIn("<!--", body, route)
            if route not in own:
                self.assertNotIn("_mode_sections", meta, f"{route} has no mode, so a mode block reaches no run")
                continue
            for text in own[route]:
                self.assertIn(text, body, route)
            for h in sorted(headings - set(own[route])):
                self.assertNotIn(h, body, f"{route} carries another mode's instructions ({h})")
        review = ri.read_agent("code-verifier", str(AGENTS / "code-verifier.md"), ["review"])[2]
        self.assertNotIn("Re-verify mode", review, "test_gate_run's stand-in tells a re-verify run by these words")

    def test_pass_one_pack_leak_detected(self):
        with tempfile.TemporaryDirectory() as d:
            docs = Path(d) / "docs/project"
            docs.mkdir(parents=True)
            (docs / "intent.md").write_text("## Goal\nFamilies never lose a shared grocery list between two phones.\n"
                                            "## Who\nPersona (blind): two adults sharing a household, comfortable with phones.\n")
            self.assertEqual(ri.pack_leaks("Persona: two adults sharing a household, comfortable with phones.", d), [])
            self.assertTrue(ri.pack_leaks("never lose a shared grocery list between two phones", d))


def dry(role, *extra, env=None):
    with tempfile.TemporaryDirectory() as d:
        pack = Path(d) / "pack.md"
        pack.write_text("pack")
        out = subprocess.run([sys.executable, str(RI), role, "--dir", d, "--pack", str(pack), "--out", str(Path(d) / "ev"),
                              "--agent-file", str(AGENTS / f"{role}.md"), "--dry-run", *extra],
                             capture_output=True, text=True, env=env)
        return out.returncode, (json.loads(out.stdout) if out.stdout.strip().startswith("{") else {"err": out.stderr})


class CommandShapeTest(unittest.TestCase):
    def test_claude_command(self):
        code, info = dry("loyal-evaluator")
        self.assertEqual(code, 0, info)
        cmd = info["cmd"]
        self.assertEqual(cmd[:2], ["claude", "-p"])
        self.assertEqual(cmd[cmd.index("--agent") + 1], "loyal-evaluator")
        for flag in ("--restricted", "--disable-slash-commands", "--strict-mcp-config", "--agents", "--session-id"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "Read,Grep,Glob,Bash")
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "dontAsk")
        self.assertIn("stream-json", cmd)
        self.assertNotIn("--dangerously-skip-permissions", cmd)
        self.assertNotIn("--setting-sources", cmd)
        self.assertTrue(info["env_claude_tmpdir"])

    def test_resume_replaces_session_id(self):
        code, info = dry("loyal-evaluator", "--resume", "abc")
        self.assertIn("--resume", info["cmd"])
        self.assertNotIn("--session-id", info["cmd"])

    def test_codex_only_for_code_verifier(self):
        code, _ = dry("loyal-evaluator", "--family", "codex")
        self.assertEqual(code, 2)

    def test_codex_command_is_fenced(self):
        if not ri.shutil.which("codex"):
            self.skipTest("codex not installed (NOT_RUN)")
        code, info = dry("code-verifier", "--family", "codex")
        cmd = info["cmd"]
        self.assertEqual(cmd[0], "sandbox-exec")
        self.assertEqual(cmd[cmd.index("-s") + 1], "danger-full-access")
        self.assertFalse(info["env_session_id_passed"], "the builder's session id is not inherited")
        self.assertTrue(info["env_heavy_owner"].startswith("codex-"))


class StreamTest(unittest.TestCase):
    def test_parse_claude_stream(self):
        lines = [
            json.dumps({"type": "system", "subtype": "init", "session_id": "S", "model": "claude-opus-5-5",
                        "tools": ["Read", "Bash"]}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"},
                                                                     {"type": "text", "text": "x"}]}}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}}),
            json.dumps({"type": "result", "result": "DONE", "num_turns": 3, "is_error": False, "total_cost_usd": 0.5,
                        "usage": {"input_tokens": 3, "cache_creation_input_tokens": 40, "cache_read_input_tokens": 900,
                                  "output_tokens": 70},
                        "permission_denials": [{"tool_name": "Read", "tool_input": {"file_path": "/real/x"}}]}),
        ]
        info = ri.parse_claude_stream(lines)
        self.assertEqual(info["usage"], {"input": 3, "cache_write": 40, "cache_read": 900, "output": 70,
                                         "cost_usd": 0.5, "duration_ms": None})
        self.assertEqual(info["tool_uses"], 2)
        self.assertEqual(info["session_id"], "S")
        self.assertEqual(info["tools_seen"], ["Read", "Bash"])
        self.assertEqual(len(info["denials"]), 1)

    def test_an_answer_continued_past_the_output_limit_is_kept_whole(self):
        def say(text, mid):
            return json.dumps({"type": "assistant", "message": {"id": mid, "content": [{"type": "text", "text": text}]}})
        limit = json.dumps({"type": "user", "isSynthetic": True, "message": {"role": "user", "content": [
            {"type": "text", "text": "Output token limit hit. Resume directly — no apology, no recap of what you were "
                                     "doing. Pick up mid-thought if that is where the cut happened."}]}})
        lines = [say("I will read the sources first.", "m0"),
                 json.dumps({"type": "assistant", "message": {"id": "m0", "content": [{"type": "tool_use", "name": "Read"}]}}),
                 json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "file text"}]}}),
                 say('```json\n{"points": [{"quote": "a"}, ', "m1"), limit,
                 say('{"quote": "b"}]}\n```', "m2"),
                 json.dumps({"type": "result", "result": '{"quote": "b"}]}\n```', "num_turns": 2, "is_error": False})]
        info = ri.parse_claude_stream(lines)
        self.assertEqual(info["result"], '```json\n{"points": [{"quote": "a"}, {"quote": "b"}]}\n```',
                         "the part before the cut is part of the answer; the text before a tool call is not")
        self.assertEqual(info["output_limit_cuts"], 1, "the join is on record")
        self.assertEqual(info["result_last_event"], '{"quote": "b"}]}\n```')

    def test_an_answer_restarted_after_the_cut_never_reads_as_a_verdict(self):
        """A model that writes its answer again from the start after a cut leaves a block that does not parse: no
        verdict, never half of one; the cut is on record."""
        limit = json.dumps({"type": "user", "isSynthetic": True, "message": {"content": [
            {"type": "text", "text": "Output token limit hit. Resume directly."}]}})
        whole = '```json\n{"verdict": "ACCEPT", "findings": []}\n```'
        lines = [json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": 'Findings.\n```json\n{"verd'}]}}),
                 limit,
                 json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": whole}]}}),
                 json.dumps({"type": "result", "result": whole, "num_turns": 2, "is_error": False})]
        info = ri.parse_claude_stream(lines)
        self.assertTrue(info["result"].startswith("Findings."), "nothing written before the cut is dropped")
        self.assertEqual(info["output_limit_cuts"], 1)

    def test_a_later_turn_is_the_result_and_earlier_answers_stay_apart(self):
        """A background task's notice can open a turn after an answer; the final answer is the result (it may take
        the earlier verdict back), and the earlier one is kept on record, never read as the verdict."""
        verdict = 'Findings above.\n```json\n{"verdict": "PASS"}\n```'
        later = "The background run finished: 4 tests fail, so the PASS above is wrong; this is a FAIL."
        lines = [json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": verdict}]}}),
                 json.dumps({"type": "result", "result": verdict, "num_turns": 9, "is_error": False,
                             "permission_denials": [{"tool_name": "Read", "tool_input": {"file_path": "/real/secret"}}],
                             "usage": {"output_tokens": 100}, "total_cost_usd": 1.0, "duration_ms": 5}),
                 json.dumps({"type": "system", "subtype": "task_notification", "status": "completed"}),
                 json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": later}]}}),
                 json.dumps({"type": "result", "result": later, "num_turns": 1, "is_error": False,
                             "usage": {"output_tokens": 7}, "total_cost_usd": 1.2, "duration_ms": 3})]
        info = ri.parse_claude_stream(lines)
        self.assertEqual(info["result"], later, "an earlier verdict never stands over a later answer")
        self.assertEqual(info["earlier_answers"], [verdict])
        self.assertEqual(info["answers"], 2)
        self.assertEqual(len(info["denials"]), 1, "a denial in any turn counts")
        self.assertEqual((info["usage"]["output"], info["usage"]["cost_usd"], info["turns"]), (107, 1.2, 10))

    def test_an_unrecognized_synthetic_message_is_counted(self):
        lines = [json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "part one"}]}}),
                 json.dumps({"type": "user", "isSynthetic": True, "message": {"content": [
                     {"type": "text", "text": "Max output reached; carry on where you stopped."}]}}),
                 json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "part two"}]}}),
                 json.dumps({"type": "result", "result": "part two", "num_turns": 2, "is_error": False})]
        self.assertEqual(ri.parse_claude_stream(lines)["unrecognized_synthetic"], 1, "a reworded notice shows")

    def test_an_earlier_attempts_side_files_are_removed(self):
        with tempfile.TemporaryDirectory() as d:
            stem = Path(d) / "code-verifier"
            for side in (".result.last-event.md", ".result.earlier-answers.md"):
                Path(str(stem) + side).write_text("from an earlier attempt")
            sys.path.insert(0, str(RI.parent))
            saved = ri.claude_cmd
            ri.claude_cmd = lambda *a, **k: (_ for _ in ()).throw(SystemExit(2))
            try:
                with self.assertRaises(SystemExit):
                    ri.run_once("code-verifier", "claude", {}, Path(d), stem, "pack")
            finally:
                ri.claude_cmd = saved
            self.assertFalse(any(Path(str(stem) + s).exists() for s in (".result.last-event.md", ".result.earlier-answers.md")))

    def test_parse_codex_stream_and_unavailable(self):
        lines = [json.dumps({"type": "thread.started", "thread_id": "T"}),
                 json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}),
                 json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "RESULT"}}),
                 json.dumps({"type": "turn.completed"})]
        info = ri.parse_codex_stream(lines)
        self.assertEqual((info["tool_uses"], info["result"], info["session_id"]), (1, "RESULT", "T"))
        quota = ri.parse_codex_stream([json.dumps({"type": "error", "message": "You've hit your usage limit."})])
        self.assertEqual(ri.codex_unavailable(quota), "usage limit")


FAKE_CODEX = """#!/bin/sh
cat > /dev/null
echo '{"type":"thread.started","thread_id":"T"}'
echo '{"type":"error","message":"You have hit your usage limit. Try again later."}'
exit 1
"""
FAKE_CLAUDE = """#!/bin/sh
cat > /dev/null
echo '{"type":"system","subtype":"init","session_id":"S2","model":"m","tools":["Read"]}'
echo '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash"}]}}'
echo '{"type":"result","result":"verdict","num_turns":2,"is_error":false,"permission_denials":[]}'
"""


class FallbackTest(unittest.TestCase):
    def test_auto_family_records_the_switch(self):
        with tempfile.TemporaryDirectory() as d:
            bindir = Path(d) / "bin"
            bindir.mkdir()
            for name, body in (("codex", FAKE_CODEX), ("claude", FAKE_CLAUDE)):
                (bindir / name).write_text(body)
                os.chmod(bindir / name, 0o755)
            work = Path(d) / "work"
            work.mkdir()
            pack = Path(d) / "pack.md"
            pack.write_text("pack")
            env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
            out = subprocess.run([sys.executable, str(RI), "code-verifier", "--dir", str(work), "--pack", str(pack),
                                  "--out", str(Path(d) / "ev"), "--agent-file", str(AGENTS / "code-verifier.md"),
                                  "--family", "auto"], capture_output=True, text=True, env=env, timeout=120)
            summary = json.loads((Path(d) / "ev/code-verifier.summary.json").read_text())
            self.assertEqual(summary["status"], "OK", out.stderr[-500:])
            self.assertEqual(summary["family"], "claude")
            self.assertEqual(summary["family_switch"]["from"], "codex")
            self.assertIn("usage limit", summary["family_switch"]["reason"])


FAKE_CODEX_OK = """#!/bin/sh
cat > /dev/null
out=""
while [ $# -gt 0 ]; do
  if [ "$1" = "-o" ]; then out="$2"; fi
  shift
done
printf 'REVIEW RESULT' > "$out"
echo '{"type":"thread.started","thread_id":"T"}'
echo '{"type":"item.completed","item":{"type":"command_execution"}}'
echo '{"type":"turn.completed"}'
"""
FAKE_CLAUDE_SILENT = """#!/bin/sh
cat > /dev/null
echo '{"type":"system","subtype":"init","session_id":"S3","model":"m","tools":["Read"]}'
exit 1
"""


class ResultAndFamilyTest(unittest.TestCase):
    def run_ri(self, d, fakes, *extra):
        bindir = Path(d) / "bin"
        bindir.mkdir(exist_ok=True)
        for name, body in fakes.items():
            (bindir / name).write_text(body)
            os.chmod(bindir / name, 0o755)
        work = Path(d) / "work"
        work.mkdir(exist_ok=True)
        pack = Path(d) / "pack.md"
        pack.write_text("pack")
        env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
        subprocess.run([sys.executable, str(RI), "code-verifier", "--dir", str(work), "--pack", str(pack),
                        "--out", str(Path(d) / "ev"), "--agent-file", str(AGENTS / "code-verifier.md"), *extra],
                       capture_output=True, text=True, env=env, timeout=120)
        return json.loads((Path(d) / "ev/code-verifier.summary.json").read_text())

    def test_codex_last_message_reaches_the_evidence_folder(self):
        with tempfile.TemporaryDirectory() as d:
            summary = self.run_ri(d, {"codex": FAKE_CODEX_OK}, "--family", "codex")
            self.assertEqual(summary["status"], "OK", summary)
            self.assertEqual((Path(d) / "ev/code-verifier.result.md").read_text(), "REVIEW RESULT")

    def test_an_earlier_attempts_result_never_stands_in(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "ev").mkdir()
            (Path(d) / "ev/code-verifier.result.md").write_text("OLD PASS")
            summary = self.run_ri(d, {"claude": FAKE_CLAUDE_SILENT}, "--family", "claude")
            self.assertEqual(summary["status"], "ERROR")
            self.assertFalse((Path(d) / "ev/code-verifier.result.md").exists())

    def test_named_network_hosts_are_reviewed_on_claude(self):
        with tempfile.TemporaryDirectory() as d:
            summary = self.run_ri(d, {"codex": FAKE_CODEX_OK, "claude": FAKE_CLAUDE}, "--family", "auto",
                                  "--network", "api.example.com")
            self.assertEqual(summary["family"], "claude")
            self.assertIn("Gate network", summary["family_switch"]["reason"])

    def test_caches_are_opened_by_name_and_browser_profiles_never(self):
        cfg = ri.settings("code-verifier", Path("/tmp/copy"))
        allow = cfg["sandbox"]["filesystem"]["allowRead"] + cfg["sandbox"]["filesystem"]["allowWrite"]
        for broad in (HOME / "Library/Caches", HOME / ".cache", HOME / "Library/Caches/ms-playwright"):
            self.assertNotIn(str(broad), allow)
        self.assertFalse([a for a in allow if "mcp-chrome" in a or "chrome-devtools-mcp" in a], allow)
        self.assertFalse([w for w in cfg["sandbox"]["filesystem"]["allowWrite"] if "ms-playwright" in w])
        prof = ri.codex_profile(Path("/tmp/copy"), Path("/tmp/codex-home"), [], Path("/tmp/private"))
        self.assertIn('(allow network-outbound (remote unix-socket (subpath "/tmp/copy")))', prof)
        self.assertNotIn("mcp-chrome", prof)


FAKE_CLAUDE_SLOW = """#!/bin/sh
cat > /dev/null
sleep 30
"""


class StopAndSandboxTest(unittest.TestCase):
    def test_uv_can_read_proxy_settings_and_tools_get_a_private_temp(self):
        cfg = ri.settings("code-verifier", Path("/tmp/copy"))
        self.assertEqual(cfg["sandbox"]["network"]["allowMachLookup"], ["com.apple.SystemConfiguration.configd"])
        with tempfile.TemporaryDirectory() as d:
            opts = {"deny": [], "project": None, "allow_read": [], "network": [], "effort": "low",
                    "agent_file": str(AGENTS / "code-verifier.md")}
            _, env, extra = ri.claude_cmd("code-verifier", opts, Path(d), Path(d) / "stem", "sid")
            try:
                for key in ("TMPDIR", "PYTEST_DEBUG_TEMPROOT", "CHECKER_TMP", "CLAUDE_CODE_TMPDIR"):
                    self.assertEqual(env[key], extra["private_tmp"], key)
            finally:
                ri.shutil.rmtree(extra["private_tmp"], ignore_errors=True)

    def test_a_stopped_checker_leaves_no_private_folder(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "home"
            (home / ".gate-copies").mkdir(parents=True)
            stale = home / ".gate-copies/tmp-old"
            stale.mkdir()
            os.utime(stale, (0, 0))
            bindir = Path(d) / "bin"
            bindir.mkdir()
            (bindir / "claude").write_text(FAKE_CLAUDE_SLOW)
            os.chmod(bindir / "claude", 0o755)
            work = Path(d) / "work"
            work.mkdir()
            pack = Path(d) / "pack.md"
            pack.write_text("pack")
            env = {**os.environ, "HOME": str(home), "PATH": f"{bindir}:{os.environ['PATH']}"}
            proc = subprocess.Popen([sys.executable, str(RI), "loyal-evaluator", "--dir", str(work), "--pack",
                                     str(pack), "--out", str(Path(d) / "ev"),
                                     "--agent-file", str(AGENTS / "loyal-evaluator.md")],
                                    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            deadline = time.time() + 20
            fresh = lambda: [t for t in (home / ".gate-copies").glob("tmp-*") if t != stale]
            while time.time() < deadline and not fresh():
                time.sleep(0.2)
            self.assertFalse(stale.exists(), "a folder left by a run killed hours ago is swept")
            self.assertTrue(fresh(), "the run made its private folder")
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=30)
            self.assertEqual(list((home / ".gate-copies").glob("tmp-*")), [], "stopping the run removes it")


    def test_a_stop_while_the_command_is_built_leaves_no_private_folder(self):
        """The stop handler raises SystemExit; one that lands after the private folder is made and before the run
        starts must still remove it (deterministic form of a race the timing test above can lose under load)."""
        sys.path.insert(0, str(RI.parent))  # as when the script runs: its own folder holds its modules
        with tempfile.TemporaryDirectory() as d:
            saved = ri.HOME, ri.settings

            def stopped(*args, **kwargs):
                raise SystemExit(128 + signal.SIGTERM)
            ri.HOME, ri.settings = Path(d), stopped
            try:
                opts = {"deny": [], "allow_read": [], "network": [], "effort": "high"}
                with self.assertRaises(SystemExit):
                    ri.run_once("loyal-evaluator", "claude", opts, Path(d), Path(d) / "x", "pack")
            finally:
                ri.HOME, ri.settings = saved
            self.assertEqual(list((Path(d) / ".gate-copies").glob("tmp-*")), [], "stopping the run removes it")


FAKE_CLAUDE_ROUTED = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
sys.stdin.read()
served = os.environ.get("FAKE_SERVED") or (args[args.index("--model") + 1] if "--model" in args else "claude-default-x")
print(json.dumps({"type": "system", "subtype": "init", "session_id": "S9", "model": served, "tools": ["Read"]}))
for f in [x for x in os.environ.get("FAKE_READS", "").split(",") if x]:
    path = f[4:] if f.startswith("rel:") else os.path.join(os.getcwd(), f)  # rel: passes the path as written
    print(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": path}}]}}))
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Grep",
                                                              "input": {"pattern": "x"}}]}}))
error = os.environ.get("FAKE_ERROR") == "1"
print(json.dumps({"type": "result", "result": None if error else "verdict", "num_turns": 2, "is_error": error,
                  "permission_denials": []}))
'''

AGENT_WITH_MODES = """---
name: code-verifier
description: test agent with mode sections
---
Common opening.

<!-- mode: review -->
REVIEW TEXT
<!-- end mode -->

<!-- mode: demo -->
DEMO TEXT
<!-- end mode -->

<!-- mode: reverify, refix -->
REVERIFY TEXT
<!-- end mode -->

Common closing.
"""


class RoutingTest(unittest.TestCase):
    """Model and effort routing, mode sections, and --require-read (no model calls; a stand-in claude)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.home = self.d / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.bin = self.d / "bin"
        self.bin.mkdir()
        (self.bin / "claude").write_text(FAKE_CLAUDE_ROUTED)
        os.chmod(self.bin / "claude", 0o755)
        self.work = self.d / "work"
        self.work.mkdir()
        (self.d / "pack.md").write_text("pack")
        self.env = {k: v for k, v in os.environ.items() if k != "PIPELINE_MODELS_IGNORE_OVERRIDE"}
        self.env.update({"HOME": str(self.home), "PATH": f"{self.bin}:{os.environ['PATH']}",
                         "HEAVY_LOCK_DIR": str(self.d / "lock")})

    def tearDown(self):
        self.tmp.cleanup()

    def run_ri(self, role, *extra, env=None, agent_file=None):
        ev = self.d / "ev"
        out = subprocess.run([sys.executable, str(RI), role, "--dir", str(self.work), "--pack", str(self.d / "pack.md"),
                              "--out", str(ev), "--agent-file", str(agent_file or AGENTS / f"{role}.md"), *extra],
                             capture_output=True, text=True, env={**self.env, **(env or {})}, timeout=120)
        stems = sorted(ev.glob("*.summary.json"), key=lambda p: p.stat().st_mtime) if ev.is_dir() else []
        summary = json.loads(stems[-1].read_text()) if stems else {"err": out.stderr}
        return out, summary

    def override(self, routes):
        (self.home / ".claude/.pipeline-models.json").write_text(json.dumps({"routes": routes}))

    def test_model_flag_only_when_a_model_is_named(self):
        out, s = self.run_ri("loyal-evaluator", "--dry-run")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("--model", s["cmd"], "the default route leaves the Claude Code default")
        self.assertEqual(s["cmd"][s["cmd"].index("--effort") + 1], "xhigh")
        self.assertEqual((s["route"], s["requested_model"], s["requested_effort"], s["model_source"]),
                         ("loyal-evaluator", "default", "xhigh", "repo"))
        out, s = self.run_ri("loyal-evaluator", "--dry-run", "--model", "claude-sonnet-5-5", "--effort", "low")
        self.assertEqual(s["cmd"][s["cmd"].index("--model") + 1], "claude-sonnet-5-5")
        self.assertEqual(s["cmd"][s["cmd"].index("--effort") + 1], "low")
        self.assertEqual((s["model_source"], s["effort_source"]), ("flag", "flag"))
        agents = json.loads((self.d / "ev/loyal-evaluator.agents.json").read_text())
        self.assertEqual(set(agents["loyal-evaluator"]), {"description", "prompt"}, "model and effort are CLI flags")

    def test_the_route_and_the_override_pick_the_model(self):
        self.override({"code-verifier.demo": {"model": "claude-sonnet-5-5", "effort": "high"}})
        out, s = self.run_ri("code-verifier", "--dry-run", "--mode", "demo")
        self.assertEqual(out.returncode, 0, out.stderr)
        cmd = s["cmd"]
        self.assertEqual((cmd[cmd.index("--model") + 1], cmd[cmd.index("--effort") + 1]), ("claude-sonnet-5-5", "high"))
        self.assertEqual((s["route"], s["model_source"], s["route_from"]),
                         ("code-verifier.demo", "override", "derived from the role and mode"))
        out, s = self.run_ri("code-verifier", "--dry-run", "--mode", "demo",
                             env={"PIPELINE_MODELS_IGNORE_OVERRIDE": "1"})
        self.assertNotIn("--model", s["cmd"], "the benchmarks measure the repository table")
        out, s = self.run_ri("code-verifier", "--dry-run", "--route", "code-verifier.review")
        self.assertEqual((s["route"], s["route_from"]), ("code-verifier.review", "--route"))

    def test_route_derivation_follows_the_pack(self):
        def name(role, **opts):
            return ri.route_name(role, opts)[0]
        self.assertEqual(name("cold-reader", render=["--with-record", "--docs", "a.md", "--"]), "cold-reader.documents")
        self.assertEqual(name("cold-reader", render=["--docs", "a.md", "--previous", "r.md"]), "cold-reader.reread")
        self.assertEqual(name("cold-reader", render=["--milestone", "M1", "--inputs", "understanding"]),
                         "cold-reader.understanding")
        self.assertEqual(name("cold-reader", render=["--mode", "extract", "--docs", "t.md"]), "cold-reader.extract")
        self.assertEqual(name("cold-reader", render=["--mode", "fidelity", "--docs", "t.md"]), "cold-reader.fidelity")
        self.assertEqual(name("cold-reader", render=["--mode", "fidelity", "--docs", "t.md", "--previous", "r.md"]),
                         "cold-reader.refidelity")
        self.assertEqual(name("code-verifier", mode="demo", render=["--mode", "demo"]), "code-verifier.demo")
        self.assertEqual(name("code-verifier", render=["--milestone", "M1", "--copy", "/c"]), "code-verifier.review")
        self.assertEqual(name("loyal-evaluator", render=["--pass", "2"]), "loyal-evaluator")
        self.assertEqual(name("claim-verifier", render=["--inputs", "claims.md"]), "claim-verifier")
        self.assertEqual(name("cold-reader", route="cold-reader.reread"), "cold-reader.reread")

    def test_a_route_that_cannot_resolve_is_an_error_with_its_reason(self):
        for extra, words in ((["--route", "nope"], "unknown route 'nope'"),
                             (["--model", "claude-fable-5"], "Fable or Mythos"),
                             (["--model", "claude-opus-4-1"], "not allowed"),
                             (["--route", "explorer"], "builder-side")):
            out, s = self.run_ri("gate-judge", "--dry-run", *extra)
            self.assertEqual(out.returncode, 1, extra)
            self.assertEqual(s["status"], "ERROR", extra)
            self.assertIn(words, s["reason"], extra)
            self.assertIn("model routing", out.stderr)
        self.override({"gate-judge": {"model": "claude-mythos-1"}})
        out, s = self.run_ri("gate-judge", "--dry-run")
        self.assertEqual((s["status"], s["route"]), ("ERROR", "gate-judge"))
        self.assertIn("route gate-judge", s["reason"])

    def test_the_codex_family_records_the_route_without_applying_it(self):
        (self.bin / "codex").write_text(FAKE_CODEX_OK)
        os.chmod(self.bin / "codex", 0o755)
        out, s = self.run_ri("code-verifier", "--dry-run", "--family", "codex", "--model", "claude-sonnet-5-5")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual((s["family"], s["route"], s["route_applies"]), ("codex", "code-verifier.review", False))
        self.assertNotIn("requested_model", s)
        self.assertNotIn("claude-sonnet-5-5", s["cmd"])
        self.assertIn('model_reasoning_effort="xhigh"', s["cmd"], "the Codex command is as before")
        out, s = self.run_ri("code-verifier", "--dry-run", "--family", "codex", "--model", "claude-fable-5")
        self.assertEqual(s["status"], "DRY_RUN", "a Claude routing problem does not stop a Codex run")
        self.assertEqual((s["route"], s["route_applies"]), ("code-verifier.review", False))
        self.assertIn("Fable or Mythos", s["route_error"], "but it stays on record")

    def test_the_summary_records_what_was_asked_and_what_served(self):
        out, s = self.run_ri("loyal-evaluator", "--model", "claude-sonnet-5-5")
        self.assertEqual(s["status"], "OK", out.stderr[-500:])
        self.assertEqual((s["requested_model"], s["served_model"], s["model_mismatch"]),
                         ("claude-sonnet-5-5", "claude-sonnet-5-5", False))
        out, s = self.run_ri("loyal-evaluator", "--model", "claude-sonnet-5-5", env={"FAKE_SERVED": "claude-opus-5-5"})
        self.assertTrue(s["model_mismatch"])
        self.assertIn("asked for claude-sonnet-5-5, served by claude-opus-5-5", out.stderr)
        out, s = self.run_ri("loyal-evaluator", env={"FAKE_SERVED": "claude-opus-5-5-20261001"})
        self.assertEqual((s["requested_model"], s["served_model"], s["model_mismatch"]),
                         ("default", "claude-opus-5-5-20261001", False))
        prompt = json.loads((self.d / "ev/loyal-evaluator.agents.json").read_text())["loyal-evaluator"]["prompt"]
        self.assertEqual(s["prompt_sha256"], ri.hashlib.sha256(prompt.encode()).hexdigest())
        self.assertEqual(len(s["agent_sha256"]), 64)

    def test_mode_sections_keep_the_common_text_and_this_runs_mode(self):
        agent = self.d / "code-verifier.md"
        agent.write_text(AGENT_WITH_MODES)
        out, s = self.run_ri("code-verifier", "--dry-run", "--mode", "demo", agent_file=agent)
        self.assertEqual(out.returncode, 0, out.stderr)
        prompt = json.loads((self.d / "ev/code-verifier-demo.agents.json").read_text())["code-verifier"]["prompt"]
        self.assertEqual(prompt, "Common opening.\n\nDEMO TEXT\n\nCommon closing.")
        self.assertEqual(s["mode_sections"], {"kept": ["demo"], "dropped": ["refix", "reverify", "review"]})
        self.assertEqual(s["prompt_sha256"], ri.hashlib.sha256(prompt.encode()).hexdigest())
        out, s = self.run_ri("code-verifier", "--dry-run", "--route", "code-verifier.reverify", agent_file=agent)
        prompt = json.loads((self.d / "ev/code-verifier.agents.json").read_text())["code-verifier"]["prompt"]
        self.assertIn("REVERIFY TEXT", prompt)
        self.assertIn("REVIEW TEXT", prompt, "a re-verify keeps the review sections (its earlier name)")
        self.assertNotIn("DEMO TEXT", prompt)
        self.assertNotIn("<!--", prompt)

    def test_a_codex_run_gets_the_same_mode_cut(self):
        agent = self.d / "code-verifier.md"
        agent.write_text(AGENT_WITH_MODES)
        (self.bin / "codex").write_text(FAKE_CODEX_OK)
        os.chmod(self.bin / "codex", 0o755)
        work = self.d / "work"
        work.mkdir(exist_ok=True)
        saved = (ri.HOME, os.environ["PATH"])
        ri.HOME, os.environ["PATH"] = self.home, f"{self.bin}:{saved[1]}"
        try:
            opts = {"allow_read": [], "effort": "xhigh", "agent_file": str(agent),
                    "_routing": {"sections": ["review"]}}
            cmd, env, extra = ri.codex_cmd("code-verifier", opts, work, self.d / "code-verifier", "sid")
        finally:
            ri.HOME, os.environ["PATH"] = saved
            for made in ri.MADE:
                shutil.rmtree(made, ignore_errors=True)
        self.assertIn("REVIEW TEXT", extra["prefix"])
        self.assertNotIn("DEMO TEXT", extra["prefix"], "a Codex review never carries the demo instructions")
        self.assertNotIn("REVERIFY TEXT", extra["prefix"])

    def test_a_body_without_markers_is_unchanged(self):
        agent = self.d / "plain.md"
        agent.write_text("---\nname: gate-judge\ndescription: x\n---\nRead the evidence.\n\n<!-- a note -->\nDecide.\n")
        path, meta, body = ri.read_agent("gate-judge", str(agent))
        self.assertEqual(ri.mode_sections(body, {"documents", "demo"}), (body, None))
        self.assertEqual(ri.read_agent("gate-judge", str(agent), {"x"})[2], body)

    def test_broken_mode_markers_are_named(self):
        for body, words in (("a\n<!-- mode: demo -->\nb", "never closed"),
                            ("a\n<!-- end mode -->", "without an open"),
                            ("<!-- mode: a -->\n<!-- mode: b -->\n<!-- end mode -->", "inside another")):
            with self.assertRaises(ri.AgentError) as cm:
                ri.mode_sections(body, {"a"})
            self.assertIn(words, str(cm.exception))
        agent = self.d / "code-verifier.md"
        agent.write_text("---\nname: code-verifier\ndescription: x\n---\nA\n<!-- mode: demo -->\nB\n")
        out, s = self.run_ri("code-verifier", "--mode", "demo", agent_file=agent)
        self.assertEqual(s["status"], "ERROR")
        self.assertIn("never closed", s["reason"])

    def test_require_read_needs_every_matching_file_opened(self):
        (self.work / "captures").mkdir()
        for name in ("M1-1.png", "M1-2.txt"):
            (self.work / "captures" / name).write_text("x")
        out, s = self.run_ri("gate-judge", "--require-read", "captures/*", env={"FAKE_READS": "captures/M1-1.png"})
        self.assertEqual(s["status"], "INCONCLUSIVE", out.stderr[-300:])
        self.assertEqual(s["reason"], "did not open: captures/M1-2.txt")
        self.assertEqual(out.returncode, 1)
        out, s = self.run_ri("gate-judge", "--require-read", "captures/*",
                             env={"FAKE_READS": f"captures/M1-1.png,rel:captures/M1-2.txt"})
        self.assertEqual(s["status"], "OK", s)
        self.assertEqual(s["require_read"]["files"], 2)
        out, s = self.run_ri("gate-judge", "--require-read", "captures/*", env={"FAKE_ERROR": "1"})
        self.assertEqual(s["status"], "ERROR", "a run that did not end OK keeps its own status")
        out, s = self.run_ri("gate-judge", "--require-read", "none/*")
        self.assertEqual(s["status"], "OK", "a glob that matches nothing asks for nothing")
        for bad in ("/etc/*", "../x/*"):
            out, _ = self.run_ri("gate-judge", "--require-read", bad)
            self.assertEqual(out.returncode, 2, bad)

    def test_read_paths_come_from_read_tool_calls(self):
        lines = [json.dumps({"type": "assistant", "message": {"content": [
                     {"type": "tool_use", "name": "Read", "input": {"file_path": "/w/a.png"}},
                     {"type": "tool_use", "name": "Grep", "input": {"path": "/w/b.txt"}}]}}),
                 json.dumps({"type": "result", "result": "ok", "num_turns": 1, "is_error": False})]
        self.assertEqual(ri.parse_claude_stream(lines)["read_paths"], ["/w/a.png"])


FAKE_CLAUDE_SHADOW = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
sys.stdin.read()
model = args[args.index("--model") + 1] if "--model" in args else "claude-default-x"
shadow = model == os.environ.get("FAKE_SHADOW_MODEL", "claude-opus-5-5")
side = "SHADOW_" if shadow else ""
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps({"model": model, "cwd": os.getcwd(), "args": args}) + "\n")
print(json.dumps({"type": "system", "subtype": "init", "session_id": "S", "model": model, "tools": ["Read"]}))
for name in [x for x in os.environ.get(f"FAKE_{side}READS", "").split(",") if x]:
    print(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": os.path.join(os.getcwd(), name)}}]}}))
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Grep",
                                                              "input": {"pattern": "x"}}]}}))
error = os.environ.get(f"FAKE_{side}ERROR") == "1"
answer = os.environ.get(f"FAKE_{side}RESULT") or "verdict"
print(json.dumps({"type": "result", "result": None if error else answer, "num_turns": 2, "is_error": error,
                  "permission_denials": [], "usage": {"input_tokens": 5, "output_tokens": 7}}))
'''


def judge_answer(drift):
    rows = [{"id": "I-D1", "status": "HOLDS"}, {"id": "I-D2", "status": "DRIFT" if drift else "HOLDS"}]
    return "Prose.\n```json\n" + json.dumps({"verdict": "CHANGES" if drift else "ACCEPT-READY",
                                             "intent_diff": rows}) + "\n```"


class ShadowRunTest(unittest.TestCase):
    """Shadow runs beside a checker (plan 7.3 step 4): no model calls, a stand-in claude that logs each call."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.home = self.d / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.bin = self.d / "bin"
        self.bin.mkdir()
        (self.bin / "claude").write_text(FAKE_CLAUDE_SHADOW)
        os.chmod(self.bin / "claude", 0o755)
        self.work = self.d / "work"
        self.work.mkdir()
        (self.d / "pack.md").write_text("pack")
        self.calls = self.d / "calls.jsonl"
        self.env = {k: v for k, v in os.environ.items() if k != "PIPELINE_MODELS_IGNORE_OVERRIDE"}
        self.env.update({"HOME": str(self.home), "PATH": f"{self.bin}:{os.environ['PATH']}",
                         "HEAVY_LOCK_DIR": str(self.d / "lock"), "FAKE_CALLS": str(self.calls)})
        self.log = self.home / ".claude/.pipeline-shadow.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def run_ri(self, role, *extra, env=None, out=None, workdir=None):
        ev = Path(out or self.d / "ev")
        stem = f"{role}{'-demo' if '--mode' in extra and 'demo' in extra else ''}" + \
            ("-pass2" if "--resume" in extra else "")
        path = ev / f"{stem}.summary.json"
        path.unlink(missing_ok=True)
        proc = subprocess.run([sys.executable, str(RI), role, "--dir", str(workdir or self.work), "--pack",
                               str(self.d / "pack.md"), "--out", str(ev), "--agent-file", str(AGENTS / f"{role}.md"),
                               *extra], capture_output=True, text=True, env={**self.env, **(env or {})}, timeout=120)
        return proc, (json.loads(path.read_text()) if path.is_file() else {"err": proc.stderr}), ev

    def ran(self):
        return [json.loads(x) for x in self.calls.read_text().splitlines()] if self.calls.is_file() else []

    def override(self, shadow):
        (self.home / ".claude/.pipeline-models.json").write_text(json.dumps({"shadow": shadow}))

    def test_no_shadow_by_default(self):
        proc, s, ev = self.run_ri("gate-judge")
        self.assertEqual(s["status"], "OK", proc.stderr[-400:])
        self.assertNotIn("shadow", s)
        self.assertEqual(len(self.ran()), 1)
        self.assertFalse((ev / "shadow").exists())
        self.assertFalse(self.log.exists())

    def test_the_flag_runs_a_shadow_and_compares_it(self):
        proj = self.d / "proj"
        proj.mkdir()
        (proj / ".coding-pipeline.json").write_text('{"version":1,"managed":true}')
        out = proj / ".evidence/gate/M1/r2"
        proc, s, ev = self.run_ri("gate-judge", "--project", str(proj), "--shadow", "claude-opus-5-5:high",
                                  out=out, env={"FAKE_RESULT": judge_answer(True), "FAKE_SHADOW_RESULT": judge_answer(False)})
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        self.assertEqual(s["status"], "OK")
        sh = s["shadow"]
        self.assertEqual((sh["route"], sh["model"], sh["effort"], sh["source"], sh["status"]),
                         ("gate-judge", "claude-opus-5-5", "high", "flag", "OK"))
        self.assertEqual((sh["misses"], sh["extras"]), (1, 0), "the shadow called the primary's DRIFT a HOLDS")
        calls = self.ran()
        self.assertEqual(len(calls), 2)
        self.assertNotIn("--model", calls[0]["args"], "the main run keeps its own route")
        self.assertEqual((calls[1]["args"][calls[1]["args"].index("--model") + 1],
                          calls[1]["args"][calls[1]["args"].index("--effort") + 1]), ("claude-opus-5-5", "high"))
        self.assertEqual(calls[1]["cwd"], str(self.work.resolve()), "a role that only reads reuses the main folder")
        shadow = json.loads((out / "shadow/gate-judge.summary.json").read_text())
        self.assertEqual((shadow["requested_model"], shadow["requested_effort"], shadow["served_model"]),
                         ("claude-opus-5-5", "high", "claude-opus-5-5"))
        self.assertEqual(shadow["usage"]["output"], 7, "the shadow's usage is in its own summary")
        self.assertEqual((out / "shadow/gate-judge.pack.md").read_text(), (out / "gate-judge.pack.md").read_text())
        diff = json.loads((out / "shadow/gate-judge.shadow-diff.json").read_text())
        self.assertEqual(diff["shadow_missed"][0]["key"], "I-D2")
        self.assertEqual(sh["diff"], str(out / "shadow/gate-judge.shadow-diff.json"))
        self.assertIn("ACCEPT-READY", (out / "shadow/gate-judge.result.md").read_text())
        self.assertIn("CHANGES", (out / "gate-judge.result.md").read_text(), "the main result is its own")
        line = json.loads(self.log.read_text().splitlines()[-1])
        self.assertEqual((line["project"], line["evidence"], line["route"], line["round"], line["misses"],
                          line["extras"]), (str(proj.resolve()), str(out.resolve()), "gate-judge", 2, 1, 0))
        self.assertEqual(line["primary"], {"model": "default", "effort": "xhigh", "served": "claude-default-x"})
        self.assertEqual(line["shadow"], {"model": "claude-opus-5-5", "effort": "high", "served": "claude-opus-5-5",
                                          "status": "OK"})
        spec = importlib.util.spec_from_file_location("spend", RI.parent / "spend.py")
        spend = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(RI.parent))
        spec.loader.exec_module(spend)
        counted = {r["path"] for r in spend.run_summaries(proj) if r["usage"]}
        self.assertIn("gate/M1/r2/shadow/gate-judge.summary.json", counted, "spend.py counts the shadow run")

    def test_the_override_entry_applies_and_the_flag_wins(self):
        self.override({"gate-judge": {"model": "claude-opus-5-5", "effort": "high"}})
        proc, s, _ = self.run_ri("gate-judge")
        self.assertEqual((s["shadow"]["effort"], s["shadow"]["source"], s["shadow"]["status"]),
                         ("high", "override", "OK"), proc.stderr[-400:])
        proc, s, _ = self.run_ri("gate-judge", "--shadow", "claude-opus-5-5:medium")
        self.assertEqual((s["shadow"]["effort"], s["shadow"]["source"]), ("medium", "flag"))
        proc, s, _ = self.run_ri("gate-judge", env={"PIPELINE_MODELS_IGNORE_OVERRIDE": "1"})
        self.assertNotIn("shadow", s, "the benchmarks ignore the override's shadows too")

    def test_no_shadow_turns_it_off(self):
        self.override({"gate-judge": {"model": "claude-opus-5-5", "effort": "high"}})
        proc, s, ev = self.run_ri("gate-judge", "--no-shadow")
        self.assertEqual(s["shadow"]["skipped"], "turned off by --no-shadow")
        self.assertEqual(len(self.ran()), 1)
        self.assertFalse((ev / "shadow").exists())

    def test_a_shadow_never_changes_the_main_run(self):
        answer = judge_answer(True)
        proc, s, ev = self.run_ri("gate-judge", "--shadow", "claude-opus-5-5:high",
                                  env={"FAKE_SHADOW_ERROR": "1", "FAKE_RESULT": answer})
        self.assertEqual((proc.returncode, s["status"]), (0, "OK"), proc.stderr[-400:])
        self.assertEqual(s["shadow"]["status"], "ERROR")
        self.assertIsNone(s["shadow"]["misses"])
        self.assertIn("shadow result", s["shadow"]["diff_error"])
        self.assertEqual((ev / "gate-judge.result.md").read_text(), answer)
        self.assertEqual(len(self.ran()), 2, "never retried, never escalated")
        line = json.loads(self.log.read_text().splitlines()[-1])
        self.assertEqual((line["shadow"]["status"], line["misses"], line["round"]), ("ERROR", None, None))
        proc, s, ev = self.run_ri("gate-judge", "--shadow", "claude-opus-5-5:high", env={"FAKE_ERROR": "1"})
        self.assertEqual((proc.returncode, s["status"]), (1, "ERROR"))
        self.assertEqual(s["shadow"]["skipped"], "the main run ended ERROR")
        self.assertEqual(len(self.ran()), 3, "no shadow beside a main run that did not end OK")
        proc, s, _ = self.run_ri("gate-judge", "--shadow", "claude-fable-5:high")
        self.assertEqual(s["status"], "OK", "a bad shadow setting never stops the main run")
        self.assertIn("Fable or Mythos", s["shadow"]["skipped"])

    def test_require_read_applies_to_the_shadow(self):
        (self.work / "captures").mkdir()
        (self.work / "captures/M1-1.png").write_text("x")
        proc, s, _ = self.run_ri("gate-judge", "--require-read", "captures/*", "--shadow", "claude-opus-5-5:high",
                                 env={"FAKE_READS": "captures/M1-1.png"})
        self.assertEqual(s["status"], "OK", proc.stderr[-400:])
        self.assertEqual(s["shadow"]["status"], "INCONCLUSIVE")

    def test_the_code_verifier_needs_its_own_copy(self):
        proc, s, ev = self.run_ri("code-verifier", "--mode", "demo", "--shadow", "claude-sonnet-5-5:high",
                                  env={"FAKE_SHADOW_MODEL": "claude-sonnet-5-5"})
        self.assertEqual(s["status"], "OK", proc.stderr[-400:])
        self.assertEqual(s["shadow"]["skipped"], "no separate copy (--shadow-dir)")
        self.assertIn("shadow skipped: no separate copy (--shadow-dir)", proc.stderr)
        self.assertEqual(len(self.ran()), 1)
        copy = self.d / "shadow-copy"
        (copy / ".demo-captures").mkdir(parents=True)
        (copy / ".demo-captures/M1-1.txt").write_text("seen")
        (self.d / "pack.md").write_text(f"Inventory of {self.work}/src: a.py\n")
        proc, s, ev = self.run_ri("code-verifier", "--mode", "demo", "--shadow", "claude-sonnet-5-5:high",
                                  "--shadow-dir", str(copy), env={"FAKE_SHADOW_MODEL": "claude-sonnet-5-5"})
        self.assertEqual(s["shadow"]["status"], "OK", proc.stderr[-400:])
        self.assertEqual(self.ran()[-1]["cwd"], str(copy.resolve()))
        cfg = json.loads((ev / "shadow/code-verifier-demo.settings.json").read_text())
        self.assertIn(str(copy.resolve()), cfg["sandbox"]["filesystem"]["allowWrite"])
        self.assertNotIn(str(self.work.resolve()), cfg["sandbox"]["filesystem"]["allowWrite"])
        spack = (ev / "shadow/code-verifier-demo.pack.md").read_text()
        self.assertIn(f"Working copy: {copy.resolve()}", spack)
        self.assertIn(f"Inventory of {copy.resolve()}/src: a.py", spack)
        self.assertIn(f"Inventory of {self.work}/src", (ev / "code-verifier-demo.pack.md").read_text())
        self.assertNotIn(str(self.work.resolve()), spack, "the shadow's pack names its own copy")
        self.assertEqual((ev / "shadow/captures/M1-1.txt").read_text(), "seen", "its captures are kept")
        proc, s, _ = self.run_ri("code-verifier", "--shadow", "claude-sonnet-5-5:high", "--shadow-dir",
                                 str(self.work), env={"FAKE_SHADOW_MODEL": "claude-sonnet-5-5"})
        self.assertIn("own copy", s["shadow"]["skipped"])

    def test_the_loyal_evaluator_and_a_resumed_run_are_never_shadowed(self):
        self.override({"loyal-evaluator": {"model": "claude-opus-5-5", "effort": "high"},
                       "gate-judge": {"model": "claude-opus-5-5", "effort": "high"}})
        proc, s, _ = self.run_ri("loyal-evaluator")
        self.assertEqual(s["status"], "OK", proc.stderr[-400:])
        self.assertIn("its later passes resume pass 1's session", s["shadow"]["skipped"])
        proc, s, _ = self.run_ri("gate-judge", "--resume", "abc")
        self.assertIn("resumed pass is never shadowed", s["shadow"]["skipped"])
        self.assertEqual(len(self.ran()), 2)

    def test_the_codex_family_is_never_shadowed(self):
        (self.bin / "codex").write_text(FAKE_CODEX_OK)
        os.chmod(self.bin / "codex", 0o755)
        proc, s, _ = self.run_ri("code-verifier", "--dry-run", "--family", "codex", "--shadow",
                                 "claude-opus-5-5:high", "--shadow-dir", str(self.d))
        self.assertEqual(s["family"], "codex", proc.stderr[-400:])
        self.assertIn("Codex family", s["shadow"]["skipped"])

    def test_a_dry_run_shows_the_shadow_command_and_runs_nothing(self):
        proc, s, ev = self.run_ri("gate-judge", "--dry-run", "--shadow", "claude-opus-5-5:high")
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        sh = json.loads(proc.stdout)["shadow"]
        self.assertEqual(sh["status"], "DRY_RUN")
        self.assertEqual(sh["cmd"][sh["cmd"].index("--model") + 1], "claude-opus-5-5")
        self.assertEqual(self.ran(), [])
        self.assertFalse((ev / "shadow/gate-judge.summary.json").exists())
        self.assertFalse(self.log.exists())


FAKE_CLAUDE_SEES = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
pack = sys.stdin.read()
dirs = [args[i + 1] for i, a in enumerate(args) if a == "--add-dir"]
with open(os.environ["FAKE_SEEN"], "a") as f:
    f.write(json.dumps({"stdin": pack, "add_dirs": dirs, "present": [os.path.isdir(d) for d in dirs],
                        "model": args[args.index("--model") + 1] if "--model" in args else None}) + "\n")
print(json.dumps({"type": "system", "subtype": "init", "session_id": "S", "model": "m", "tools": ["Read"]}))
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}))
print(json.dumps({"type": "result", "result": "verdict", "num_turns": 1, "is_error": False, "permission_denials": []}))
'''


class ChangePatchTest(unittest.TestCase):
    """render_pack.py writes <stem>.change.patch beside a review pack, in the project the checker may never read:
    the run gets its own read-only copy, and the pack names that copy."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.home, self.bin = self.d / "home", self.d / "bin"
        self.home.mkdir()
        self.bin.mkdir()
        for name, body in (("claude", FAKE_CLAUDE_SEES), ("codex", FAKE_CODEX_OK)):
            (self.bin / name).write_text(body)
            os.chmod(self.bin / name, 0o755)
        self.proj = self.d / "proj"
        (self.proj / "docs/project").mkdir(parents=True)
        (self.proj / ".coding-pipeline.json").write_text('{"version":1,"managed":true}')
        self.out = self.proj / ".evidence/gate/M1/r1"
        self.out.mkdir(parents=True)
        self.patch = self.out / "code-verifier.change.patch"
        self.seen = self.d / "seen.jsonl"
        self.env = {**os.environ, "HOME": str(self.home), "PATH": f"{self.bin}:{os.environ['PATH']}",
                    "HEAVY_LOCK_DIR": str(self.d / "lock"), "FAKE_SEEN": str(self.seen)}
        self.env.pop("PIPELINE_MODELS_IGNORE_OVERRIDE", None)

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, *extra, patch=True):
        """A review run whose pack render_pack.py writes with the change since the M1 baseline, so it names the
        evidence patch beside the pack (no baseline: no patch)."""
        if patch:
            (self.proj / "x.py").write_text("a\n")
            subprocess.run([sys.executable, str(RI.parent / "baseline.py"), "record", str(self.proj), "M1"],
                           check=True, capture_output=True, env=self.env)
            (self.proj / "x.py").write_text("b\n")
        (self.d / "work").mkdir(exist_ok=True)
        proc = subprocess.run([sys.executable, str(RI), "code-verifier", "--dir", str(self.d / "work"), "--out",
                               str(self.out), "--project", str(self.proj), "--agent-file",
                               str(AGENTS / "code-verifier.md"), "--render", "--milestone", "M1", "--", *extra],
                              capture_output=True, text=True, env=self.env, timeout=120)
        summary = json.loads((self.out / "code-verifier.summary.json").read_text())
        seen = [json.loads(x) for x in self.seen.read_text().splitlines()] if self.seen.is_file() else []
        return proc, summary, seen

    def test_the_checker_reads_its_own_copy_and_nothing_in_the_project(self):
        proc, s, seen = self.render("--shadow", "claude-sonnet-5-5:high", "--shadow-dir", str(self.d))
        self.assertEqual(s["status"], "OK", proc.stderr[-400:])
        evidence, readable = str(self.patch.resolve()), s["change_patch_readable"]
        folder = str(Path(readable).parent)
        self.assertEqual(s["change_patch"], evidence)
        self.assertTrue(Path(readable).name == self.patch.name and folder.startswith(str(self.home / ".gate-copies")))
        main, shadow = seen
        self.assertIn(f"The full patch: {readable}.", main["stdin"], "the pack fed to the checker names the copy")
        self.assertNotIn(evidence, main["stdin"])
        self.assertEqual(s["pack_sha256"], ri.hashlib.sha256(main["stdin"].encode()).hexdigest(),
                         "the pack's sha256 is of the pack as fed")
        self.assertIn(readable, (self.out / "code-verifier.pack.md").read_text())
        self.assertIn(folder, main["add_dirs"], "--restricted lets the Read tool open it")
        self.assertTrue(main["present"][main["add_dirs"].index(folder)])
        cfg = json.loads((self.out / "code-verifier.settings.json").read_text())
        allow = cfg["sandbox"]["filesystem"]["allowRead"]
        self.assertIn(folder, allow)
        self.assertEqual([a for a in allow if a.startswith(str(self.proj.resolve()))], [],
                         "nothing under the project is allowed")
        self.assertIn(f"Edit(/{folder}/**)", cfg["permissions"]["deny"], "read-only, like the stacks folder")
        self.assertNotIn(folder, cfg["sandbox"]["filesystem"]["allowWrite"])
        self.assertEqual(shadow["model"], "claude-sonnet-5-5")
        self.assertIn(readable, shadow["stdin"], "the shadow reads the same copy")
        self.assertTrue(shadow["present"][shadow["add_dirs"].index(folder)], "it lasts until the shadow ends")
        self.assertFalse(Path(folder).exists(), "and is removed when the run ends")
        self.assertEqual(list((self.home / ".gate-copies").glob("patch-*")), [])

    def test_no_patch_no_copy(self):
        proc, s, seen = self.render(patch=False)
        self.assertEqual(s["status"], "OK", proc.stderr[-400:])
        self.assertNotIn("change_patch", s)
        self.assertFalse([d for d in seen[0]["add_dirs"] if "patch-" in d])
        self.assertFalse((self.home / ".gate-copies").is_dir() and
                         list((self.home / ".gate-copies").glob("patch-*")))

    def test_the_codex_fence_reads_the_copy(self):
        proc, s, _ = self.render("--family", "codex", "--dry-run")
        self.assertEqual(s["status"], "DRY_RUN", proc.stderr[-400:])
        profile = (self.out / "code-verifier.sb").read_text()
        self.assertIn(f'(allow file-read* (subpath "{Path(s["change_patch_readable"]).parent}"))', profile)
        self.assertNotIn(str(self.patch.resolve()), profile)
        self.assertFalse(Path(s["change_patch_readable"]).exists())


class ProjectServerTest(unittest.TestCase):
    def test_server_from_the_real_project_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "proj"
            proj.mkdir()
            proc = subprocess.Popen([sys.executable, "-m", "http.server", "0", "--bind", "127.0.0.1"], cwd=proj,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                import time
                time.sleep(1.5)
                hits = ri.project_servers(str(proj))
                self.assertTrue(any(str(proc.pid) in h for h in hits), hits)
                self.assertEqual(ri.project_servers(str(Path(d) / "elsewhere")), [])
            finally:
                proc.terminate()
                proc.wait()


if __name__ == "__main__":
    unittest.main()
