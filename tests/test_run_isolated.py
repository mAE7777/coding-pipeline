"""Unit tests for run_isolated.py (no model calls): settings, command shape, stream parsing, statuses."""
import http.server
import importlib.util
import json
import os
import socketserver
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
