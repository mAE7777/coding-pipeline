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


class SyncBase(unittest.TestCase):
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


class SyncTest(SyncBase):
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


# The stand-in for the fast workflow's install.py update --json (its interface: one JSON object with result, before,
# after, commits, notes, reason, todo; exit 0 for current and updated, 1 otherwise). It logs its arguments; the file
# fast-mode in the home folder makes it refuse (dirty), print no JSON (garbage), print a line before the JSON
# (stray), or report a diverged branch (diverged). Otherwise it installs HEAD when the manifest names another commit.
STUB_FAST = r'''import json, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parent
argv = sys.argv[1:]
home = Path(argv[argv.index("--home") + 1])
with open(home / "fast-calls.log", "a") as f:
    f.write(" ".join(argv) + "\n")
def git(*a):
    return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True).stdout.strip()
manifest = home / ".claude/.pipeline-fast-install.json"
before = json.loads(manifest.read_text()).get("revision")
head = git("rev-parse", "HEAD")
mode = (home / "fast-mode").read_text().strip() if (home / "fast-mode").exists() else ""
out = {"result": "current", "before": before, "after": head, "commits": [], "notes": [], "reason": None, "todo": None}
if mode == "garbage":
    print("Traceback (most recent call last):")
    sys.exit(1)
if mode == "dirty":
    out.update(result="refused", reason="the repository has uncommitted changes to 1 tracked file(s) "
               "(skills/dev-fast/SKILL.md)", todo="commit or discard them, then update again")
elif before != head:
    out.update(result="updated", commits=git("log", "--oneline", "-n15", before + ".." + head).splitlines())
    manifest.write_text(json.dumps({"revision": head, "repo": str(REPO), "installed": "2026-10-19T08:00:00Z",
                                    "folders": [], "files": {}}))
if mode == "diverged":
    out["notes"].append("main and origin/main have diverged (1 local and 1 upstream commit(s)): nothing was merged")
if mode == "stray":
    print("installed 12 folder(s), 30 file(s)")
print(json.dumps(out, indent=1 if mode == "stray" else None))
sys.exit(0 if out["result"] in ("current", "updated") else 1)
'''


