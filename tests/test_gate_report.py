"""Tests for gate_report.py: the verdict is computed from evidence by fixed precedence."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GR = ROOT / "skills/_shared/scripts/gate_report.py"
CHECKERS = ("code-verifier", "loyal-evaluator", "loyal-evaluator-pass2", "code-verifier-demo", "gate-judge")
INTENT = """# Intent
## Goal
x
## Done examples
- I-D1 a. Example: b
## Mechanism cards
## Must not lose
- L-01 keep · check: probe
## Re-freeze log
"""
MS = """# Milestones
## M1 · One
Status: gate
Promise: p
Carries: I-D1
Readiness: built [x] · gate-passed [ ] · accepted [ ] · released [ ] · live-verified [ ]
"""
REVIEW_PASS = {"mode": "review", "verdict": "PASS", "done_examples": [{"id": "I-D1", "status": "HOLDS"}],
               "must_not_lose": [{"id": "L-01", "status": "HOLDS"}], "mechanisms": [],
               "wiring": [{"component": "add", "status": "proven"}], "findings": [], "not_run": []}
DEMO_PASS = {"mode": "demo", "steps": [{"milestone": "M1", "step": 1, "expected": "a", "observed": "a", "status": "HOLDS"}]}
CLEAN = {"verdict": "ACCEPT-READY",
         "intent_diff": [{"id": "I-D1", "status": "HOLDS", "evidence": "q"}, {"id": "L-01", "status": "HOLDS", "evidence": "q"}],
         "blocking": [], "logged": [], "not_run": [], "resolved": []}


class GateReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs/project").mkdir(parents=True)
        (self.root / "docs/project/intent.md").write_text(INTENT)
        (self.root / "docs/project/milestones.md").write_text(MS)

    def tearDown(self):
        self.tmp.cleanup()

    def evidence(self, rnd, judge, statuses=None, layer1="PASS", copies="PASS", switch=False, review=None, demo=None,
                 checks=None):
        ev = self.root / f".evidence/gate/M1/r{rnd}"
        ev.mkdir(parents=True, exist_ok=True)
        (ev / "layer1.json").write_text(json.dumps({"status": layer1, "checks": checks or [{"name": "gate.sh", "status": layer1}]}))
        for name, body in (("code-verifier", review or REVIEW_PASS), ("code-verifier-demo", demo or DEMO_PASS)):
            (ev / f"{name}.result.md").write_text("Result.\n```json\n" + json.dumps(body) + "\n```\n")
        (ev / "copies.json").write_text(json.dumps({"status": copies, "problems": {"x": [1]} if copies == "FAIL" else {}}))
        for c in CHECKERS:
            s = {"status": (statuses or {}).get(c, "OK"), "family": "claude", "session_id": f"sess-{c}"}
            if switch and c == "code-verifier":
                s["family_switch"] = {"from": "codex", "to": "claude", "reason": "usage limit"}
            (ev / f"{c}.summary.json").write_text(json.dumps(s))
        body = judge if isinstance(judge, str) else "Verdict below.\n```json\n" + json.dumps(judge) + "\n```\n"
        (ev / "gate-judge.result.md").write_text(body)
        return ev

    def report(self, rnd, ev):
        out = subprocess.run([sys.executable, str(GR), str(self.root), "--milestone", "M1", "--round", str(rnd),
                              "--evidence", str(ev), "--fingerprint", "product:abc"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_clean_round_is_accept_ready(self):
        r = self.report(1, self.evidence(1, CLEAN))
        self.assertEqual(r["verdict"], "ACCEPT-READY", r)
        self.assertIn("ACCEPT-READY=SHIP", r["evidence_line"])
        self.assertEqual(r["sessions"]["gate-judge"], "sess-gate-judge")
        self.assertIn("gate-passed [x] (product:abc)", (self.root / "docs/project/milestones.md").read_text())
        self.assertIn("## Round 1", (self.root / "docs/project/reviews/M1.md").read_text())

    def test_the_checkers_own_results_outrank_a_lenient_judge(self):
        review = {**REVIEW_PASS, "verdict": "FAIL", "findings": [
            {"id": "F01", "class": "quality-substitution", "severity": "high", "summary": "the total is a cached value, not computed"}]}
        demo = {"mode": "demo", "steps": [{"milestone": "M1", "step": 1, "expected": "12.50", "observed": "0.00", "status": "FAILS"}]}
        r = self.report(1, self.evidence(1, CLEAN, review=review, demo=demo,
                                         checks=[{"name": "gate.sh", "status": "PASS"}, {"name": "tests", "status": "SKIP", "detail": "no test command"}]))
        self.assertEqual(r["verdict"], "CHANGES", r)
        self.assertTrue(any("demo step M1-1 FAILS" in x for x in r["reasons"]), r["reasons"])
        self.assertTrue(any("F01" in x and "neither blocking nor logged" in x for x in r["reasons"]), r["reasons"])
        self.assertTrue(any("tests SKIP" in x for x in r["exceptions"]), r["exceptions"])
        self.assertNotIn("evidence_line", r)

    def test_an_untriaged_reviewer_failure_is_inconclusive(self):
        review = {**REVIEW_PASS, "verdict": "FAIL", "done_examples": [{"id": "I-D1", "status": "FAILS"}], "findings": [
            {"id": "F02", "class": "correctness", "severity": "medium", "summary": "an unreadable file is overwritten silently"}]}
        r = self.report(1, self.evidence(1, CLEAN, review=review))
        self.assertEqual(r["verdict"], "INCONCLUSIVE", r)
        self.assertTrue(any("I-D1 FAILS but the judge's row is HOLDS" in x for x in r["reasons"]), r["reasons"])

    def test_a_logged_reviewer_failure_shows_in_the_evidence_line(self):
        review = {**REVIEW_PASS, "verdict": "FAIL", "findings": [
            {"id": "F03", "class": "correctness", "severity": "medium", "summary": "a rounding corner case in the export"}]}
        judge = {**CLEAN, "logged": [{"id": "M1-F01", "summary": "F03 rounding corner case, cosmetic in this product",
                                      "evidence": "q"}]}
        r = self.report(1, self.evidence(1, judge, review=review))
        self.assertEqual(r["verdict"], "ACCEPT-READY", r)
        self.assertIn("code-verifier FAIL (overruled: M1-F01)", r["evidence_line"])

    def test_mechanism_and_milestone_rows_are_owed(self):
        (self.root / "docs/project/milestones.md").write_text(MS.replace("Carries: I-D1", "Carries: I-D1\nMechanisms: Sync") +
                                                              "\nDone examples:\n- M1.D1 When x, y. Example: z\n")
        r = self.report(1, self.evidence(1, CLEAN))
        self.assertEqual(r["verdict"], "INCONCLUSIVE", r)
        self.assertTrue(any("MECH-Sync" in x and "M1.D1" in x for x in r["reasons"]), r["reasons"])

    def test_purpose_drift_is_changes(self):
        judge = {**CLEAN, "purpose": {"goal": "g", "guess": "a different product", "same_product": False}}
        self.assertEqual(self.report(1, self.evidence(1, judge))["verdict"], "CHANGES")

    def test_missing_reviewer_or_demo_result_is_inconclusive(self):
        ev = self.evidence(1, CLEAN)
        (ev / "code-verifier.result.md").write_text("no json here")
        r = self.report(1, ev)
        self.assertEqual(r["verdict"], "INCONCLUSIVE", r)
        self.assertIn("no valid verdict JSON from the code-verifier", r["reasons"])

    def test_a_busy_machine_is_inconclusive_not_a_defect(self):
        ev = self.evidence(1, CLEAN, layer1="NOT_RUN", checks=[{"name": "gate.sh", "status": "NOT_RUN",
                                                                "reason": "the machine was busy"}])
        r = self.report(1, ev)
        self.assertEqual(r["verdict"], "INCONCLUSIVE", r)
        self.assertIn("machine was busy", r["reasons"][0])

    def test_the_gate_passed_tick_follows_the_latest_round(self):
        def run(rnd, fp, layer1="PASS"):
            ev = self.evidence(rnd, CLEAN, layer1=layer1)
            subprocess.run([sys.executable, str(GR), str(self.root), "--milestone", "M1", "--round", str(rnd), "--evidence",
                            str(ev), "--fingerprint", fp], capture_output=True, text=True, check=True)
            return (self.root / "docs/project/milestones.md").read_text()
        self.assertIn("gate-passed [x] (product:aaa)", run(1, "product:aaa"))
        text = run(2, "product:bbb", layer1="FAIL")
        self.assertIn("gate-passed [ ]", text)
        self.assertNotIn("product:aaa", text, "a failing round clears the old tick")
        self.assertIn("gate-passed [x] (product:ccc)", run(3, "product:ccc"))

    def test_deterministic_or_copy_fail_is_changes(self):
        self.assertEqual(self.report(1, self.evidence(1, CLEAN, layer1="FAIL"))["verdict"], "CHANGES")
        self.assertEqual(self.report(2, self.evidence(2, CLEAN, copies="FAIL"))["verdict"], "CHANGES")

    def test_leak_or_bad_judge_is_inconclusive(self):
        self.assertEqual(self.report(1, self.evidence(1, CLEAN, {"loyal-evaluator": "LEAK"}))["verdict"], "INCONCLUSIVE")
        self.assertEqual(self.report(2, self.evidence(2, "no json here"))["verdict"], "INCONCLUSIVE")

    def test_blocked_checker(self):
        self.assertEqual(self.report(1, self.evidence(1, CLEAN, {"code-verifier": "BLOCKED"}))["verdict"], "BLOCKED")

    def test_blocking_finding_then_same_finding_again(self):
        j = dict(CLEAN, verdict="CHANGES", blocking=[{"id": "M1-F01", "summary": "fallback", "evidence": "q",
                                                      "loop_back": "dev", "fixed_when": "error shown"}])
        r = self.report(1, self.evidence(1, j))
        self.assertEqual(r["verdict"], "CHANGES")
        self.assertIn("Status: changes", (self.root / "docs/project/milestones.md").read_text())
        ledger = json.loads((self.root / "docs/project/reviews/M1.findings.json").read_text())
        self.assertEqual(ledger["M1-F01"]["rounds_blocking"], [1])
        r2 = self.report(2, self.evidence(2, j))
        self.assertEqual(r2["verdict"], "BLOCKED", "a finding that survives a fix round goes to the owner")

    def test_resolved_marks_fixed(self):
        j = dict(CLEAN, verdict="CHANGES", blocking=[{"id": "M1-F01", "summary": "x", "evidence": "q"}])
        self.report(1, self.evidence(1, j))
        self.report(2, self.evidence(2, dict(CLEAN, resolved=["M1-F01"])))
        ledger = json.loads((self.root / "docs/project/reviews/M1.findings.json").read_text())
        self.assertEqual(ledger["M1-F01"]["status"], "fixed")

    def test_needs_owner_is_blocked(self):
        j = dict(CLEAN, verdict="BLOCKED", blocking=[{"id": "M1-F02", "summary": "which currency", "needs_owner": True}])
        self.assertEqual(self.report(1, self.evidence(1, j))["verdict"], "BLOCKED")

    def test_intent_defect_without_blocking_is_changes(self):
        j = dict(CLEAN, intent_diff=[{"id": "I-D1", "status": "INACCURATE"}, {"id": "L-01", "status": "HOLDS"}])
        r = self.report(1, self.evidence(1, j))
        self.assertEqual(r["verdict"], "CHANGES")
        self.assertTrue(any("judge said ACCEPT-READY" in e for e in r["exceptions"]))

    def test_uncovered_carried_item_is_inconclusive(self):
        j = dict(CLEAN, intent_diff=[{"id": "I-D1", "status": "HOLDS"}])
        r = self.report(1, self.evidence(1, j))
        self.assertEqual(r["verdict"], "INCONCLUSIVE")
        self.assertTrue(any("L-01" in x for x in r["reasons"]))

    def test_judge_stricter_than_its_findings(self):
        r = self.report(1, self.evidence(1, dict(CLEAN, verdict="CHANGES")))
        self.assertEqual(r["verdict"], "INCONCLUSIVE")

    def test_case_and_shape_do_not_let_a_failure_through(self):
        review = {**REVIEW_PASS, "verdict": "Fail", "findings": [
            {"id": "F04", "class": "Silent_Degradation", "severity": "High", "summary": "a failed save shows success"}]}
        r = self.report(1, self.evidence(1, CLEAN, review=review))
        self.assertEqual(r["verdict"], "INCONCLUSIVE", r)
        self.assertTrue(any("F04" in x for x in r["reasons"]), r["reasons"])
        bare = {**REVIEW_PASS, "verdict": "FAIL"}
        r = self.report(2, self.evidence(2, CLEAN, review=bare))
        self.assertEqual(r["verdict"], "INCONCLUSIVE", r)
        self.assertTrue(any("named no finding" in x for x in r["reasons"]), r["reasons"])
        other = {"mode": "demo", "steps": [{"milestone": "M0", "step": 1, "status": "HOLDS"}]}
        r = self.report(3, self.evidence(3, CLEAN, demo=other))
        self.assertTrue(any("no step for M1" in x for x in r["reasons"]), r["reasons"])
        lower = dict(CLEAN, verdict="accept-ready", intent_diff=[{"id": "I-D1", "status": "holds"},
                                                                 {"id": "L-01", "status": "Holds"}])
        self.assertEqual(self.report(4, self.evidence(4, lower))["verdict"], "ACCEPT-READY")
        noted = dict(CLEAN, intent_diff=CLEAN["intent_diff"] + [{"id": "EXTRA-1", "status": "EXTRA"},
                                                              {"id": "ORPHAN-1", "status": "orphan"}])
        self.assertEqual(self.report(6, self.evidence(6, noted))["verdict"], "ACCEPT-READY",
                         "EXTRA and ORPHAN rows are the judge's to block or log, not unknown statuses")
        odd = dict(CLEAN, intent_diff=[{"id": "I-D1", "status": "PARTIAL"}, {"id": "L-01", "status": "HOLDS"}])
        r = self.report(5, self.evidence(5, odd))
        self.assertEqual(r["verdict"], "INCONCLUSIVE", r)

    def test_malformed_or_missing_evidence_is_inconclusive_and_clears_the_tick(self):
        self.report(1, self.evidence(1, CLEAN))
        self.assertIn("gate-passed [x]", (self.root / "docs/project/milestones.md").read_text())
        r = self.report(2, self.evidence(2, dict(CLEAN, blocking="the export is broken")))
        self.assertEqual(r["verdict"], "INCONCLUSIVE", r)
        self.assertIn("wrong shape", r["reasons"][0])
        self.assertIn("gate-passed [ ]", (self.root / "docs/project/milestones.md").read_text())
        ev = self.evidence(3, CLEAN)
        (ev / "layer1.json").unlink()
        r = self.report(3, ev)
        self.assertEqual(r["verdict"], "INCONCLUSIVE", r)
        self.assertIn("layer1.json", r["reasons"][0])

    def test_family_switch_is_an_exception(self):
        r = self.report(1, self.evidence(1, CLEAN, switch=True))
        self.assertEqual(r["verdict"], "ACCEPT-READY")
        self.assertTrue(any("usage limit" in e for e in r["exceptions"]))


if __name__ == "__main__":
    unittest.main()
