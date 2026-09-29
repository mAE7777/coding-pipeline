"""Tests for gate.sh's modes: the check run, --fingerprint, --inventory, and bad options."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "skills/_shared/gate.sh"
FIX = ROOT / "tests/fixtures"
# Git without this machine's global settings: a global ignore rule must not decide what a test stages or sees.
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull}


def gate(*args):
    return subprocess.run(["bash", str(GATE), *args], capture_output=True, text=True, timeout=300, env=GIT_ENV)


class GateShTest(unittest.TestCase):
    def test_fingerprint_matches_script(self):
        a = gate("--fingerprint", str(FIX / "clean")).stdout.strip()
        b = subprocess.run([sys.executable, str(ROOT / "skills/_shared/scripts/fingerprint.py"),
                            str(FIX / "clean")], capture_output=True, text=True).stdout.strip()
        self.assertTrue(a.startswith("product:"), a)
        self.assertEqual(a, b)

    def test_inventory_mode(self):
        out = gate("--inventory", str(FIX / "degradation"))
        self.assertEqual(out.returncode, 0)
        self.assertIn("swallowed-error", out.stdout)

    def test_bad_option(self):
        self.assertEqual(gate("--nope").returncode, 2)

    def test_check_run_names_every_skip(self):
        out = gate(str(FIX / "clean"))
        self.assertIn("RESULT:", out.stdout)
        for line in out.stdout.splitlines():
            if line.startswith("SKIP"):
                self.assertGreater(len(line.split(None, 2)[-1]), 5, f"a SKIP must say why: {line}")

    def test_secret_is_a_fail(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            key = "AKIA" + "ABCDEFGHIJKLMNOP"
            (Path(d) / "config.py").write_text(f"AWS = '{key}'\n")
            out = gate(d)
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertIn("FAIL   secrets", out.stdout)

    def test_tooling_names_in_committed_record_fail(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            docs = Path(d) / "docs/project"
            docs.mkdir(parents=True)
            (docs / "decisions.md").write_text("## D-001\nDecided after the code-verifier run in /gate.\n")
            (docs / "state.md").write_text("local notes about /dev and heavy.py\n")
            subprocess.run(["git", "init", "-q", d], check=True, env=GIT_ENV)
            subprocess.run(["git", "-C", d, "add", "docs/project/decisions.md"], check=True, env=GIT_ENV)
            out = gate(d)
            self.assertIn("FAIL   pipeline-traces", out.stdout)
            self.assertIn("decisions.md", out.stdout)
            self.assertNotIn("state.md", out.stdout.split("pipeline-traces", 1)[1].splitlines()[0],
                             "local-only files may name the tooling")
            (docs / "decisions.md").write_text("## D-001\nDecided after the review.\n")
            out = gate(d)
            self.assertIn("PASS   pipeline-traces", out.stdout)
            (docs / "interfaces.md").write_text("## API\n- POST /capture stores a photo\n- GET /plan returns the week\n"
                                                "The extension talks to Claude Code through a subagent.\n")
            subprocess.run(["git", "-C", d, "add", "docs/project/interfaces.md"], check=True, env=GIT_ENV)
            out = gate(d)
            self.assertIn("PASS   pipeline-traces", out.stdout, "product routes and product words are not tooling")
            (docs / "decisions.md").write_text("## D-002\nAccepted after /gate M1 and /plan adopt.\n")
            out = gate(d)
            self.assertIn("FAIL   pipeline-traces", out.stdout)


    def test_committed_templates_never_trip_the_trace_check(self):
        """A project that commits its record straight from the templates must pass; the new names must fail."""
        import tempfile
        sys.path.insert(0, str(ROOT / "skills/_shared/scripts"))
        import inbox  # noqa: E402
        templates = ROOT / "skills/_shared/templates"
        with tempfile.TemporaryDirectory() as d:
            docs = Path(d) / "docs/project"
            docs.mkdir(parents=True)
            for name in ("intent.md", "milestones.md", "decisions.md", "interfaces.md", "fix-log.md"):
                (docs / name).write_text((templates / name).read_text())
            (docs / "inbox.md").write_text(inbox.HEADER)
            subprocess.run(["git", "init", "-q", d], check=True, env=GIT_ENV)
            subprocess.run(["git", "-C", d, "add", "docs/project"], check=True, env=GIT_ENV)
            staged = subprocess.run(["git", "-C", d, "ls-files"], capture_output=True, text=True, env=GIT_ENV).stdout
            self.assertIn("docs/project/fix-log.md", staged, "every template is checked, the fix log included")
            out = gate(d)
            self.assertIn("PASS   pipeline-traces", out.stdout, out.stdout[-600:])
            for trace in ("Weighed with /inbox review.", "Proven with rulings.py record.", "Run /next auto.",
                          "Recorded by project_status record."):
                (docs / "decisions.md").write_text(f"## D-003\n{trace}\n")
                self.assertIn("FAIL   pipeline-traces", gate(d).stdout, trace)

    def test_a_record_file_git_ignores_is_named(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            docs = Path(d) / "docs/project"
            docs.mkdir(parents=True)
            (docs / "fix-log.md").write_text("# Fix log\n")
            (docs / "decisions.md").write_text("# Decisions\n")
            subprocess.run(["git", "init", "-q", d], check=True, env=GIT_ENV)
            (Path(d) / ".git/info/exclude").write_text("fix-log.md\n")
            subprocess.run(["git", "-C", d, "add", "docs/project"], check=True, env=GIT_ENV)
            out = gate(d).stdout
            self.assertIn("FAIL   record-tracked", out)
            self.assertIn("docs/project/fix-log.md", out)
            self.assertNotIn("docs/project/decisions.md (ignored", out)
            subprocess.run(["git", "-C", d, "add", "-f", "docs/project/fix-log.md"], check=True, env=GIT_ENV)
            self.assertIn("PASS   record-tracked", gate(d).stdout, "a tracked file is committed whatever the rules say")
            # A git that cannot read an ignore file cannot vouch for anything: that is a failure, never a pass.
            (docs / "inbox.md").write_text("# Inbox\n")
            exclude = Path(d) / ".git/info/exclude"
            exclude.chmod(0)
            try:
                out = gate(d).stdout
            finally:
                exclude.chmod(0o644)
            self.assertIn("FAIL   record-tracked", out)
            self.assertIn("could not tell", out)
            # A worktree (its .git is a file) is checked like any checkout; outside git the check says it was skipped.
            subprocess.run(["git", "-C", d, "commit", "-qm", "record", "--no-gpg-sign"], check=True, env={
                **GIT_ENV, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@example.com"})
            wt = Path(d) / "wt"
            subprocess.run(["git", "-C", d, "worktree", "add", "-q", "--detach", str(wt)], check=True, env=GIT_ENV)
            (wt / "docs/project/milestones.md").write_text("# Milestones\n")
            (Path(d) / ".git/info/exclude").write_text("fix-log.md\nmilestones.md\n")
            out = gate(str(wt)).stdout
            self.assertIn("FAIL   record-tracked", out, "a worktree is checked, not skipped")
            self.assertIn("docs/project/milestones.md", out)
            # Noise that says nothing about ignore rules does not turn a clear answer into "could not tell".
            fake = Path(d) / "bin"
            fake.mkdir()
            real_git = subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip()
            (fake / "git").write_text(f"#!/bin/bash\n\"{real_git}\" \"$@\"\nrc=$?\n"
                                      "echo \"warning: unable to access '/somewhere/.config/git/attributes'\" >&2\n"
                                      "exit $rc\n")
            (fake / "git").chmod(0o755)
            (Path(d) / ".git/info/exclude").write_text("")
            noisy = subprocess.run(["bash", str(GATE), str(wt)], capture_output=True, text=True, timeout=300,
                                   env={**GIT_ENV, "PATH": f"{fake}:{os.environ['PATH']}"}).stdout
            self.assertIn("PASS   record-tracked", noisy, noisy[-800:])
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("SKIP   record-tracked", gate(d).stdout)


if __name__ == "__main__":
    unittest.main()