class FastSyncTest(SyncBase):
    """The fast workflow's part: /pipeline update calls its install.py update, status and the hooks watch it."""

    def setUp(self):
        super().setUp()
        self.fast = Path(self.tmp.name) / "fast"
        git(self.tmp.name, "init", "-q", "-b", "main", str(self.fast))
        (self.fast / "skills/dev-fast").mkdir(parents=True)
        (self.fast / "skills/dev-fast/SKILL.md").write_text("dev-fast v1\n")
        (self.fast / "install.py").write_text(STUB_FAST)
        git(self.fast, "add", "-A")
        git(self.fast, "commit", "-q", "-m", "the first fast version")
        self.fast_first = git(self.fast, "rev-parse", "HEAD")
        self.fast_manifest = self.home / ".claude/.pipeline-fast-install.json"
        self.write_fast_manifest(self.fast_first)

    def write_fast_manifest(self, revision, repo=None, older=False):
        m = {"revision": revision, "folders": [], "files": {}}
        if not older:
            m.update(repo=str(repo or self.fast), installed="2026-10-18T08:00:00Z")
        self.fast_manifest.write_text(json.dumps(m))

    def fast_commit(self, text, message, repo=None):
        repo = repo or self.fast
        (repo / "skills/dev-fast/SKILL.md").write_text(text)
        git(repo, "commit", "-q", "-am", message)
        return git(repo, "rev-parse", "HEAD")

    def fast_calls(self):
        log = self.home / "fast-calls.log"
        return log.read_text().splitlines() if log.is_file() else []

    def fast_mode(self, mode):
        (self.home / "fast-mode").write_text(mode)

    def notice_of(self, out):
        return out["hookSpecificOutput"]["additionalContext"] if out else None

    # ------------------------------------------------------------ update

    def test_without_the_fast_workflow_nothing_about_it_runs_or_prints(self):
        self.fast_manifest.unlink()
        out = self.sync("update")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertNotIn("fast", out.stdout)
        self.assertEqual(self.fast_calls(), [])
        self.assertIsNone(json.loads(self.sync("update", "--json").stdout)["fast"])
        self.assertIsNone(self.sync_record()["fast"])

    def test_both_current_then_fast_alone_updated_with_its_commits(self):
        out = self.sync("update")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertTrue(out.stdout.startswith("current"), out.stdout)
        self.assertIn("\nfast: current\n", out.stdout)
        self.assertEqual(self.fast_calls(), [f"update --home {self.home} --json"])
        new = self.fast_commit("dev-fast v2\n", "teach dev-fast the tail")
        out = self.sync("update")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn(f"fast: updated {self.fast_first[:7]} -> {new[:7]} (1 commit)\n  {new[:7]} teach dev-fast the "
                      "tail", out.stdout)
        self.assertTrue(out.stdout.startswith("current"), "the pipeline's own part is reported first")
        rec = self.sync_record()
        self.assertEqual((rec["result"], rec["fast"]["result"], rec["fast"]["before"], rec["fast"]["after"],
                          rec["fast"]["count"]), ("current", "updated", self.fast_first, new, 1))
        as_json = json.loads(self.sync("update", "--json").stdout)
        self.assertEqual((as_json["result"], as_json["fast"]["result"]), ("current", "current"))

    def test_more_than_fifteen_fast_commits_are_counted_and_cut(self):
        for i in range(17):
            self.fast_commit(f"dev-fast v{i + 2}\n", f"fast change {i}")
        out = self.sync("update")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("(17 commits)", out.stdout)
        self.assertEqual(out.stdout.count("fast change"), 15)
        self.assertIn("  ... and 2 more", out.stdout)

    def test_a_fast_refusal_never_blocks_the_pipeline_and_exits_1(self):
        new = self.upstream_commit("skills/dev/SKILL.md", "dev v2\n", "teach dev")
        self.fast_mode("dirty")
        out = self.sync("update")
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn(f"updated: {self.first[:7]} -> {new[:7]}", out.stdout)
        self.assertEqual((self.home / ".claude/skills/dev/SKILL.md").read_text(), "dev v2\n", "the pipeline updated")
        self.assertIn("fast: refused: the repository has uncommitted changes to 1 tracked file(s) "
                      "(skills/dev-fast/SKILL.md); commit or discard them, then update again", out.stdout)
        rec = self.sync_record()
        self.assertEqual((rec["result"], rec["fast"]["result"]), ("updated", "refused"))
        self.assertEqual(len(rec["history"]), 1, "open sessions are still told about the pipeline's update")

    def test_a_pipeline_refusal_never_blocks_fast_and_exits_1(self):
        (self.repo / "skills/dev/SKILL.md").write_text("half an edit\n")
        new = self.fast_commit("dev-fast v2\n", "teach dev-fast")
        out = self.sync("update")
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("update refused: the repository", out.stdout)
        self.assertIn(f"fast: updated {self.fast_first[:7]} -> {new[:7]} (1 commit)", out.stdout)
        self.assertEqual(json.loads(self.fast_manifest.read_text())["revision"], new)
        self.assertEqual(self.calls(), [], "the pipeline's install never ran")

    def test_without_a_pipeline_install_fast_still_updates(self):
        (self.home / ".claude/.pipeline-install.json").unlink()
        new = self.fast_commit("dev-fast v2\n", "teach dev-fast")
        out = self.sync("update")
        self.assertEqual(out.returncode, 1, "the pipeline's part refused")
        self.assertIn("no readable install manifest", out.stdout)
        self.assertIn(f"-> {new[:7]} (1 commit)", out.stdout)

    def test_another_update_running_stops_both_parts_but_a_gate_run_stops_only_the_pipeline(self):
        runs = self.home / ".claude/.pipeline-runs"
        runs.mkdir()
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", "pipeline_sync.py update"])
        try:
            (runs / f"{other.pid}.json").write_text(json.dumps({"pid": other.pid, "script": "pipeline_sync.py update"}))
            self.fast_commit("dev-fast v2\n", "teach dev-fast")
            out = self.sync("update")
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("update refused: a pipeline run is in progress", out.stdout)
            self.assertIn("fast: refused: another /pipeline update is running: pipeline_sync.py update (pid "
                          f"{other.pid}", out.stdout)
            self.assertEqual(self.fast_calls(), [], "two updates never install fast at once")
        finally:
            other.kill()
            other.wait()
        gate = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", "gate_run.py"])
        try:
            (runs / f"{gate.pid}.json").write_text(json.dumps({"pid": gate.pid, "script": "gate_run.py"}))
            out = self.sync("update")
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("update refused: a pipeline run is in progress", out.stdout)
            self.assertIn("fast: updated", out.stdout, "a gate run uses none of fast's files")
        finally:
            gate.kill()
            gate.wait()

    def test_no_pull_reaches_fast_and_its_notes_are_printed(self):
        self.fast_mode("diverged")
        out = self.sync("update", "--no-pull")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertEqual(self.fast_calls(), [f"update --home {self.home} --json --no-pull"])
        self.assertIn("fast note: main and origin/main have diverged", out.stdout)

    def test_an_older_fast_manifest_says_to_apply_once_and_runs_nothing(self):
        self.write_fast_manifest(self.fast_first[:7], older=True)
        out = self.sync("update")
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("\nfast: installed by an older version; run python3 install.py apply once in the fast "
                      "repository\n", out.stdout)
        self.assertEqual(self.fast_calls(), [])
        self.assertTrue(out.stdout.startswith("current"), "the pipeline's part ran as usual")

    def test_output_that_is_not_the_json_result_fails_and_stray_lines_are_passed_over(self):
        self.fast_mode("garbage")
        out = self.sync("update")
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("fast: failed: the fast workflow's install.py update gave no result this script can read "
                      "(exit 1)", out.stdout)
        self.assertIn("Traceback (most recent call last):", out.stdout, "its own output is shown")
        self.fast_mode("stray")
        out = self.sync("update")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("\nfast: current\n", out.stdout)

    def test_a_fast_repository_that_is_gone_or_a_manifest_that_is_unreadable_is_refused(self):
        self.write_fast_manifest(self.fast_first, repo=Path(self.tmp.name) / "moved")
        out = self.sync("update")
        self.assertEqual(out.returncode, 1)
        self.assertIn("which no longer holds its repository (no install.py there); clone the fast repository and run "
                      "python3 install.py apply once in the fast repository", out.stdout)
        self.fast_manifest.write_text("{half")
        out = self.sync("update")
        self.assertEqual(out.returncode, 1)
        self.assertIn("fast: refused: the fast workflow's install manifest", out.stdout)
        self.assertEqual(self.sync("status").returncode, 0)

    # ------------------------------------------------------------ status

    def test_status_names_the_fast_install_its_repository_and_commits_not_installed(self):
        out = self.sync("status")
        self.assertIn(f"fast: installed {self.fast_first[:7]} at 2026-10-18T08:00:00Z from {self.fast}", out.stdout)
        self.assertIn(f"fast repository: HEAD {self.fast_first[:7]}, the installed revision", out.stdout)
        new = self.fast_commit("dev-fast v2\n", "teach dev-fast")
        out = self.sync("status")
        self.assertIn(f"fast repository: HEAD {new[:7]}; 1 commit(s) not installed: type /pipeline update", out.stdout)
        s = json.loads(self.sync("status", "--json").stdout)["fast"]
        self.assertEqual((s["installed"], s["repo"], s["head"], s["ahead"], s["not_installed"]),
                         (self.fast_first, str(self.fast), new, True, 1))
        self.sync("update")
        self.assertIn("fast last update: updated at ", self.sync("status").stdout)
        self.write_fast_manifest(self.fast_first[:7], older=True)
        out = self.sync("status")
        self.assertIn("fast: installed by an older version, which recorded no repository; run python3 install.py "
                      "apply once in the fast repository", out.stdout)
        self.fast_manifest.unlink()
        self.assertNotIn("fast", self.sync("status").stdout)
        self.assertIsNone(json.loads(self.sync("status", "--json").stdout)["fast"])

    def test_a_fast_repository_in_a_linked_worktree_is_read_where_it_is(self):
        wt = Path(self.tmp.name) / "fast-wt"
        git(self.fast, "worktree", "add", "-q", "-b", "work", str(wt))
        self.write_fast_manifest(self.fast_first, repo=wt)
        new = self.fast_commit("dev-fast in the worktree\n", "a worktree change", repo=wt)
        self.assertIn(f"fast repository: HEAD {new[:7]}; 1 commit(s) not installed", self.sync("status").stdout)
        out = self.hook("SessionStart")
        self.assertIn(f"The fast workflow's repository has 1 commit(s) not installed ({self.fast_first[:7]}.."
                      f"{new[:7]}).", out["systemMessage"])

    # ------------------------------------------------------------ hooks

    def test_session_start_names_fast_commits_not_installed_and_both_in_one_message(self):
        self.assertIsNone(self.hook("SessionStart"))
        rec = json.loads((self.home / ".claude/.pipeline-sessions/s1.json").read_text())
        self.assertEqual((rec["revision"], rec["fast_revision"]), (self.first, self.fast_first))
        fast_new = self.fast_commit("dev-fast v2\n", "teach dev-fast")
        out = self.hook("SessionStart", session="s2")
        self.assertEqual(out["systemMessage"], f"The fast workflow's repository has 1 commit(s) not installed "
                                               f"({self.fast_first[:7]}..{fast_new[:7]}). Type /pipeline update.")
        (self.repo / "skills/dev/SKILL.md").write_text("dev v2\n")
        git(self.repo, "commit", "-q", "-am", "a local change")
        head = git(self.repo, "rev-parse", "HEAD")
        out = self.hook("SessionStart", session="s3")
        self.assertEqual(out["systemMessage"], f"The pipeline repository has 1 commit(s) not installed "
                                               f"({self.first[:7]}..{head[:7]}). The fast workflow's repository has 1 "
                                               f"commit(s) not installed ({self.fast_first[:7]}..{fast_new[:7]}). "
                                               "Type /pipeline update.")
        self.write_fast_manifest(self.fast_first[:7], older=True)
        out = self.hook("SessionStart", session="s4")
        self.assertNotIn("fast", out["systemMessage"], "an older manifest names no repository to compare")

    def test_session_start_with_only_fast_installed(self):
        (self.home / ".claude/.pipeline-install.json").unlink()
        new = self.fast_commit("dev-fast v2\n", "teach dev-fast")
        out = self.hook("SessionStart")
        self.assertIn(f"({self.fast_first[:7]}..{new[:7]})", out["systemMessage"])
        rec = json.loads((self.home / ".claude/.pipeline-sessions/s1.json").read_text())
        self.assertEqual((rec["revision"], rec["fast_revision"]), (None, self.fast_first))

    def test_prompt_says_fast_skills_when_only_fast_changed_and_both_when_both_did(self):
        self.hook("SessionStart")
        self.fast_commit("dev-fast v2\n", "teach dev-fast")
        self.assertEqual(self.sync("update").returncode, 0)
        fast_new = git(self.fast, "rev-parse", "HEAD")
        text = self.notice_of(self.hook("UserPromptSubmit"))
        self.assertIn(f"The fast skills in ~/.claude were updated ({self.fast_first[:7]} -> {fast_new[:7]})", text)
        self.assertIn("~/.claude/skills/<name>-fast/SKILL.md", text)
        self.assertNotIn("The coding pipeline", text, "the pipeline itself did not change")
        self.assertIsNone(self.hook("UserPromptSubmit"), "once per change")
        self.upstream_commit("skills/dev/SKILL.md", "dev v2\n", "teach dev")
        new = self.upstream_commit("skills/gate/SKILL.md", "gate v2\n", "teach gate")
        fast_newer = self.fast_commit("dev-fast v3\n", "teach dev-fast again")
        self.assertEqual(self.sync("update").returncode, 0)
        text = self.notice_of(self.hook("UserPromptSubmit"))
        self.assertIn(f"The coding pipeline in ~/.claude was updated ({self.first[:7]} -> {new[:7]})", text)
        self.assertIn("Skills changed: dev, gate.", text)
        self.assertIn(f"The fast skills were updated too ({fast_new[:7]} -> {fast_newer[:7]})", text)
        self.assertIn("If this session has used neither pipeline's skills, nothing needs doing.", text)
        rec = json.loads((self.home / ".claude/.pipeline-sessions/s1.json").read_text())
        self.assertEqual((rec["revision"], rec["fast_revision"]), (new, fast_newer), "both are recorded")
        self.upstream_commit("skills/dev/SKILL.md", "dev v3\n", "dev again")
        self.assertEqual(self.sync("update").returncode, 0)
        text = self.notice_of(self.hook("UserPromptSubmit"))
        self.assertNotIn("fast", text, "only the pipeline changed")

    def test_a_record_without_the_fast_field_records_it_silently(self):
        sessions = self.home / ".claude/.pipeline-sessions"
        sessions.mkdir()
        (sessions / "s1.json").write_text(json.dumps({"revision": self.first, "recorded": "2026-10-18T08:00:00Z"}))
        self.assertIsNone(self.hook("UserPromptSubmit"), "written before fast was watched: nothing to say")
        self.assertEqual(json.loads((sessions / "s1.json").read_text())["fast_revision"], self.fast_first)
        self.fast_commit("dev-fast v2\n", "teach dev-fast")
        self.assertEqual(self.sync("update").returncode, 0)
        self.assertIn("The fast skills", self.notice_of(self.hook("UserPromptSubmit")), "from then on it is watched")

    def test_a_short_fast_revision_and_the_full_sha_of_the_same_commit_are_no_change(self):
        self.write_fast_manifest(self.fast_first[:7], older=True)  # what fast's install.py wrote before update
        self.hook("SessionStart")
        rec = json.loads((self.home / ".claude/.pipeline-sessions/s1.json").read_text())
        self.assertEqual(rec["fast_revision"], self.fast_first[:7])
        self.write_fast_manifest(self.fast_first)  # its first update: the same commit, now with repo and full sha
        self.assertIsNone(self.hook("UserPromptSubmit"), "the same commit is no change")
        self.assertIsNone(self.hook("SessionStart", session="s2"), "and nothing is not installed")
        new = self.fast_commit("dev-fast v2\n", "teach dev-fast")
        self.assertEqual(self.sync("update").returncode, 0)
        text = self.notice_of(self.hook("UserPromptSubmit"))
        self.assertIn(f"The fast skills in ~/.claude were updated ({self.fast_first[:7]} -> {new[:7]})", text)
        self.assertIsNone(self.hook("UserPromptSubmit"))
        self.write_fast_manifest(self.fast_first[:6] + "x")  # not a short sha: compared as it is
        self.assertIn("The fast skills", self.notice_of(self.hook("UserPromptSubmit")))

    def test_a_fast_install_that_appears_after_the_session_began_is_recorded_silently(self):
        self.fast_manifest.unlink()
        self.hook("SessionStart")
        self.assertIsNone(json.loads((self.home / ".claude/.pipeline-sessions/s1.json").read_text())["fast_revision"])
        self.write_fast_manifest(self.fast_first)
        self.assertIsNone(self.hook("UserPromptSubmit"), "this session never read a fast skill's old text")
        self.fast_manifest.write_text("{half")
        self.assertIsNone(self.hook("UserPromptSubmit"), "an unreadable manifest is no change")
        self.assertEqual(json.loads((self.home / ".claude/.pipeline-sessions/s1.json").read_text())["fast_revision"],
                         self.fast_first, "and keeps what was recorded")


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
