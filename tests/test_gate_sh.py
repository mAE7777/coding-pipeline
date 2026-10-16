"""Tests for gate.sh's modes: the check run, --fingerprint, --inventory, and bad options."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "skills/_shared/gate.sh"
FIX = ROOT / "tests/fixtures"
SCRIPTS = ROOT / "skills/_shared/scripts"
# Git without this machine's global settings (the global config and the XDG ignore file both carry ignore rules): a
# rule set for the whole machine must not decide what a test stages or sees.
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "XDG_CONFIG_HOME": os.devnull}


def gate(*args):
    if args and not args[0].startswith("--"):
        import tempfile
        import shutil
        target = Path(args[0])
        if target.is_relative_to(FIX):
            with tempfile.TemporaryDirectory() as d:
                copy = Path(d) / "fixture"
                shutil.copytree(target, copy)
                return gate(str(copy), *args[1:])
        sys.path.insert(0, str(ROOT / "skills/_shared/scripts"))
        from project_policy import set_mode
        set_mode(target, True)
    return subprocess.run(["bash", str(GATE), *args], capture_output=True, text=True, timeout=300, env=GIT_ENV)


class GateShTest(unittest.TestCase):
    def test_fingerprint_matches_script(self):
        a = gate("--fingerprint", str(FIX / "clean")).stdout.strip()
        b = subprocess.run([sys.executable, str(ROOT / "skills/_shared/scripts/fingerprint.py"),
                            str(FIX / "clean")], capture_output=True, text=True, env=GIT_ENV).stdout.strip()
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
                          "Recorded by project_status record.", "Flagged by gate_checks.py test-tamper.",
                          "Numbered by decisions.py add.", "Re-read through reentry_digest after the compaction.",
                          "Scoped by regate_scope to the changed files.", "Compared by shadow_diff.py.",
                          "Checked with pr_watch.py land-check.", "Vendored files verified by craft_sync.",
                          "The judge runs on high in ~/.claude/.pipeline-models.json.",
                          "Shadow rounds logged in .pipeline-shadow.jsonl."):
                (docs / "decisions.md").write_text(f"## D-003\n{trace}\n")
                self.assertIn("FAIL   pipeline-traces", gate(d).stdout, trace)
            # product words that share a script's stem are not tooling: a Django app has models.py and decisions
            (docs / "decisions.md").write_text("## D-004\nThe ledger's tables live in models.py and its routing "
                                               "in models.json; the decisions page lists every decision.\n")
            self.assertIn("PASS   pipeline-traces", gate(d).stdout, "ordinary product names pass")

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
            self.assertIn("info/exclude", out, "the unreadable rule file is named, not git's first line of noise")
            # An ignore file by any other name counts the same.
            rules = Path(d) / "my-rules"
            rules.write_text("nothing\n")
            subprocess.run(["git", "-C", d, "config", "core.excludesFile", str(rules)], check=True, env=GIT_ENV)
            rules.chmod(0)
            try:
                out = gate(d).stdout
            finally:
                rules.chmod(0o644)
            self.assertIn("could not tell", out)
            self.assertIn("my-rules", out)
            subprocess.run(["git", "-C", d, "config", "--unset", "core.excludesFile"], check=True, env=GIT_ENV)
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
        # An ignore file that cannot even be looked at (its folder is closed) is unreadable, not absent.
        with tempfile.TemporaryDirectory() as d:
            docs = Path(d) / "docs/project"
            docs.mkdir(parents=True)
            (docs / "fix-log.md").write_text("# Fix log\n")
            subprocess.run(["git", "init", "-q", d], check=True, env=GIT_ENV)
            closed = Path(d) / "closed"
            closed.mkdir()
            (closed / "rules").write_text("nothing\n")
            subprocess.run(["git", "-C", d, "config", "core.excludesFile", str(closed / "rules")], check=True, env=GIT_ENV)
            closed.chmod(0)
            try:
                out = gate(d).stdout
            finally:
                closed.chmod(0o755)
            self.assertIn("could not tell", out)
            self.assertIn("closed/rules", out)
        # A project in a subfolder of its repository is checked against the repository's rules.
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d) / "apps/tally"
            (proj / "docs/project").mkdir(parents=True)
            (proj / "docs/project/fix-log.md").write_text("# Fix log\n")
            subprocess.run(["git", "init", "-q", d], check=True, env=GIT_ENV)
            (Path(d) / ".gitignore").write_text("fix-log.md\n")
            out = gate(str(proj)).stdout
            self.assertIn("FAIL   record-tracked", out)
            self.assertIn("docs/project/fix-log.md", out)
            # Without HOME the gate still runs to its end.
            no_home = {k: v for k, v in GIT_ENV.items() if k != "HOME"}
            out = subprocess.run(["bash", str(GATE), str(proj)], capture_output=True, text=True, timeout=300, env=no_home)
            self.assertIn("RESULT:", out.stdout, out.stderr[-400:])
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("SKIP   record-tracked", gate(d).stdout)
            # A repository git cannot read is a failure to vouch for anything, not "not a repository".
            (Path(d) / ".git").write_text("gitdir: /nonexistent/elsewhere\n")
            self.assertRegex(gate(d).stdout, r"FAIL\s+record-tracked\s+git cannot read this repository")
            # The reason shown is git's own error, not a wrapper's noise printed before it.
            fake = Path(d) / "bin"
            fake.mkdir()
            real_git = subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip()
            (fake / "git").write_text(f"#!/bin/bash\necho 'xcrun: cannot write the cache file' >&2\n\"{real_git}\" \"$@\"\n")
            (fake / "git").chmod(0o755)
            out = subprocess.run(["bash", str(GATE), d], capture_output=True, text=True, timeout=300,
                                 env={**GIT_ENV, "PATH": f"{fake}:{os.environ['PATH']}"}).stdout
            line = next(l for l in out.splitlines() if "record-tracked" in l)
            self.assertIn("fatal:", line)
            self.assertNotIn("xcrun", line)

    def test_record_tracked_edge_cases(self):
        import shutil
        import tempfile

        def repo(d):
            docs = Path(d) / "docs/project"
            docs.mkdir(parents=True)
            (docs / "fix-log.md").write_text("# Fix log\n")
            subprocess.run(["git", "init", "-q", str(d)], check=True, env=GIT_ENV)
            sys.path.insert(0, str(ROOT / "skills/_shared/scripts"))
            from project_policy import set_mode
            set_mode(Path(d), True)

        def run(d, **env):
            return subprocess.run(["bash", str(GATE), str(d)], capture_output=True, text=True, timeout=300,
                                  env={**GIT_ENV, **env}).stdout

        # An unreadable global git config may name the ignore file that hides a record file: never a pass.
        with tempfile.TemporaryDirectory() as d:
            repo(d)
            rules = Path(d) / "rules"
            rules.write_text("fix-log.md\n")
            cfg = Path(d) / "gitconfig"
            cfg.write_text(f"[core]\n\texcludesFile = {rules}\n")
            cfg.chmod(0)
            try:
                out = run(d, GIT_CONFIG_GLOBAL=str(cfg))
            finally:
                cfg.chmod(0o644)
            self.assertNotIn("PASS   record-tracked", out)
            self.assertIn("gitconfig", out)
        # Reached through a symlinked path, the walk for .gitignore files stops at the repository.
        with tempfile.TemporaryDirectory() as d:
            real = Path(d) / "real"
            repo(real)
            link = Path(d) / "link"
            link.symlink_to(real, target_is_directory=True)
            above = Path(d) / ".gitignore"
            above.write_text("nothing\n")
            above.chmod(0)
            try:
                out = run(link)
            finally:
                above.chmod(0o644)
            self.assertIn("PASS   record-tracked", out, "a file above the repository is not one of its rules")
        # Whether a rule file is missing does not depend on the language of ls's messages.
        with tempfile.TemporaryDirectory() as d:
            repo(d)
            fake = Path(d) / "bin"
            fake.mkdir()
            (fake / "ls").write_text("#!/bin/bash\necho \"ls: $2: Datei oder Verzeichnis nicht gefunden\" >&2\nexit 1\n")
            (fake / "ls").chmod(0o755)
            out = run(d, PATH=f"{fake}:{os.environ['PATH']}")
            self.assertIn("PASS   record-tracked", out, out[-600:])
        # A repository on a machine without git: not checked, said so; never "not in a git repository".
        with tempfile.TemporaryDirectory() as d:
            repo(d)
            farm = Path(d) / "farm"
            farm.mkdir()
            for src in ("/bin", "/usr/bin", "/usr/sbin", "/sbin"):
                for f in Path(src).iterdir():
                    if f.name != "git" and not (farm / f.name).exists():
                        (farm / f.name).symlink_to(f)
            (farm / "python3").unlink(missing_ok=True)
            (farm / "python3").symlink_to(shutil.which("python3"))
            out = run(d, PATH=str(farm))
            for check in ("record-tracked", "pipeline-traces", "env-files"):
                self.assertRegex(out, rf"FAIL\s+{check}\s+git is not installed", "the gate cannot vouch, so it says so")
            self.assertIn("RESULT: FAIL", out, "nothing unchecked hides under a green summary")
        # A rule file the operating system will not let git open (a sandbox, privacy protection) is not absent.
        if shutil.which("sandbox-exec"):
            with tempfile.TemporaryDirectory() as d:
                repo(d)
                rules = Path(d) / "rules"
                rules.write_text("fix-log.md\n")
                subprocess.run(["git", "-C", d, "config", "core.excludesFile", str(rules)], check=True, env=GIT_ENV)
                real = str(rules.resolve())
                profile = f'(version 1) (allow default) (deny file-read* (literal "{real}"))'
                out = subprocess.run(["sandbox-exec", "-p", profile, "bash", str(GATE), d], capture_output=True,
                                     text=True, timeout=300, env=GIT_ENV).stdout
                self.assertNotIn("PASS   record-tracked", out, out[-600:])
                self.assertIn("rules", out)
        # Through a symlink to a project in a subfolder of its repository, the repository is still found.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            proj = root / "apps/tally"
            (proj / "docs/project").mkdir(parents=True)
            (proj / "docs/project/fix-log.md").write_text("# Fix log\n")
            subprocess.run(["git", "init", "-q", str(root)], check=True, env=GIT_ENV)
            (root / ".gitignore").write_text("fix-log.md\n")
            sys.path.insert(0, str(ROOT / "skills/_shared/scripts"))
            from project_policy import set_mode
            set_mode(proj, True)
            link = Path(d) / "tally-link"
            link.symlink_to(proj, target_is_directory=True)
            out = run(link)
            self.assertIn("FAIL   record-tracked", out, out[-600:])
            self.assertIn("docs/project/fix-log.md", out)
        # With GIT_CONFIG_GLOBAL set, git never reads the XDG config, so an unreadable one is no reason to fail.
        with tempfile.TemporaryDirectory() as d:
            repo(d)
            xdg = Path(d) / "home/.config/git"
            xdg.mkdir(parents=True)
            (xdg / "config").write_text("[core]\n")
            (xdg / "config").chmod(0)
            try:
                out = run(d, HOME=str(Path(d) / "home"), XDG_CONFIG_HOME=str(Path(d) / "home/.config"))
            finally:
                (xdg / "config").chmod(0o644)
            self.assertIn("PASS   record-tracked", out, out[-600:])


STATUS = re.compile(r"^(PASS|FAIL|WARN|SKIP)\s+(\S+)\s+(.*)$")
GIT_ID = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
          "GIT_COMMITTER_EMAIL": "t@example.com"}
PY_TEST = ("import unittest\n\n\nclass T(unittest.TestCase):\n"
           "    def test_one(self):\n        self.assertEqual(1, 1)\n        self.assertTrue(True)\n\n"
           "    def test_two(self):\n        self.assertIn('a', 'ab')\n")
JS_TEST = "jest.setTimeout(5000);\n\nit('adds', () => {\n  expect(1 + 1).toBe(2);\n});\n"
STATE = "# State\n\n## Milestone\nM1 \u00b7 phase: building\n"


def lines_of(out, check):
    """(status, detail) for each line one check printed."""
    return [(m.group(1), m.group(3)) for m in map(STATUS.match, out.splitlines()) if m and m.group(2) == check]


def write(root, files):
    for rel, text in files.items():
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def with_baseline(d, files, milestone="M1"):
    """A project whose milestone started with these files."""
    write(d, {**files, "docs/project/state.md": STATE.replace("M1", milestone)})
    subprocess.run([sys.executable, str(SCRIPTS / "baseline.py"), "record", str(d), milestone], check=True,
                   capture_output=True, env=GIT_ENV)
    return Path(d)


class BaselineChecksTest(unittest.TestCase):
    """test-tamper, file-growth, and prose-lint: what changed since the milestone's baseline, and outbound text."""

    def failing(self, out):
        return " ".join(t for s, t in lines_of(out, "test-tamper") if s == "FAIL")

    def test_a_deleted_test_file_fails_but_a_moved_one_does_not(self):
        with tempfile.TemporaryDirectory() as d:
            root = with_baseline(d, {"tests/test_a.py": PY_TEST, "tests/test_b.py": "def test_b():\n    assert 1\n",
                                     "tests/test_c.py": "def test_c():\n    assert 2\n"})
            (root / "tests/test_b.py").unlink()
            (root / "tests/unit").mkdir()
            (root / "tests/test_c.py").rename(root / "tests/unit/test_c.py")
            out = gate(d).stdout
            self.assertEqual([s for s, _ in lines_of(out, "test-tamper")], ["FAIL", "WARN"], out)
            self.assertIn("tests/test_b.py deleted", self.failing(out))
            self.assertNotIn("test_c.py", self.failing(out), "a move with unchanged content is not a deletion")
            self.assertIn("RESULT: FAIL", out)

    def test_a_new_skip_only_or_expected_failure_marker_fails(self):
        with tempfile.TemporaryDirectory() as d:
            old_skip = "import pytest\n\n\n@pytest.mark.skip(reason='upstream outage')\ndef test_old():\n    assert 1\n"
            with_baseline(d, {"tests/test_a.py": PY_TEST, "tests/test_old.py": old_skip, "web/app.test.ts": JS_TEST})
            write(d, {"tests/test_a.py": PY_TEST.replace("    def test_two", "    @unittest.skip('later')\n    def test_two"),
                      "web/app.test.ts": JS_TEST.replace("it('adds'", "it.only('adds'"),
                      "tests/test_old.py": "# kept as it was\n" + old_skip,
                      "tests/test_new.py": "import pytest\n\n\n@pytest.mark.xfail\ndef test_new():\n    assert 0\n"})
            fail = self.failing(gate(d).stdout)
            self.assertIn("tests/test_a.py:9 new skip marker @unittest.skip", fail)
            self.assertIn("web/app.test.ts:3 new only marker it.only", fail)
            self.assertIn("tests/test_new.py:4 new expected-failure marker @pytest.mark.xfail", fail)
            self.assertNotIn("test_old.py", fail, "a marker already there at the baseline is not new")

    def test_a_raised_timeout_fails_and_a_lowered_one_does_not(self):
        with tempfile.TemporaryDirectory() as d:
            slow = "import pytest\n\n\n@pytest.mark.timeout(30)\ndef test_slow():\n    assert 1\n"
            with_baseline(d, {"web/app.test.ts": JS_TEST, "tests/test_slow.py": slow,
                              "jest.config.js": "module.exports = { testTimeout: 5000 };\n"})
            write(d, {"web/app.test.ts": "// CI is slow\n" + JS_TEST.replace("5000", "20_000"),
                      "tests/test_slow.py": slow.replace("(30)", "(10)"),
                      "jest.config.js": "module.exports = { testTimeout: 60000 };\n"})
            fail = self.failing(gate(d).stdout)
            self.assertIn("web/app.test.ts:2 timeout raised 5000 -> 20_000", fail)
            self.assertIn("jest.config.js:1 timeout raised 5000 -> 60000", fail, "a test runner's config counts too")
            self.assertNotIn("test_slow.py", fail, "a lowered timeout is not a finding")

    def test_an_assertion_drop_warns(self):
        with tempfile.TemporaryDirectory() as d:
            with_baseline(d, {"tests/test_a.py": PY_TEST, "web/app.test.ts": JS_TEST})
            write(d, {"tests/test_a.py": PY_TEST.replace("        self.assertTrue(True)\n", "")})
            got = lines_of(gate(d).stdout, "test-tamper")
            self.assertEqual([s for s, _ in got], ["WARN"], got)
            self.assertIn("fell from 4 to 3 since the M1 baseline", got[0][1])
            self.assertIn("tests/test_a.py 3 -> 2 (baseline line 7 gone)", got[0][1])

    def test_a_clean_change_passes(self):
        with tempfile.TemporaryDirectory() as d:
            with_baseline(d, {"tests/test_a.py": PY_TEST, "web/app.test.ts": JS_TEST})
            write(d, {"tests/test_a.py": PY_TEST + "\n    def test_three(self):\n        self.assertFalse(False)\n",
                      "web/app.test.ts": JS_TEST.replace("5000", "2000")})
            got = lines_of(gate(d).stdout, "test-tamper")
            self.assertEqual([s for s, _ in got], ["PASS"], got)
            self.assertIn("assertions 4 -> 5", got[0][1])

    def test_only_an_owner_ruling_clears_a_finding(self):
        with tempfile.TemporaryDirectory() as d:
            root = with_baseline(d, {"tests/test_a.py": PY_TEST, "tests/test_b.py": "def test_b():\n    assert 1\n"})
            (root / "tests/test_b.py").unlink()
            entry = ("# Decisions\n\n## D-004 \u00b7 2026-10-16 \u00b7 retire the old parser's tests\n"
                     "Decision: delete the old parser and its tests [test-change: {path}]\n"
                     "Why: the parser is gone\nAlternatives: keep it unused\nSource: {source}\nAffects: M1\n"
                     "Supersedes: none\n")
            owner = '[owner 2026-10-16] "Delete the old parser and its tests."'
            decisions = root / "docs/project/decisions.md"
            decisions.write_text(entry.format(path="tests/test_b.py", source="[proposed]"))
            fail = self.failing(gate(d).stdout)
            self.assertIn("tests/test_b.py deleted", fail, "a proposed entry clears nothing")
            self.assertIn("not cleared, the entry's Source is not an owner ruling: tests/test_b.py (D-004)", fail)
            decisions.write_text(entry.format(path="tests/test_x.py", source=owner))
            self.assertIn("tests/test_b.py deleted", self.failing(gate(d).stdout), "a ruling on another file")
            decisions.write_text(entry.format(path="tests/test_b.py", source=owner))
            got = lines_of(gate(d).stdout, "test-tamper")
            self.assertEqual([s for s, _ in got], ["PASS"], got)
            self.assertIn("cleared by owner ruling: tests/test_b.py (D-004)", got[0][1])

    def test_tamper_on_the_tally_fixtures(self):
        """The planted fixture's thin test file, put over the clean fixture's, is caught; the clean one passes."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "tally"
            shutil.copytree(FIX / "agents/tally-clean", root)
            with_baseline(root, {})
            self.assertEqual([s for s, _ in lines_of(gate(str(root)).stdout, "test-tamper")], ["PASS"])
            shutil.copy(FIX / "agents/tally-defects/tests/test_app.py", root / "tests/test_app.py")
            got = lines_of(gate(str(root)).stdout, "test-tamper")
            self.assertEqual([s for s, _ in got], ["WARN"], got)
            self.assertIn("tests/test_app.py", got[0][1])

    def test_file_growth_warns(self):
        def lines(n):
            return "".join(f"x{i} = {i}\n" for i in range(n))
        with tempfile.TemporaryDirectory() as d:
            with_baseline(d, {"app.py": lines(900), "huge.py": lines(1100), "vendor/lib.js": lines(10),
                              "notes.md": lines(10)})
            write(d, {"app.py": lines(1200), "huge.py": lines(1300), "new.ts": lines(1050),
                      "vendor/lib.js": lines(2000), "package-lock.json": lines(5000), "notes.md": lines(2000),
                      "gen.py": "# Code generated by protoc. DO NOT EDIT.\n" + lines(1500),
                      "web/app.min.js": lines(3000)})
            got = lines_of(gate(d).stdout, "file-growth")
            self.assertEqual([s for s, _ in got], ["WARN"], got)
            self.assertIn("app.py 900 -> 1,200", got[0][1])
            self.assertIn("new.ts new -> 1,050", got[0][1])
            for quiet in ("huge.py", "vendor/lib.js", "package-lock.json", "notes.md", "gen.py", "app.min.js"):
                self.assertNotIn(quiet, got[0][1])

    def test_prose_lint_warns_with_examples_and_never_fails(self):
        readme = ("# Tool\n"
                  "It counts \u2014 fast.\n"
                  "Ranges 2019\u20132021, quotes \u201chere\u201d, a pivotal tapestry.\n"
                  "```\nconst s = \u201cq\u201d \u2014 delve;\n```\n"
                  "Run `delve --fast` with orientation: landscape.\n"
                  "\u4e2d\u6587\u8bf4\u660e\uff1a\u201c\u5f15\u53f7\u201d \u2014 \u53ef\u4ee5\n"
                  "I hope this helps.\n")
        with tempfile.TemporaryDirectory() as d:
            write(d, {"README.md": readme, "docs/guide.md": "Additionally, it works.\n",
                      "docs/project/intent.md": "A crucial \u2014 point.\n",
                      "locales/zh/README.md": "\u2014 \u201cx\u201d\n", "docs/i18n/fr.md": "Il \u2014 marche.\n"})
            got = lines_of(gate(d).stdout, "prose-lint")
            self.assertEqual([s for s, _ in got], ["WARN"], got)
            detail = got[0][1]
            self.assertIn("spaced em dash 1 (README.md:2)", detail)
            self.assertIn("en dash 1 (README.md:3)", detail)
            self.assertIn("curly quote 2 (README.md:3)", detail)
            self.assertIn("AI vocabulary 3 (README.md:3 pivotal, README.md:3 tapestry, docs/guide.md:1 additionally)",
                          detail)
            self.assertIn("chatbot phrase 1 (README.md:9 I hope this helps)", detail)
            self.assertNotIn("README.md:5", detail, "fenced code is not prose")
            self.assertNotIn("README.md:7", detail, "inline code and a screen orientation are not prose")
            self.assertNotIn("README.md:8", detail, "a line in Chinese keeps its own quotes and dashes")
            self.assertNotIn("intent.md", detail, "planning records are not outbound text")
            self.assertNotIn("fr.md", detail)
            self.assertIn("2 locale or translation file(s) left out", detail)
            self.assertIn("Commit messages not checked", detail)

    def test_prose_lint_reads_commit_messages_since_the_recorded_commit(self):
        env = {**GIT_ENV, **GIT_ID}
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True, env=env)
            write(d, {"app.py": "x = 1\n"})
            subprocess.run(["git", "-C", d, "add", "app.py"], check=True, env=env)
            subprocess.run(["git", "-C", d, "commit", "-qm", "start", "--no-gpg-sign"], check=True, env=env)
            root = with_baseline(d, {})
            head = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True,
                                  env=env).stdout.strip()
            recorded = root / ".evidence/baseline-M1.head"
            self.assertEqual(recorded.read_text(), head + "\n", "baseline.py record notes the commit it started from")
            recorded.unlink()
            got = lines_of(gate(d).stdout, "prose-lint")
            self.assertIn("commit messages not checked: the M1 baseline records no git commit", got[0][1])
            recorded.write_text(head + "\n")
            write(d, {"app.py": "x = 2\n"})
            subprocess.run(["git", "-C", d, "commit", "-qam", "Make it faster \u2014 a pivotal change\n\nCertainly!",
                            "--no-gpg-sign"], check=True, env=env)
            new = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True,
                                 env=env).stdout.strip()
            got = lines_of(gate(d).stdout, "prose-lint")
            self.assertEqual([s for s, _ in got], ["WARN"], got)
            self.assertIn(f"spaced em dash 1 (commit {new[:7]}:1)", got[0][1])
            self.assertIn(f"chatbot phrase 1 (commit {new[:7]}:3 Certainly!)", got[0][1])
            self.assertIn(f"1 commit message(s) since {head[:7]} checked", got[0][1],
                          "the baseline's own commit is not one since the baseline")

    def test_without_a_baseline_the_comparisons_are_skipped_with_the_reason(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, {"tests/test_a.py": PY_TEST})
            out = gate(d).stdout
            for check in ("test-tamper", "file-growth"):
                got = lines_of(out, check)
                self.assertEqual([s for s, _ in got], ["SKIP"], got)
                self.assertIn("there is no docs/project/state.md", got[0][1])
            write(d, {"docs/project/state.md": STATE.replace("M1", "M2")})
            got = lines_of(gate(d).stdout, "test-tamper")
            self.assertEqual([s for s, _ in got], ["SKIP"], got)
            self.assertIn("no baseline recorded for M2", got[0][1])
            # state.md says a baseline was recorded, and it is gone: nothing can vouch, so it is no quiet skip.
            write(d, {"docs/project/state.md": STATE.replace("M1", "M2") + "\n## Baseline\nproduct:0123456789abcdef\n"})
            out = gate(d).stdout
            self.assertRegex(out, r"FAIL\s+test-tamper\s+test-tamper could not run: .*baseline-M2\.txt is gone")
            self.assertRegex(out, r"WARN\s+file-growth\s+file-growth could not run")

    def test_a_check_that_cannot_run_is_named(self):
        with tempfile.TemporaryDirectory() as d:
            root = with_baseline(d, {"tests/test_a.py": PY_TEST})
            (root / "docs/project/state.md").write_bytes(b"## Milestone\nM1 \xff\xfe\n")
            out = gate(d).stdout
            self.assertRegex(out, r"FAIL\s+test-tamper\s+test-tamper could not run: docs/project/state.md is not UTF-8")
            self.assertRegex(out, r"WARN\s+file-growth\s+file-growth could not run: docs/project/state.md is not UTF-8")
            # The helper itself broken before it printed anything: every check is still named.
            fake = Path(d) / "bin"
            fake.mkdir()
            (fake / "python3").write_text(f"#!/bin/bash\ncase \"$1\" in *gate_checks.py) echo 'RuntimeError: boom' >&2; "
                                          f"exit 1 ;; esac\nexec \"{shutil.which('python3')}\" \"$@\"\n")
            (fake / "python3").chmod(0o755)
            out = subprocess.run(["bash", str(GATE), d], capture_output=True, text=True, timeout=300,
                                 env={**GIT_ENV, "PATH": f"{fake}:{os.environ['PATH']}"}).stdout
            self.assertRegex(out, r"FAIL\s+test-tamper\s+test-tamper could not run: RuntimeError: boom")
            self.assertRegex(out, r"WARN\s+file-growth\s+file-growth could not run: RuntimeError: boom")
            self.assertRegex(out, r"WARN\s+prose-lint\s+prose-lint could not run: RuntimeError: boom")
            self.assertIn("RESULT: FAIL", out)


if __name__ == "__main__":
    unittest.main()
