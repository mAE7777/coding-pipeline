"""Tests for install.py against a throwaway home folder."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.py"


# A stand-in for the Codex package that ~/.agents/skills links into: the same three scripts. Each logs its run in the
# home folder (outside the package, which an install may restore); the converter also bumps a generation marker, the
# stand-in for the copies Codex loads.
CONVERTER = """import hashlib, os, sys
from pathlib import Path
pkg = Path(__file__).resolve().parents[1]
source = Path(sys.argv[sys.argv.index("--source") + 1])
lines = [hashlib.sha256(f.read_bytes()).hexdigest() + "  " + str(f.relative_to(source))
         for f in sorted(source.rglob("*")) if f.is_file()]
(pkg / "source-manifest.sha256").write_text("\\n".join(lines) + "\\n")
for skill in (source / "skills").iterdir():
    if (skill / "SKILL.md").is_file():
        (pkg / ".agents/skills" / skill.name).mkdir(parents=True, exist_ok=True)
        (pkg / ".agents/skills" / skill.name / "SKILL.md").write_text((skill / "SKILL.md").read_text())
if (Path(os.environ["HOME"]) / "touch-live").exists():
    (pkg.parent / "codex-package" / "NOTES.md").write_text("written by someone else during the sync")
gen = pkg / "generation.txt"
gen.write_text(str(int(gen.read_text()) + 1 if gen.is_file() else 1))
with open(Path(os.environ["HOME"]) / "codex-log.txt", "a") as f:
    f.write("convert\\n")
"""
ACCEPTANCE = """import json, os, sys
from pathlib import Path
root = Path(sys.argv[sys.argv.index("--root") + 1])
gates = json.loads((root / "gates.json").read_text())
with open(Path(os.environ["HOME"]) / "codex-log.txt", "a") as f:
    f.write("acceptance\\n")
if gates.pop("crash", False):
    sys.exit(3)
lie = gates.pop("lie", False)
ok = all(v == "PASS" for v in gates.values())
Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps({"status": "PASS" if ok else "FAIL",
    "gates": [{"name": k, "status": v, "detail": ""} for k, v in gates.items()]}))
sys.exit(0 if ok or lie else 1)
"""
INSTALLER = """import os, sys
from pathlib import Path
pkg = Path(__file__).resolve().parents[1]
home = Path(sys.argv[sys.argv.index("--home") + 1])
fail_at = Path(os.environ["HOME"]) / "fail-install-at"
if fail_at.is_file() and (pkg / "generation.txt").read_text() == fail_at.read_text():
    sys.exit(5)
for skill in (pkg / ".agents/skills").iterdir():
    link = home / ".agents/skills" / skill.name
    if not link.exists():
        link.symlink_to(skill)
with open(Path(os.environ["HOME"]) / "codex-log.txt", "a") as f:
    f.write("install\\n")
