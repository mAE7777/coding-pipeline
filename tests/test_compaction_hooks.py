"""Tests for the PreCompact snapshot and the post-compaction reload gate."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "hooks/snapshot-state.py"
GATE = ROOT / "hooks/reload-gate.py"
STATE = "# State\n## Milestone\nM2 · phase: building\n## Open\n- [ ] add export\n## Blockers\nnone\n## Next step\nadd export\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self.tmp.name) / "proj"
        self.docs = self.proj / "docs/project"
        self.docs.mkdir(parents=True)
        (self.proj / ".coding-pipeline.json").write_text('{"version":1,"managed":true}')
        self.env = {**os.environ, "RELOAD_STATE_DIR": str(Path(self.tmp.name) / "reload")}

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, script, mode=None, **payload):
        payload = {"cwd": str(self.proj), "session_id": "s1", **payload}
        args = [sys.executable, str(script)] + ([mode] if mode else [])
        return subprocess.run(args, input=json.dumps(payload), capture_output=True, text=True, env=self.env)

    def decision(self, out):
        if not out.stdout.strip():
            return "allow"
        return json.loads(out.stdout)["hookSpecificOutput"].get("permissionDecision", "allow")


class SnapshotTest(Base):
    def test_snapshot_written_with_state_excerpt(self):
        (self.docs / "state.md").write_text(STATE)
        out = self.call(SNAP, trigger="auto")
        self.assertEqual(out.returncode, 0, out.stderr)
        snaps = list((self.proj / ".evidence/compact").glob("*.md"))
        self.assertEqual(len(snaps), 1)
        body = snaps[0].read_text()
        for expected in ("M2 · phase: building", "- [ ] add export", "state.md sha256:"):
            self.assertIn(expected, body)

    def test_snapshot_from_a_subfolder(self):
        (self.docs / "state.md").write_text(STATE)
        (self.proj / "src/deep").mkdir(parents=True)
        out = self.call(SNAP, cwd=str(self.proj / "src/deep"), trigger="auto")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len(list((self.proj / ".evidence/compact").glob("*.md"))), 1, "a cd into a subfolder still snapshots")

    def test_snapshot_no_state_is_no_op(self):
        self.assertEqual(self.call(SNAP).returncode, 0)
        self.assertFalse((self.proj / ".evidence").exists())


class ReloadGateTest(Base):
    def setUp(self):
        super().setUp()
        for n in ("state.md", "intent.md", "milestones.md"):
            (self.docs / n).write_text(STATE)
        (self.proj / "app.py").write_text("x = 1\n")

    def test_arm_injects_directive(self):
        self.call(SNAP)
        out = self.call(GATE, "arm", source="compact")
        ctx = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("docs/project/state.md, then docs/project/intent.md", ctx)
        self.assertIn(".evidence/compact/", ctx)

    def test_writes_blocked_until_all_required_read(self):
        self.call(GATE, "arm")
        write = {"tool_input": {"file_path": str(self.proj / "app.py")}}
        self.assertEqual(self.decision(self.call(GATE, "guard", **write)), "deny")
        for n in ("state.md", "intent.md"):
            self.call(GATE, "track", tool_input={"file_path": str(self.docs / n)})
        self.assertEqual(self.decision(self.call(GATE, "guard", **write)), "deny", "milestones.md still unread")
        self.call(GATE, "track", tool_input={"file_path": str(self.docs / "milestones.md")})
        self.assertEqual(self.decision(self.call(GATE, "guard", **write)), "allow")

    def test_writes_outside_project_not_blocked(self):
        self.call(GATE, "arm")
        out = self.call(GATE, "guard", tool_input={"file_path": str(Path(self.tmp.name) / "elsewhere.txt")})
        self.assertEqual(self.decision(out), "allow")

    def test_other_session_not_blocked(self):
        self.call(GATE, "arm")
        out = self.call(GATE, "guard", session_id="s2", tool_input={"file_path": str(self.proj / "app.py")})
        self.assertEqual(self.decision(out), "allow")

    def test_not_armed_means_no_block(self):
        out = self.call(GATE, "guard", tool_input={"file_path": str(self.proj / "app.py")})
        self.assertEqual(self.decision(out), "allow")

    def test_shell_writes_blocked_and_shell_reads_allowed_while_armed(self):
        self.call(GATE, "arm")
        for cmd in ("echo x > app.py", "sed -i '' 's/1/2/' app.py", "python3 fix.py", "cat a | tee b",
                    "git checkout -- app.py", "rm app.py", "sort -o app.py app.py", "uniq notes.txt app.py",
                    "tree -o app.py"):
            self.assertEqual(self.decision(self.call(GATE, "guard", tool_name="Bash", tool_input={"command": cmd})),
                             "deny", cmd)
        for cmd in ("git status --short", "cat docs/project/state.md", "grep -n Open docs/project/state.md | head -3",
                    "sed -n 1,20p app.py", "ls -la"):
            self.assertEqual(self.decision(self.call(GATE, "guard", tool_name="Bash", tool_input={"command": cmd})),
                             "allow", cmd)

    def test_reads_that_look_compound_are_allowed_and_their_writing_twins_are_not(self):
        self.call(GATE, "arm")
        cont = ROOT / "skills/_shared/scripts/continuity.py"
        other = Path(self.tmp.name) / "continuity.py"
        other.write_text("print('not the pipeline')\n")
        (self.proj / "a").mkdir()
        (self.proj / "a/b").symlink_to(Path(self.tmp.name), target_is_directory=True)  # leads out of the project
        copy = Path(self.tmp.name) / "copy"
        copy.mkdir()
        (copy / "continuity.py").write_bytes(cont.read_bytes())  # identical, but its neighbours are not the pipeline's
        reads = ('grep -n "Open\\|Next step" docs/project/milestones.md',
                 'grep -n "^## \\|export" docs/project/state.md | head -80',
                 "git show HEAD@{1} --stat",
                 "git log @{u}..HEAD --oneline",
                 "grep -n 'a|b' docs/project/state.md",
                 f"git -C {self.proj} status --short",
                 f"git -C {self.proj} log --oneline -8",
                 "git --no-pager log -3",
                 f"python3 {cont} recover {self.proj}",
                 f"{sys.executable} {cont} recover .")
        for cmd in reads:
            self.assertEqual(self.decision(self.call(GATE, "guard", tool_name="Bash", tool_input={"command": cmd})),
                             "allow", cmd)
        writes = (f"git -C {self.proj} checkout -- app.py",
                  "git -c core.pager=touch log",
                  "git diff --output=app.py",
                  "git branch -D main",
                  'grep -n "a\\|b" app.py > out.txt',
                  'grep "$(rm app.py)" app.py',
                  "grep `rm app.py` app.py",
                  "cat <(rm app.py)",
                  f"python3 {cont} stop",
                  f"python3 {cont} recover {self.proj}; rm app.py",
                  f"python3 {cont} recover {self.proj}\nrm app.py",
                  f"python3 {other} recover {self.proj}",
                  "python3 ~no-such-user-here/continuity.py recover .",
                  # a backslash-newline joins lines in the shell, so an option on the next line is still that option
                  "find . \\\n-delete",
                  "find . \\\n-exec rm {} \\;",
                  "sort -\\\no out.txt app.py",
                  "sed \\\n-i '' -e 's/1/2/' app.py",
                  "git log \\\n--output=x",
                  # a bracket that starts with ^] or ] holds that ], and a class like [:alpha:] is not its end
                  "sed 's/[^]/x/g;s]/R/w out]x]' app.py",
                  "sed 's/[[:alpha:]]/x/w out' app.py",
                  # options that take a separate value do not hide the program after them
                  "awk -F , 'BEGIN{system(\"touch p\")}'",
                  "awk -v x=1 'BEGIN{system(\"touch p\")}'",
                  # attached and abbreviated forms of writing options
                  "git branch -uother",
                  "git branch --unset-up",
                  "git branch -vD main",
                  "sort -ro out.txt app.py",
                  "cat app.py >&2out",
                  "sed -I '' 's/1/2/' app.py",
                  "sed -ni 's/1/2/p' app.py",
                  # third review: an awk string holding ; { or } before a redirect; escapes; clusters; abbreviations
                  "awk '{print $1 \";\" NR > \"out.csv\"}' app.py",
                  "awk -F, '{printf \"{...}\\n\", $1 > \"out.json\"}' app.py",
                  "awk '{print \"}\" > \"out.txt\"}' app.py",
                  "echo \\>& rm app.py",
                  "cat `echo \\`rm app.py\\``",
                  "sed -ne 'w out.txt' -e p app.py",
                  "sed -nf p app.py",
                  "sort --out=out.txt app.py",
                  "rg --pr ./run.sh x",
                  # a byte-identical copy of the recovery script elsewhere imports whatever sits beside it
                  f"python3 {Path(self.tmp.name) / 'copy' / 'continuity.py'} recover .",
                  # gawk -o in a cluster writes the program to a file
                  "awk -bo out.awk '{print}' app.py",
                  # git reads a folder's own config, which can name a command to run (core.fsmonitor)
                  "git -C /tmp status --short",
                  f"git -C {Path(self.tmp.name)} status",
                  "git -C a -C b status",  # git applies the second -C inside the first: a/b, a link out
                  # sixth review: macOS sed -l takes no value; awk value options in long form and -W; zsh's $=X
                  "sed -n -l 'p;w out.txt' p app.py",
                  "awk --assign x=1 '{print > \"out\"}' app.py",
                  "awk --field-separator , '{print > \"out\"}' app.py",
                  "awk -W x '{print > \"out\"}' app.py",
                  "awk -W profile=prof.out '{print}' app.py",
                  "cat $=X",
                  "cat $~X",
                  # brace expansion turns one word into several
                  "sed -n s/a/b/ {-i,} app.py",
                  "find . {-delete,}",
                  # shell parsing a quote-aware splitter must not read differently from bash
                  "grep $'\\'' x; rm app.py #'",
                  'cat app.py # "\nrm app.py\n"',
                  # read-only programs that can still write or run something
                  "awk 'BEGIN { system(\"rm app.py\") }'",
                  "awk '{ \"date\" | getline d }' app.py",
                  "awk '{ print $1 > \"out.txt\" }' app.py",
                  "cat $(rm app.py)",
                  "diff <(cat app.py) >(rm app.py)",
                  "cat app.py <<EOF\nx\nEOF",
                  'grep "unclosed app.py',
                  # backquotes end at the next backquote whatever the quotes inside (bash and zsh)
                  "cat `echo '`; rm app.py; echo '`",
                  # zsh: a glob qualifier runs code, =(...) runs a command, ${(e)...} evaluates
                  "ls *(e:'rm app.py':)",
                  "cat =(rm app.py)",
                  'cat ${(e)x}',
                  "cat ${x:-$(rm app.py)}",
                  "awk '@load \"x\"; {print}' app.py",
                  "awk -l x '{print}' app.py",
                  "awk --source='BEGIN{system(\"rm app.py\")}' app.py",
                  "awk -i inc.awk '{print}' app.py",
                  "less -k keys app.py",
                  "less --lesskey-src=keys app.py",
                  "awk -o out.awk '{print}' app.py",
                  "awk --profile=prof '{print}' app.py",
                  "awk -d '{print}' app.py",
                  "tree -R -H . -L 1",
                  "bat cache --build",
                  "cat $[1]",
                  # a command word that hides the program it runs, or a variable the shell expands
                  "rm${IFS}x/cat",
                  "./cat app.py",
                  "cat $X",
                  'sed -n "$S" app.py',
                  # sed: only a small grammar of printing commands is a read
                  "sed -n '\\%x%w out' app.py",
                  "sed -n '1~2w out' app.py",
                  "sed 'a\\\nx' app.py",
                  "sed -n 'w copy.txt' app.py",
                  "sed 's/x/rm app.py/e' app.py",
                  "sed -n '1,5p;w copy.txt' app.py",
                  "rg --pre ./run.sh x",
                  "sort --compress-program=./run.sh app.py",
                  "less '+!rm app.py' app.py",
                  "less -o log.txt app.py",
                  "bat --pager='rm app.py' app.py",
                  "file -C -m magic")
        reads += ("sed -n '/^## Open/,/^## /p' docs/project/state.md",
                  "sed 's/\\x1b\\[[0-9;]*m//g' app.py | head",
                  "awk '{print $1}' app.py",
                  "cat app.py 2>/dev/null",
                  "sed -n '1,/```json/p' app.py",
                  "grep -n \"kind <> 'guest'\" app.py",
                  "diff <(cat app.py) <(sort app.py)",
                  "sed -n 1,30p $(ls app.py | head -1)",
                  "find . \\( -name a -o -name b \\)",
                  "/usr/bin/grep -n x app.py",
                  "sed -n '/^## Open/,/^## /{/x/p;}' app.py",
                  "sed -e 's|a|b|g' -e '3q' app.py")
        for cmd in reads[-12:]:
            self.assertEqual(self.decision(self.call(GATE, "guard", tool_name="Bash", tool_input={"command": cmd})),
                             "allow", cmd)
        for cmd in writes:
            self.assertEqual(self.decision(self.call(GATE, "guard", tool_name="Bash", tool_input={"command": cmd})),
                             "deny", cmd)

    def test_shell_reads_count_as_rereading(self):
        self.call(GATE, "arm")
        for n in ("state.md", "intent.md", "milestones.md"):
            self.call(GATE, "track", tool_name="Bash", tool_input={"command": f"cat docs/project/{n}"})
        write = {"tool_input": {"file_path": str(self.proj / "app.py")}}
        self.assertEqual(self.decision(self.call(GATE, "guard", **write)), "allow")

    def test_naming_a_file_without_printing_it_is_not_reading_it(self):
        self.call(GATE, "arm")
        for n in ("state.md", "intent.md", "milestones.md"):
            for cmd in (f"ls docs/project/{n}", f"wc -l docs/project/{n}", f"grep -c Open docs/project/{n}"):
                self.call(GATE, "track", tool_name="Bash", tool_input={"command": cmd})
        write = {"tool_input": {"file_path": str(self.proj / "app.py")}}
        self.assertEqual(self.decision(self.call(GATE, "guard", **write)), "deny")
        for n in ("state.md", "intent.md", "milestones.md"):
            self.call(GATE, "track", tool_name="Bash", tool_input={"command": f"ls docs/project && sed -n 1,400p docs/project/{n}"})
        self.assertEqual(self.decision(self.call(GATE, "guard", **write)), "allow")

    def test_printing_a_file_to_nowhere_or_only_counting_it_is_not_reading_it(self):
        self.call(GATE, "arm")
        files = " ".join(f"docs/project/{n}" for n in ("state.md", "intent.md", "milestones.md"))
        for cmd in (f"cat {files} >/dev/null", f"cat {files} 1>/dev/null 2>&1", f"cat {files} &>/dev/null",
                    f"cat {files}>/dev/null", f"cat {files}>>/dev/null", f"cat {files}&>/dev/null",
                    f"cat {files} >&-", f"cat {files} 1>&-", f"cat {files} | true",
                    f"cat {files} | wc -l", f"cat {files} | wc -c >/dev/null"):
            self.call(GATE, "track", tool_name="Bash", tool_input={"command": cmd})
            self.assertEqual(self.decision(self.call(GATE, "guard", tool_input={"file_path": str(self.proj / "app.py")})),
                             "deny", cmd)
        self.call(GATE, "track", tool_name="Bash", tool_input={"command": f"cat {files} 2>/dev/null | head -400"})
        self.assertEqual(self.decision(self.call(GATE, "guard", tool_input={"file_path": str(self.proj / "app.py")})),
                         "allow")

    def test_a_refusal_names_its_real_cause(self):
        self.call(GATE, "arm")
        out = self.call(GATE, "guard", tool_name="Bash", tool_input={"command": "ls $HOME"})
        reason = json.loads(out.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("cannot read for certain", reason)
        self.assertIn("variable", reason, "the agent is told why, not that its read changes files")
        out = self.call(GATE, "guard", tool_name="Bash", tool_input={"command": "rm app.py"})
        self.assertIn("change files", json.loads(out.stdout)["hookSpecificOutput"]["permissionDecisionReason"])
        # Both refusals start with the words the ledger knows this block by, so a recurrence is still recognized.
        for reason_text in (reason, json.loads(out.stdout)["hookSpecificOutput"]["permissionDecisionReason"]):
            self.assertTrue(reason_text.startswith("Blocked: shell commands that change files wait until the build "
                                                   "record is re-read after compaction"), reason_text)

    def test_a_pipe_named_like_the_recovery_script_does_not_hang_the_gate(self):
        self.call(GATE, "arm")
        fifo = Path(self.tmp.name) / "continuity.py"
        os.mkfifo(fifo)
        started = time.monotonic()
        out = self.call(GATE, "guard", tool_name="Bash", tool_input={"command": f"python3 {fifo} recover ."})
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(self.decision(out), "deny")

    def test_a_subfolder_cwd_does_not_disarm(self):
        self.call(GATE, "arm")
        sub = self.proj / "src"
        sub.mkdir()
        out = self.call(GATE, "guard", cwd=str(sub), tool_input={"file_path": str(self.proj / "app.py")})
        self.assertEqual(self.decision(out), "deny")

    def test_codex_apply_patch_is_guarded(self):
        self.call(GATE, "arm")
        patch = "*** Begin Patch\n*** Update File: app.py\n@@\n-x = 1\n+x = 2\n*** End Patch\n"
        self.assertEqual(self.decision(self.call(GATE, "guard", tool_name="apply_patch", tool_input={"patch": patch})), "deny")
        outside = "*** Begin Patch\n*** Add File: /tmp/elsewhere.txt\n+hi\n*** End Patch\n"
        self.assertEqual(self.decision(self.call(GATE, "guard", tool_name="apply_patch", tool_input={"patch": outside})), "allow")
        # Codex's real payload: the patch arrives in tool_input.command
        self.assertEqual(self.decision(self.call(GATE, "guard", tool_name="apply_patch", tool_input={"command": patch})), "deny")
        self.assertEqual(self.decision(self.call(GATE, "guard", tool_name="apply_patch", tool_input={"command": "garbled"})),
                         "deny", "a patch with no readable target fails closed while armed")

    def test_project_without_state_is_silent(self):
        (self.docs / "state.md").unlink()
        self.assertEqual(self.call(GATE, "arm").stdout.strip(), "")

    def test_bad_mode(self):
        self.assertEqual(subprocess.run([sys.executable, str(GATE), "nope"], input="{}", text=True,
                                        capture_output=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
