"""Tests for regate_scope.py: which re-gate rounds may be focused, and the snapshots the decision compares."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/_shared/scripts"
RS = SCRIPTS / "regate_scope.py"
sys.path.insert(0, str(SCRIPTS))
import regate_scope  # noqa: E402
from fingerprint import fingerprint  # noqa: E402

MS = """# Milestones

## M1 \u00b7 Add and show
Status: changes
Promise: A person adds an item and sees it.
Carries: I-D1
Mechanisms: none

Done examples:
- M1.D1 When milk is added, it prints. Example: add milk \u2192 "1. milk"

Readiness: built [x] \u00b7 gate-passed [ ] \u00b7 accepted [ ] \u00b7 released [ ] \u00b7 live-verified [ ]

## M2 \u00b7 Remove
Status: planned
Promise: A person removes an item.
Carries: none
Mechanisms: none

Done examples:
- M2.D1 When milk is removed, the list is empty. Example: remove milk \u2192 "(empty)"

Readiness: built [ ] \u00b7 gate-passed [ ] \u00b7 accepted [ ] \u00b7 released [ ] \u00b7 live-verified [ ]
"""
APP = "items = []\n\n\ndef add(x):\n    items.append(x)\n"


class RegateScopeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name) / "proj"
        docs = self.p / "docs/project"
        docs.mkdir(parents=True)
        (docs / "milestones.md").write_text(MS)
        (docs / "intent.md").write_text("# Intent\n## Goal\nKeep a list.\n")
        (self.p / "app.py").write_text(APP)
        (self.p / "lib.py").write_text("def helper():\n    return 1\n")
        (self.p / "tests").mkdir()
        (self.p / "tests/test_app.py").write_text("import app\n")
        self.base = self.p / ".evidence/gate/M1"

    def tearDown(self):
        self.tmp.cleanup()

    def full_round(self, rnd=1, verdict="CHANGES", blocking=(("M1-F01", ["app.py"]),), evaluator="OK"):
        """A finished full round: its listing, snapshot, evaluator results, verdict, and the judge's findings."""
        ev = self.base / f"r{rnd}"
        ev.mkdir(parents=True)
        fp, rows = fingerprint(self.p, "product")
        regate_scope.write_listing(ev / "candidate.txt", fp, rows)
        ok, line = regate_scope.keep_snapshot(self.p, "M1", "full", rnd, fp, rows)
        self.assertTrue(ok, line)
        for stem in ("loyal-evaluator", "loyal-evaluator-pass2"):
            (ev / f"{stem}.summary.json").write_text(json.dumps({"status": evaluator}))
            (ev / f"{stem}.result.md").write_text("I tried adding an item.\n")
        (ev / "verdict.json").write_text(json.dumps({"verdict": verdict, "fingerprint": fp}))
        self.block(rnd, blocking)
        return fp

    def focused_round(self, rnd, verdict="CHANGES", blocking=()):
        ev = self.base / f"r{rnd}"
        ev.mkdir(parents=True)
        fp, rows = fingerprint(self.p, "product")
        regate_scope.write_listing(ev / "candidate.txt", fp, rows)
        (ev / "verdict.json").write_text(json.dumps({"verdict": verdict, "fingerprint": fp}))
        self.block(rnd, blocking)

    def block(self, rnd, blocking, status="open"):
        path = self.p / "docs/project/reviews/M1.findings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        ledger = json.loads(path.read_text()) if path.exists() else {}
        for fid, files in blocking:
            row = ledger.setdefault(fid, {"summary": f"{fid} defect", "first_round": rnd, "rounds_blocking": [],
                                          "status": status})
            row["rounds_blocking"].append(rnd)
            row.update({"files": files, "fixed_when": "python3 app.py prints it", "class": "correctness",
                        "severity": "high", "where": (files or ["?"])[0] + ":1"})
        path.write_text(json.dumps(ledger))

    def decide(self, rnd=2, *flags):
        ev = self.base / f"r{rnd}"
        ev.mkdir(parents=True, exist_ok=True)
        out = subprocess.run([sys.executable, str(RS), "decide", str(self.p), "--milestone", "M1", "--round", str(rnd),
                              "--out", str(ev / "scope.json"), *flags], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        scope = json.loads((ev / "scope.json").read_text())
        self.assertTrue(out.stdout.startswith(scope["scope"] + ": "), out.stdout)
        return scope

    def assertFull(self, scope, *phrases):
        self.assertEqual(scope["scope"], "full", scope)
        for phrase in phrases:
            self.assertTrue(any(phrase in r for r in scope["reasons"]), (phrase, scope["reasons"]))

    # ---- focused ------------------------------------------------------------------------------------------------
    def test_a_fix_inside_the_findings_files_is_focused(self):
        fp = self.full_round()
        (self.p / "app.py").write_text(APP + "\n\ndef show():\n    return items\n")
        scope = self.decide()
        self.assertEqual((scope["scope"], scope["kind"]), ("focused", "changes"), scope["reasons"])
        self.assertEqual(scope["since"]["round"], 1)
        self.assertEqual(scope["since"]["fingerprint"], fp)
        self.assertEqual(scope["changed_files"], [{"path": "app.py", "status": "modified", "added": 4, "removed": 0}])
        self.assertEqual(scope["changed_lines"], 4)
        self.assertIn("+def show():", Path(scope["delta_patch"]).read_text())
        self.assertEqual(scope["findings"], [{"id": "M1-F01", "status": "open", "fixed_round": None,
                                              "summary": "M1-F01 defect", "class": "correctness",
                                              "severity": "high", "files": ["app.py"], "where": "app.py:1",
                                              "fixed_when": "python3 app.py prints it"}])
        self.assertEqual(scope["reverify"], {"since": scope["since"], "changed_files": scope["changed_files"],
                                             "changed_lines": 4, "delta_patch": scope["delta_patch"]},
                         "a changes round re-verifies the whole change since the last full round")
        self.assertEqual(sorted(scope["carried"]), ["loyal-evaluator", "loyal-evaluator-pass2"])
        carried = scope["carried"]["loyal-evaluator"]
        self.assertEqual((carried["round"], carried["fingerprint"]), (1, fp))
        self.assertTrue(Path(carried["summary"]).is_file() and Path(carried["result"]).is_file())

    def test_test_files_are_allowed_and_added_or_deleted_files_count(self):
        self.full_round()
        (self.p / "app.py").write_text(APP + "# fixed\n")
        (self.p / "tests/test_app.py").write_text("import app\nassert app.items == []\n")
        (self.p / "tests/test_more.py").write_text("import app\n")
        scope = self.decide()
        self.assertEqual(scope["scope"], "focused", scope["reasons"])
        self.assertEqual({c["path"]: c["status"] for c in scope["changed_files"]},
                         {"app.py": "modified", "tests/test_app.py": "modified", "tests/test_more.py": "added"})
        (self.p / "lib.py").unlink()
        self.assertFull(self.decide(), "lib.py")

    def test_the_change_is_cumulative_since_the_last_full_round(self):
        self.full_round(blocking=(("M1-F01", ["app.py"]),))
        (self.p / "app.py").write_text(APP + "".join(f"# fix line {i}\n" for i in range(100)))
        self.focused_round(2, blocking=(("M1-F02", ["lib.py"]),))
        (self.p / "lib.py").write_text("def helper():\n    return 2\n")
        scope = self.decide(3)
        self.assertEqual(scope["scope"], "focused", scope["reasons"])
        self.assertEqual(scope["since"]["round"], 1, "measured from the last full round, not the last round")
        self.assertEqual(sorted(c["path"] for c in scope["changed_files"]), ["app.py", "lib.py"])
        self.assertEqual([f["id"] for f in scope["findings"]], ["M1-F01", "M1-F02"])
        (self.p / "lib.py").write_text("def helper():\n    return 2\n" + "# more\n" * 50)
        self.assertFull(self.decide(3), "152 changed lines since r1")

    def test_a_hotfix_after_acceptance_is_focused_on_its_fix_log_entry(self):
        fp = self.full_round(verdict="ACCEPT-READY", blocking=())
        rows = fingerprint(self.p, "product")[1]
        ok, line = regate_scope.keep_snapshot(self.p, "M1", "accepted", 1, fp, rows,
                                              source=self.base / "full-candidate")
        self.assertTrue(ok, line)
        ms = self.p / "docs/project/milestones.md"
        ms.write_text(MS.replace("Status: changes", "Status: accepted", 1))
        (self.p / "docs/project/decisions.md").write_text(
            "# Decisions\n\n## D-002 \u00b7 2026-10-01 \u00b7 Accept M1\n"
            f"Decision: Accept M1 \u00b7 contract 0123456789abcdef \u00b7 fingerprint {fp} \u00b7 review reviews/M1.md\n"
            'Source: [owner 2026-10-01] "yes, accept it"\n')
        log = self.p / "docs/project/fix-log.md"
        log.write_text("# Fix log\n\n## F-001 \u00b7 2026-09-30 \u00b7 an older fix\nChange: lib.py\n\n"
                       "## F-002 \u00b7 2026-10-02 \u00b7 the list loses an item\nSymptom: add twice shows one\n"
                       "Reproduction: python3 -m pytest tests/test_app.py\n"
                       "Change: app.py: append before saving, the smallest change\n")
        (self.p / "app.py").write_text(APP.replace("items.append(x)", "items.append(x)  # saved"))
        scope = self.decide()
        self.assertEqual((scope["scope"], scope["kind"]), ("focused", "hotfix"), scope["reasons"])
        self.assertEqual([f["id"] for f in scope["fixes"]], ["F-002"], "only entries since the acceptance")
        self.assertEqual(scope["fixes"][0]["change"], "app.py: append before saving, the smallest change")
        self.assertEqual(scope["since"]["snapshot"], str(self.base / "full-candidate"),
                         "the rules measure from the round whose evaluator results are carried")
        self.assertEqual(scope["reverify"]["since"]["snapshot"], str(self.base / "accepted-candidate"))
        (self.p / "lib.py").write_text("def helper():\n    return 3\n")
        self.assertFull(self.decide(), "lib.py", "a fix-log Change line")
        log.write_text("# Fix log\n\n## F-001 \u00b7 2026-09-30 \u00b7 an older fix\nChange: app.py\n")
        self.assertFull(self.decide(), "the fix log has no entry since")

    def accept(self, rnd, date="2026-10-01", ms=MS):
        """The candidate now passed in round rnd (its accepted-candidate snapshot) and the owner accepted it."""
        fp, rows = fingerprint(self.p, "product")
        ok, line = regate_scope.keep_snapshot(self.p, "M1", "accepted", rnd, fp, rows)
        self.assertTrue(ok, line)
        (self.p / "docs/project/milestones.md").write_text(ms.replace("Status: changes", "Status: accepted", 1))
        (self.p / "docs/project/decisions.md").write_text(
            f"# Decisions\n\n## D-002 · {date} · Accept M1\n"
            f"Decision: Accept M1 · contract 0123456789abcdef · fingerprint {fp} · review reviews/M1.md\n"
            f'Source: [owner {date}] "yes, accept it"\n')
        return fp

    def fix_log(self, *entries):
        (self.p / "docs/project/fix-log.md").write_text("# Fix log\n\n" + "".join(
            f"## {fid} · {date} · a fix\nSymptom: s\nReproduction: r\nChange: {change}\n\n"
            for fid, date, change in entries))

    def test_a_finding_fixed_in_a_focused_round_is_re_verified_in_every_later_one(self):
        self.full_round(blocking=(("M1-F01", ["app.py"]),))
        (self.p / "app.py").write_text(APP + "# F01 fixed\n")
        self.focused_round(2, blocking=(("M1-F02", ["app.py"]),))
        path = self.p / "docs/project/reviews/M1.findings.json"
        ledger = json.loads(path.read_text())
        ledger["M1-F01"].update(status="fixed", fixed_round=2)
        path.write_text(json.dumps(ledger))
        (self.p / "app.py").write_text(APP)  # the fix for F02 undoes F01's fix: no change since r1 at all
        scope = self.decide(3)
        self.assertEqual(scope["scope"], "focused", scope["reasons"])
        self.assertEqual(scope["changed_files"], [])
        self.assertEqual([(f["id"], f["status"], f["fixed_round"]) for f in scope["findings"]],
                         [("M1-F01", "fixed", 2), ("M1-F02", "open", None)],
                         "every finding blocking since the carried round, fixed ones included")

    def test_hotfix_rules_measure_the_whole_change_since_the_last_full_round(self):
        self.full_round(blocking=(("M1-F01", ["app.py"]),))
        (self.p / "app.py").write_text(APP + "".join(f"# fix line {i}\n" for i in range(80)))
        self.focused_round(2, verdict="ACCEPT-READY")
        self.accept(2)
        self.fix_log(("F-001", "2026-10-02", "lib.py"))
        (self.p / "lib.py").write_text("def helper():\n    return 1\n" + "".join(f"# hotfix {i}\n" for i in range(60)))
        scope = self.decide(3)
        self.assertEqual((scope["scope"], scope["kind"]), ("focused", "hotfix"), scope["reasons"])
        self.assertEqual((scope["since"]["round"], scope["changed_lines"]), (1, 140))
        self.assertEqual(sorted(c["path"] for c in scope["changed_files"]), ["app.py", "lib.py"],
                         "app.py is named by F01, blocking since r1; lib.py by the fix-log entry")
        rv = scope["reverify"]
        self.assertEqual((rv["since"]["round"], rv["since"]["snapshot"]), (2, str(self.base / "accepted-candidate")))
        self.assertEqual([c["path"] for c in rv["changed_files"]], ["lib.py"], "the re-verify reviews the hotfix")
        self.assertIn("+# hotfix 0", Path(rv["delta_patch"]).read_text())
        self.assertNotIn("# fix line", Path(rv["delta_patch"]).read_text())
        self.assertEqual([f["id"] for f in scope["findings"]], ["M1-F01"])
        (self.p / "lib.py").write_text("def helper():\n    return 1\n" + "".join(f"# hotfix {i}\n" for i in range(70)))
        # Two contained steps (a focused fix, then a hotfix) never add up to an uncontained change.
        self.assertFull(self.decide(3), "150 changed lines since r1")
        import shutil
        shutil.rmtree(self.base / "full-candidate")
        self.assertFull(self.decide(3), "snapshot missing", "the last full round's candidate")

    def test_a_hotfix_on_the_final_milestone_may_be_focused(self):
        final = MS.replace("Status: planned", "Status: dropped")
        (self.p / "docs/project/milestones.md").write_text(final)
        self.full_round(verdict="ACCEPT-READY", blocking=())
        self.accept(1, ms=final)
        self.fix_log(("F-001", "2026-10-02", "app.py"))
        (self.p / "app.py").write_text(APP + "# hotfix\n")
        scope = self.decide(2)
        self.assertEqual((scope["scope"], scope["kind"]), ("focused", "hotfix"), scope["reasons"])
        self.fix_log()
        self.assertFull(self.decide(2), "M1 is the final milestone", "the fix log has no entry since")

    def test_a_fix_log_entry_written_before_the_acceptance_is_not_a_hotfix(self):
        self.full_round(blocking=(("M1-F01", ["app.py"]),))
        (self.p / "app.py").write_text(APP + "# fixed\n")
        self.fix_log(("F-001", "2026-10-01", "app.py"))  # the gate fix, logged the day it was accepted
        self.focused_round(2, verdict="ACCEPT-READY")
        self.accept(2, date="2026-10-01")
        self.assertEqual(json.loads((self.base / "accepted-candidate.json").read_text())["fix_log_ids"], ["F-001"])
        (self.p / "app.py").write_text(APP + "# fixed\n# changed again, unlogged\n")
        self.assertFull(self.decide(3), "the fix log has no entry since")
        self.fix_log(("F-001", "2026-10-01", "app.py"), ("F-002", "2026-10-01", "app.py"))
        scope = self.decide(3)
        self.assertEqual(([f["id"] for f in scope["fixes"]], scope["scope"]), (["F-002"], "focused"), scope["reasons"])
        rec = json.loads((self.base / "accepted-candidate.json").read_text())
        del rec["fix_log_ids"]
        (self.base / "accepted-candidate.json").write_text(json.dumps(rec))
        self.assertFull(self.decide(3), "the fix log has no entry since")  # no record: the acceptance day is unsure

    def test_a_file_whose_lines_cannot_be_counted_is_full(self):
        self.full_round(blocking=(("M1-F01", ["legacy.py", "logo.png"]),))
        (self.p / "legacy.py").write_bytes("# résumé\n".encode("latin-1"))
        scope = self.decide()
        self.assertFull(scope, "legacy.py changed since r1 and its lines cannot be counted (binary or not UTF-8")
        self.assertEqual(scope["changed_files"], [{"path": "legacy.py", "status": "added", "added": None,
                                                   "removed": None, "binary": True, "why": "binary or not UTF-8 text"}])
        self.assertIn("Binary files /dev/null and b/legacy.py differ", Path(scope["delta_patch"]).read_text())

    def test_the_delta_patch_marks_a_missing_final_newline(self):
        self.full_round(blocking=(("M1-F01", ["app.py", "lib.py"]),))
        (self.p / "app.py").write_text(APP.rstrip("\n"))
        (self.p / "lib.py").write_text("def helper():\n    return 2\n")
        scope = self.decide()
        text = Path(scope["delta_patch"]).read_text()
        self.assertIn("-    items.append(x)\n+    items.append(x)\n\\ No newline at end of file\n", text)
        import baseline
        self.assertEqual(sorted(baseline.split_patch(text)), ["app.py", "lib.py"], "each file keeps its own block")
        self.assertEqual([(c["path"], c["added"], c["removed"]) for c in scope["changed_files"]],
                         [("app.py", 1, 1), ("lib.py", 1, 1)])

    # ---- full, one reason at a time ---------------------------------------------------------------------------
    def test_round_one_is_always_full(self):
        self.assertEqual(self.decide(1)["reasons"], ["round 1 is always full"])

    def test_the_final_milestone_is_always_full(self):
        self.full_round()
        (self.p / "docs/project/milestones.md").write_text(MS.replace("Status: planned", "Status: dropped"))
        (self.p / "app.py").write_text(APP + "# fixed\n")
        self.assertFull(self.decide(), "M1 is the final milestone")

    def test_full_flag(self):
        self.full_round()
        (self.p / "app.py").write_text(APP + "# fixed\n")
        self.assertFull(self.decide(2, "--full"), "--full was given")

    def test_only_a_changes_verdict_allows_a_focused_round(self):
        self.full_round(verdict="INCONCLUSIVE")
        (self.p / "app.py").write_text(APP + "# fixed\n")
        self.assertFull(self.decide(), "ended INCONCLUSIVE, not CHANGES")

    def test_a_file_no_finding_names_is_full(self):
        self.full_round()
        (self.p / "lib.py").write_text("def helper():\n    return 2\n")
        self.assertFull(self.decide(), "neither a test file nor named in a finding blocking since r1: lib.py")

    def test_a_blocking_finding_without_files_is_full(self):
        self.full_round(blocking=(("M1-F01", ["app.py"]), ("M1-F02", None)))
        (self.p / "app.py").write_text(APP + "# fixed\n")
        self.assertFull(self.decide(), "without files, so the fix cannot be bounded: M1-F02")

    def test_logged_findings_never_count(self):
        self.full_round()
        path = self.p / "docs/project/reviews/M1.findings.json"
        ledger = json.loads(path.read_text())
        ledger["M1-F09"] = {"summary": "cosmetic", "first_round": 1, "rounds_blocking": [], "status": "logged",
                            "files": ["lib.py"]}
        path.write_text(json.dumps(ledger))
        (self.p / "lib.py").write_text("def helper():\n    return 2\n")
        scope = self.decide()
        self.assertFull(scope, "lib.py")
        self.assertNotIn("M1-F09", [f["id"] for f in scope["findings"]])

    def test_150_changed_lines_is_full_and_149_is_not(self):
        self.full_round()
        (self.p / "app.py").write_text(APP + "# x\n" * 149)
        self.assertEqual(self.decide()["scope"], "focused")
        (self.p / "app.py").write_text(APP + "# x\n" * 150)
        self.assertFull(self.decide(), "150 changed lines since r1")

    def test_intent_bearing_files_are_full(self):
        self.full_round(blocking=(("M1-F01", ["app.py", "spec/rules.py"]),))
        (self.p / "docs/project/gate.md").write_text("Intent-bearing paths: spec/\n")
        (self.p / "spec").mkdir()
        (self.p / "spec/rules.py").write_text("RULES = 1\n")
        self.assertFull(self.decide(), "spec/rules.py is intent-bearing")

    def test_an_intent_or_contract_change_is_full(self):
        self.full_round()
        (self.p / "app.py").write_text(APP + "# fixed\n")
        (self.p / "docs/project/intent.md").write_text("# Intent\n## Goal\nKeep two lists.\n")
        self.assertFull(self.decide(), "intent.md changed since r1")
        (self.p / "docs/project/intent.md").write_text("# Intent\n## Goal\nKeep a list.\n")
        (self.p / "docs/project/milestones.md").write_text(MS.replace('"1. milk"', '"1) milk"'))
        self.assertFull(self.decide(), "contract")

    def test_manifests_lockfiles_migrations_and_build_config_are_full(self):
        named = ["package.json", "yarn.lock", "db/migrations/001_add.sql", ".github/workflows/ci.yml", "Makefile",
                 "tsconfig.json"]
        self.full_round(blocking=(("M1-F01", ["app.py", *named]),))
        for rel in named:
            (self.p / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.p / rel).write_text("x\n")
        scope = self.decide()
        self.assertFull(scope, "package.json is a dependency manifest", "yarn.lock is a lockfile",
                        "db/migrations/001_add.sql is a migration", ".github/workflows/ci.yml is a build or CI",
                        "Makefile is a build or CI", "tsconfig.json is a build or CI")

    def test_unusable_carried_evidence_is_full(self):
        self.full_round(evaluator="LEAK")
        (self.p / "app.py").write_text(APP + "# fixed\n")
        self.assertFull(self.decide(), "carried evidence unusable: r1's loyal-evaluator ended LEAK")
        (self.base / "r1/loyal-evaluator-pass2.summary.json").unlink()
        (self.base / "r1/loyal-evaluator.result.md").unlink()
        self.assertFull(self.decide(), "r1 has no loyal-evaluator-pass2 summary", "r1 has no loyal-evaluator result")

    def test_a_missing_snapshot_is_full(self):
        self.full_round()
        (self.p / "app.py").write_text(APP + "# fixed\n")
        import shutil
        shutil.rmtree(self.base / "full-candidate")
        self.assertFull(self.decide(), "snapshot missing")
        self.full_round(rnd=3)
        (self.base / "r3/candidate.txt").unlink()
        self.assertFull(self.decide(4), "snapshot missing", "is not recorded")

    def test_a_snapshot_of_a_moving_tree_is_not_kept(self):
        fp, rows = fingerprint(self.p, "product")
        (self.p / "app.py").write_text("changed after the fingerprint\n")
        ok, line = regate_scope.keep_snapshot(self.p, "M1", "full", 1, fp, rows)
        self.assertFalse(ok)
        self.assertIn("the tree changed while copying", line)
        self.assertFalse((self.base / "full-candidate").exists())
        self.assertFalse((self.base / "full-candidate.json").exists())

    def test_usage(self):
        out = subprocess.run([sys.executable, str(RS), "decide", str(self.p), "--milestone", "M1"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)


if __name__ == "__main__":
    unittest.main()
