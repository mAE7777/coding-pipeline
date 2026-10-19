"""End-to-end flows with both pipelines installed: this repository's scripts (pipeline_sync.py, project_policy.py,
heavy.py, adopt.py) working with the fast workflow's real install.py and fast.py, from a clone of the fast
repository. FAST_REPO names it (default: the sibling folder coding-pipeline-fast); the tests are skipped when it is
absent. Each test runs in temp folders with a temp HOME and local bare repositories standing in for GitHub; the
pipeline's own installer is the stand-in from test_pipeline_sync. No model, no network.
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pipeline_sync import GIT_ENV, SyncBase, git  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/_shared/scripts"
FAST_REPO = Path(os.environ.get("FAST_REPO") or ROOT.parent / "coding-pipeline-fast").resolve()
HAVE_FAST = (FAST_REPO / "install.py").is_file() and (FAST_REPO / "skills/_fast/fast.py").is_file()


@unittest.skipUnless(HAVE_FAST, f"the fast repository is not at {FAST_REPO} (set FAST_REPO)")
class BothPipelines(SyncBase):
    def setUp(self):
        super().setUp()
        d = Path(self.tmp.name)
        # The fast repository's committed files (git archive: the owner's uncommitted work never leaks in, and a
        # shallow clone works too) as one commit, with a bare origin, the installed clone, and a second clone that
        # stands in for upstream pushes.
        src = d / "fast-src"
        src.mkdir()
        tar = subprocess.run(["git", "-C", str(FAST_REPO), "archive", "--format=tar", "HEAD"], capture_output=True,
                             check=True, env={**os.environ, **GIT_ENV}).stdout
        subprocess.run(["tar", "-x", "-C", str(src)], input=tar, check=True)
        git(src, "init", "-q", "-b", "main")
        git(src, "add", "-A")
        git(src, "commit", "-q", "-m", "the fast workflow as committed")
        self.fast_origin = d / "fast-origin.git"
        git(d, "init", "-q", "--bare", "-b", "main", str(self.fast_origin))
        git(src, "push", "-q", str(self.fast_origin), "main")
        self.fast = d / "fast"
        self.fast_work = d / "fast-work"
        git(d, "clone", "-q", "-b", "main", str(self.fast_origin), str(self.fast))
        git(d, "clone", "-q", "-b", "main", str(self.fast_origin), str(self.fast_work))
        out = self.run_py(self.fast / "install.py", "apply", "--home", str(self.home))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.fast_first = git(self.fast, "rev-parse", "HEAD")
        self.fast_py = self.home / ".claude/skills/_fast/fast.py"
        self.projects = d / "projects"
        self.projects.mkdir()

    def run_py(self, script, *args, cwd=None, timeout=120):
        return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, cwd=cwd,
                              env=self.env, timeout=timeout)

    def notice_of(self, out):
        return out["hookSpecificOutput"]["additionalContext"] if out else None

    def fast_upstream(self, rel, append, message):
        p = self.fast_work / rel
        p.write_text(p.read_text() + append)
        git(self.fast_work, "commit", "-q", "-am", message)
        git(self.fast_work, "push", "-q", "origin", "main")
        return git(self.fast_work, "rev-parse", "HEAD")

    def project(self, name, git_repo=True):
        p = self.projects / name
        p.mkdir()
        (p / "app.py").write_text("def add(a, b):\n    return a + b\n")
        if git_repo:
            git(p, "init", "-q", "-b", "main")
            git(p, "add", "-A")
            git(p, "commit", "-q", "-m", "first")
        return p

    # ------------------------------------------------------------ /pipeline update (flow 9)

    def test_update_pulls_and_installs_both_and_a_dirty_fast_repository_refuses_only_its_own_part(self):
        self.hook("SessionStart", session="open")
        new = self.fast_upstream("skills/dev-fast/SKILL.md", "\nA line upstream added.\n", "teach dev-fast a line")
        out = self.sync("update")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue(out.stdout.startswith("current"), out.stdout)
        self.assertIn(f"fast: updated {self.fast_first[:7]} -> {new[:7]} (1 commit)", out.stdout)
        self.assertEqual(git(self.fast, "rev-parse", "HEAD"), new, "fast-forwarded")
        installed = self.home / ".claude/skills/dev-fast/SKILL.md"
        self.assertTrue(installed.read_text().endswith("A line upstream added.\n"))
        manifest = json.loads((self.home / ".claude/.pipeline-fast-install.json").read_text())
        self.assertEqual((manifest["revision"], manifest["repo"]), (new, str(self.fast)))
        self.assertEqual(self.sync_record()["fast"]["result"], "updated")
        check = self.run_py(self.fast / "install.py", "check", "--home", str(self.home))
        self.assertEqual(check.returncode, 0, check.stdout)
        # The open session is told once, about the fast skills alone.
        text = self.notice_of(self.hook("UserPromptSubmit", session="open"))
        self.assertIn(f"The fast skills in ~/.claude were updated ({self.fast_first[:7]} -> {new[:7]})", text)
        self.assertIsNone(self.hook("UserPromptSubmit", session="open"), "once")
        # Both behind, the fast repository dirty: the pipeline updates, fast refuses with its reason.
        full_new = self.upstream_commit("skills/dev/SKILL.md", "dev v2\n", "teach dev the tail")
        newer = self.fast_upstream("skills/fix-fast/SKILL.md", "\nAnother.\n", "teach fix-fast a line")
        (self.fast / "skills/dev-fast/SKILL.md").write_text("an edit in progress\n")
        out = self.sync("update")
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn(f"-> {full_new[:7]}", out.stdout.split("\nfast:")[0], "the pipeline's part updated")
        self.assertIn("fast: refused: ", out.stdout)
        self.assertIn("skills/dev-fast/SKILL.md", out.stdout)
        self.assertNotEqual(git(self.fast, "rev-parse", "HEAD"), newer, "nothing pulled into a dirty repository")
        self.assertEqual(json.loads((self.home / ".claude/.pipeline-fast-install.json").read_text())["revision"],
                         new, "nothing installed")
        self.assertEqual(self.sync_record()["fast"]["result"], "refused")
        status = self.sync("status").stdout
        self.assertIn(f"\nlast update: updated at ", status)
        self.assertIn(f" -> {full_new[:7]})\n", status)
        self.assertRegex(status, r"\nfast last update: refused at \S+: \S+ has uncommitted changes")
        # Once the edit is gone, the next update brings fast up too.
        git(self.fast, "checkout", "--", "skills/dev-fast/SKILL.md")
        out = self.sync("update")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn(f"fast: updated {new[:7]} -> {newer[:7]} (1 commit)", out.stdout)

    def test_status_names_the_fast_install_and_the_new_session_hears_of_fast_commits_not_installed(self):
        status = self.sync("status")
        self.assertEqual(status.returncode, 0, status.stdout)
        self.assertIn(str(self.fast), status.stdout)
        git(self.fast, "pull", "-q", "--ff-only", "origin", "main")  # nothing new yet
        self.fast_upstream("skills/dev-fast/SKILL.md", "\nUpstream.\n", "one more")
        git(self.fast, "pull", "-q", "--ff-only", "origin", "main")  # the owner pulled, did not install
        out = self.hook("SessionStart", session="fresh")
        self.assertIsNotNone(out, "the owner is told")
        self.assertIn("/pipeline update", json.dumps(out))


if __name__ == "__main__":
    unittest.main()
