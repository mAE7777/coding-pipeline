"""Tests for reentry_digest.py: what a session needs after a compaction, printed from the record files alone."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIGEST = ROOT / "skills/_shared/scripts/reentry_digest.py"

INTENT = """# Intent

Locked by the owner 2026-09-28 · hash 0123456789abcdef · ruling D-001 · re-freezes 1

## Goal
A habit tracker that keeps working offline.

## Identity and promise
A pocket notebook for habits.

## Who
Persona (blind): adult, phone

## Load-bearing behavior
Nothing logged offline is lost.

## Done examples
- I-D1 When a habit is checked offline, it shows as done. Example: tick "walk" in airplane mode → "walk" done
- I-D2 If sync fails, the user sees "not synced yet". Example: server down → banner "not synced yet"
- I-D3 When two phones edit, both edits stay. Example: A ticks walk, B ticks read → both ticked

## Mechanism cards
<!-- one per load-bearing mechanism -->
### Offline queue
Purpose: edits survive no network
Observable guarantee: an edit made offline appears after reconnect
Rejected imitation: retrying only while the app is open
Discriminating probe: edit offline, kill the app, reconnect

### Merge
Purpose: two phones never overwrite each other
Observable guarantee: both edits visible
Rejected imitation: last write wins
Discriminating probe: edit the same day on two phones

## Must not lose
- L-01 Every offline edit reaches the server · check: kill-and-reconnect probe
- L-02 No account needed to start · not code-checkable (owner checks at acceptance)

## Re-freeze log
### RF-1 · 2026-10-02 · D-004
Supersedes I-D2 with I-D2a: If sync fails, the user sees "saved on this phone". Example: server down → "saved on this phone"
Drops L-02 (reason: accounts are now required)
"""

MILESTONES = """# Milestones

<!--
Format rules (checked automatically)
-->

## M1 · Track offline
Status: accepted
Promise: tick habits without a network
Carries: I-D1
Mechanisms: Offline queue

Readiness: built [x] · gate-passed [x] · accepted [x] · released [ ] · live-verified [ ]

## M2 · Sync
Status: building
Promise: what you ticked reaches your other phone
Carries: I-D2, I-D3
Mechanisms: Offline queue, Merge

Demo ending:
1. tick on phone A → it shows on phone B

Checkpoints:
- M2.C1 queue drains on reconnect · why here: everything depends on it · check: `npm test -- queue`

Readiness: built [ ] · gate-passed [ ] · accepted [ ] · released [ ] · live-verified [ ]

## Idea-anchor closure
| Item | What it is | Where it lives |
"""

STATE = """# State

<!-- The compaction and handoff anchor. -->

Updated: 2026-10-16T09:00:00Z

## Writer
claude session abc

## Milestone
M2 · phase: building

## Understanding
Sync must never lose an offline tick.

## Open
- [ ] drain the queue on reconnect
- [x] queue model

## In flight
none

## Failures
queue test flaky on reconnect

## Blockers
none

## Next step
write the reconnect drain

