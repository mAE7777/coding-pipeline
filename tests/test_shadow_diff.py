"""Unit tests for shadow_diff.py: comparing a checker run with its shadow, and the promotion readiness summary."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/_shared/scripts/shadow_diff.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("shadow_diff", SCRIPT)
sd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sd)


def result(data, prose="Summary of what was checked."):
    return f"{prose}\n\n```json\n{json.dumps(data, indent=1)}\n```\n"


def keys(items):
    return sorted(i.get("key") or (i.get("primary") or i.get("shadow")).get("id") or i["class"] for i in items)


class CompareTest(unittest.TestCase):
    def test_the_judge(self):
        primary = {"verdict": "CHANGES", "purpose": {"same_product": True},
                   "intent_diff": [{"id": "I-D1", "status": "HOLDS"}, {"id": "I-D2", "status": "DRIFT"},
                                   {"id": "M1.D1", "status": "HOLDS"}, {"id": "L-01", "status": "MISSING"}],
                   "blocking": [{"id": "M1-F01", "summary": "the export drops rows"}],
                   "logged": [{"id": "M1-F02", "summary": "a label reads oddly"}]}
        shadow = {"verdict": "ACCEPT-READY", "purpose": {"same_product": True},
                  "intent_diff": [{"id": "I-D1", "status": "holds"}, {"id": "I-D2", "status": "HOLDS"},
                                  {"id": "M1.D1", "status": "DRIFT"}, {"id": "L-01", "status": "INACCURATE"}],
                  "blocking": [], "logged": [{"id": "M1-F01", "summary": "the export drops rows"},
                                            {"id": "M1-F02", "summary": "a label reads oddly"},
                                            {"id": "M1-F03", "summary": "slow start"}]}
        res = sd.compare(primary, shadow, "gate-judge")
        self.assertEqual(keys(res["shadow_missed"]), ["I-D2", "M1-F01"],
                         "a DRIFT the shadow calls HOLDS, and a block the shadow only logged")
        self.assertEqual(keys(res["shadow_extra"]), ["M1-F03", "M1.D1"])
        self.assertEqual(keys(res["differences"]), ["L-01"], "both report a defect, with another status")
        self.assertIn("I-D1", keys(res["agreements"]), "statuses compare without regard to case")
        self.assertIn("M1-F02", keys(res["agreements"]))
        verdict = {v["field"]: v for v in res["verdict"]}
        self.assertFalse(verdict["verdict"]["same"])
        self.assertTrue(verdict["purpose.same_product"]["same"])
        self.assertEqual(res["counts"], {"agreements": 2, "misses": 2, "extras": 2, "differences": 1,
                                         "verdict_differences": 1})

    def test_the_demo(self):
        primary = {"mode": "demo", "steps": [
            {"milestone": "M1", "step": 1, "status": "HOLDS"}, {"milestone": "M1", "step": 2, "status": "FAILS"},
            {"milestone": "M2", "step": 1, "status": "HOLDS"}, {"milestone": "M2", "step": 2, "status": "UNGROUNDED"}]}
        shadow = {"mode": "demo", "steps": [
            {"milestone": "M1", "step": 1, "status": "HOLDS"}, {"milestone": "M1", "step": 2, "status": "HOLDS"},
            {"milestone": "M2", "step": 1, "status": "FAILS"}, {"milestone": "M2", "step": 3, "status": "HOLDS"}]}
        res = sd.compare(primary, shadow, "code-verifier-demo")
        self.assertEqual(res["role"], "code-verifier")
        self.assertEqual(keys(res["shadow_missed"]), ["M1-2", "M2-2"],
                         "a FAILS the shadow calls HOLDS, and an UNGROUNDED step the shadow never ran")
        self.assertEqual(keys(res["shadow_extra"]), ["M2-1"])
        self.assertEqual(keys(res["differences"]), ["M2-3"], "a clean step only the shadow ran")
        self.assertEqual(keys(res["agreements"]), ["M1-1"])
        self.assertEqual(res["verdict"], [], "a demo run has no verdict field")

    def test_the_code_verifier(self):
        primary = {"verdict": "FAIL",
                   "done_examples": [{"id": "M1.D1", "status": "HOLDS"}, {"id": "M1.D2", "status": "FAILS"}],
                   "mechanisms": [{"name": "Retry Queue", "status": "HOLDS"}],
                   "must_not_lose": [{"id": "L-01", "status": "HOLDS"}],
                   "wiring": [{"component": "export", "status": "proven"}, {"component": "sync", "status": "UNWIRED"}],
                   "findings": [
                       {"id": "F01", "class": "correctness", "severity": "high", "where": "src/export.py:42",
                        "summary": "rows after 1000 are dropped"},
                       {"id": "F02", "class": "security", "severity": "medium", "where": "src/api.py:10",
                        "summary": "no auth on the delete route"},
                       {"id": "F03", "class": "clarity", "severity": "low", "where": "src/ui.py:5", "summary": "label"},
                       {"id": "F04", "class": "interface", "severity": "medium", "where": "src/cli.py:1",
                        "summary": "the flag is ignored"}]}
        shadow = {"verdict": "FAIL",
                  "done_examples": [{"id": "M1.D1", "status": "HOLDS"}, {"id": "M1.D2", "status": "FAILS"}],
                  "mechanisms": [{"name": "retry queue", "status": "FAILS"}],
                  "must_not_lose": [{"id": "L-01", "status": "HOLDS"}],
                  "wiring": [{"component": "export", "status": "PROVEN"}, {"component": "sync", "status": "proven"}],
                  "findings": [
                      {"id": "F01", "class": "security", "severity": "high", "where": "src/other.py:3",
                       "summary": "a sequential id that names another finding"},
                      {"id": "F02", "class": "correctness", "severity": "high", "where": "src/export.py:40",
                       "summary": "export truncates at 1000 rows"},
                      {"id": "F03", "class": "security", "severity": "low", "where": "src/api.py",
                       "summary": "delete route lacks auth"},
                      {"id": "F09", "class": "clarity", "severity": "medium", "where": "src/ui.py:7",
                       "summary": "label"}]}
        res = sd.compare(primary, shadow, "code-verifier")
        missed = res["shadow_missed"]
        self.assertIn("sync", keys(missed), "an UNWIRED component the shadow calls proven")
        self.assertIn("F04", keys(missed), "a finding the shadow never reported")
        downgraded = [m for m in missed if m["kind"] == "finding" and m.get("shadow")]
        self.assertEqual([(m["primary"]["id"], m["shadow"]["id"]) for m in downgraded], [("F02", "F03")],
                         "matched on class and file (ids are per run); a medium the shadow ranked low is missed")
        extra = res["shadow_extra"]
        self.assertIn("Retry Queue", keys(extra), "mechanism names compare without regard to case")
        self.assertTrue(any(e["kind"] == "finding" and e["shadow"]["id"] == "F01" and e["primary"] is None
                            for e in extra), "an id that names another class and file is not a match")
        self.assertTrue(any(e["kind"] == "finding" and e["primary"] and e["primary"]["id"] == "F03" for e in extra),
                        "a low the shadow ranked medium is extra")
        agreed = [a for a in res["agreements"] if a["kind"] == "finding"]
        self.assertEqual([(a["primary"]["id"], a["shadow"]["id"]) for a in agreed], [("F01", "F02")],
                         "the same defect at another line of the same file matches")
        self.assertIn("M1.D2", keys(res["agreements"]))
        self.assertTrue(res["verdict"][0]["same"])

    def test_other_roles(self):
        res = sd.compare({"claims": [{"id": "C1", "status": "REFUTED"}, {"id": "C2", "status": "CONFIRMED"}]},
                         {"claims": [{"id": "C1", "status": "CONFIRMED"}, {"id": "C2", "status": "CONFIRMED"}]},
                         "claim-verifier")
        self.assertEqual(keys(res["shadow_missed"]), ["C1"])
        res = sd.compare({"verdict": "AMBIGUOUS", "divergences": [{"quote": "the list syncs", "severity": "material"}],
                          "previous": [{"item": "term X", "settled": False}]},
                         {"verdict": "CLEAR", "divergences": [{"quote": "The list  syncs", "severity": "minor"}],
                          "previous": [{"item": "term X", "settled": True}]}, "cold-reader")
        self.assertEqual(len(res["shadow_missed"]), 2, "an open earlier item, and a material divergence called minor")
        self.assertEqual(res["counts"]["verdict_differences"], 1)

    def test_the_cli(self):
        with tempfile.TemporaryDirectory() as d:
            p, s, bad = Path(d) / "p.result.md", Path(d) / "s.result.md", Path(d) / "bad.result.md"
            p.write_text(result({"verdict": "CHANGES", "intent_diff": [{"id": "I-D1", "status": "DRIFT"}]}))
            s.write_text(result({"verdict": "ACCEPT-READY", "intent_diff": [{"id": "I-D1", "status": "HOLDS"}]}))
            bad.write_text("no json here\n```json\n{not json}\n```\n")
            run = lambda *a: subprocess.run([sys.executable, str(SCRIPT), *a], capture_output=True, text=True, timeout=60)
            out = run("compare", str(p), str(s), "--role", "gate-judge")
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("1 shadow missed", out.stdout)
            self.assertIn("intent_diff I-D1: primary DRIFT, shadow HOLDS", out.stdout)
            self.assertIn("verdict verdict: primary CHANGES, shadow ACCEPT-READY", out.stdout)
            out = run("compare", "--role", "gate-judge", str(p), str(s), "--json")
            self.assertEqual(json.loads(out.stdout)["counts"]["misses"], 1)
            out = run("compare", str(p), str(bad), "--role", "gate-judge")
            self.assertEqual(out.returncode, 1)
            self.assertIn("the shadow result", out.stderr)
            self.assertNotIn("the primary result", out.stderr)
            out = run("compare", str(Path(d) / "missing.md"), str(s), "--role", "gate-judge", "--json")
            self.assertEqual(out.returncode, 1)
            self.assertEqual(json.loads(out.stdout)["unparsed"], ["primary"])
            for args in ([], ["compare", str(p), str(s)], ["compare", str(p), "--role", "x"], ["frobnicate"],
                         ["summary", "--log"]):
                self.assertEqual(run(*args).returncode, 2, args)
            self.assertEqual(run("--help").returncode, 0)


def entry(route="gate-judge", evidence="/p/.evidence/gate/M1/r1", misses=0, extras=0, status="OK",
          model="claude-opus-5-5", effort="high"):
    return {"time": "2026-10-16T10:00:00Z", "project": "/p", "evidence": evidence, "route": route,
            "primary": {"model": "default", "effort": "xhigh", "served": "claude-opus-5-5"},
            "shadow": {"model": model, "effort": effort, "served": model, "status": status},
            "misses": misses, "extras": extras, "round": 1}


class SummaryTest(unittest.TestCase):
    def rows(self, entries):
        return {(r["route"], r["shadow"]["model"], r["shadow"]["effort"]): r for r in sd.summarize(entries)}

    def test_ready_only_with_three_distinct_rounds_and_no_miss(self):
        rounds = [f"/p/.evidence/gate/M1/r{n}" for n in (1, 2, 3)]
        r = self.rows([entry(evidence=e, extras=1) for e in rounds])[("gate-judge", "claude-opus-5-5", "high")]
        self.assertTrue(r["ready"], r)
        self.assertEqual((r["runs"], r["rounds"], r["misses"], r["extras"]), (3, 3, 0, 3), "extras do not block")
        r = self.rows([entry(evidence=rounds[0]), entry(evidence=rounds[0]), entry(evidence=rounds[1])])
        r = r[("gate-judge", "claude-opus-5-5", "high")]
        self.assertFalse(r["ready"])
        self.assertIn("2 of 3 distinct rounds", " ".join(r["why_not"]), "rounds are distinct evidence folders")
        r = self.rows([entry(evidence=e, misses=int(e.endswith("r2"))) for e in rounds])
        r = r[("gate-judge", "claude-opus-5-5", "high")]
        self.assertFalse(r["ready"])
        self.assertIn("1 miss(es)", r["why_not"][0])

    def test_a_failed_shadow_run_blocks_and_does_not_count_as_a_round(self):
        rounds = [f"/p/.evidence/gate/M1/r{n}" for n in (1, 2, 3)]
        entries = [entry(evidence=e) for e in rounds] + [entry(evidence="/p/.evidence/gate/M1/r4", status="ERROR",
                                                               misses=None, extras=None)]
        r = self.rows(entries)[("gate-judge", "claude-opus-5-5", "high")]
        self.assertEqual((r["runs"], r["rounds"], r["failed"]), (4, 3, 1))
        self.assertFalse(r["ready"])

    def test_each_route_and_setting_is_its_own_row(self):
        rows = self.rows([entry(), entry(effort="medium"), entry(route="code-verifier.demo",
                                                                 model="claude-sonnet-5-5")])
        self.assertEqual(len(rows), 3)

    def test_the_cli_reads_the_log(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "shadow.jsonl"
            lines = [json.dumps(entry(evidence=f"/p/.evidence/gate/M1/r{n}")) for n in (1, 2, 3)]
            log.write_text("\n".join(lines + ["{broken"]) + "\n")
            out = subprocess.run([sys.executable, str(SCRIPT), "summary", "--log", str(log)], capture_output=True,
                                 text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("ready to promote", out.stdout)
            self.assertIn("1 unreadable line(s) skipped", out.stdout)
            self.assertIn("Promotion stays manual", out.stdout)
            env = {**os.environ, "HOME": str(Path(d) / "home")}
            out = subprocess.run([sys.executable, str(SCRIPT), "summary", "--json"], capture_output=True, text=True,
                                 timeout=60, env=env)
            self.assertEqual(json.loads(out.stdout)["settings"], [], "no log: no runs")

    def test_record_and_round(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "a/shadow.jsonl"
            sd.record({"route": "gate-judge"}, log)
            sd.record({"route": "gate-judge"}, log)
            lines = [json.loads(x) for x in log.read_text().splitlines()]
            self.assertEqual(len(lines), 2)
            self.assertTrue(lines[0]["time"].endswith("Z"))
        self.assertEqual(sd.round_of("/p/.evidence/gate/M1/r3"), 3)
        self.assertEqual(sd.round_of("/p/.evidence/plan-r2"), 2)
        self.assertIsNone(sd.round_of("/tmp/tmpab3r9/ev"))
        self.assertIsNone(sd.round_of("/p/.evidence/capture/extract-1"))


if __name__ == "__main__":
    unittest.main()
