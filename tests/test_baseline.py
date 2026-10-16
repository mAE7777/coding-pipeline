"""Tests for baseline.py: the recorded start of a milestone, the commit it started from, and what changed since."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "skills/_shared/scripts/baseline.py"
FINGERPRINT = ROOT / "skills/_shared/scripts/fingerprint.py"


def git_env(d):
    """git that reads no user configuration and never looks above the test's own folder."""
    return {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "XDG_CONFIG_HOME": os.devnull,
            "GIT_CEILING_DIRECTORIES": str(Path(d).resolve().parent), "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def baseline(d, *args):
    return subprocess.run([sys.executable, str(BASELINE), *args], capture_output=True, text=True, env=git_env(d))


def write(root, files):
    for rel, text in files.items():
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


class RecordTest(unittest.TestCase):
    def test_the_commit_is_recorded_inside_git(self):
        with tempfile.TemporaryDirectory() as d:
            env = git_env(d)
            subprocess.run(["git", "init", "-q", d], check=True, env=env)
            write(d, {"app.py": "x = 1\n"})
            subprocess.run(["git", "-C", d, "add", "app.py"], check=True, env=env)
            subprocess.run(["git", "-C", d, "commit", "-qm", "start", "--no-gpg-sign"], check=True, env=env)
            head = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True,
                                  env=env).stdout.strip()
            r = baseline(d, "record", d, "M1")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((Path(d) / ".evidence/baseline-M1.head").read_text(), head + "\n",
                             "the full hash, one line: gate_checks.py prose-lint reads the commits since it")

    def test_no_commit_file_outside_git_or_before_the_first_commit(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, {"app.py": "x = 1\n"})
            self.assertEqual(baseline(d, "record", d, "M1").returncode, 0)
            self.assertTrue((Path(d) / ".evidence/baseline-M1.txt").is_file())
            self.assertFalse((Path(d) / ".evidence/baseline-M1.head").exists(), "not a git work tree")
            subprocess.run(["git", "init", "-q", d], check=True, env=git_env(d))
            self.assertEqual(baseline(d, "record", d, "M2").returncode, 0)
            self.assertFalse((Path(d) / ".evidence/baseline-M2.head").exists(), "a repository with no commit yet")


class ChangedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        write(self.d, {"app.py": "x = 1\n", "gone.py": "y = 1\n", "same.py": "z = 1\n", "src/keep.py": "k = 1"})
        self.assertEqual(baseline(self.d, "record", self.d, "M2").returncode, 0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_changed_lists_the_files_and_writes_the_review_list(self):
        write(self.d, {"app.py": "x = 2\n", "src/new.py": "n = 1\n", "docs/project/state.md": "planning\n"})
        (Path(self.d) / "gone.py").unlink()
        r = baseline(self.d, "changed", self.d, "M2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["app.py", "gone.py", "src/new.py"],
                         "added, modified, and deleted product files, sorted; planning files are not product")
        r = baseline(self.d, "changed", self.d, "M2", "--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        listing = Path(self.d) / "docs/project/reviews/M2.changed.txt"
        self.assertEqual(r.stdout.strip(), str(listing.resolve()))
        fp = subprocess.run([sys.executable, str(FINGERPRINT), self.d], capture_output=True, text=True).stdout.strip()
        self.assertEqual(listing.read_text(), f"# M2: files changed since its baseline, at fingerprint {fp}\n"
                                              "app.py\ngone.py\nsrc/new.py\n")

    def test_nothing_changed_and_no_baseline(self):
        r = baseline(self.d, "changed", self.d, "M2")
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        r = baseline(self.d, "changed", self.d, "M3", "--write")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no baseline for M3", r.stderr)
        self.assertFalse((Path(self.d) / "docs/project/reviews/M3.changed.txt").exists())
        for args in (("changed", self.d, "M2", "--nope"), ("diff", self.d, "M2", "--max-bytes"),
                     ("record", self.d, "M4", "extra"), ("list", self.d, "M2")):
            self.assertEqual(baseline(self.d, *args).returncode, 2, args)

    def test_diff_still_prints_the_listing_and_the_hunks(self):
        write(self.d, {"app.py": "x = 2\n", "src/keep.py": "k = 2"})
        (Path(self.d) / "gone.py").unlink()
        r = baseline(self.d, "diff", self.d, "M2")
        self.assertEqual(r.returncode, 0, r.stderr)
        for line in ("modified  app.py", "deleted   gone.py", "modified  src/keep.py", "-x = 1", "+x = 2"):
            self.assertIn(line, r.stdout.splitlines())
        self.assertIn("-k = 1\n\\ No newline at end of file\n+k = 2\n\\ No newline at end of file", r.stdout,
                      "a last line without a newline is marked, never glued to the next diff line")
        r = baseline(self.d, "diff", self.d, "M2", "--max-bytes", "10")
        self.assertIn("Diff not shown (over the size budget or binary)", r.stdout)


PATCH = """diff --git a/src/a.sql b/src/a.sql
index 1111111..2222222 100644
--- a/src/a.sql
+++ b/src/a.sql
@@ -1,3 +1,3 @@
 select 1;
--- a comment that reads like a header
+++ a line that reads like one too
 select 2;
diff --git a/img.png b/img.png
new file mode 100644
index 0000000..3333333
Binary files /dev/null and b/img.png differ
--- a/old.py
+++ /dev/null
@@ -1 +0,0 @@
-gone = 1
\\ No newline at end of file
"""


class SplitPatchTest(unittest.TestCase):
    def test_files_of_a_patch_git_style_or_plain(self):
        sys.path.insert(0, str(BASELINE.parent))
        from baseline import split_hunks, split_patch
        files = split_patch(PATCH)
        self.assertEqual(sorted(files), ["img.png", "old.py", "src/a.sql"])
        self.assertEqual((files["src/a.sql"]["status"], files["src/a.sql"]["binary"]), ("modified", False))
        self.assertIn("+++ a line that reads like one too", files["src/a.sql"]["text"],
                      "a hunk line that looks like a header stays in its hunk")
        self.assertEqual((files["img.png"]["status"], files["img.png"]["binary"]), ("added", True))
        self.assertEqual(files["old.py"]["status"], "deleted")
        self.assertTrue(files["old.py"]["text"].endswith("\\ No newline at end of file\n"))
        head, hunks = split_hunks(files["src/a.sql"]["text"])
        self.assertTrue(head.startswith("diff --git") and len(hunks) == 1)
        self.assertEqual(sorted(split_patch(PATCH, known={"b/src/a.sql"})), ["b/src/a.sql", "img.png", "old.py"],
                         "a path known as written keeps its prefix")


if __name__ == "__main__":
    unittest.main()
