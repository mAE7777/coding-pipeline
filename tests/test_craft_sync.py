"""Tests for craft_sync.py: the vendored craft layer stays honest about what it copied and what changed upstream."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "skills/_shared/scripts/craft_sync.py"

PRINCIPLE = "# Laziness Protocol\n\n- Minimize the diff.\n"
PLAYBOOK = "### Bug fix\n\n1. Reproduce it via the control skill.\n2. Fix it.\n"
EDITED = "### Bug fix\n\n1. Reproduce it via `playwright-cli`.\n2. Fix it.\n"


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class CraftSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.home = d / "home"
        self.home.mkdir()
        self.repo = d / "plugins"
        self.pstack = self.repo / "pstack"
        self.put(self.pstack / "skills/principle-laziness-protocol/SKILL.md", PRINCIPLE)
        self.put(self.pstack / "skills/poteto-mode/playbooks/bug-fix.md", PLAYBOOK)
        self.put(self.pstack / "LICENSE", "MIT License\n")
        self.craft = d / "craft"
        self.put(self.craft / "principles/principle-laziness-protocol.md", PRINCIPLE)
        self.put(self.craft / "methods/bug-fix.md", EDITED)
        self.put(self.craft / "LICENSE-pstack", "MIT License\n")
        self.put(self.craft / "SKILL.md", "---\nname: craft\n---\n")
        self.commit = "0000000"
        self.files = [
            self.entry("principles/principle-laziness-protocol.md", "skills/principle-laziness-protocol/SKILL.md",
                       PRINCIPLE, None),
            self.entry("methods/bug-fix.md", "skills/poteto-mode/playbooks/bug-fix.md", PLAYBOOK,
                       "control skill becomes playwright-cli"),
            self.entry("LICENSE-pstack", "LICENSE", "MIT License\n", None),
        ]
        self.write_manifest()
        self.env = {**os.environ, "HOME": str(self.home), "GIT_CONFIG_NOSYSTEM": "1"}
        self.env.pop("PSTACK_DIR", None)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def entry(self, local, upstream, text, edit):
        return {"local": local, "upstream": upstream, "commit": self.commit, "sha256": sha(text), "local_edit": edit}

    def write_manifest(self):
        manifest = {"upstream": {"name": "pstack", "commit": self.commit}, "own": ["SKILL.md", "UPSTREAM.json"],
                    "files": self.files}
        (self.craft / "UPSTREAM.json").write_text(json.dumps(manifest, indent=2))

    def run_sync(self, *args, env=None):
        return subprocess.run([sys.executable, str(SYNC), *args], capture_output=True, text=True,
                              env=env or self.env, timeout=60)

    def compare(self, *extra):
        return self.run_sync("--craft", str(self.craft), "--upstream", str(self.pstack), *extra)

    def git(self, *args):
        out = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, env={
            **self.env, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com"})
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def test_verify_passes_when_the_manifest_tells_the_truth(self):
        out = self.run_sync("verify", "--craft", str(self.craft))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("PASS (3 entries, 0 problem(s))", out.stdout)

    def test_verify_fails_when_a_verbatim_file_was_edited(self):
        self.put(self.craft / "principles/principle-laziness-protocol.md", PRINCIPLE + "- A local addition.\n")
        out = self.run_sync("verify", "--craft", str(self.craft))
        self.assertEqual(out.returncode, 1)
        self.assertIn("principles/principle-laziness-protocol.md: differs from", out.stdout)
        self.assertIn("local_edit is null", out.stdout)

    def test_verify_fails_when_an_edit_is_claimed_but_the_file_is_verbatim(self):
        self.put(self.craft / "methods/bug-fix.md", PLAYBOOK)
        out = self.run_sync("verify", "--craft", str(self.craft))
        self.assertEqual(out.returncode, 1)
        self.assertIn("methods/bug-fix.md: identical to", out.stdout)

    def test_verify_fails_on_an_unlisted_or_missing_file(self):
        self.put(self.craft / "methods/new-method.md", "# New\n")
        (self.craft / "LICENSE-pstack").unlink()
        out = self.run_sync("verify", "--craft", str(self.craft), "--json")
        self.assertEqual(out.returncode, 1)
        problems = json.loads(out.stdout)["problems"]
        self.assertIn("methods/new-method.md: not listed in UPSTREAM.json", problems)
        self.assertIn("LICENSE-pstack: listed but missing", problems)

    def test_verify_ignores_bytecode_caches(self):
        self.put(self.craft / "__pycache__/x.pyc", "")
        self.assertEqual(self.run_sync("verify", "--craft", str(self.craft)).returncode, 0)

    def test_nothing_changed_upstream_exits_0(self):
        out = self.compare()
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("unchanged         principles/principle-laziness-protocol.md", out.stdout)
        self.assertIn("local edit        methods/bug-fix.md", out.stdout)
        self.assertIn("(control skill becomes playwright-cli)", out.stdout)
        self.assertIn("0 upstream change(s) since 0000000", out.stdout)

    def test_the_repository_root_holding_pstack_is_accepted(self):
        out = self.run_sync("--craft", str(self.craft), "--upstream", str(self.repo))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_the_checkout_can_come_from_the_environment(self):
        out = self.run_sync("--craft", str(self.craft), env={**self.env, "PSTACK_DIR": str(self.pstack)})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_a_changed_verbatim_file_is_diffed_against_the_recorded_text(self):
        self.put(self.pstack / "skills/principle-laziness-protocol/SKILL.md",
                 PRINCIPLE.replace("Minimize the diff.", "Make the smallest change.") + "- Consolidate decisions.\n")
        out = self.compare("--diff")
        self.assertEqual(out.returncode, 1)
        self.assertIn("upstream changed  principles/principle-laziness-protocol.md", out.stdout)
        self.assertIn("(+2 -1 lines)", out.stdout)
        self.assertIn("+- Consolidate decisions.", out.stdout)

    def test_a_vanished_upstream_file_is_reported(self):
        shutil.rmtree(self.pstack / "skills/poteto-mode")
        out = self.compare("--json")
        self.assertEqual(out.returncode, 1)
        rows = {r["local"]: r["status"] for r in json.loads(out.stdout)["entries"]}
        self.assertEqual(rows["methods/bug-fix.md"], "missing upstream")
        self.assertEqual(rows["LICENSE-pstack"], "unchanged")

    def test_an_edited_file_is_diffed_against_git_history_when_it_has_the_commit(self):
        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.commit = self.git("rev-parse", "--short", "HEAD")
        for f in self.files:
            f["commit"] = self.commit
        self.write_manifest()
        self.put(self.pstack / "skills/poteto-mode/playbooks/bug-fix.md", PLAYBOOK + "3. Open a PR.\n")
        out = self.compare("--json")
        self.assertEqual(out.returncode, 1)
        row = [r for r in json.loads(out.stdout)["entries"] if r["local"] == "methods/bug-fix.md"][0]
        self.assertEqual((row["status"], row["added"], row["removed"], row["against"]),
                         ("upstream changed", 1, 0, "recorded"))

    def test_without_history_an_edited_file_is_diffed_against_the_local_copy_and_says_so(self):
        self.put(self.pstack / "skills/poteto-mode/playbooks/bug-fix.md", PLAYBOOK + "3. Open a PR.\n")
        out = self.compare()
        self.assertEqual(out.returncode, 1)
        self.assertIn("upstream changed  methods/bug-fix.md", out.stdout)
        self.assertIn("(+2 -1 lines, against the local file)", out.stdout)

    def test_bad_usage_exits_2(self):
        cases = [
            ("--craft", str(self.craft)),
            ("--craft", str(self.craft), "--upstream", str(self.craft)),
            ("--craft", str(self.craft / "absent"), "--upstream", str(self.pstack)),
            ("--craft", str(self.craft), "--upstream", str(self.pstack), "--bogus"),
            ("verify", "--craft", str(self.craft), "--upstream", str(self.pstack)),
            ("--craft",),
        ]
        for args in cases:
            out = self.run_sync(*args)
            self.assertEqual(out.returncode, 2, f"{args}: {out.stdout}{out.stderr}")
            self.assertIn("Usage: craft_sync.py", out.stderr)
        (self.craft / "UPSTREAM.json").write_text("{not json")
        self.assertEqual(self.run_sync("verify", "--craft", str(self.craft)).returncode, 2)

    def test_help_prints_usage_and_succeeds(self):
        for args in (["--help"], ["-h"], ["verify", "--help"]):
            out = self.run_sync(*args)
            self.assertEqual(out.returncode, 0, args)
            self.assertIn("craft_sync.py verify", out.stdout)

    def test_the_shipped_craft_layer_matches_its_manifest(self):
        out = self.run_sync("verify")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        manifest = json.loads((ROOT / "skills/craft/UPSTREAM.json").read_text())
        self.assertEqual({e["commit"] for e in manifest["files"]}, {"99743e9"})
        principles = {e["local"] for e in manifest["files"] if e["local"].startswith("principles/")}
        self.assertEqual(len(principles), 24)


if __name__ == "__main__":
    unittest.main()