## Last step
dev M2 · 2026-10-16 09:00 UTC · claude session abc · started
"""


class DigestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "habits"
        self.docs = self.root / "docs/project"
        self.docs.mkdir(parents=True)
        (self.docs / "intent.md").write_text(INTENT)
        (self.docs / "milestones.md").write_text(MILESTONES)
        (self.docs / "state.md").write_text(STATE)
        (self.docs / "decisions.md").write_text("# Decisions\n\n<!--\n## D-000 · not an entry\n-->\n\n" + "".join(
            f"## D-{i:03d} · 2026-10-{i:02d} · decision number {i}\nDecision: x\nWhy: y\n\n" for i in range(1, 8)))

    def tearDown(self):
        self.tmp.cleanup()

    def digest(self, where=None):
        return subprocess.run([sys.executable, str(DIGEST), str(where or self.root)], capture_output=True, text=True)

    def part(self, text, heading):
        """The lines under a '## <heading>...' part, up to the next part."""
        start = text.index("\n## " + heading) + 1
        end = text.find("\n## ", start + 1)
        return text[start:end if end > 0 else len(text)]

    def test_state_sections_each_headed_by_file_and_section(self):
        out = self.digest()
        self.assertEqual(out.returncode, 0, out.stderr)
        text = out.stdout
        for name, expected in (("Milestone", "M2 · phase: building"), ("Understanding", "never lose an offline tick"),
                               ("Open", "- [ ] drain the queue on reconnect"), ("In flight", "none"),
                               ("Failures", "queue test flaky"), ("Blockers", "none"),
                               ("Next step", "write the reconnect drain"),
                               ("Eliminated approaches", "none recorded")):
            self.assertIn(expected, self.part(text, f"docs/project/state.md · {name}"), name)
        self.assertNotIn("Last step", text, "the digest carries what is needed, not the whole file")
        self.assertNotIn("compaction and handoff anchor", text, "template comments are left out")

    def test_eliminated_approaches_are_printed_when_recorded(self):
        (self.docs / "state.md").write_text(STATE + "\n## Eliminated approaches\n- polling every second: drains "
                                                    "the battery (tried 2026-10-15)\n")
        part = self.part(self.digest().stdout, "docs/project/state.md · Eliminated approaches")
        self.assertIn("polling every second", part)

    def test_the_current_milestone_section_whole(self):
        text = self.digest().stdout
        part = self.part(text, "docs/project/milestones.md · M2 · Sync")
        for expected in ("Status: building", "Carries: I-D2, I-D3", "1. tick on phone A", "M2.C1 queue drains",
                         "Readiness: built [ ]"):
            self.assertIn(expected, part)
        self.assertNotIn("Track offline", text, "only the current milestone")
        self.assertNotIn("Idea-anchor closure", part)

    def test_intent_with_refreezes_applied(self):
        text = self.digest().stdout
        self.assertIn("A habit tracker that keeps working offline.", self.part(text, "docs/project/intent.md · Goal"))
        keep = self.part(text, "docs/project/intent.md · Must not lose")
        self.assertIn("L-01 Every offline edit reaches the server", keep)
        self.assertNotIn("L-02", keep, "dropped by the re-freeze")
        done = self.part(text, "docs/project/intent.md · Done examples M2 carries")
        self.assertIn('I-D2a If sync fails, the user sees "saved on this phone"', done)
        self.assertIn("(supersedes I-D2)", done)
        self.assertNotIn('"not synced yet"', done)
        self.assertIn("I-D3 When two phones edit", done)
        self.assertNotIn("I-D1 ", done, "only what the milestone carries")
        cards = self.part(text, "docs/project/intent.md · Mechanism cards M2 names")
        self.assertIn("### Offline queue", cards)
        self.assertIn("Rejected imitation: last write wins", cards)

    def test_last_five_decision_headings_and_the_full_file_paths(self):
        text = self.digest().stdout
        heads = self.part(text, "docs/project/decisions.md · last 5")
        self.assertIn("\nD-003 · 2026-10-03 · decision number 3", heads)
        self.assertIn("\nD-007 · 2026-10-07 · decision number 7", heads)
        self.assertNotIn("D-002", heads)
        self.assertNotIn("D-000", heads, "a heading inside a template comment is not an entry")
        self.assertNotIn("Why: y", heads, "headings only")
        last = text.strip().splitlines()[-1]
        self.assertTrue(last.startswith("Full files: "), last)
        self.assertTrue(last.endswith(". Read any of them when a detail is not above."), last)
        for name in ("state.md", "milestones.md", "intent.md", "decisions.md"):
            self.assertIn(str(self.docs / name), last)

    def test_without_a_named_milestone_the_first_open_one_is_shown(self):
        (self.docs / "state.md").write_text(STATE.replace("M2 · phase: building", "none · phase: idle"))
        text = self.digest().stdout
        self.assertIn("## docs/project/milestones.md · M2 · Sync (state.md names no milestone", text)

    def test_a_status_written_with_capitals_is_still_done(self):
        (self.docs / "state.md").write_text(STATE.replace("M2 · phase: building", "none · phase: idle"))
        (self.docs / "milestones.md").write_text(MILESTONES.replace("Status: accepted", "Status: Accepted"))
        self.assertIn("Status: Accepted", (self.docs / "milestones.md").read_text())
        self.assertIn("## docs/project/milestones.md · M2 · Sync (state.md names no milestone", self.digest().stdout)

    def test_missing_files_are_named_and_a_folder_inside_the_project_works(self):
        (self.docs / "intent.md").unlink()
        (self.docs / "decisions.md").unlink()
        sub = self.root / "src"
        sub.mkdir()
        out = self.digest(sub)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("## docs/project/intent.md\nnot found", out.stdout)
        self.assertIn("## docs/project/decisions.md\nnot found", out.stdout)
        self.assertNotIn(str(self.docs / "intent.md"), out.stdout.strip().splitlines()[-1])

    def test_no_record_is_a_failed_check_and_no_argument_is_bad_usage(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        out = self.digest(empty)
        self.assertEqual(out.returncode, 1)
        self.assertIn("no docs/project/state.md", out.stdout)
        self.assertEqual(subprocess.run([sys.executable, str(DIGEST)], capture_output=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