"""


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        claude = self.home / ".claude"
        (claude / "skills/qa").mkdir(parents=True)
        (claude / "skills/qa/SKILL.md").write_text("old qa\n")
        (claude / "skills/plan/references").mkdir(parents=True)
        (claude / "skills/plan/references/interrogation.md").write_text("old reference\n")
        (claude / "skills/plan/brain.md").write_text("the owner's notes\n")
        (claude / "skills/plan/friction.log").write_text("log\n")
        (claude / "skills/_shared/scripts").mkdir(parents=True)
        (claude / "skills/_shared/scripts/someone_elses.py").write_text("keep me\n")
        (claude / "agents").mkdir(parents=True)
        (claude / "agents/task-implementer.md").write_text("old agent\n")
        hooks = {"hooks": {"PreToolUse": [{"hooks": [{"command": c}]} for c in (
            "python3 heavy-guard.py", "python3 reload-gate.py guard", "python3 continuity.py claim")],
            "PostToolUse": [{"hooks": [{"command": "python3 reload-gate.py track"}]}],
            "SessionStart": [{"hooks": [{"command": "python3 reload-gate.py arm"}, {"command": "python3 continuity.py session-start"}]}],
            "PreCompact": [{"hooks": [{"command": "python3 snapshot-state.py"}]}],
            "Stop": [{"hooks": [{"command": "python3 typecheck-once.py"}, {"command": "python3 continuity.py stop"},
                              {"command": "~/.claude/hooks/verify-pipeline-completion.sh"}]}]}}
        (claude / "settings.json").write_text(json.dumps(hooks))

    def tearDown(self):
        self.tmp.cleanup()

    def run_i(self, cmd):
        return subprocess.run([sys.executable, str(INSTALL), cmd, "--home", str(self.home)], capture_output=True, text=True)

    def codex_package(self, gates):
        pkg = self.home / "codex-package"
        for rel, text in (("scripts/convert_helm.py", CONVERTER), ("scripts/acceptance.py", ACCEPTANCE),
                          ("scripts/install_global.py", INSTALLER), ("gates.json", json.dumps(gates))):
            (pkg / rel).parent.mkdir(parents=True, exist_ok=True)
            (pkg / rel).write_text(text)
        (pkg / "validation").mkdir(exist_ok=True)
        (pkg / ".agents/skills/plan").mkdir(parents=True, exist_ok=True)
        (self.home / ".agents/skills").mkdir(parents=True, exist_ok=True)
        if not (self.home / ".agents/skills/plan").exists():
            (self.home / ".agents/skills/plan").symlink_to(pkg / ".agents/skills/plan")
        return pkg

    def log(self):
        return (self.home / "codex-log.txt").read_text().split()

    def stale(self, pkg):
        """Make Codex's copies look converted from older files, as after a pipeline change."""
        m = pkg / "source-manifest.sha256"
        m.write_text("".join("0" * 64 + line[64:] + "\n" for line in m.read_text().splitlines()))

    def test_apply_brings_codex_up_to_date_in_the_same_command(self):
        self.codex_package({"pipeline": "PASS"})
        out = self.run_i("apply")
        self.assertNotIn("Codex has no", out.stdout, out.stdout)
        self.assertNotIn("Codex's copies were converted from older versions", out.stdout)
        self.assertEqual(self.log(), ["convert", "acceptance", "install"])
        out = self.run_i("apply")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("Codex already current", out.stdout)
        self.assertEqual(self.log(), ["convert", "acceptance", "install"], "nothing runs twice for the same files")

    def test_any_failing_gate_fails_the_install_and_codex_keeps_its_last_accepted_copies(self):
        pkg = self.codex_package({"pipeline": "PASS", "discovery": "PASS"})
        out = self.run_i("apply")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertEqual((pkg / "generation.txt").read_text(), "1")
        self.stale(pkg)
        (pkg / "gates.json").write_text(json.dumps({"pipeline": "PASS", "discovery": "FAIL"}))
        for attempt in (1, 2):
            out = self.run_i("apply")
            self.assertEqual(out.returncode, 1, f"attempt {attempt}: a failing gate never passes by being seen before")
            self.assertIn("Codex acceptance: discovery fail", out.stdout)
            self.assertIn("the last accepted package is back (the rejected one is kept at", out.stdout)
            self.assertEqual((pkg / "generation.txt").read_text(), "1", "Codex keeps its last accepted copies")
            self.assertEqual(json.loads((pkg / "gates.json").read_text())["discovery"], "FAIL")
            self.assertFalse((self.home / ".codex-package.staging").exists())
            self.assertEqual((self.home / ".codex-package.rejected/generation.txt").read_text(), "2", "kept to look at")
        self.assertEqual(self.log()[-2:], ["convert", "acceptance"])
        kept = list((self.home / ".claude/_backups").glob("codex-acceptance-*.json"))
        self.assertTrue(kept, "the failed report is kept")
        self.assertIn('"discovery", "status": "FAIL"', kept[-1].read_text(), "the kept report is this run's")
        (pkg / "gates.json").write_text(json.dumps({"pipeline": "PASS", "discovery": "PASS"}))
        out = self.run_i("apply")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertEqual((pkg / "generation.txt").read_text(), "2")
        self.assertFalse((self.home / ".codex-package.previous").exists())
        out = subprocess.run([sys.executable, str(INSTALL), "apply", "--home", str(self.home), "--no-codex"],
                             capture_output=True, text=True)
        self.assertIn("Codex not synced (--no-codex)", out.stdout)

    def test_an_acceptance_that_crashes_contradicts_itself_or_runs_nothing_fails(self):
        pkg = self.codex_package({"pipeline": "PASS", "crash": True})
        out = self.run_i("apply")
        self.assertEqual(out.returncode, 1)
        self.assertIn("wrote no readable report (exit 3", out.stdout)
        self.assertFalse((pkg / "generation.txt").exists(), "the package was never converted in place")
        (pkg / "gates.json").write_text(json.dumps({"pipeline": "FAIL", "lie": True}))
        out = self.run_i("apply")
        self.assertIn("exited 0 while its report lists 1 failing gate(s)", out.stdout)
        (pkg / "gates.json").write_text(json.dumps({}))
        out = self.run_i("apply")
        self.assertEqual(out.returncode, 1)
        self.assertIn("reported no gates", out.stdout)

    def test_a_package_changed_during_the_sync_is_never_overwritten(self):
        pkg = self.codex_package({"pipeline": "PASS"})
        (self.home / "touch-live").write_text("")
        out = self.run_i("apply")
        self.assertEqual(out.returncode, 1)
        self.assertIn("the package changed while its new copies were being built", out.stdout)
        self.assertIn("NOTES.md", out.stdout)
        self.assertTrue((pkg / "NOTES.md").is_file(), "the other writer's file survives")
        self.assertFalse((pkg / "generation.txt").exists())

    def test_a_failed_installer_puts_the_last_accepted_package_back(self):
        pkg = self.codex_package({"pipeline": "PASS"})
        self.assertEqual(self.run_i("apply").returncode, 0)
        self.stale(pkg)
        (self.home / "fail-install-at").write_text("2")
        out = self.run_i("apply")
        self.assertEqual(out.returncode, 1)
        self.assertIn("Codex installer failed (exit 5)", out.stdout)
        self.assertIn("the last accepted package is back (the new one is kept at", out.stdout)
        self.assertIn("and its installer ran again", out.stdout)
        self.assertNotIn("failed too", out.stdout)
        self.assertEqual((pkg / "generation.txt").read_text(), "1")
        self.assertFalse((self.home / ".codex-package.previous").exists())

    def test_a_stopped_sync_is_finished_or_undone_at_the_next_apply(self):
        pkg = self.codex_package({"pipeline": "PASS"})
        self.assertEqual(self.run_i("apply").returncode, 0)
        previous, staging = self.home / ".codex-package.previous", self.home / ".codex-package.staging"
        # stopped between the two renames: no package, the last accepted one beside it
        os.rename(pkg, previous)
        out = self.run_i("check")
        self.assertIn("stopped halfway through replacing the package", out.stdout)
        out = self.run_i("apply")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("the last accepted package is back", out.stdout)
        self.assertEqual((pkg / "generation.txt").read_text(), "1")
        self.assertFalse(previous.exists())
        # stopped while a clone was being checked: the package was never touched
        shutil.copytree(pkg, staging, symlinks=True)
        (staging / "generation.txt").write_text("99")
        out = self.run_i("apply")
        self.assertIn("a Codex copy left by a stopped sync was removed", out.stdout)
        self.assertFalse(staging.exists())
        self.assertEqual((pkg / "generation.txt").read_text(), "1")
        # stopped while the new package was under acceptance in its place
        shutil.copytree(pkg, previous, symlinks=True)
        (pkg / "generation.txt").write_text("77")
        self.assertIn("unaccepted copies are live", self.run_i("check").stdout)
        out = self.run_i("apply")
        self.assertIn("stopped before its acceptance finished; the last accepted package is back", out.stdout)
        self.assertEqual((pkg / "generation.txt").read_text(), "1")
        self.assertEqual((self.home / ".codex-package.rejected/generation.txt").read_text(), "77")
        self.assertFalse(previous.exists())
        # stopped after the acceptance passed, before the installer finished
        superseded = self.home / ".codex-package.superseded"
        shutil.copytree(pkg, superseded, symlinks=True)
        self.assertIn("stopped before its installer finished", self.run_i("check").stdout)
        before = len(self.log())
        out = self.run_i("apply")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("a stopped sync's installer step was run again", out.stdout)
        self.assertEqual(self.log()[before:], ["install"])
        self.assertFalse(superseded.exists())

    def test_the_advice_fits_a_package_without_a_converter(self):
        pkg = self.home / "hand-built"
        (pkg / ".agents/skills/plan").mkdir(parents=True)
        (pkg / "source-manifest.sha256").write_text("0  skills/plan/SKILL.md\n")
        (self.home / ".agents/skills").mkdir(parents=True)
        (self.home / ".agents/skills/plan").symlink_to(pkg / ".agents/skills/plan")
        out = subprocess.run([sys.executable, str(INSTALL), "apply", "--home", str(self.home)], capture_output=True, text=True)
        self.assertIn("no scripts/convert_helm.py for install.py to run", out.stdout)

    def test_check_fails_before_install(self):
        out = self.run_i("check")
        self.assertEqual(out.returncode, 1)
        self.assertIn("retired skill still loads", out.stdout)
        self.assertIn("retired agent still loads", out.stdout)

    def test_apply_installs_archives_and_keeps_the_owners_files(self):
        out = self.run_i("apply")
        claude = self.home / ".claude"
        self.assertTrue((claude / "skills/gate/SKILL.md").exists())
        self.assertTrue((claude / "agents/gate-judge.md").exists())
        self.assertTrue((claude / "skills/_shared/scripts/run_isolated.py").exists())
        self.assertFalse((claude / "skills/qa").exists())
        self.assertTrue(any((claude / "_archived-skills").glob("qa-*")))
        self.assertFalse((claude / "agents/task-implementer.md").exists())
        self.assertFalse((claude / "skills/plan/references/interrogation.md").exists(), "a stale reference is removed")
        self.assertTrue((claude / "skills/plan/friction.log").exists(), "the owner's log is kept")
        self.assertTrue((claude / "skills/_shared/scripts/someone_elses.py").exists(), "other shared files untouched")
        self.assertTrue((claude / ".pipeline-install.json").exists())
        self.assertNotIn("FAIL   install     differs", out.stdout)
        self.assertNotIn("missing:", out.stdout)

    def test_check_catches_a_modified_install(self):
        self.run_i("apply")
        (self.home / ".claude/skills/gate/SKILL.md").write_text("edited by hand\n")
        out = self.run_i("check")
        self.assertIn("differs from the repository", out.stdout)

    def test_check_catches_shadows_and_codex_leftovers(self):
        self.run_i("apply")
        shadow = self.home / "Projects/lab/app/.claude/skills/dev"
        shadow.mkdir(parents=True)
        (self.home / ".agents/skills/qa").mkdir(parents=True)
        out = self.run_i("check")
        self.assertIn("project-level skill shadows ours", out.stdout)
        self.assertIn("Codex still offers a retired skill", out.stdout)

    def test_codex_conversion_must_match_the_installed_files(self):
        self.run_i("apply")
        package = self.home / "pkg/skills"
        for name in ("plan",):
            (package / name).mkdir(parents=True)
        (self.home / ".agents/skills").mkdir(parents=True)
        (self.home / ".agents/skills/plan").symlink_to(package / "plan")
        installed = self.home / ".claude/skills/plan/SKILL.md"
        import hashlib
        good = hashlib.sha256(installed.read_bytes()).hexdigest()
        (self.home / "pkg/source-manifest.sha256").write_text(f"{'0' * 64}  skills/plan/SKILL.md\n")
        out = self.run_i("check")
        self.assertIn("converted from older versions of 1 file(s) (skills/plan/SKILL.md)", out.stdout)
        self.assertIn("does not carry", out.stdout)
        self.assertIn("skills/", out.stdout.split("does not carry", 1)[1])
        self.assertNotIn("hooks/heavy-guard.py", out.stdout.split("does not carry", 1)[1], "hooks run from ~/.claude")
        (self.home / "pkg/source-manifest.sha256").write_text(f"{good}  skills/plan/SKILL.md\n")
        self.assertNotIn("converted from older versions", self.run_i("check").stdout)

    def test_a_live_edit_stops_apply_until_ported_or_overwritten(self):
        self.run_i("apply")
        gate = self.home / ".claude/skills/gate/SKILL.md"
        gate.write_text("an edit made under ~/.claude\n")
        # the repository has moved on too, so apply wants to update this file
        manifest = json.loads((self.home / ".claude/.pipeline-install.json").read_text())
        manifest["files"][str(gate)] = "0" * 64
        (self.home / ".claude/.pipeline-install.json").write_text(json.dumps(manifest))
        out = self.run_i("apply")
        self.assertEqual(out.returncode, 1)
        self.assertIn("changed or added under ~/.claude since the last install", out.stdout)
        self.assertEqual(gate.read_text(), "an edit made under ~/.claude\n", "nothing was overwritten")
        out = subprocess.run([sys.executable, str(INSTALL), "apply", "--home", str(self.home), "--overwrite-live-edits"],
                             capture_output=True, text=True)
        self.assertNotEqual(gate.read_text(), "an edit made under ~/.claude\n")
        backups = list((self.home / ".claude/_backups").glob("pipeline-install-*/skills/gate/SKILL.md"))
        self.assertTrue(backups and backups[-1].read_text() == "an edit made under ~/.claude\n", "the edit was backed up")

    def test_a_file_added_inside_an_installed_skill_stops_apply(self):
        self.run_i("apply")
        added = self.home / ".claude/skills/gate/references/my-notes.md"
        added.write_text("written by hand after the install\n")
        out = self.run_i("apply")
        self.assertEqual(out.returncode, 1)
        self.assertIn(f"since the last install: {added}", out.stdout)
        self.assertTrue(added.exists(), "nothing was removed")
        (self.home / ".claude/skills/gate/friction.log").write_text("a note the owner keeps\n")
        added.unlink()
        again = self.run_i("apply")
        self.assertEqual(again.returncode, 0, "brain.md, friction.log, and tests/ stay the owner's: " + again.stdout[-600:])

    def test_unapproved_codex_hooks_are_noted(self):
        (self.home / ".codex").mkdir()
        (self.home / ".codex/hooks.json").write_text('{"hooks": {"Stop": [{"hooks": [{"command": "python3 continuity.py stop --tool codex"}]}]}}')
        (self.home / ".codex/config.toml").write_text('model = "x"\n')
        out = self.run_i("check")
        self.assertIn("none are recorded in ~/.codex/config.toml yet", out.stdout)

    def test_unregistered_hook_is_named(self):
        (self.home / ".claude/settings.json").write_text(json.dumps({"hooks": {}}))
        out = self.run_i("check")
        self.assertIn("hook not registered in settings.json: heavy-guard.py", out.stdout)

    def test_missing_tools_are_named(self):
        bare = self.home / "bin"
        bare.mkdir()
        (bare / "claude").write_text("#!/bin/sh\necho '2.1.100 (Claude Code)'\n")
        (bare / "claude").chmod(0o755)
        out = subprocess.run([sys.executable, str(INSTALL), "check", "--home", str(self.home)], capture_output=True,
                             text=True, env={"PATH": str(bare), "HOME": str(self.home)})
        self.assertIn("required tool not installed: playwright-cli", out.stdout)
        self.assertIn("older than 2.1.283", out.stdout)
        self.assertIn("checkers' browser is not ready", out.stdout)
        self.assertIn("optional tool codex: not installed", out.stdout)


if __name__ == "__main__":
    unittest.main()
