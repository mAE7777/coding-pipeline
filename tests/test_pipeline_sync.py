"""Tests for pipeline_sync.py: /pipeline update, status, and the two notice hooks, against a throwaway home folder
and a throwaway pipeline repository with a bare origin. The repository's install.py and settings_patch.py are
stand-ins that log their calls, so no real install runs."""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "skills/_shared/scripts/pipeline_sync.py"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

# The stand-in install.py: apply copies skills/, agents/, hooks/ into ~/.claude and writes a manifest like the real
# one (revision, repo, a sha256 per installed file); check passes when the manifest names HEAD.
STUB_INSTALL = r'''import datetime, hashlib, json, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parent
argv = sys.argv[1:]
home = Path(argv[argv.index("--home") + 1])
with open(home / "calls.log", "a") as f:
    f.write("install.py " + argv[0] + "\n")
head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
manifest = home / ".claude/.pipeline-install.json"
if argv[0] == "apply":
    if (home / "fail-apply").exists():
        print("STOP   install     changed or added under ~/.claude since the last install: " + str(home / "x"))
        print("install: nothing changed.")
        sys.exit(1)
    files = {}
    for part in ("skills", "agents", "hooks"):
        for p in sorted((REPO / part).rglob("*")):
            if p.is_file():
                dst = home / ".claude" / p.relative_to(REPO)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(p.read_bytes())
                files[str(dst)] = hashlib.sha256(p.read_bytes()).hexdigest()
    manifest.write_text(json.dumps({"installed": datetime.datetime.now().isoformat(), "revision": head,
                                    "repo": str(REPO), "files": files}, indent=1))
    print("installed: %d action(s)" % len(files))
    sys.exit(0)
ok = json.loads(manifest.read_text())["revision"] == head and not (home / "fail-check").exists()
print("PASS   install     files current" if ok else "FAIL   install     installed from another revision")
sys.exit(0 if ok else 1)
'''
STUB_SETTINGS = r'''import sys
from pathlib import Path
argv = sys.argv[1:]
home = Path(argv[argv.index("--home") + 1])
with open(home / "calls.log", "a") as f:
    f.write("settings_patch.py " + " ".join(a for a in argv if a.startswith("--a")) + "\n")
'''
# A git on PATH that logs every call: the prompt hook must never run it.
LOGGING_GIT = """#!/bin/sh
echo "$@" >> "{log}"
exec {git} "$@"
"""


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.home = d / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.origin = d / "origin.git"
        self.repo = d / "repo"
        self.work = d / "work"
        git(d, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(d, "init", "-q", "-b", "main", str(self.repo))
        files = {"install.py": STUB_INSTALL, "settings_patch.py": STUB_SETTINGS, "skills/dev/SKILL.md": "dev v1\n",
                 "skills/gate/SKILL.md": "gate v1\n", "skills/_shared/scripts/gate_run.py": "# v1\n",
                 "skills/_shared/references/project-control.md": "control v1\n",
                 "agents/code-verifier.md": "verifier v1\n", "hooks/reload-gate.py": "# v1\n"}
        for rel, text in files.items():
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "the first version")
        git(self.repo, "remote", "add", "origin", str(self.origin))
        git(self.repo, "push", "-q", "-u", "origin", "main")
        git(d, "clone", "-q", str(self.origin), str(self.work))
        self.call(self.repo / "install.py", "apply", "--home", str(self.home))  # the bootstrap install
        (self.home / "calls.log").unlink()
        self.first = git(self.repo, "rev-parse", "HEAD")
        self.env = {**os.environ, **GIT_ENV, "HOME": str(self.home)}

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, script, *args):
        return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, check=True)

    def sync(self, *args, stdin=None, env=None):
        return subprocess.run([sys.executable, str(SYNC), *args], capture_output=True, text=True, timeout=120,
                              input=stdin if stdin is not None else "", env=env or self.env)

    def hook(self, which, session="s1", source="startup", env=None):
        payload = {"session_id": session, "hook_event_name": which, "source": source, "cwd": str(self.repo)}
        out = self.sync("session-start" if which == "SessionStart" else "prompt", stdin=json.dumps(payload), env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stderr, "", "a hook never fails loudly")
        return json.loads(out.stdout) if out.stdout.strip() else None

    def calls(self):
        log = self.home / "calls.log"
        return log.read_text().split("\n")[:-1] if log.is_file() else []

    def upstream_commit(self, rel, text, message):
        (self.work / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.work / rel).write_text(text)
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", message)
        git(self.work, "push", "-q", "origin", "main")
        return git(self.work, "rev-parse", "HEAD")

    def sync_record(self):
        return json.loads((self.home / ".claude/.pipeline-sync.json").read_text())

    # ------------------------------------------------------------ update

    def test_current_when_the_manifest_names_head_and_check_passes(self):
        out = self.sync("update")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue(out.stdout.startswith("current"), out.stdout)
        self.assertEqual(self.calls(), ["install.py check"], "nothing installed when nothing changed")
        self.assertIn("main is even with origin/main", out.stdout)
        self.assertEqual(self.sync_record()["result"], "current")
        as_json = json.loads(self.sync("update", "--json").stdout)
        self.assertEqual(as_json["result"], "current")

    def test_behind_origin_is_fast_forwarded_and_installed(self):
        self.upstream_commit("skills/dev/SKILL.md", "dev v2\n", "teach dev the new freeze")
        new = self.upstream_commit("agents/code-verifier.md", "verifier v2\n", "sharpen the verifier")
        out = self.sync("update")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), new, "fast-forwarded")
        self.assertEqual(self.calls(), ["install.py apply", "settings_patch.py --apply", "install.py check"],
                         "files first, then the hooks that run them, then the proof")
        self.assertIn(f"updated: {self.first[:7]} -> {new[:7]}", out.stdout)
        log = out.stdout[out.stdout.index("commits:"):]
        self.assertLess(log.index("sharpen the verifier"), log.index("teach dev the new freeze"), "newest first")
        self.assertIn("changed: skills dev; agents code-verifier", out.stdout)
        self.assertNotIn("gate", out.stdout.split("changed:")[1].split("\n")[0], "an unchanged skill is not named")
        self.assertIn("fast-forwarded main by 2 commit(s)", out.stdout)
        rec = self.sync_record()
        self.assertEqual((rec["result"], rec["before"], rec["after"]), ("updated", self.first, new))
        self.assertEqual(rec["history"][-1]["changed"]["skill_md"], ["dev"])
        self.assertEqual((self.home / ".claude/skills/dev/SKILL.md").read_text(), "dev v2\n")

    def test_the_commit_list_stops_at_fifteen(self):
        for i in range(17):
            self.upstream_commit("skills/gate/SKILL.md", f"gate v{i + 2}\n", f"gate change {i}")
        out = self.sync("update")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertEqual(out.stdout.count("gate change"), 15)
        self.assertIn("... and 2 more", out.stdout)

    def test_a_diverged_branch_is_reported_and_not_merged(self):
        upstream = self.upstream_commit("skills/dev/SKILL.md", "dev upstream\n", "upstream change")
        (self.repo / "skills/gate/SKILL.md").write_text("gate local\n")
        git(self.repo, "commit", "-q", "-am", "a local change")
        local = git(self.repo, "rev-parse", "HEAD")
        out = self.sync("update")
        self.assertIn("main and origin/main have diverged (1 local and 1 upstream commit(s)): nothing was merged",
                      out.stdout)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), local, "never merged")
        self.assertNotEqual(local, upstream)
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn(f"-> {local[:7]}", out.stdout, "the local HEAD is installed")
        self.assertIn("changed: skills gate", out.stdout)

    def test_a_dirty_tree_is_refused(self):
        (self.repo / "skills/dev/SKILL.md").write_text("half an edit\n")
        out = self.sync("update")
        self.assertEqual(out.returncode, 1)
        self.assertIn("update refused: the repository", out.stdout)
        self.assertIn("uncommitted changes to 1 tracked file(s) (skills/dev/SKILL.md)", out.stdout)
        self.assertIn("What to do:", out.stdout)
        self.assertEqual(self.calls(), [], "nothing ran")
        self.assertEqual(self.sync_record()["result"], "refused")

    def test_an_untracked_file_under_skills_is_refused_and_one_elsewhere_is_not(self):
        (self.repo / "notes.txt").write_text("mine\n")
        (self.repo / "private").mkdir()
        (self.repo / "private/brain.md").write_text("the overlay is never committed\n")
        self.assertEqual(self.sync("update").returncode, 0)
        (self.repo / "skills/new").mkdir()
        (self.repo / "skills/new/SKILL.md").write_text("a skill in progress\n")
        out = self.sync("update")
        self.assertEqual(out.returncode, 1)
        self.assertIn("1 untracked file(s) where install.py installs from (skills/new/SKILL.md)", out.stdout)

    def test_a_live_run_is_refused_and_dead_entries_are_pruned(self):
        runs = self.home / ".claude/.pipeline-runs"
        runs.mkdir()
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", "gate_run.py"])
        try:
            dead = subprocess.Popen([sys.executable, "-c", "pass"])
            dead.wait()
            entries = {child.pid: "gate_run.py", dead.pid: "run_isolated.py",
                       os.getpid(): "run_isolated.py"}  # a pid alive but running something else: reused
            for pid, script in entries.items():
                (runs / f"{pid}.json").write_text(json.dumps({"pid": pid, "script": script, "project": "/p/proj",
                                                              "started": "2026-10-18T10:00:00Z"}))
            (runs / "junk.json").write_text("{not json")
            out = self.sync("update")
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("a pipeline run is in progress", out.stdout)
            self.assertIn(f"gate_run.py (pid {child.pid}, /p/proj", out.stdout)
            self.assertEqual(sorted(p.name for p in runs.iterdir()), [f"{child.pid}.json"], "the rest are pruned")
            status = self.sync("status")
            self.assertIn(f"runs in progress: gate_run.py (pid {child.pid}", status.stdout)
        finally:
            child.kill()
            child.wait()
        out = self.sync("update")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertEqual(list(runs.iterdir()), [], "the update's own entry is gone too")

    def test_a_failed_fetch_goes_on_with_the_local_head(self):
        git(self.repo, "remote", "set-url", "origin", str(self.origin) + "-gone")
        out = self.sync("update")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("fetching origin/main failed", out.stdout)
        self.assertIn("going on with the local HEAD", out.stdout)
        self.assertTrue(out.stdout.startswith("current"))

    def test_no_pull_never_fetches(self):
        self.upstream_commit("skills/dev/SKILL.md", "dev v2\n", "upstream change")
        out = self.sync("update", "--no-pull")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.first)
        self.assertIn("not pulled (--no-pull)", out.stdout)

    def test_a_failed_apply_exits_1_with_its_own_message(self):
        self.upstream_commit("skills/dev/SKILL.md", "dev v2\n", "upstream change")
        (self.home / "fail-apply").write_text("")
        out = self.sync("update")
        self.assertEqual(out.returncode, 1)
        self.assertIn("update failed: install.py apply did not install (exit 1)", out.stdout)
        self.assertIn("STOP   install     changed or added under ~/.claude", out.stdout)
        self.assertEqual(self.calls(), ["install.py apply"], "no hook is registered for files not installed")
        self.assertEqual(self.sync_record()["history"], [])

    def test_a_failing_check_after_the_install_fails_the_update(self):
        self.upstream_commit("skills/dev/SKILL.md", "dev v2\n", "upstream change")
        (self.home / "fail-check").write_text("")
        out = self.sync("update")
        self.assertEqual(out.returncode, 1)
        self.assertIn("install.py check fails", out.stdout)
        self.assertIn("FAIL   install", out.stdout)
        self.assertIn(f"installed: {self.first[:7]} -> ", out.stdout)
        self.assertIn("changed: skills dev", out.stdout)
        self.assertEqual(len(self.sync_record()["history"]), 1, "the files were installed: sessions are told")

    def test_refusals_without_a_manifest_or_a_git_repository(self):
        manifest = self.home / ".claude/.pipeline-install.json"
        saved = manifest.read_text()
        manifest.unlink()
        out = self.sync("update")
        self.assertEqual(out.returncode, 1)
        self.assertIn("no readable install manifest", out.stdout)
        self.assertIn("python3 install.py apply, then python3 settings_patch.py --apply", out.stdout)
        plain = Path(self.tmp.name) / "plain"
        shutil.copytree(self.repo, plain, ignore=shutil.ignore_patterns(".git"))
        manifest.write_text(saved.replace(str(self.repo), str(plain)))
        out = self.sync("update")
        self.assertEqual(out.returncode, 1)
        self.assertIn("is not a git work tree", out.stdout)

    def test_status_reports_without_the_network(self):
        new = self.upstream_commit("skills/dev/SKILL.md", "dev v2\n", "upstream change")
        git(self.repo, "fetch", "-q")
        git(self.repo, "remote", "set-url", "origin", str(self.origin) + "-gone")  # no fetch can happen
        out = self.sync("status")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(f"installed: {self.first[:7]}", out.stdout)
        self.assertIn("0 ahead, 1 behind origin/main as of the last fetch", out.stdout)
        self.assertIn("the installed revision is the repository's HEAD", out.stdout)
        self.assertIn("runs in progress: none", out.stdout)
        git(self.repo, "merge", "-q", "--ff-only", "origin/main")
        out = self.sync("status", "--json")
        s = json.loads(out.stdout)
        self.assertEqual((s["head"], s["not_installed"], s["uncommitted"]), (new, 1, 0))

    # ------------------------------------------------------------ hooks

    def test_session_start_records_the_revision_and_names_commits_not_installed(self):
        self.assertIsNone(self.hook("SessionStart"))
        rec = json.loads((self.home / ".claude/.pipeline-sessions/s1.json").read_text())
        self.assertEqual(rec["revision"], self.first)
        (self.repo / "skills/dev/SKILL.md").write_text("dev v2\n")
        git(self.repo, "commit", "-q", "-am", "a local change")
        head = git(self.repo, "rev-parse", "HEAD")
        out = self.hook("SessionStart", session="s2")
        self.assertEqual(out["systemMessage"], f"The pipeline repository has 1 commit(s) not installed "
                                               f"({self.first[:7]}..{head[:7]}). Type /pipeline update.")

    def test_a_resumed_session_keeps_its_record_and_old_records_are_pruned(self):
        sessions = self.home / ".claude/.pipeline-sessions"
        sessions.mkdir()
        (sessions / "s1.json").write_text(json.dumps({"revision": "an-older-revision"}))
        old, recent = sessions / "gone.json", sessions / "kept.json"
        for path, days in ((old, 15), (recent, 13)):
            path.write_text(json.dumps({"revision": self.first}))
            t = time.time() - days * 86400
            os.utime(path, (t, t))
        self.hook("SessionStart", session="s1", source="resume")
        self.assertEqual(json.loads((sessions / "s1.json").read_text())["revision"], "an-older-revision",
                         "its conversation still holds what it read then")
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.hook("SessionStart", session="s1", source="clear")
        self.assertEqual(json.loads((sessions / "s1.json").read_text())["revision"], self.first, "a fresh context")

    def test_prompt_gives_the_notice_once_per_change_fast_and_without_git(self):
        real_git = shutil.which("git")
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        git_log = Path(self.tmp.name) / "git-calls.log"
        (bin_dir / "git").write_text(LOGGING_GIT.format(log=git_log, git=real_git))
        (bin_dir / "git").chmod(0o755)
        logged = {**self.env, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        self.hook("SessionStart")
        started = time.monotonic()
        self.assertIsNone(self.hook("UserPromptSubmit", env=logged), "nothing changed, nothing said")
        self.assertIsNone(self.hook("UserPromptSubmit", session="s-new", env=logged),
                          "a session older than the hook is recorded silently")
        self.assertTrue((self.home / ".claude/.pipeline-sessions/s-new.json").is_file())
        self.upstream_commit("skills/dev/SKILL.md", "dev v2\n", "teach dev")
        new = self.upstream_commit("skills/_shared/references/project-control.md", "control v2\n", "clarify control")
        self.assertEqual(self.sync("update").returncode, 0)
        if git_log.exists():
            git_log.unlink()
        timed = time.monotonic()
        out = self.hook("UserPromptSubmit", env=logged)
        self.assertLess(time.monotonic() - timed, 1.5, "far inside the hook's 5 s")
        context = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn(f"The coding pipeline in ~/.claude was updated ({self.first[:7]} -> {new[:7]}) after this "
                      "session read its instructions.", context)
        self.assertIn("re-read the SKILL.md of the skill in use (~/.claude/skills/<name>/SKILL.md)", context)
        self.assertIn("Scripts, hooks, and checker agents already run the new version.", context)
        self.assertIn("Skills changed: dev.", context)
        self.assertIn("Shared references changed: project-control.md.", context)
        self.assertIn("invoke it again (for example /dev resume)", context, "dev's SKILL.md changed")
        self.assertIsNone(self.hook("UserPromptSubmit", env=logged), "once per change")
        other = self.hook("UserPromptSubmit", session="s-new", env=logged)
        self.assertIn("was updated", other["hookSpecificOutput"]["additionalContext"], "every open session is told")
        self.assertIsNone(self.hook("UserPromptSubmit", session="s-new", env=logged))
        self.assertFalse(git_log.exists(), "the prompt hook never runs git")
        self.assertLess(time.monotonic() - started, 30)

    def test_two_updates_between_prompts_name_both_and_a_hand_install_names_none(self):
        self.hook("SessionStart")
        self.upstream_commit("skills/dev/SKILL.md", "dev v2\n", "teach dev")
        self.assertEqual(self.sync("update").returncode, 0)
        self.upstream_commit("agents/code-verifier.md", "verifier v2\n", "sharpen")
        self.upstream_commit("skills/gate/references/x.md", "gate ref\n", "a gate reference")
        self.assertEqual(self.sync("update").returncode, 0)
        context = self.hook("UserPromptSubmit")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Skills changed: dev, gate.", context)
        self.upstream_commit("hooks/reload-gate.py", "# v2\n", "a hook")
        git(self.repo, "pull", "-q", "--ff-only")
        self.call(self.repo / "install.py", "apply", "--home", str(self.home))  # by hand: no history
        context = self.hook("UserPromptSubmit")["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("Skills changed", context)
        self.assertIn("invoke it again", context, "unknown changes get the cautious advice")

    def test_corrupt_state_files_never_raise(self):
        claude = self.home / ".claude"
        (claude / ".pipeline-sessions").mkdir()
        (claude / ".pipeline-runs").mkdir()
        (claude / ".pipeline-sessions/s1.json").write_text("{half")
        (claude / ".pipeline-runs/123.json").write_text("[1, 2")
        (claude / ".pipeline-sync.json").write_text(json.dumps({"history": ["x", {"after": 3, "changed": "abc"}]}))
        self.assertIsNone(self.hook("UserPromptSubmit"), "a corrupt record is no record")
        self.assertIsNone(self.hook("SessionStart"))
        self.assertEqual(self.sync("status").returncode, 0)
        self.assertEqual(self.sync("update").returncode, 0)
        (claude / ".pipeline-sessions/s1.json").write_text(json.dumps({"revision": "older"}))
        (claude / ".pipeline-sync.json").write_text(json.dumps({"history": [{"after": self.first, "before": "older",
                                                                             "changed": {"skills": "abc"}}]}))
        context = self.hook("UserPromptSubmit")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("No skill's own files changed.", context)
        self.assertNotIn("invoke it again", context, "no SKILL.md changed")
        self.assertIsNone(self.hook("SessionStart", session="../../escape"))
        self.assertEqual(sorted(p.name for p in (claude / ".pipeline-sessions").iterdir()), ["s1.json"])
        self.assertFalse((self.home / "escape.json").exists())
        (claude / ".pipeline-install.json").write_text("not json")
        for which in ("SessionStart", "UserPromptSubmit"):
            self.assertIsNone(self.hook(which))
        (claude / ".pipeline-install.json").write_text(json.dumps(["a", "list"]))
        self.assertIsNone(self.hook("UserPromptSubmit"))
        self.assertEqual(self.sync("status").returncode, 0)
        out = self.sync("update")
        self.assertEqual(out.returncode, 1)
        self.assertIn("no readable install manifest", out.stdout)
        bad = self.sync("prompt", stdin="this is not json")
        self.assertEqual((bad.returncode, bad.stdout, bad.stderr), (0, "", ""))

    def test_bad_usage_exits_2_and_help_exits_0(self):
        self.assertEqual(self.sync().returncode, 2)
        self.assertEqual(self.sync("update", "--bogus").returncode, 2)
        self.assertEqual(self.sync("--help").returncode, 0)


SLOW_CLAUDE = r'''#!/usr/bin/env python3
import os, sys, time
sys.stdin.read()
time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
print('{"type": "result", "result": "done", "num_turns": 1, "is_error": false}')
'''


class RunRegistryTest(unittest.TestCase):
    """run_isolated.py registers itself while it runs and leaves when it ends, a stopped run included (gate_run.py
    is covered by tests/test_compat_587f48c.py, which runs a whole round)."""

    def start(self, d, sleep):
        home, work, bindir = Path(d) / "home", Path(d) / "work", Path(d) / "bin"
        for p in (home, work, bindir):
            p.mkdir()
        (bindir / "claude").write_text(SLOW_CLAUDE)
        (bindir / "claude").chmod(0o755)
        (Path(d) / "pack.md").write_text("pack")
        env = {**os.environ, "HOME": str(home), "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_SLEEP": str(sleep),
               "HEAVY_LOCK_DIR": str(Path(d) / "lock")}
        proc = subprocess.Popen([sys.executable, str(ROOT / "skills/_shared/scripts/run_isolated.py"), "gate-judge",
                                 "--dir", str(work), "--pack", str(Path(d) / "pack.md"), "--out", str(Path(d) / "ev"),
                                 "--agent-file", str(ROOT / "agents/gate-judge.md")],
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return proc, home / ".claude/.pipeline-runs"

    def wait_for(self, runs):
        deadline = time.time() + 20
        while time.time() < deadline:
            entries = list(runs.glob("*.json")) if runs.is_dir() else []
            if entries:
                return [json.loads(p.read_text()) for p in entries]
            time.sleep(0.05)
        return []

    def test_a_run_is_registered_while_it_runs_and_removed_when_stopped(self):
        with tempfile.TemporaryDirectory() as d:
            proc, runs = self.start(d, 60)
            try:
                entries = self.wait_for(runs)
                self.assertEqual([(e["pid"], e["script"]) for e in entries], [(proc.pid, "run_isolated.py")])
                self.assertTrue(entries[0]["started"])
            finally:
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=30)
            self.assertEqual(list(runs.glob("*.json")), [], "a stopped run leaves the registry")

    def test_a_finished_run_leaves_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            proc, runs = self.start(d, 0)
            proc.wait(timeout=60)
            self.assertTrue(runs.is_dir(), "it was registered")
            self.assertEqual(list(runs.glob("*.json")), [])


class PersonalFilesTest(unittest.TestCase):
    def test_install_never_writes_the_update_state(self):
        sys.dont_write_bytecode = True  # no __pycache__ beside install.py
        sys.path.insert(0, str(ROOT))
        try:
            import install
        finally:
            sys.path.remove(str(ROOT))
        with tempfile.TemporaryDirectory() as d:
            repo, home = Path(d) / "repo", Path(d) / "home"
            for rel in (".pipeline-sessions/s1.json", ".pipeline-runs/1.json", ".pipeline-sync.json", "notes.md"):
                (repo / "private" / rel).parent.mkdir(parents=True, exist_ok=True)
                (repo / "private" / rel).write_text("overlay\n")
            real = install.REPO
            install.REPO = repo
            try:
                want = install.desired(home)
            finally:
                install.REPO = real
            claude = home / ".claude"
            self.assertIn(claude / "notes.md", want)
            for rel in (".pipeline-sessions/s1.json", ".pipeline-runs/1.json", ".pipeline-sync.json"):
                self.assertNotIn(claude / rel, want)


if __name__ == "__main__":
    unittest.main()
