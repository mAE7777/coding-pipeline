"""Tests for the Level-3 fixtures added for the model-routing comparisons (plan 7.2 and 7.3), with no model.

For each new expectation: a verdict that catches everything passes, a verdict that misses one planted item
reports that item alone, and the empty verdict reports every item (so pooled counts are items, not runs).
For each new fixture: its folder holds what its spec names, its pack renders the way agent_fixtures.py renders
it with nothing NOT PROVIDED and no canary in it, and its planted defect is really there (the products run).
The fast-reviewer fixtures (fast plan 4.6) are tested the same way on synthetic text answers, with their review
copy made a git repository and gate-fast's prompt filled from a fast repository made in a temporary folder (and
from the real one beside this repository, when it is there).
"""
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "skills/_shared/scripts"))
import agent_fixtures  # noqa: E402
import fixture_expectations as fx  # noqa: E402
import render_pack  # noqa: E402
from fixture_expectations import FIXTURES  # noqa: E402

FIX = ROOT / "tests/fixtures/agents"
RENDER = ROOT / "skills/_shared/scripts/render_pack.py"
NEW = ("code-verifier-demo-web-planted", "code-verifier-demo-web-clean", "code-verifier-demo-silent-step",
       "gate-judge-story-demo", "gate-judge-story-review",
       "cold-reader-understanding-shift-narrowed", "cold-reader-understanding-shift-mechanism",
       "cold-reader-understanding-shift-weakened", "cold-reader-understanding-shift-clean", "cold-reader-reread-partial", "cold-reader-reread-clean",
       "cold-reader-extract-clean", "claim-verifier-misquote", "claim-verifier-clean",
       "probe-explorer-recall", "probe-explain-grounding",
       "code-verifier-review-structure-planted", "code-verifier-review-structure-clean",
       "code-verifier-review-outside-excerpt", "code-verifier-reverify-refix-works",
       "code-verifier-reverify-refix-fails", "code-verifier-reverify-refix-breaks-other")
REFIX = ("code-verifier-reverify-refix-works", "code-verifier-reverify-refix-fails",
         "code-verifier-reverify-refix-breaks-other")
# The role prefix that `agent_fixtures.py --only <prefix>` (and repro:route:fixtures:<prefix>) selects each route by.
PREFIX = {"code-verifier.demo": "code-verifier-demo", "gate-judge": "gate-judge",
          "cold-reader.understanding": "cold-reader-understanding", "cold-reader.reread": "cold-reader-reread",
          "cold-reader.extract": "cold-reader-extract", "claim-verifier": "claim-verifier",
          "code-verifier.review": "code-verifier-review", "code-verifier.reverify": "code-verifier-reverify",
          "fast-reviewer": "fast-reviewer"}
FAST = sorted(n for n, s in FIXTURES.items() if s.get("fast_plan"))


def empty(name):
    return FIXTURES[name]["expect"]({}, {"summary": {}, "result": ""})


class RegistrationTest(unittest.TestCase):
    def test_every_fixture_names_its_kind_and_the_routes_it_serves(self):
        routes = json.loads((ROOT / "skills/_shared/models.json").read_text())["routes"]
        for name, spec in FIXTURES.items():
            with self.subTest(name):
                self.assertIn(spec["kind"], ("planted", "clean", "other"))
                self.assertTrue((FIX / spec["folder"]).is_dir())
                for route in spec["serves"].split(","):
                    if route.strip() not in fx.UNROUTED:
                        self.assertIn(route.strip(), routes)

    def test_each_routed_role_has_planted_and_clean_fixtures_under_its_prefix(self):
        """repro:route needs at least one planted and one clean fixture among those its prefix selects."""
        for route, prefix in PREFIX.items():
            with self.subTest(route):
                mine = [s for n, s in FIXTURES.items() if n.startswith(prefix)]
                self.assertTrue(all(s["serves"] == route for s in mine), prefix)
                self.assertEqual({s["kind"] for s in mine}, {"planted", "clean"})

    def test_the_spec_files_exist_and_probes_name_their_agent(self):
        for name in NEW:
            spec = FIXTURES[name]
            with self.subTest(name):
                for rel in spec.get("files", []):
                    self.assertTrue((FIX / spec["folder"] / rel.partition("=>")[0]).is_file(), rel)
                if spec.get("pack"):
                    self.assertTrue((FIX / spec["folder"] / spec["pack"]).is_file())
                if spec["role"] == "probe":
                    self.assertTrue((ROOT / spec["agent"]).is_file())
                if spec.get("base"):
                    self.assertTrue((FIX / spec["base"]).is_dir())
                if spec.get("scope"):
                    self.assertEqual(spec.get("mode"), "reverify")
                    self.assertTrue((FIX / spec["folder"] / spec["scope"]).is_file())

    def test_evolve_finds_the_probes_whose_text_changed(self):
        import evolve
        self.assertIn("probe-explorer-recall", evolve.probe_fixtures(ROOT, ["skills/craft/explore/explorer-prompt.md"]))
        found = evolve.probe_fixtures(ROOT, ["skills/explain/references/modes.md"])
        self.assertIn("probe-explain-grounding", found)
        self.assertNotIn("probe-explorer-recall", found)

    def test_every_planted_fixture_counts_each_item_in_an_empty_verdict(self):
        counts = {"code-verifier-demo-web-planted": 2, "code-verifier-demo-silent-step": 2,
                  "gate-judge-story-demo": 3, "gate-judge-story-review": 3,
                  "cold-reader-understanding-shift-narrowed": 2, "cold-reader-understanding-shift-mechanism": 2,
                  "cold-reader-understanding-shift-weakened": 2, "cold-reader-reread-partial": 5,
                  "claim-verifier-misquote": 5, "probe-explorer-recall": 8,
                  "probe-explain-grounding": 4, "code-verifier-review-structure-planted": 3,
                  "code-verifier-review-outside-excerpt": 1, "code-verifier-reverify-refix-fails": 3,
                  "code-verifier-reverify-refix-breaks-other": 4}
        for name, n in counts.items():
            with self.subTest(name):
                self.assertEqual(len(empty(name)), n, empty(name))
        for name in NEW:
            if FIXTURES[name]["kind"] == "clean":
                self.assertTrue(empty(name), f"{name}: an empty verdict must fail the clean control")

    def test_the_reverify_route_pools_at_least_six_planted_items_per_run(self):
        """Plan 7.3: at least 30 item-trials per side at --runs 5."""
        planted = [n for n, s in FIXTURES.items() if s["serves"] == "code-verifier.reverify" and s["kind"] == "planted"]
        self.assertGreaterEqual(sum(len(empty(n)) for n in planted) * 5, 30)


class DemoExpectationTest(unittest.TestCase):
    def steps(self, statuses, capture=".demo-captures/M1-{}.png"):
        return {"mode": "demo", "steps": [{"milestone": "M1", "step": n, "status": s, "capture": capture.format(n)}
                                          for n, s in enumerate(statuses, 1)]}

    def test_web_planted_needs_each_wrong_step_failed_with_its_capture(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".demo-captures").mkdir()
            for n in (3, 4):
                (Path(d) / f".demo-captures/M1-{n}.png").write_bytes(b"png")
            ctx = {"dir": d}
            self.assertEqual(fx.demo_web_planted(self.steps(["HOLDS", "HOLDS", "FAILS", "FAILS"]), ctx), [])
            missed = fx.demo_web_planted(self.steps(["HOLDS", "HOLDS", "HOLDS", "FAILS"]), ctx)
            self.assertEqual(len(missed), 1)
            self.assertIn("step 3", missed[0])
            (Path(d) / ".demo-captures/M1-4.png").unlink()
            uncaptured = fx.demo_web_planted(self.steps(["HOLDS", "HOLDS", "FAILS", "FAILS"]), ctx)
            self.assertEqual(len(uncaptured), 1)
            self.assertIn("step 4", uncaptured[0])
            self.assertIn("without a capture", uncaptured[0])
        unnamed = {"steps": [{"milestone": "M1", "step": "3", "status": "FAILS"}, {"milestone": "M1", "step": 4,
                                                                                    "status": "FAILS", "capture": "x"}]}
        self.assertEqual(len(fx.demo_web_planted(unnamed)), 1, "a FAILS step must name its capture")

    def test_web_clean_needs_all_four_steps_holding(self):
        self.assertEqual(fx.demo_web_clean(self.steps(["HOLDS"] * 4)), [])
        self.assertTrue(fx.demo_web_clean(self.steps(["HOLDS", "HOLDS", "FAILS", "HOLDS"])))
        self.assertTrue(fx.demo_web_clean(self.steps(["HOLDS"] * 3)), "a skipped step is not a pass")

    def test_a_silent_step_may_fail_or_be_ungrounded_but_never_hold(self):
        self.assertEqual(fx.demo_silent(self.steps(["HOLDS", "HOLDS", "UNGROUNDED", "FAILS", "HOLDS"])), [])
        missed = fx.demo_silent(self.steps(["HOLDS", "HOLDS", "HOLDS", "FAILS", "HOLDS"]))
        self.assertEqual(len(missed), 1)
        self.assertIn("export --out", missed[0])
        missed = fx.demo_silent(self.steps(["HOLDS", "HOLDS", "FAILS", "HOLDS", "HOLDS"]))
        self.assertEqual(len(missed), 1)
        self.assertIn("total --json", missed[0])


class JudgeExpectationTest(unittest.TestCase):
    def test_story_demo_counts_each_contradicted_capture(self):
        rows = [{"id": "M1.D1", "status": "DRIFT", "evidence": "capture M1-2 reads Total food: 52.50"},
                {"id": "L-01", "status": "MISSING", "evidence": "capture M1-4: the {broken file was overwritten"}]
        good = {"verdict": "CHANGES", "intent_diff": rows, "blocking": [{"summary": "the demo result is not what ran"}]}
        self.assertEqual(fx.judge_story_demo(good), [])
        self.assertIn("step 2", fx.judge_story_demo({**good, "intent_diff": rows[1:]})[0])
        self.assertIn("step 4", fx.judge_story_demo({**good, "intent_diff": rows[:1]})[0])
        held = [{**r, "status": "HOLDS"} for r in rows]
        self.assertEqual(len(fx.judge_story_demo({"verdict": "ACCEPT-READY", "intent_diff": held})), 3)

    def test_story_review_counts_each_contradicted_claim(self):
        good = {"verdict": "CHANGES", "intent_diff": [],
                "blocking": [{"summary": "M1.D2: the reviewer's probe_unreadable test FAILED", "evidence": "..."},
                             {"summary": "M1.D3: export printed a header and two lines for three expenses"}]}
        self.assertEqual(fx.judge_story_review(good), [])
        one = fx.judge_story_review({**good, "blocking": good["blocking"][:1]})
        self.assertEqual(len(one), 1)
        self.assertIn("export", one[0])
        other = fx.judge_story_review({**good, "blocking": good["blocking"][1:]})
        self.assertEqual(len(other), 1)
        self.assertIn("probe test", other[0])


class ColdReaderExpectationTest(unittest.TestCase):
    def test_each_subtle_shift_is_one_item_beside_the_verdict(self):
        narrowed = {"verdict": "AMBIGUOUS", "divergences": [{"quote": "import their bank's CSV export",
                                                             "reading_a": "CSV and OFX", "reading_b": "CSV only",
                                                             "severity": "material"}]}
        self.assertEqual(fx.understanding_narrowed(narrowed), [])
        self.assertEqual(len(fx.understanding_narrowed({**narrowed, "divergences": []})), 1)
        mechanism = {"verdict": "AMBIGUOUS", "missing": ["M1.D4: cached and written in the background, not saved first"]}
        self.assertEqual(fx.understanding_mechanism(mechanism), [])
        self.assertEqual(len(fx.understanding_mechanism({"verdict": "AMBIGUOUS", "missing": ["OFX"]})), 1)
        self.assertEqual(len(fx.understanding_mechanism({"verdict": "CLEAR"})), 2)
        weakened = {"verdict": "AMBIGUOUS", "divergences": [{"quote": "a file already imported is skipped (L-02)",
                                                             "reading_a": "each transaction once",
                                                             "reading_b": "each file once", "severity": "material"}]}
        self.assertEqual(fx.understanding_weakened(weakened), [])
        self.assertEqual(len(fx.understanding_weakened({"verdict": "AMBIGUOUS", "missing": ["OFX"]})), 1)

    def reread(self):
        return {"verdict": "AMBIGUOUS",
                "previous": [{"item": "I-D2 When a loan is overdue, the tool warns the user.", "settled": True,
                              "by": "past its due date (14 days after the loan ...) ... and reminds the borrower"},
                             {"item": "C-01 local file vs C-03 sync to the borrower's phone", "settled": True,
                              "by": "Named non-goals: Syncing loans to the borrower's phone"},
                             {"item": "I-D3 When a book comes back, it is marked returned", "settled": False,
                              "by": ""}],
                "divergences": [{"quote": "and reminds the borrower", "reading_a": "prints a reminder",
                                 "reading_b": "sends an email", "severity": "material"}]}

    def test_reread_partial_counts_the_open_the_new_and_each_fixed_finding(self):
        good = self.reread()
        self.assertEqual(fx.reread_partial(good), [])
        unfixed_closed = json.loads(json.dumps(good))
        unfixed_closed["previous"][2]["settled"] = True
        self.assertIn("unfixed", fx.reread_partial(unfixed_closed)[0])
        self.assertIn("new ambiguity", fx.reread_partial({**good, "divergences": []})[0])
        reopened = json.loads(json.dumps(good))
        reopened["previous"][0].update(settled=False, by="still no definition")
        self.assertEqual(fx.reread_partial(reopened), ["a fixed finding re-reported as open: what makes a loan overdue (I-D2)"])
        dropped = {**good, "previous": good["previous"][::2]}
        self.assertEqual(fx.reread_partial(dropped), ["a fixed finding not marked settled: the local file against the "
                                                      "phone sync (C-01, C-03)"])

    def test_reread_clean_fails_on_a_finding_left_open(self):
        good = {"verdict": "CLEAR", "previous": [{"item": i, "settled": True} for i in ("a", "b", "c")]}
        self.assertEqual(fx.reread_clean(good), [])
        self.assertTrue(fx.reread_clean({**good, "previous": [{"item": "a", "settled": False}]}))

    def faithful(self):
        rows = [("T001", "for our flat of three: Ana, Ben and me", "three people share the flat"),
                ("T001", "Every week it assigns the four chores, bins, kitchen, bathroom and hoovering",
                 "four chores assigned weekly"),
                ("T001", "nobody gets the same chore two weeks running", "no repeats in consecutive weeks"),
                ("T003", "A web page on our home server is enough.", "a web page on the home server"),
                ("T003", "No accounts: whoever opens the page sees the rota.", "no accounts"),
                ("T004", "When two of us swap chores, the swap stays until the end of that week, even if someone "
                         "reloads the page.", "an agreed swap is never lost"),
                ("T006", "Their chores go to the other two, split as evenly as possible.", "away: chores split evenly"),
                ("T007", "Weeks start on Monday.", "weeks start Monday"),
                ("T007", "And no email reminders, we decided against them", "no email reminders")]
        return {"mode": "extraction", "verdict": "CLEAR",
                "points": [{"refs": [f"SRC-1 {t}"], "quote": q, "point": p, "attribution": "owner",
                            "status": "rejected" if "email" in p else "current"} for t, q, p in rows]}

    def test_extract_clean_accepts_a_faithful_extraction_and_counts_each_lapse(self):
        good = self.faithful()
        self.assertEqual(fx.extract_clean(good), [])
        for label, words in fx.EXTRACT_CLEAN_POINTS.items():
            without = {**good, "points": [p for p in good["points"] if not fx.said(p, *words)]}
            self.assertEqual(fx.extract_clean(without), [f"load-bearing point missing: {label}"])
        tidied = json.loads(json.dumps(good))
        tidied["points"][3]["quote"] = "A web page on the home server is enough."
        self.assertEqual(len(fx.extract_clean(tidied)), 1)
        self.assertIn("verbatim", fx.extract_clean(tidied)[0])
        wanted = json.loads(json.dumps(good))
        wanted["points"][-1].update(point="email reminders each week", status="current")
        self.assertEqual(fx.extract_clean(wanted), ["the rejected email reminders appear as a current requirement"])
        invented = json.loads(json.dumps(good))
        invented["points"][0]["attribution"] = "assistant"
        self.assertEqual(len(fx.extract_clean(invented)), 1)
        self.assertEqual(len(fx.extract_clean({})), len(fx.EXTRACT_CLEAN_POINTS) + 1)

    def test_extract_planted_still_reads_its_transcript(self):
        quote = "The one thing that must never happen: an expense we entered disappears."
        point = {"refs": ["SRC-1 T001"], "quote": quote, "point": "an expense never disappears", "attribution": "owner",
                 "status": "current"}
        self.assertEqual(fx.quote_problems([point], fx.EXTRACT_SOURCE), [])
        self.assertNotIn("the must-not-lose point", " ".join(fx.extract_planted({"points": [point]})))


class ClaimExpectationTest(unittest.TestCase):
    def good(self):
        return {"claims": [{"id": "C1", "status": "CONFIRMED", "quote": "Standard | $0.021 per GB-month"},
                           {"id": "C2", "status": "CORRECTED", "quote": "The first 100 GB of egress each month is free."},
                           {"id": "C3", "status": "CORRECTED", "quote": "Published 14 May 2026."},
                           {"id": "C4", "status": "CORRECTED", "correction": "The host, Lee Park, said those words."},
                           {"id": "C5", "status": "CORRECTED", "quote": "$5.00 per million on Archive"}]}

    def test_each_misquote_is_one_item(self):
        self.assertEqual(fx.claims_misquote(self.good()), [])
        for i, cid in ((1, "C2"), (2, "C3"), (3, "C4"), (4, "C5")):
            confirmed = json.loads(json.dumps(self.good()))
            confirmed["claims"][i]["status"] = "CONFIRMED"
            problems = fx.claims_misquote(confirmed)
            self.assertEqual(len(problems), 1, problems)
            self.assertTrue(problems[0].startswith(cid))
        vague = json.loads(json.dumps(self.good()))
        vague["claims"][2]["quote"] = "a different date"
        self.assertIn("without the source's own words", fx.claims_misquote(vague)[0])

    def test_the_clean_twin_wants_every_claim_confirmed(self):
        self.assertEqual(fx.claims_clean({"claims": [{"id": f"C{i}", "status": "CONFIRMED"} for i in range(1, 6)]}), [])
        self.assertTrue(fx.claims_clean({"claims": [{"id": f"C{i}", "status": "CONFIRMED"} for i in range(1, 5)]}))

    def test_the_saved_sources_hold_the_truth_and_the_misquotes_do_not(self):
        sources = "\n".join(p.read_text() for p in sorted((FIX / "claims-misquote/sources").glob("*.md")))
        for truth in ("The first 100 GB of egress each month is free", "Published 14 May 2026",
                      "**Lee Park:**", "We have no plans to charge for reads this year"):
            self.assertIn(truth, sources)
        planted = (FIX / "claims-misquote/claims.md").read_text()
        for wrong in ("1,000 GB", "14 April 2026", "Dana Reyes, said: \"We will never charge for reads.\"",
                      "Archive tier, writes cost $0.40"):
            self.assertIn(wrong, planted)
        self.assertNotIn("http", planted + (FIX / "claims-clean/claims.md").read_text(), "no live website")


class ProbeExpectationTest(unittest.TestCase):
    def answers(self):
        out = []
        for q, (_, places) in fx.RECALL.items():
            rel, start, end = places[0]
            out.append({"q": q, "file": rel, "line": fx.recall_span(rel, start, end)[0]})
        return {"answers": out}

    def test_recall_counts_each_question(self):
        self.assertEqual(fx.explorer_recall(self.answers()), [])
        for i in range(len(fx.RECALL)):
            wrong = self.answers()
            wrong["answers"][i]["file"] = "shelf/__init__.py"
            problems = fx.explorer_recall(wrong)
            self.assertEqual(len(problems), 1)
            self.assertTrue(problems[0].startswith(f"question {i + 1} "))
        herring = self.answers()
        herring["answers"][3] = {"q": 4, "file": "shelf/overdue.py", "line": 5}  # the caller, not the comparison
        problems = fx.explorer_recall(herring)
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("question 4"))
        cli = (fx.RECALL_DIR / "shelf/cli.py").read_text().splitlines()
        help_line = next(i for i, line in enumerate(cli, 1) if "two weeks" in line)
        stale = self.answers()
        stale["answers"][0] = {"q": 1, "file": "./shelf/cli.py", "line": str(help_line)}
        self.assertTrue(fx.explorer_recall(stale)[0].startswith("question 1"))
        other = self.answers()
        other["answers"][5] = {"q": 6, "file": "/work/folder/shelf/cli.py", "lines": "64-67"}
        self.assertEqual(fx.explorer_recall(other), [], "the second place for question 6, given as a range")

    def test_recall_places_are_what_the_questions_ask(self):
        anchors = {1: "loan_days", 2: "def save", 3: "safe_cell", 4: "is_overdue", 5: "cmd_return", 6: "def load",
                   7: "normalize_isbn", 8: "reminder_text"}
        for q, (_, places) in fx.RECALL.items():
            rel, start, end = places[0]
            lo, hi = fx.recall_span(rel, start, end)
            lines = (fx.RECALL_DIR / rel).read_text().splitlines()
            self.assertIn(anchors[q], lines[lo - 1])
            self.assertLessEqual(lo, hi)
        lo, hi = fx.recall_span("shelf/store.py", "def save")
        body = "\n".join((fx.RECALL_DIR / "shelf/store.py").read_text().splitlines()[lo - 1:hi])
        self.assertIn("os.replace", body)

    def text(self, body):
        return {"summary": {}, "result": body + '\n\n```json\n{"register": "user"}\n```\n'}

    def test_explain_must_not_claim_what_no_evidence_proves(self):
        honest = ("You can now note what you spend and see what one category has cost you: add an expense, "
                  "then ask for its total.\n\nComing next, not checked yet:\n- Undo the last expense\n"
                  "- Bring in your bank's CSV file\n")
        v = {"register": "user", "capabilities_claimed": [{"capability": "record expenses and see a category total",
                                                            "rests_on": "docs/project/reviews/M1.md"}]}
        self.assertEqual(fx.explain_grounding(v, self.text(honest)), [])
        claims_undo = honest + "\nYou can also undo the last expense you added.\n"
        self.assertEqual(len(fx.explain_grounding(v, self.text(claims_undo))), 1)
        self.assertIn("undo", fx.explain_grounding(v, self.text(claims_undo))[0])
        listed = {**v, "capabilities_claimed": v["capabilities_claimed"] + [{"capability": "import a bank export"}]}
        self.assertEqual(len(fx.explain_grounding(listed, self.text(honest))), 1)
        self.assertNotIn("import", " ".join(fx.explain_grounding(
            v, self.text(honest + "\nIt is important that you add each expense.\n"))))
        jargon = honest + "\nThe schema keeps your data tidy.\n"
        self.assertIn("schema", fx.explain_grounding(v, self.text(jargon))[0])
        self.assertIn("what the gate proved", fx.explain_grounding(v, self.text("You can undo nothing yet."))[0])

    def test_the_explain_record_describes_undo_and_import_without_evidence(self):
        root = FIX / "explain-grounding"
        for rel in ("app.py", "README.md", "CHANGELOG.md"):
            text = (root / rel).read_text().lower()
            self.assertIn("undo", text, rel)
            self.assertIn("import", text, rel)
        evidence = (root / "tests/test_app.py").read_text() + (root / "docs/project/reviews/M1.md").read_text() + \
            "".join(p.read_text() for p in (root / ".evidence").rglob("*.txt"))
        prose = "\n".join(line for line in evidence.lower().splitlines() if not re.match(r"\s*(import|from) ", line))
        self.assertNotIn("undo", prose)
        self.assertNotIn("import", prose)


class ReviewLensExpectationTest(unittest.TestCase):
    """The structure lens twins and the defect outside the review pack's excerpt."""

    def planted(self):
        return {"mode": "review", "verdict": "FAIL",
                "done_examples": [{"id": d, "status": "HOLDS"} for d in fx.STRUCTURE_DONE],
                "findings": [{"id": "F01", "class": "structure", "severity": "medium", "where": "tally/report.py:7",
                              "summary": "_amount is a second implementation of money.format_amount"},
                             {"id": "F02", "class": "Structure", "severity": "medium", "where": "tally/cli.py:58",
                              "summary": "the report command reads the ledger's private _expenses list"},
                             {"id": "F03", "class": "structure", "severity": "medium", "where": "tally/dates.py:27",
                              "summary": "the comment says month_of raises BadDay; it only slices the string"}]}

    def test_structure_planted_counts_each_planted_item(self):
        good = self.planted()
        self.assertEqual(fx.structure_planted(good), [])
        for i, rel in enumerate(("report.py", "cli.py", "dates.py")):
            missed = json.loads(json.dumps(good))
            del missed["findings"][i]
            problems = fx.structure_planted(missed)
            self.assertEqual(len(problems), 1, problems)
            self.assertIn(rel, problems[0])
            other_class = json.loads(json.dumps(good))
            other_class["findings"][i]["class"] = "correctness"
            self.assertEqual(len(fx.structure_planted(other_class)), 1, "only a structure finding counts")
        wrong_file = json.loads(json.dumps(good))
        wrong_file["findings"][1]["where"] = "tally/ledger.py:8"
        self.assertEqual(len(fx.structure_planted(wrong_file)), 1, "the finding must name the file")
        invented = {**good, "done_examples": [{"id": "M2.D2", "status": "FAILS"}]}
        self.assertEqual(fx.structure_planted(invented), ["M2.D2 FAILS, but its behavior holds (an invented "
                                                          "correctness claim)"])
        self.assertEqual(len(fx.structure_planted({})), 3)

    def test_structure_clean_allows_logged_nits_only(self):
        good = {"verdict": "PASS", "done_examples": [{"id": d, "status": "HOLDS"} for d in fx.STRUCTURE_DONE],
                "findings": [{"class": "structure", "severity": "low", "summary": "the docstring narrates"}]}
        self.assertEqual(fx.structure_clean(good), [])
        loud = json.loads(json.dumps(good))
        loud["findings"][0]["severity"] = "medium"
        self.assertEqual(len(fx.structure_clean(loud)), 1)
        marked = json.loads(json.dumps(good))
        marked["findings"][0]["presumptive_blocker"] = True
        self.assertEqual(len(fx.structure_clean(marked)), 1)
        failed = json.loads(json.dumps(good))
        failed["done_examples"][0]["status"] = "FAILS"
        self.assertEqual(len(fx.structure_clean(failed)), 1, "a FAILS row is one problem, not two")
        skipped = {**good, "done_examples": good["done_examples"][1:] + [{"id": "M2-D3", "status": "UNGROUNDED"}]}
        self.assertEqual(len(fx.structure_clean(skipped)), 2)
        self.assertEqual(len(fx.structure_clean({})), 3)

    def test_outside_excerpt_is_caught_by_the_file_or_the_dropped_line(self):
        by_file = {"findings": [{"class": "correctness", "severity": "high", "where": "tally/dedupe.py:31",
                                 "summary": "split adds each key to seen, so a repeated line is never new"}]}
        self.assertEqual(fx.outside_excerpt(by_file), [])
        by_run = {"must_not_lose": [{"id": "L-03", "status": "FAILS",
                                     "evidence": "two identical coffees on 02/09 -> 1 imported, 1 already recorded"}]}
        self.assertEqual(fx.outside_excerpt(by_run), [])
        held = {"must_not_lose": [{"id": "L-03", "status": "HOLDS", "evidence": "two identical lines, both imported"}]}
        self.assertEqual(len(fx.outside_excerpt(held)), 1, "a holding row is no catch")
        other = {"findings": [{"class": "correctness", "summary": "a date of 31/09 is refused"}]}
        self.assertEqual(len(fx.outside_excerpt(other)), 1)
        self.assertEqual(len(fx.outside_excerpt({})), 1)


class ReverifyExpectationTest(unittest.TestCase):
    """The three re-verify fixtures: a FIXED or NOT_FIXED row per scope finding, and the broken caller."""

    def rows(self, f01, f02, f03, findings=()):
        return {"mode": "reverify", "verdict": "FAIL",
                "reverify": [{"id": fid, "status": s, "evidence": "..."} for fid, s in
                             (("M1-F01", f01), ("M1-F02", f02), ("M1-F03", f03))],
                "findings": list(findings)}

    def test_refix_works_wants_every_finding_fixed_and_nothing_new_that_blocks(self):
        self.assertEqual(fx.refix_works(self.rows("FIXED", "FIXED", "FIXED")), [])
        self.assertEqual(fx.refix_works(self.rows("fixed", "Fixed", "FIXED")), [], "statuses compared without case")
        for i in range(3):
            statuses = ["FIXED"] * 3
            statuses[i] = "NOT_FIXED"
            problems = fx.refix_works(self.rows(*statuses))
            self.assertEqual(len(problems), 1)
            self.assertTrue(problems[0].startswith(f"M1-F0{i + 1}: NOT_FIXED"))
        nit = {"class": "structure", "severity": "low", "summary": "csv_line could be inlined"}
        self.assertEqual(fx.refix_works(self.rows("FIXED", "FIXED", "FIXED", [nit])), [])
        new = {"class": "correctness", "severity": "high", "summary": "export drops the last line"}
        self.assertEqual(len(fx.refix_works(self.rows("FIXED", "FIXED", "FIXED", [new]))), 1)
        renamed = self.rows("FIXED", "FIXED", "FIXED")
        renamed["reverify"][0]["id"] = "F01"
        self.assertEqual(len(fx.refix_works(renamed)), 1, "a row must carry the scope's id, as gate_report.py reads it")
        self.assertEqual(len(fx.refix_works({})), 3)

    def test_refix_fails_counts_each_finding(self):
        self.assertEqual(fx.refix_fails(self.rows("NOT_FIXED", "FIXED", "NOT_FIXED")), [])
        for statuses, fid in ((("FIXED", "FIXED", "NOT_FIXED"), "M1-F01"), (("NOT_FIXED", "NOT_FIXED", "NOT_FIXED"),
                                                                             "M1-F02"),
                              (("NOT_FIXED", "FIXED", "FIXED"), "M1-F03")):
            problems = fx.refix_fails(self.rows(*statuses))
            self.assertEqual(len(problems), 1, problems)
            self.assertTrue(problems[0].startswith(fid))
        self.assertIn("a different path", fx.refix_fails(self.rows("NOT_FIXED", "FIXED", "FIXED"))[0])
        self.assertEqual(len(fx.refix_fails(self.rows("NOT FIXED", "FIXED", "NOT_FIXED"))), 1,
                         "NOT FIXED is not a status gate_report.py reads")
        self.assertEqual(len(fx.refix_fails({})), 3)

    def test_refix_breaks_other_wants_the_fixes_and_the_broken_caller(self):
        caller = {"id": "F01", "class": "correctness", "severity": "high", "where": "tally/archive.py:14",
                  "summary": "archive now writes the header twice: csv_lines starts with it"}
        self.assertEqual(fx.refix_breaks_other(self.rows("FIXED", "FIXED", "FIXED", [caller])), [])
        by_row = {**self.rows("FIXED", "FIXED", "FIXED"), "done_examples": [{"id": "M1.D3", "status": "FAILS"}]}
        self.assertEqual(fx.refix_breaks_other(by_row), [])
        missed = fx.refix_breaks_other(self.rows("FIXED", "FIXED", "FIXED"))
        self.assertEqual(len(missed), 1)
        self.assertIn("archive", missed[0])
        logged = {**caller, "severity": "low"}
        self.assertEqual(len(fx.refix_breaks_other(self.rows("FIXED", "FIXED", "FIXED", [logged]))), 1)
        blamed = fx.refix_breaks_other(self.rows("NOT_FIXED", "FIXED", "FIXED", [caller]))
        self.assertEqual(len(blamed), 1, "the export's own finding is fixed; the archive is a new one")
        self.assertTrue(blamed[0].startswith("M1-F01"))
        self.assertEqual(len(fx.refix_breaks_other({})), 4)


class PackTest(unittest.TestCase):
    """Each new fixture's pack, built the way agent_fixtures.py builds it, with no model."""

    def built(self, name, inspect):
        """inspect(pack text, {project, workdir, patch}) on the fixture's pack, rendered as agent_fixtures.py renders
        it (the project made by make_project, the checker's folder by prepare), before the work folder goes."""
        spec = FIXTURES[name]
        with tempfile.TemporaryDirectory() as d:
            work = Path(d)
            project = agent_fixtures.make_project(spec, work)
            workdir, _ = agent_fixtures.prepare(spec, project, work)
            ctx = {"project": project, "workdir": workdir, "patch": work / "ev/code-verifier.change.patch"}
            if spec.get("pack"):
                return inspect(agent_fixtures.embedded_pack(spec, project), ctx)
            out = work / "ev/code-verifier.pack.md"
            r = subprocess.run([sys.executable, str(RENDER), spec["role"], "--out", str(out),
                                *agent_fixtures.render_args(spec, project, workdir)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return inspect(out.read_text(), ctx)

    def pack(self, name):
        spec = FIXTURES[name]
        return self.built(name, lambda text, ctx: (text, ctx["workdir"].name,
                                                   agent_fixtures.judge_captures(spec, ctx["workdir"])))

    def test_every_new_pack_renders_complete_and_without_canaries(self):
        for name in NEW:
            with self.subTest(name):
                text, _, _ = self.pack(name)
                self.assertNotIn("NOT PROVIDED", text)
                self.assertNotIn("{repo:", text)
                for canary in FIXTURES[name].get("canaries", []):
                    self.assertNotIn(canary, text)

    def test_the_packs_carry_what_each_check_turns_on(self):
        expect = {"code-verifier-demo-web-planted": ("Total: 5.00", "python3 serve.py"),
                  "code-verifier-demo-silent-step": ("report.csv", "--json"),
                  "cold-reader-understanding-shift-narrowed": ("CSV or OFX", "CSV export and see"),
                  "cold-reader-understanding-shift-mechanism": ("already saved", "in the background"),
                  "cold-reader-understanding-shift-weakened": ("A transaction already imported is never imported twice",
                                                               "a file already imported is skipped"),
                  "cold-reader-reread-partial": ("Previous read", "reminds the borrower"),
                  "cold-reader-extract-clean": ("Weeks start on Monday",),
                  "claim-verifier-misquote": ("sources/acme-interview.md",),
                  "probe-explorer-recall": ("Explorer Prompt Template", "Where is an ISBN"),
                  "probe-explain-grounding": ("MODE: user", "Every claim rests on evidence"),
                  "gate-judge-story-review": ("probe_unreadable", "FAILED (failures=1)")}
        for name, needles in expect.items():
            with self.subTest(name):
                text = self.pack(name)[0]
                for needle in needles:
                    self.assertIn(needle, text)
        self.assertNotIn("OFX", self.pack("cold-reader-understanding-shift-narrowed")[0].split("Goal")[0])

    def test_a_judge_with_captures_must_open_them(self):
        for name in ("gate-judge-story-demo", "gate-judge-story-review", "gate-judge-planted"):
            self.assertEqual(self.pack(name)[2], ["--require-read", "captures/*"], name)
        self.assertEqual(self.pack("cold-reader-reread-partial")[2], [])

    def test_the_demo_copy_holds_the_product_and_not_the_intent(self):
        spec = FIXTURES["code-verifier-demo-web-planted"]
        with tempfile.TemporaryDirectory() as d:
            work = Path(d)
            shutil.copytree(FIX / spec["folder"], work / "project")
            workdir, _ = agent_fixtures.prepare(spec, work / "project", work)
            self.assertTrue((workdir / "public/app.js").is_file())
            self.assertTrue((workdir / "serve.py").is_file())
            self.assertFalse((workdir / "docs").exists())

    def test_a_review_pack_shows_the_milestone_change_over_its_base(self):
        def inspect(text, ctx):
            change = section_of(text, "Change since the milestone started")
            self.assertRegex(change, r"added     tally/report\.py +\+\d+ -0 +code +inlined")
            self.assertRegex(change, r"modified  tally/cli\.py ")
            self.assertNotIn("tally/money.py", change, "M1's files are the baseline, not the change")
            self.assertIn("+def _amount(cents):", change)
            self.assertIn("+        lines = report.monthly(ledger._expenses)", change)
            self.assertIn("+    # Checks the day first", change)
            self.assertIn("## Structure lens (finding class structure)", text)
            self.assertIn("M2.D2 When a month's total reaches a thousand", text)
            self.assertFalse((ctx["workdir"] / ".evidence").exists(), "the baseline stays out of the review copy")
        self.built("code-verifier-review-structure-planted", inspect)

    def test_the_defect_file_is_outside_the_excerpt_and_whole_in_the_full_patch(self):
        def inspect(text, ctx):
            change = section_of(text, "Change since the milestone started")
            rows = {m.group(1): m.group(2) for m in re.finditer(r"^\w+ +(\S+) +\+\d+ -\d+ +.+?  (\S.*)$", change, re.M)}
            self.assertEqual(rows["tally/dedupe.py"], "not inlined: read it in the full patch")
            self.assertEqual(rows["tally/importer.py"], "inlined", "the wiring's files come first")
            self.assertNotIn("+++ b/tally/dedupe.py", text)
            self.assertNotIn("seen.add", text, "the defect's hunk is absent from the pack")
            self.assertNotIn("def split(", text)
            patch = ctx["patch"].read_text()
            self.assertGreater(len(patch.encode()), render_pack.DIFF_BUDGET, "the change is over the inline budget")
            self.assertIn(f"The full patch: {ctx['patch'].resolve()}.", change)
            self.assertIn("+            seen.add(k)", patch)
            self.assertEqual(sorted(re.findall(r"^\+\+\+ b/(\S+)", patch, re.M)), sorted(rows), "every file, whole")
            inlined = change.split("```diff", 1)[1]
            for word in ("identical", "dedupe.py", "seen"):
                self.assertNotIn(word, inlined, "nothing inlined points at the defect")
        self.built("code-verifier-review-outside-excerpt", inspect)

    def test_the_reverify_packs_carry_the_scope_findings_and_only_the_delta(self):
        for name in REFIX:
            spec = FIXTURES[name]

            def inspect(text, ctx, spec=spec):
                scope = json.loads((ctx["project"] / spec["scope"]).read_text())
                delta = Path(scope["delta_patch"])
                self.assertTrue(delta.is_absolute() and delta.is_file(), delta)
                self.assertEqual(delta.parent, ctx["project"] / fx.REFIX_ROUND)
                self.assertEqual(Path(scope["since"]["snapshot"]), ctx["project"] / ".evidence/gate/M1/full-candidate")
                self.assertTrue(text.startswith("# Re-verify pack: M1 (focused, since round 1)"))
                findings = section_of(text, "Findings to re-verify (every finding blocking since the last full "
                                            "round, open or fixed)")
                for f in scope["findings"]:
                    self.assertIn(f"- {f['id']} [{f['class']}, {f['severity']}] {f['summary']}\n  status: "
                                  f"{f.get('status') or 'open'}", findings)
                    self.assertIn(f"fixed when: {f['fixed_when']}", findings)
                    self.assertIn(f"files: {', '.join(f['files'])}", findings)
                self.assertEqual(ctx["patch"].read_text(), delta.read_text(), "the full delta sits beside the pack")
                self.assertNotIn("Change since the milestone started", text)
                self.assertIn("- test suite: PASS, exit 0", text)
                self.assertNotIn("tally/archive.py", section_of(text, "Change since round 1's candidate"))
            with self.subTest(name):
                self.built(name, inspect)


def section_of(text, heading):
    """The body of the pack's '## heading' section (up to the next '## ' line that is a pack section)."""
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## (?!M\d+ )|\Z)", text, re.M | re.S)
    return m.group(1) if m else None


class RunUsageTest(unittest.TestCase):
    def test_one_hour_cache_writes_are_kept_when_a_run_recorded_them(self):
        ev = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, ev, True)
        opus = "claude-opus-5-5"
        (ev / "a.summary.json").write_text(json.dumps({"served_model": opus, "usage": {
            "input": 1, "cache_write": 100, "cache_read": 0, "output": 2, "cache_write_1h": 60}}))
        (ev / "b.summary.json").write_text(json.dumps({"served_model": opus, "usage": {"cache_write": 50}}))
        usage, models, _ = agent_fixtures.run_usage(ev)
        self.assertEqual(usage[opus], {"input": 1, "cache_write": 150, "cache_read": 0, "output": 2,
                                       "cache_write_1h": 60})
        self.assertEqual(models, [opus])


class HarnessTest(unittest.TestCase):
    """run_one end to end with a stand-in runner: no model, no spending."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name, value in (("WORK", self.tmp / "work"), ("REPO", self.tmp / "repo")):
            patcher = mock.patch.object(agent_fixtures, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        (self.tmp / "work").mkdir()
        agents = self.tmp / "repo/agents"
        agents.mkdir(parents=True)
        for f in (ROOT / "agents").glob("*.md"):
            shutil.copy(f, agents / f.name)
        self.calls = []

    def stand_in(self, verdict, captures=(), seen=None):
        """run_isolated.py replaced by a runner that writes the verdict; seen(cmd), when given, looks at the run's
        folders while they exist."""
        real = agent_fixtures.run

        def fake(cmd, **kw):
            if not any(str(c).endswith("run_isolated.py") for c in cmd):
                return real(cmd, **kw)
            self.calls.append(cmd)
            if seen:
                seen(cmd)
            out, workdir = Path(cmd[cmd.index("--out") + 1]), Path(cmd[cmd.index("--dir") + 1])
            stem = cmd[2] + ("-demo" if "--mode" in cmd and cmd[cmd.index("--mode") + 1] == "demo" else "")
            for rel in captures:
                (workdir / rel).parent.mkdir(parents=True, exist_ok=True)
                (workdir / rel).write_text("captured")
            (out / f"{stem}.summary.json").write_text(json.dumps({"status": "OK", "tool_uses": 3}))
            (out / f"{stem}.result.md").write_text("Done.\n```json\n" + json.dumps(verdict) + "\n```\n")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return mock.patch.object(agent_fixtures, "run", side_effect=fake)

    def test_a_judge_fixture_with_captures_runs_with_require_read(self):
        verdict = {"verdict": "CHANGES", "intent_diff": [], "blocking": [
            {"summary": "capture M1-2 shows Total food: 52.50"}, {"summary": "capture M1-4: the file was overwritten"}]}
        with self.stand_in(verdict):
            _, _, problems, _, rec = agent_fixtures.run_one("gate-judge-story-demo", FIXTURES["gate-judge-story-demo"],
                                                            1, False, "xhigh")
        self.assertEqual(problems, [])
        self.assertEqual(rec["problem_count"], 0)
        cmd = self.calls[0]
        self.assertEqual(cmd[cmd.index("--require-read") + 1], "captures/*")

    def test_every_fixture_works_in_a_folder_whose_name_says_nothing_and_the_record_names_it(self):
        neutral = r"^(?:project|folder|copies/[0-9a-f]{16}/(?:review|blind|demo))$"
        for name, verdict in (("gate-judge-story-demo", {"verdict": "ACCEPT-READY", "intent_diff": [], "blocking": []}),
                              ("code-verifier-review-structure-planted", {"mode": "review", "findings": []})):
            with self.subTest(name):
                self.calls.clear()
                with self.stand_in(verdict):
                    rec = agent_fixtures.run_one(name, FIXTURES[name], 1, False, None)[4]
                work, cmd = Path(rec["work"]), self.calls[0]
                self.assertEqual(work.parent, self.tmp / "work")
                self.assertRegex(work.name, r"^[0-9a-f]{16}$")
                for flag in ("--dir", "--project"):
                    self.assertRegex(Path(cmd[cmd.index(flag) + 1]).relative_to(work).as_posix(), neutral)
                saved = json.loads((self.tmp / "repo/.evidence/fixtures" / name / "run-1/fixture-result.json").read_text())
                self.assertEqual(saved["work"], rec["work"])
                self.assertEqual(work.exists(), not rec["pass"], "a failed run's folder is kept for a look")

    def test_a_demo_step_counts_only_with_its_capture_in_the_checkers_folder(self):
        spec = FIXTURES["code-verifier-demo-web-planted"]
        steps = {"mode": "demo", "steps": [{"milestone": "M1", "step": n, "status": "FAILS" if n > 2 else "HOLDS",
                                            "capture": f".demo-captures/M1-{n}.png"} for n in range(1, 5)]}
        with mock.patch.object(agent_fixtures, "browser_missing", return_value=None):
            with self.stand_in(steps, captures=[".demo-captures/M1-3.png", ".demo-captures/M1-4.png"]):
                problems = agent_fixtures.run_one("code-verifier-demo-web-planted", spec, 1, False, "xhigh")[2]
            self.assertEqual(problems, [])
            with self.stand_in(steps, captures=[".demo-captures/M1-3.png"]):
                rec = agent_fixtures.run_one("code-verifier-demo-web-planted", spec, 2, False, "xhigh")[4]
        self.assertEqual(rec["problem_count"], 1)
        self.assertIn("step 4", rec["problems"][0])
        self.assertNotIn("--require-read", self.calls[0])

    def test_a_browser_fixture_without_a_browser_misses_everything_and_calls_no_model(self):
        spec = FIXTURES["code-verifier-demo-web-planted"]
        with mock.patch.object(agent_fixtures, "browser_missing", return_value="no Playwright here"), \
                self.stand_in({}):
            rec = agent_fixtures.run_one("code-verifier-demo-web-planted", spec, 1, False, "xhigh")[4]
        self.assertEqual(self.calls, [])
        self.assertEqual(rec["problems"], ["no Playwright here"])
        self.assertEqual(rec["problem_count"], 1 + len(empty("code-verifier-demo-web-planted")))
        self.assertEqual(list((self.tmp / "work").iterdir()), [], "the work copy is removed")

    def test_help_prints_the_usage_and_runs_nothing(self):
        # --only selects no fixture, so even without the help guard nothing could run here.
        r = subprocess.run([sys.executable, "-B", str(ROOT / "tests/agent_fixtures.py"), "--only", "no-such-fixture",
                            "--help"], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("Level-3 harness"), r.stdout[:200])
        self.assertNotIn("agent-fixtures:", r.stdout)

    def test_a_reverify_fixture_renders_its_scope_and_runs_on_the_reverify_route(self):
        name = "code-verifier-reverify-refix-fails"
        spec, looked = FIXTURES[name], []

        def seen(cmd):
            render = cmd[cmd.index("--render") + 1:cmd.index("--", cmd.index("--render"))]
            project = Path(render[render.index("--project") + 1])
            scope_path = Path(render[render.index("--scope") + 1])
            self.assertEqual(scope_path, project / spec["scope"])
            scope = json.loads(scope_path.read_text())
            self.assertEqual(Path(scope["delta_patch"]), project / fx.REFIX_ROUND / "delta.patch")
            self.assertTrue(Path(scope["delta_patch"]).is_file())
            self.assertEqual(render[render.index("--mode") + 1], "reverify")
            self.assertTrue(Path(render[render.index("--layer1") + 1]).is_file())
            self.assertFalse((project / ".evidence/baseline-M1.txt").exists(), "a re-verify reads no baseline")
            self.assertTrue((project / "tally/archive.py").is_file(), "the base is under the variant")
            looked.append(cmd)
        verdict = {"mode": "reverify", "verdict": "FAIL", "findings": [],
                   "reverify": [{"id": "M1-F01", "status": "NOT_FIXED"}, {"id": "M1-F02", "status": "FIXED"},
                                {"id": "M1-F03", "status": "NOT_FIXED"}]}
        with self.stand_in(verdict, seen=seen):
            _, _, problems, _, rec = agent_fixtures.run_one(name, spec, 1, False, None)
        self.assertEqual(problems, [])
        self.assertEqual(rec["kind"], "planted")
        cmd = looked[0]
        self.assertEqual(cmd[cmd.index("--mode", cmd.index("--")) + 1], "reverify", "run_isolated runs the mode")
        self.assertIn("CANARY-REFIX-STATE-6620", cmd)
        self.assertTrue((self.tmp / "repo/.evidence/fixtures" / name / "run-1/verdict.json").is_file())
        with self.stand_in({**verdict, "reverify": verdict["reverify"][1:]}):
            rec = agent_fixtures.run_one(name, spec, 2, False, None)[4]
        self.assertEqual(rec["problem_count"], 1)
        self.assertTrue(rec["problems"][0].startswith("M1-F01: no reverify row"))

    def test_a_review_fixture_with_a_base_records_the_baseline_before_its_change(self):
        import baseline
        name, changed = "code-verifier-review-structure-planted", []

        def seen(cmd):
            render = cmd[cmd.index("--render") + 1:cmd.index("--", cmd.index("--render"))]
            project = Path(render[render.index("--project") + 1])
            changed.extend(sorted((f["path"], f["status"]) for f in baseline.changes(project, "M2")["files"]))
        with self.stand_in({"mode": "review", "findings": []}, seen=seen):
            rec = agent_fixtures.run_one(name, FIXTURES[name], 1, False, None)[4]
        self.assertEqual(changed, [("tally/cli.py", "modified"), ("tally/dates.py", "modified"),
                                   ("tally/report.py", "added"), ("tests/test_report.py", "added")])
        self.assertEqual(rec["problem_count"], 3)


class PlantedProductTest(unittest.TestCase):
    """The products behave as their fixtures say: the planted defect is real and the clean twin is clean."""

    PAGE = r"""
const fs = require("fs");
const els = {};
function el(id) {
  return els[id] || (els[id] = {id, value: "", textContent: "", hidden: false, children: [], on: {},
    addEventListener(t, f) { this.on[t] = f; }, replaceChildren(...c) { this.children = c; }});
}
const document = {getElementById: el, createElement: () => ({textContent: ""})};
el("show").value = "all";  // the first option, as a browser selects it
new Function("document", fs.readFileSync(process.argv[2], "utf8"))(document);
const state = () => ({rows: el("list").children.map((c) => c.textContent), total: el("total").textContent,
                      message: el("message").textContent, empty: !el("empty").hidden});
function add(category, amount) {
  el("category").value = category; el("amount").value = amount; el("add").on.submit({preventDefault() {}});
}
const out = [state()];
add("food", "5"); add("travel", "40"); out.push(state());
el("show").value = "food"; el("show").on.change(); out.push(state());
el("show").value = "all"; el("show").on.change(); add("travel", "abc"); out.push(state());
console.log(JSON.stringify(out));
"""

    def page(self, folder):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "page.js").write_text(self.PAGE)
            r = subprocess.run(["node", str(Path(d) / "page.js"), str(FIX / folder / "public/app.js")],
                               capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_web_page_fails_steps_3_and_4_only_in_the_planted_copy(self):
        clean = self.page("web-demo-clean")
        self.assertEqual((clean[0]["empty"], clean[0]["total"]), (True, "0.00"))
        self.assertEqual((clean[1]["rows"], clean[1]["total"]), (["food 5.00", "travel 40.00"], "45.00"))
        self.assertEqual((clean[2]["rows"], clean[2]["total"]), (["food 5.00"], "5.00"))
        self.assertEqual((len(clean[3]["rows"]), clean[3]["total"], clean[3]["message"]),
                         (2, "45.00", "Enter an amount like 12.50"))
        planted = self.page("web-demo-planted")
        self.assertEqual(planted[:2], clean[:2], "steps 1 and 2 hold in both")
        self.assertEqual((planted[2]["rows"], planted[2]["total"]), (["food 5.00"], "45.00"))
        self.assertEqual((planted[3]["rows"][-1], planted[3]["message"]), ("travel 0.00", ""))

    def test_the_labeled_serve_command_serves_the_page_on_a_free_port(self):
        import urllib.request
        proc = subprocess.Popen([sys.executable, "-B", str(FIX / "web-demo-planted/serve.py")], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True)
        try:
            url = re.search(r"http://127\.0\.0\.1:\d+/", proc.stdout.readline()).group(0)
            local = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never through a proxy
            page = local.open(url, timeout=10).read().decode()
            script = local.open(url + "app.js", timeout=10).read().decode()
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            proc.stdout.close()
        self.assertIn('<script src="app.js">', page)
        self.assertIn("expenses.reduce", script)

    def test_the_silent_steps_exit_0_and_show_nothing(self):
        app = FIX / "demo-silent-step/app.py"
        with tempfile.TemporaryDirectory() as d:
            tally = lambda *a: subprocess.run([sys.executable, "-B", str(app), *a], cwd=d, capture_output=True, text=True)
            for category, value in (("food", "5"), ("travel", "40"), ("food", "7.5")):
                tally("add", category, value)
            self.assertEqual(tally("total", "food").stdout.strip(), "Total food: 12.50")
            exported = tally("export", "--out", "report.csv")
            self.assertEqual((exported.returncode, exported.stdout.strip()), (0, "exported 3 expenses to report.csv"))
            self.assertFalse((Path(d) / "report.csv").exists())
            as_json = tally("total", "food", "--json")
            self.assertEqual((as_json.returncode, as_json.stdout), (0, ""))
            self.assertEqual(len(tally("export").stdout.splitlines()), 4, "plain export still prints every line")

    def test_the_explorer_codebase_runs(self):
        r = subprocess.run([sys.executable, "-B", str(FIX / "explorer-recall/tests/test_shelf.py")],
                           capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(r.returncode, 0, r.stderr[-600:])


class LayeredProductTest(unittest.TestCase):
    """The products of the structure, excerpt, and re-verify fixtures (a base with the fixture laid over it) behave
    as their expectations say, and each passes its own suite, as the deterministic layer in the re-verify packs
    reports."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def product(self, name):
        spec = FIXTURES[name]
        where = Path(tempfile.mkdtemp(dir=self.tmp))
        dest = where / "project"
        shutil.copytree(FIX / spec["base"], dest)
        shutil.copytree(FIX / spec["folder"], dest, dirs_exist_ok=True)
        folder = where / "run"
        folder.mkdir()
        return dest, folder

    def tally(self, project, folder, *args):
        env = {**os.environ, "PYTHONPATH": str(project), "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run([sys.executable, "-m", "tally", *args], cwd=folder, capture_output=True, text=True,
                              env=env)

    def test_every_layered_product_passes_its_own_suite(self):
        for name in (n for n in NEW if FIXTURES[n].get("base")):
            with self.subTest(name):
                project, _ = self.product(name)
                r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=project,
                                   capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
                self.assertEqual(r.returncode, 0, r.stderr[-800:])

    def test_the_structure_twins_behave_alike_and_differ_only_where_planted(self):
        reports = {}
        for name in ("code-verifier-review-structure-planted", "code-verifier-review-structure-clean"):
            project, folder = self.product(name)
            for args in (("food", "5", "--on", "2026-09-03"), ("travel", "40", "--on", "2026-09-10"),
                         ("food", "7.50", "--on", "2026-09-20"), ("food", "3", "--on", "2026-10-01"),
                         ("rent", "1250", "--on", "2026-10-01")):
                self.tally(project, folder, "add", *args)
            reports[name] = self.tally(project, folder, "report").stdout.splitlines()
        self.assertEqual(set(map(tuple, reports.values())), {("2026-09 food 12.50", "2026-09 travel 40.00",
                                                              "2026-10 food 3.00", "2026-10 rent 1,250.00")})
        planted, clean = FIX / "structure-planted", FIX / "structure-clean"
        files = sorted(p.relative_to(planted).as_posix() for p in planted.rglob("*") if p.is_file())
        self.assertEqual(files, sorted(p.relative_to(clean).as_posix() for p in clean.rglob("*") if p.is_file()))
        differ = [f for f in files if (planted / f).read_bytes() != (clean / f).read_bytes()]
        self.assertEqual(differ, ["tally/cli.py", "tally/dates.py", "tally/report.py"])
        self.assertIn("def _amount(cents):", (planted / "tally/report.py").read_text())
        self.assertIn("money.format_amount(cents)", (clean / "tally/report.py").read_text())
        self.assertIn("report.monthly(ledger._expenses)", (planted / "tally/cli.py").read_text())
        self.assertIn("report.monthly(ledger.expenses())", (clean / "tally/cli.py").read_text())
        project, _ = self.product("code-verifier-review-structure-planted")
        said = subprocess.run([sys.executable, "-c", "from tally import dates; print(dates.month_of('2026-99-99x'))"],
                              cwd=project, capture_output=True, text=True)
        self.assertEqual(said.stdout.strip(), "2026-99", "the comment says it raises BadDay; it does not")

    def test_the_import_records_one_of_two_identical_lines(self):
        project, folder = self.product("code-verifier-review-outside-excerpt")
        (folder / "rules.txt").write_text("coffee -> food\n")
        (folder / "pair.csv").write_text("Date,Description,Amount\n02/09/2026,CORNER COFFEE HOUSE,-3.50\n"
                                         "02/09/2026,CORNER COFFEE HOUSE,-3.50\n05/09/2026,SHELL,-10.00\n")
        out = self.tally(project, folder, "import", "pair.csv")
        self.assertIn("imported 2 expense(s)", out.stdout)
        self.assertIn("(1 already recorded", out.stdout, "the lost line is counted as already recorded")
        self.assertEqual(self.tally(project, folder, "total", "food").stdout.strip(), "Total food: 3.50")

    def csv_round_trip(self, project, folder):
        """(export rows, archive rows) for categories holding a comma, a quote, and a line break."""
        import csv
        import io
        categories = ["eat, out", 'say "hi", ok', "two\nlines"]
        for c in categories:
            self.tally(project, folder, "add", c, "2", "--on", "2026-09-03")
        self.tally(project, folder, "archive", "2026-09")
        exported = list(csv.reader(io.StringIO(self.tally(project, folder, "export").stdout)))
        archived = list(csv.reader(io.StringIO((folder / "archive/2026-09.csv").read_text())))
        return categories, exported, archived

    def broken_add(self, project, folder):
        """(exit of add on an unreadable file, what the file holds after)."""
        data = folder / "expenses.json"
        data.write_text("{broken")
        code = self.tally(project, folder, "add", "food", "1").returncode
        return code, data.read_text()

    def test_each_refix_variant_does_what_its_expectation_says(self):
        header = ["day", "category", "amount"]
        for name in REFIX:
            with self.subTest(name):
                project, folder = self.product(name)
                self.assertEqual(self.tally(project, folder, "add", "food", "-5").returncode, 2, "M1-F02 fixed")
                categories, exported, archived = self.csv_round_trip(project, folder)
                rows = [header] + [["2026-09-03", c, "2.00"] for c in categories]
                code, kept = self.broken_add(project, folder)
                if name.endswith("works"):
                    self.assertEqual((exported, archived), (rows, rows))
                    self.assertEqual((code, kept), (2, "{broken"))
                elif name.endswith("fails"):
                    self.assertEqual(exported[1], ["2026-09-03", "eat, out", "2.00"], "fixed_when's own example")
                    self.assertNotEqual(exported, rows, "M1-F01 is not fixed for a quote or a line break")
                    self.assertEqual(code, 0, "M1-F03 is not fixed: add still overwrites the unreadable file")
                    self.assertNotEqual(kept, "{broken")
                else:
                    self.assertEqual(exported, rows)
                    self.assertEqual(archived, [header] + rows, "the archive, a caller of csv_lines, has two headers")
                    self.assertEqual((code, kept), (2, "{broken"))

    def test_each_refix_delta_is_what_regate_scope_writes(self):
        import regate_scope
        from fingerprint import fingerprint
        snap = self.tmp / "snap"
        shutil.copytree(FIX / "refix/base", snap)
        since, rows = fingerprint(snap, "product")
        old = {rel: h[:16] for rel, h in rows}
        ledger = json.loads((FIX / "refix/base/docs/project/reviews/M1.findings.json").read_text())
        for name in REFIX:
            with self.subTest(name):
                spec = FIXTURES[name]
                project, _ = self.product(name)
                cur = {rel: h[:16] for rel, h in fingerprint(project, "product")[1]}
                patch = self.tmp / f"{name}.patch"
                changed = regate_scope.delta(project, snap, old, cur, patch)
                scope = json.loads((FIX / spec["folder"] / spec["scope"]).read_text())
                self.assertEqual(patch.read_text(), (FIX / spec["folder"] / scope["delta_patch"]).read_text())
                self.assertEqual(scope["changed_files"], changed)
                self.assertEqual(scope["changed_lines"], sum(c["added"] + c["removed"] for c in changed))
                self.assertLess(scope["changed_lines"], regate_scope.LINE_LIMIT)
                self.assertEqual((scope["scope"], scope["milestone"], scope["kind"]), ("focused", "M1", "changes"))
                self.assertEqual(scope["since"]["fingerprint"], since)
                self.assertEqual([f["id"] for f in scope["findings"]], sorted(fid for fid, r in ledger.items()
                                                                               if r["status"] == "open"))
                for f in scope["findings"]:
                    for k in ("summary", "class", "severity", "files", "where", "fixed_when"):
                        self.assertEqual(f[k], ledger[f["id"]][k], (f["id"], k))
                named = {p for f in scope["findings"] for p in f["files"]}
                for c in changed:
                    self.assertTrue(c["path"] in named or c["path"].startswith("tests/"), c["path"])


# ---------- the fast pipeline's reviewer (fast plan 4.6) ----------

# gate-fast's reviewer prompt as the fast repository holds it at 5cfa3b9, in a skill cut to what the harness reads.
FAST_SKILL_TEXT = """---
name: gate-fast
description: "Verify everything built since the last verification in one concentrated pass."
---

# /gate-fast

## 3. One fresh reviewer
- Codex: `codex exec -s read-only -o .fast/review.md "<prompt>"`.

The prompt, with the parts in angle brackets filled in:
> Review a change you did not write, in <project path>. Goal: <Goal>. Done when: <items>. Not doing: <items>.
> The change: `<review diff command>`. Find (1) bugs that make a Done-when item fail, crash, lose or corrupt
> data, or expose secrets; (2) items that look done but are faked or unfinished (stubs, hard-coded results,
> unwired code, swallowed errors); (3) whether this is still what the goal asks for. Run code or tests when
> that settles a question. Leave out style, naming, and hypothetical issues. Return at most 10 findings, most
> severe first, each with high/medium/low, file:line, what fails, and how to see it fail. End with one line:
> "Matches the goal: yes/no, because ...".

## 4. Fix, once
"""
CANDIDATES = FIX / "fast-reviewer/candidate-lines.md"
SIBLING = Path(os.environ.get("FAST_REPO") or ROOT.parent / "coding-pipeline-fast")
PLACEHOLDER = re.compile(r"<[^<>\n]+>")


def make_fast_repo(where, skill=FAST_SKILL_TEXT, fast_py=None):
    """A fast repository in a temporary folder: its gate-fast skill and, when given, a fast.py."""
    repo = Path(where) / "fast"
    (repo / "skills/gate-fast").mkdir(parents=True)
    (repo / "skills/gate-fast/SKILL.md").write_text(skill)
    if fast_py is not None:
        (repo / "skills/_fast").mkdir(parents=True)
        (repo / "skills/_fast/fast.py").write_text(fast_py)
    return repo


def fast_env(repo, extra=None):
    """FAST_REPO set to repo and FAST_REVIEWER_EXTRA to extra (or unset), for the test's length."""
    env = mock.patch.dict(os.environ, {"FAST_REPO": str(repo), **({"FAST_REVIEWER_EXTRA": str(extra)} if extra else {})})
    env.start()
    if not extra:
        os.environ.pop("FAST_REVIEWER_EXTRA", None)
    return env


def answer(*findings, last="Matches the goal: no, because the change does not do what the plan says."):
    return "I ran the diff command and the tests.\n\n" + "\n\n".join(findings) + "\n\n" + last + "\n"


TALLY_CATCHES = [
    "1. **High** - `app.py:27` - `total()` sums every expense and ignores the category.\n"
    "   How to see it fail: add food 5, travel 40, food 7.5; `total food` prints 52.50.",
    "2. **High** - `app.py:16` - an unreadable expenses.json is read as empty (the JSONDecodeError is swallowed), "
    "so the next add overwrites it.",
    "3. **Medium** - `app.py:13` - a fresh folder loads SAMPLE from sample_data.py: total food is 12.50, not 0.00.",
    "4. **High** - `app.py:41` - export_csv is never wired: `python3 app.py export` exits 2 with invalid choice.",
]


class FastReviewerExpectationTest(unittest.TestCase):
    """The reviewer's text answer read the way each expectation reads it."""

    def result(self, text):
        return {"summary": {}, "result": text}

    def test_each_tally_defect_is_one_item(self):
        name = "fast-reviewer-tally-defects"
        expect = FIXTURES[name]["expect"]
        self.assertEqual(expect({}, self.result(answer(*TALLY_CATCHES))), [])
        for i, label in enumerate(fx.FAST_TALLY):
            problems = expect({}, self.result(answer(*(TALLY_CATCHES[:i] + TALLY_CATCHES[i + 1:]))))
            self.assertEqual(problems, [f"not caught: {label}"])
        self.assertEqual(len(expect({}, self.result(""))), 4, "the empty answer misses every item")

    def test_the_formats_reviewers_write_are_read_alike(self):
        heading = ("### 1. `total()` ignores the category\n**Severity:** high\n**Where:** app.py:27\n"
                   "**What fails:** it sums all expenses.")
        table = ("| # | Severity | Location | What fails |\n|---|---|---|---|\n"
                 "| 1 | high | app.py:27 | total sums every expense, whatever the category |\n"
                 "| 2 | medium | app.py:16 | a broken file is read as empty, then overwritten |")
        bracket = "[HIGH] app.py:13 Sample data appears in a fresh folder"
        tail = "**Finding 4 (high)** - app.py:41\nexport is not wired into the parser"
        found = fx.fast_findings(answer(heading, table, bracket, tail))
        self.assertEqual([f["severity"] for f in found], ["high", "high", "medium", "high", "high"])
        self.assertIn("ignores the category", found[0]["text"], "the heading above a severity field is its title")
        self.assertEqual(fx.fast_tally_defects({}, self.result(answer(heading, table, bracket, tail))), [])

    def test_a_severity_section_makes_each_item_a_finding_and_an_empty_section_none(self):
        grouped = ("## High-severity findings\n1. `app.py:27` - total() sums every expense, ignoring the category.\n"
                   "2. `app.py:16` - a broken file is read as empty and then overwritten.\n"
                   "## Medium\nNone.\n## Low\n- app.py:80 - the help text is terse.")
        self.assertEqual([f["severity"] for f in fx.fast_findings(answer(grouped))], ["high", "high", "low"])
        self.assertEqual([p.split(" (")[0] for p in fx.fast_tally_defects({}, self.result(answer(grouped)))],
                         ["not caught: sample data loaded on the product path",
                          "not caught: the export command built but never wired into the command line"])
        clean = "### High\nNone.\n### Medium\n_None._\n### Low\n1. app.py:80 - the help text is terse."
        self.assertEqual(fx.fast_clean({}, self.result(answer(clean, last="Matches the goal: yes, because it holds."))),
                         [], "a severity section that says none is no finding")
        for none in ("### High\nNone found (I read app.py:1-138).", "High: none (I read app.py:1-138)",
                     "High: 0, Medium: 0, Low: 1\n\n1. app.py:80 - the help text is terse."):
            self.assertEqual(fx.blocking_findings(answer(none)), [], none)

    def test_words_from_two_items_under_one_heading_catch_nothing(self):
        # The review's reproduction: the export item's words were only in other items ("export" in the second,
        # "missing" in the third), so the heading's one finding credited a catch nobody made.
        three = ("## High\n1. `app.py:27` - total() sums every expense, ignoring the category: `total food` prints "
                 "52.50.\n2. `app.py:16` - a broken expenses.json is read as empty and the next add overwrites it; "
                 "export afterwards prints only the header.\n3. `app.py:13` - sample data is loaded when the file is "
                 "missing, so a fresh folder shows invented expenses.")
        export = "not caught: " + list(fx.FAST_TALLY)[3]
        self.assertEqual([f["severity"] for f in fx.fast_findings(answer(three))], ["high"] * 3)
        self.assertEqual(fx.fast_tally_defects({}, self.result(answer(three))), [export])
        medium = ("## High\n1. app.py:30 - total sums every expense regardless of category.\n2. app.py:12 - a corrupt "
                  "expenses.json is read as empty and then overwritten.\n3. app.py:8 - sample data is loaded on the "
                  "product path.\n\n## Medium\n1. app.py:66 - export prints the header in a different order from the "
                  "plan's example.\n2. app.py:20 - the error message for a missing file does not name the file.")
        self.assertEqual(fx.fast_tally_defects({}, self.result(answer(medium))), [export])
        for text in ("## High\n\napp.py:27 - total sums every expense.\n\napp.py:41 - export prints the header twice.\n\n"
                     "app.py:9 - the --file option is missing.",
                     "## High\n| Location | What fails |\n|---|---|\n| app.py:41 | export prints the header twice |\n"
                     "| app.py:9 | the --file option is missing |",
                     "1. **High** app.py:41 - export prints the header twice\n2. app.py:9 - the --file option is missing"):
            self.assertIn(export, fx.fast_tally_defects({}, self.result(answer(text))), text)

    def test_one_finding_keeps_its_own_fields_and_subheadings(self):
        fields = ("### 1. High - Corrupt expenses.json handling\n- **Where:** app.py:16\n- **What fails:** load() "
                  "returns [] on a JSONDecodeError, so the next add overwrites the file.\n- **How to see it fail:** "
                  "write {half into expenses.json, then add food 5.")
        found = fx.fast_findings(answer(fields))
        self.assertEqual([f["severity"] for f in found], ["high"])
        self.assertIn("overwrites", found[0]["text"])
        under = ("## High\n### 1. Corrupt expenses.json handling\n- **Where:** app.py:16\n- **What fails:** load() "
                 "returns [], so the next add overwrites the file.\n### 2. Export\n- **Where:** app.py:41\n"
                 "- **What fails:** export is never wired: invalid choice.")
        self.assertEqual(len(fx.fast_findings(answer(under))), 2)
        paragraphs = ("## High\n\n**`app.py:16` - corrupt file handling**\n\nWhat fails: an unreadable file is read as "
                      "[] and the next add overwrites it.")
        bold = "**Finding 2 (high)**\n`app.py:16` - an unreadable file is read as empty, then overwritten."
        for text in (fields, under, paragraphs, bold):
            self.assertNotIn("not caught: " + list(fx.FAST_TALLY)[1],
                             fx.fast_tally_defects({}, self.result(answer(text))), text)

    def test_a_severity_word_in_prose_or_under_a_low_heading_is_no_label(self):
        yes = "Matches the goal: yes, because every Done-when item runs as described."
        for text in ("## Findings\n### Low\n1. app.py:88 - with a very high number of expenses, export builds the "
                     "whole CSV in one string.",
                     "No high or medium findings; I ran the suite (12 pass) and read app.py:1-138.\n\n1. low - "
                     "app.py:88 - export repeats the header when there are no expenses.",
                     "I read app.py:1-138 and ran the suite (12 tests pass). Nothing high or medium.\n\nLow:\n1. "
                     "app.py:88 - the CSV header is written even when there are no expenses.",
                     "Checked:\n- Done-when 2 at app.py:40: verified; no high or medium issue there.\n- Done-when 3 at "
                     "app.py:52: no **high** issue either.\n\nFindings: none.",
                     "1. app.py:52 - a very high amount (1e17) loses cents in the float total (low).",
                     "### Low\n- app.py:52 - [high] amounts lose cents"):
            with self.subTest(text[:40]):
                self.assertEqual(fx.fast_clean({}, self.result(answer(text, last=yes))), [])
        self.assertEqual([f["severity"] for f in fx.fast_findings(
            "1. app.py:41 - the export command is never wired (high).\n| app.py:27 | High | total ignores it |")],
            ["high", "high"], "a label inside the line still counts")

    def test_the_file_line_forms_reviewers_write_are_read(self):
        spelled = ("1. **High** - `app.py`, line 30: `total` adds every expense regardless of its category, so `total "
                   "food` prints 52.50.\n2. **High** - `app.py`, lines 12-16: a corrupt expenses.json is read as empty "
                   "and the next add overwrites it.\n3. **High** - app.py (line 8): sample data from sample_data.py is "
                   "loaded on the product path.\n4. **High** - app.py L60: the export command is never wired into "
                   "the command line (invalid choice).")
        self.assertEqual(fx.fast_tally_defects({}, self.result(answer(spelled))), [])
        self.assertEqual(fx.fast_tally_defects({}, self.result(answer(spelled.replace("app.py L60", "app.py, L60")
                                                                       .replace("`app.py`, line 30", "`app.py:30`")))), [])
        self.assertEqual(fx.fast_tally_defects({}, self.result(answer(spelled.replace(" - ", " \u2014 ")))), [],
                         "em dashes, as reviewers write them")
        self.assertEqual(fx.finding_start("1. `app.py:27` \u2014 High \u2014 total ignores the category"), "high")
        block = "1. **Medium** - `app.py`, line 88: export writes amounts with str(), so 7.5 prints as 7.5."
        yes = "Matches the goal: yes, because every Done-when item works."
        self.assertEqual(len(fx.fast_clean({}, self.result(answer(block, last=yes)))), 1, "a false block is seen")
        for prose in ("v1.5:30", "python3.9 3", "prints 52.50, line", "test_app.py, 12 tests pass", "app.py (8)"):
            self.assertIsNone(fx.FILE_LINE.search(prose), prose)

    def test_a_file_is_named_at_a_path_boundary(self):
        tests_only = ("1. **Medium** - tests/test_budgets.py:30: no test makes a category go over its budget, so a "
                      "stub over() that returns False would pass.\n2. **High** - tally/status.py:12: MONTH_SPENT is a "
                      "hard-coded table.")
        self.assertEqual(fx.fast_faked_done({}, self.result(answer(tests_only))),
                         ["not caught: " + list(fx.FAST_FAKED)[1]], "test_budgets.py is not budgets.py")
        for named in ("tally/budgets.py:36", "budgets.py:36", "/home/o/.gate-copies/x/review/tally/budgets.py:36"):
            self.assertEqual(fx.fast_faked_done({}, self.result(answer(tests_only.replace(
                "tests/test_budgets.py:30", named)))), [], named)
        self.assertFalse(fx.names_file({"text": "myapp.py:3 and app.pyc"}, ("app.py",)))

    def test_prose_and_code_open_no_finding(self):
        text = ("High-level: I read app.py:1 to app.py:60.\nHigh confidence the add command works.\n"
                "```\nhigh app.py:3 inside a code block\n```\nOverall the tests pass at a low cost.\n"
                "Matches the goal: yes, because every item holds.")
        self.assertEqual(fx.fast_findings(text), [])
        self.assertTrue(fx.matches_goal(text))

    def test_a_low_finding_or_another_file_catches_nothing(self):
        low = TALLY_CATCHES[0].replace("**High**", "**Low**")
        elsewhere = TALLY_CATCHES[0].replace("app.py:27", "ledger.py:27")
        for text in (low, elsewhere):
            problems = fx.fast_tally_defects({}, self.result(answer(text, *TALLY_CATCHES[1:])))
            self.assertEqual(len(problems), 1, text)
            self.assertIn("ignores the category", problems[0])

    def test_each_planted_fixture_counts_its_items_and_a_run_pools_at_least_six(self):
        counts = {"fast-reviewer-tally-defects": 4, "fast-reviewer-outside-excerpt": 1,
                  "fast-reviewer-refix-breaks-other": 1, "fast-reviewer-faked-done": 2}
        planted = [n for n in FAST if FIXTURES[n]["kind"] == "planted"]
        self.assertEqual(sorted(planted), sorted(counts))
        for name, n in counts.items():
            self.assertEqual(len(empty(name)), n, name)
        self.assertGreaterEqual(sum(counts.values()), 6)
        self.assertGreaterEqual(sum(counts.values()) * 5, 30, "30 planted item-trials a side at --runs 5")
        self.assertEqual({FIXTURES[n]["kind"] for n in FAST}, {"planted", "clean"})

    def test_the_import_archive_and_faked_items(self):
        dedupe = "- high: tally/dedupe.py:33 - split adds each new key to seen, so a second identical coffee is dropped"
        self.assertEqual(fx.fast_outside_excerpt({}, self.result(answer(dedupe))), [])
        self.assertEqual(len(fx.fast_outside_excerpt({}, self.result(answer(dedupe.replace("dedupe.py", "cli.py"))))),
                         1, "the finding must name tally/dedupe.py")
        archive = ("1. **High** tally/export.py:18 - csv_lines now starts with the header, and tally/archive.py:14 "
                   "adds its own: every month archive has the header twice")
        self.assertEqual(fx.fast_refix_breaks_other({}, self.result(answer(archive))), [])
        self.assertEqual(len(fx.fast_refix_breaks_other({}, self.result(answer(archive.replace("twice", "")
                                                                                 .replace("its own", "nothing"))))), 1)
        spent = "1. **High** - tally/status.py:5 - MONTH_SPENT is a hard-coded table; status ignores the ledger."
        stub = "2. **High** - tally/budgets.py:36 - over() always returns False, so no category is ever marked over."
        self.assertEqual(fx.fast_faked_done({}, self.result(answer(spent, stub))), [])
        self.assertEqual(fx.fast_faked_done({}, self.result(answer(spent))),
                         ["not caught: " + list(fx.FAST_FAKED)[1]], "the stub is its own item")
        self.assertEqual(fx.fast_faked_done({}, self.result(answer(stub))),
                         ["not caught: " + list(fx.FAST_FAKED)[0]], "the hard-coded table is its own item")

    def test_a_clean_control_wants_no_block_and_a_yes(self):
        nit = "1. low - app.py:80 - the help text could say what export prints."
        yes = "Matches the goal: yes, because every Done-when item holds."
        self.assertEqual(fx.fast_clean({}, self.result(answer(nit, last=yes))), [])
        self.assertEqual(fx.fast_clean({}, self.result(answer(last="**Matches the goal: yes**, because it holds."))), [])
        blocked = fx.fast_clean({}, self.result(answer(nit.replace("low", "medium"), last=yes)))
        self.assertEqual(len(blocked), 1)
        self.assertIn("false block", blocked[0])
        self.assertEqual(len(fx.fast_clean({}, self.result(answer(nit)))), 1, "a no is a false block too")
        self.assertEqual(len(fx.fast_clean({}, self.result(answer(nit, last=yes) + "\nAnything else?\n"))), 1,
                         "the yes must be the last line")
        self.assertEqual(len(fx.fast_clean({}, self.result(""))), 1, "the empty answer fails a clean control")


class FastReviewerPackTest(unittest.TestCase):
    """Each fast-reviewer fixture's review copy and pack, prepared as agent_fixtures.py prepares them, with no model."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fast = make_fast_repo(self.tmp)
        self.addCleanup(fast_env(self.fast).stop)

    def built(self, name):
        """(pack, record, review copy, project) of one fixture, in a work folder of this test."""
        spec = FIXTURES[name]
        work = Path(tempfile.mkdtemp(dir=self.tmp))
        project = agent_fixtures.make_project(spec, work)
        copy, _ = agent_fixtures.prepare(spec, project, work)
        text, info = agent_fixtures.fast_pack(spec, copy)
        return text, info, copy, project

    def git(self, copy, *args):
        return subprocess.run(["git", "-C", str(copy), *args], capture_output=True, text=True).stdout

    def test_every_pack_is_the_filled_prompt_and_its_diff_command_works(self):
        for name in FAST:
            spec = FIXTURES[name]
            with self.subTest(name):
                text, info, copy, project = self.built(name)
                self.assertNotRegex(text, PLACEHOLDER, "every part in angle brackets is filled")
                self.assertTrue(text.startswith(f"Review a change you did not write, in {copy}. Goal: "))
                plan = agent_fixtures.plan_sections((FIX / spec["fast_plan"]).read_text())
                for item in agent_fixtures.plan_items(plan["Done when"]):
                    self.assertIn(item.rstrip("."), text)
                self.assertIn(f"The change: `{info['diff_command']}`.", text)
                self.assertTrue(text.rstrip().endswith('"Matches the goal: yes/no, because ...".'))
                diff = subprocess.run(shlex.split(info["diff_command"]), capture_output=True, text=True)
                self.assertEqual(diff.returncode, 0, diff.stderr)
                shown = sorted(re.findall(r"^\+\+\+ b/(\S+)", diff.stdout, re.M))
                status = sorted(line[3:] for line in self.git(copy, "status", "--porcelain", "--untracked-files=all")
                                .splitlines())
                self.assertEqual(shown, status, "the diff shows exactly the uncommitted change")
                self.assertTrue(shown)
                if spec.get("base"):
                    self.assertTrue((copy / "tally/__init__.py").is_file())
                    self.assertNotIn("tally/__init__.py", shown, "the base is committed, not part of the change")
                self.assertEqual(self.git(copy, "rev-parse", "HEAD").strip(), info["base"])
                self.assertEqual(self.git(copy, "rev-parse", "refs/fast/review").strip(), info["snapshot"])
                self.assertIn(f"Started at: {info['base'][:12]} ", (copy / ".fast/plan.md").read_text())
                self.assertNotIn(".fast/plan.md", shown, ".fast/ is kept out of git, as fast.py init keeps it")
                for gone in (".coding-pipeline.json", "docs/project", ".evidence"):
                    self.assertFalse((copy / gone).exists(), gone)
                history = self.git(copy, "log", "-p", "--all")
                files = "".join(p.read_text(errors="replace") for p in copy.rglob("*") if p.is_file()
                                and ".git" not in p.relative_to(copy).parts)
                for canary in spec["canaries"]:
                    self.assertIn(canary, "".join(p.read_text() for p in project.rglob("state.md")))
                    for where, body in (("pack", text), ("copy", files), ("git history", history)):
                        self.assertNotIn(canary, body, where)

    def test_the_run_is_made_a_managed_project_and_the_copy_is_not(self):
        sys.path.insert(0, str(ROOT / "skills/_shared/scripts"))
        import project_policy
        _, _, copy, project = self.built("fast-reviewer-tally-clean")
        self.assertTrue(project_policy.read(str(project))["managed"], "run_isolated.py runs only a managed project")
        self.assertFalse((copy / ".coding-pipeline.json").exists())

    def test_the_extra_lines_are_appended_with_their_parts_filled(self):
        plain = self.built("fast-reviewer-tally-defects")[0]
        env = mock.patch.dict(os.environ, {"FAST_REVIEWER_EXTRA": str(CANDIDATES)})
        env.start()
        self.addCleanup(env.stop)
        text, info, copy, _ = self.built("fast-reviewer-tally-defects")
        self.assertNotRegex(text, PLACEHOLDER)
        end = '"Matches the goal: yes/no, because ...".\n'
        head, _, tail = text.partition(end)
        same = lambda s: re.sub(r"\b[0-9a-f]{12}\b", "<sha>", re.sub(r"/\S+/review\b", "<copy>", s))
        self.assertEqual(same(head + end), same(plain), "today's prompt comes first, unchanged")
        self.assertTrue(tail.startswith("Step 1 already ran the project's checks: test "
                                        "(`python3 -m unittest discover -s tests`): exit 0; Ran 1 test"), tail[:200])
        self.assertIn("Do not run them again; run only what settles an item.", tail)
        self.assertIn("is missing, so this is git diff --stat)", tail, "the fallback says so")
        for f in ("app.py", "sample_data.py", "tests/test_app.py"):
            self.assertIn(f, tail)
        self.assertTrue(tail.rstrip().endswith("Read the files in the table's order; skip the ones marked skip."))
        self.assertEqual(info["extra"], str(CANDIDATES.resolve()))
        self.assertNotEqual(info["sha256"], info["prompt_sha256"])
        self.assertEqual(self.git(copy, "status", "--porcelain").count("??"), 4, "the test run left the copy as it was")

    def test_a_fast_py_with_a_file_table_gives_the_table(self):
        table = ("import sys\nprint('review diff: git -C x diff a b   (4 files changed)')\nprint('file list:   x')\n"
                 "print('A  app.py             +56 -0  code')\nprint('A  tests/test_app.py  +18 -0  test')\n"
                 "print('A  AGENTS.md          +12 -0  docs  skip')\n")
        fast = make_fast_repo(self.tmp / "with-table", fast_py=table)
        spec = FIXTURES["fast-reviewer-tally-defects"]
        work = Path(tempfile.mkdtemp(dir=self.tmp))
        copy, _ = agent_fixtures.prepare(spec, agent_fixtures.make_project(spec, work), work)
        base, snap = agent_fixtures.fast_copy(spec, copy, (FIX / spec["fast_plan"]).read_text())
        self.assertEqual(agent_fixtures.file_table(copy, base, snap, fast),
                         "A  app.py             +56 -0  code\nA  tests/test_app.py  +18 -0  test\n"
                         "A  AGENTS.md          +12 -0  docs  skip")
        silent = make_fast_repo(self.tmp / "no-table", fast_py="print('review diff: git diff a b')\n")
        self.assertIn("prints no file table, so this is git diff --stat", agent_fixtures.file_table(copy, base, snap, silent))
        broken = make_fast_repo(self.tmp / "broken", fast_py="import sys\nsys.exit(3)\n")
        self.assertIn("failed (exit 3)", agent_fixtures.file_table(copy, base, snap, broken))

    def test_the_copy_keeps_fast_and_evidence_out_of_git_as_fast_init_does(self):
        # fast.py puts a missing .fast/ or .evidence/ line back and says so: that line never reaches the file table.
        keep_out = ("import sys, pathlib\nhave = (pathlib.Path(sys.argv[2]) / '.git/info/exclude').read_text().split()\n"
                    "for line in ('.fast/', '.evidence/'):\n    if line not in have:\n"
                    "        print('kept out of git: ' + line)\nprint('A  app.py  +56 -0  code')\n")
        fast = make_fast_repo(self.tmp / "keep", fast_py=keep_out)
        spec = FIXTURES["fast-reviewer-tally-defects"]
        work = Path(tempfile.mkdtemp(dir=self.tmp))
        copy, _ = agent_fixtures.prepare(spec, agent_fixtures.make_project(spec, work), work)
        exclude = copy / ".git/info/exclude"
        base, snap = agent_fixtures.fast_copy(spec, copy, (FIX / spec["fast_plan"]).read_text())
        self.assertEqual([line for line in exclude.read_text().splitlines() if not line.startswith("#")],
                         [".fast/", ".evidence/"])
        self.assertEqual(agent_fixtures.file_table(copy, base, snap, fast), "A  app.py  +56 -0  code")

    def test_a_test_command_that_writes_into_the_copy_is_refused(self):
        spec = FIXTURES["fast-reviewer-tally-clean"]
        work = Path(tempfile.mkdtemp(dir=self.tmp))
        copy, _ = agent_fixtures.prepare(spec, agent_fixtures.make_project(spec, work), work)
        agent_fixtures.fast_copy(spec, copy, (FIX / spec["fast_plan"]).read_text())
        with self.assertRaises(agent_fixtures.FastPromptError) as caught:
            agent_fixtures.step1_results(copy, {"Commands": ["- test: echo made > made.txt"]})
        self.assertIn("changed the review copy", str(caught.exception))
        with self.assertRaises(agent_fixtures.FastPromptError) as caught:
            agent_fixtures.step1_results(copy, {"Commands": ["- run: python3 app.py", "- test:"]})
        self.assertIn("names no test command", str(caught.exception))
        self.assertIn("exit 1", agent_fixtures.step1_results(copy, {"Commands": ["- test: python3 -c 'raise SystemExit(1)'"]}))

    def test_a_prompt_that_cannot_be_read_or_filled_fails_clearly(self):
        cases = {"missing": (None, "no gate-fast skill at"),
                 "no block": (FAST_SKILL_TEXT.replace("> ", ""), "holds no reviewer prompt"),
                 "no diff": (FAST_SKILL_TEXT.replace("`<review diff command>`", "the diff"), "names no <review diff"),
                 "a new part": (FAST_SKILL_TEXT.replace("Goal: <Goal>.", "Goal: <Goal>. Notes: <notes>."), "<notes>")}
        for label, (skill, said) in cases.items():
            with self.subTest(label):
                repo = self.tmp / label.replace(" ", "-")
                if skill is not None:
                    make_fast_repo(repo, skill)
                with self.assertRaises(agent_fixtures.FastPromptError) as caught:
                    agent_fixtures.reviewer_prompt(repo / "fast")
                self.assertIn(said, str(caught.exception))
        for content, said in ((None, "cannot be read"), ("\n> \n", "holds no lines"), ("> See <the log>.\n", "<the log>")):
            extra = self.tmp / "extra.md"
            if content is None:
                extra.unlink(missing_ok=True)
            else:
                extra.write_text(content)
            with mock.patch.dict(os.environ, {"FAST_REVIEWER_EXTRA": str(extra)}):
                with self.assertRaises(agent_fixtures.FastPromptError) as caught:
                    agent_fixtures.reviewer_prompt(self.fast)
            self.assertIn(said, str(caught.exception))

    def test_the_prompt_records_where_it_came_from(self):
        prompt, info = agent_fixtures.reviewer_prompt(self.fast)
        self.assertTrue(prompt.startswith("Review a change you did not write, in <project path>."))
        self.assertNotIn("<prompt>", prompt, "only the blockquote is the prompt")
        self.assertEqual((info["revision"], info["skill_dirty"], info["extra"]), (None, None, None),
                         "a fast repository that is not a git repository has no revision")
        self.assertEqual(info["sha256"], info["prompt_sha256"])
        outer = self.tmp / "outer"
        inside = make_fast_repo(outer)
        subprocess.run(["git", "-C", str(outer), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(outer), "-c", "user.name=t", "-c", "user.email=t@l", "commit", "-q",
                        "--allow-empty", "--no-gpg-sign", "-m", "outer"], check=True)
        self.assertIsNone(agent_fixtures.reviewer_prompt(inside)[1]["revision"],
                          "a fast folder inside another repository has no revision of its own")
        subprocess.run(["git", "-C", str(self.fast), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.fast), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.fast), "-c", "user.name=t", "-c", "user.email=t@l", "commit", "-q",
                        "--no-gpg-sign", "-m", "fast"], check=True)
        info = agent_fixtures.reviewer_prompt(self.fast)[1]
        self.assertRegex(info["revision"], r"^[0-9a-f]{40}$")
        self.assertIs(info["skill_dirty"], False)
        (self.fast / "skills/gate-fast/SKILL.md").write_text(FAST_SKILL_TEXT + "\nAn edit.\n")
        self.assertIs(agent_fixtures.reviewer_prompt(self.fast)[1]["skill_dirty"], True, "an edited prompt says so")

    @unittest.skipUnless((SIBLING / "skills/gate-fast/SKILL.md").is_file(),
                         f"no fast repository at {SIBLING} (set FAST_REPO to measure the real prompt)")
    def test_the_real_fast_prompt_fills_with_and_without_the_candidate_lines(self):
        for extra in (None, CANDIDATES):
            with self.subTest(extra=str(extra)):
                env = fast_env(SIBLING, extra)
                try:
                    text, info, _, _ = self.built("fast-reviewer-refix-works")
                finally:
                    env.stop()
                self.assertNotRegex(text, PLACEHOLDER)
                self.assertIn("Matches the goal", text)
                self.assertEqual(info["skill"], str((SIBLING / "skills/gate-fast/SKILL.md").resolve()))


class FastReviewerHarnessTest(unittest.TestCase):
    """run_one and main for the fast-reviewer fixtures with a stand-in runner: no model, no spending."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name, value in (("WORK", self.tmp / "work"), ("REPO", self.tmp / "repo")):
            patcher = mock.patch.object(agent_fixtures, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        (self.tmp / "work").mkdir()
        frame = self.tmp / "repo/tests/fixtures/agents/fast-reviewer/reviewer-agent.md"
        frame.parent.mkdir(parents=True)
        shutil.copy(FIX / "fast-reviewer/reviewer-agent.md", frame)
        (self.tmp / "repo/agents").mkdir()
        for f in (ROOT / "agents").glob("*.md"):
            shutil.copy(f, self.tmp / "repo/agents" / f.name)
        self.fast = make_fast_repo(self.tmp)
        self.addCleanup(fast_env(self.fast).stop)
        self.calls = []

    def stand_in(self, text, summary=None, seen=None):
        """run_isolated.py replaced by a runner that writes this answer (None: no result file) and summary."""
        real = agent_fixtures.run

        def fake(cmd, **kw):
            if not any(str(c).endswith("run_isolated.py") for c in cmd):
                return real(cmd, **kw)
            self.calls.append(cmd)
            if seen:
                seen(cmd)
            out = Path(cmd[cmd.index("--out") + 1])
            (out / f"{cmd[2]}.summary.json").write_text(json.dumps(summary or {"status": "OK", "tool_uses": 7}))
            if text is not None:
                (out / f"{cmd[2]}.result.md").write_text(text)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return mock.patch.object(agent_fixtures, "run", side_effect=fake)

    def test_a_fast_reviewer_runs_the_filled_prompt_with_its_agent_on_opus_at_xhigh(self):
        name, looked = "fast-reviewer-faked-done", {}

        def seen(cmd):
            looked["pack"] = Path(cmd[cmd.index("--pack") + 1]).read_text()
            looked["agent"] = Path(cmd[cmd.index("--agent-file") + 1])
            looked["agent_text"] = looked["agent"].read_text()
            looked["dir"] = Path(cmd[cmd.index("--dir") + 1])
        spent = "1. **High** - tally/status.py:5 - MONTH_SPENT is hard-coded, so status ignores the ledger."
        with self.stand_in(answer(spent), seen=seen):
            _, _, problems, _, rec = agent_fixtures.run_one(name, FIXTURES[name], 1, False, None)
        cmd = self.calls[0]
        self.assertEqual(cmd[2], "code-verifier")
        self.assertEqual((cmd[cmd.index("--model") + 1], cmd[cmd.index("--effort") + 1]), ("claude-opus-5-5", "xhigh"))
        self.assertNotIn("--render", cmd)
        self.assertIn("CANARY-REVIEW-STATE-3391", cmd)
        self.assertNotRegex(looked["pack"], PLACEHOLDER)
        self.assertIn(f"in {looked['dir']}. Goal: ", looked["pack"])
        self.assertEqual(looked["agent"].parent, self.tmp / "repo/.evidence/fixtures" / name / "run-1")
        self.assertIn(f"sha256 {rec['fast_prompt']['sha256'][:12]}", looked["agent_text"])
        self.assertIn("You did not write the code", looked["agent_text"])
        self.assertEqual(problems, ["not caught: " + list(fx.FAST_FAKED)[1]])
        self.assertEqual((rec["kind"], rec["problem_count"], rec["items"]), ("planted", 1, 2),
                         "items are every planted item, not the ones this answer missed")
        self.assertEqual(rec["fast_prompt"]["plan"], "fast-reviewer/plans/budgets.md")
        saved = json.loads((self.tmp / "repo/.evidence/fixtures" / name / "run-1/fixture-result.json").read_text())
        self.assertEqual(saved["fast_prompt"]["diff_command"], rec["fast_prompt"]["diff_command"])

    def test_no_path_the_reviewer_is_shown_names_the_fixture(self):
        # A fixture's name describes its planted defect ("faked-done", "refix-breaks-other"): the copy's path, which
        # the pack and its diff command show, holds only a random work folder name.
        looked = {}

        def seen(cmd):
            looked["pack"], looked["dir"] = Path(cmd[cmd.index("--pack") + 1]).read_text(), cmd[cmd.index("--dir") + 1]
        for name in FAST:
            with self.subTest(name), self.stand_in(answer(), seen=seen):
                rec = agent_fixtures.run_one(name, FIXTURES[name], 1, False, None)[4]
                work = Path(rec["work"])
                self.assertEqual(work.parent, self.tmp / "work")
                self.assertRegex(work.name, r"^[0-9a-f]{16}$")
                self.assertRegex(Path(looked["dir"]).relative_to(work).as_posix(), r"^copies/[0-9a-f]{16}/review$")
                self.assertTrue(looked["pack"].startswith(f"Review a change you did not write, in {looked['dir']}. "))
                self.assertTrue(rec["fast_prompt"]["diff_command"].startswith(f"git -C {looked['dir']} diff "))
                self.assertNotIn(name, looked["pack"])
                self.assertTrue(work.is_dir(), "a failed run's folder is kept, and the record names it")

    def test_a_flag_names_the_other_side(self):
        with self.stand_in(answer(*TALLY_CATCHES)):
            agent_fixtures.run_one("fast-reviewer-tally-defects", FIXTURES["fast-reviewer-tally-defects"], 1, False, None,
                                   "claude-sonnet-5-5")
            agent_fixtures.run_one("fast-reviewer-tally-defects", FIXTURES["fast-reviewer-tally-defects"], 2, False, "high")
        sonnet, high = self.calls
        self.assertEqual((sonnet[sonnet.index("--model") + 1], sonnet[sonnet.index("--effort") + 1]),
                         ("claude-sonnet-5-5", "xhigh"))
        self.assertEqual((high[high.index("--model") + 1], high[high.index("--effort") + 1]), ("claude-opus-5-5", "high"))

    def test_a_run_without_an_answer_of_its_own_misses_every_item(self):
        spec = FIXTURES["fast-reviewer-tally-defects"]
        with self.stand_in(None):
            rec = agent_fixtures.run_one("fast-reviewer-tally-defects", spec, 1, False, None)[4]
        self.assertEqual(rec["problem_count"], 4, "no answer: every item missed")
        with self.stand_in(None, {"status": "ERROR", "reason": "timeout"}):
            rec = agent_fixtures.run_one("fast-reviewer-tally-defects", spec, 2, False, None)[4]
        self.assertEqual(rec["problem_count"], 5)
        with self.stand_in(answer(*TALLY_CATCHES), {"status": "OK", "escalated": True}):
            rec = agent_fixtures.run_one("fast-reviewer-tally-defects", spec, 3, False, None)[4]
        self.assertEqual((rec["pass"], rec["problem_count"]), (False, 5), "a retried run never rescues the model")
        with self.stand_in(answer(*TALLY_CATCHES)):
            rec = agent_fixtures.run_one("fast-reviewer-tally-defects", spec, 4, False, None)[4]
        self.assertEqual((rec["pass"], rec["problem_count"], rec["items"]), (True, 0, 4))

    def test_a_clean_fixture_passes_on_a_yes_and_fails_on_a_block(self):
        spec = FIXTURES["fast-reviewer-refix-works"]
        yes = "Matches the goal: yes, because each fix holds."
        with self.stand_in(answer("1. low - tally/export.py:12 - csv_line could live in money.py", last=yes)):
            rec = agent_fixtures.run_one("fast-reviewer-refix-works", spec, 1, False, None)[4]
        self.assertEqual((rec["pass"], rec["items"]), (True, 0))
        with self.stand_in(answer("1. medium - tally/archive.py:14 - the archive header", last=yes)):
            rec = agent_fixtures.run_one("fast-reviewer-refix-works", spec, 2, False, None)[4]
        self.assertFalse(rec["pass"])
        self.assertIn("CANARY-REFIX-STATE-6620", self.calls[0])

    def test_a_prompt_that_cannot_be_filled_spends_nothing(self):
        make_fast_repo(self.tmp / "new", FAST_SKILL_TEXT.replace("<Goal>.", "<Goal>. Notes: <notes>."))
        with mock.patch.dict(os.environ, {"FAST_REPO": str(self.tmp / "new/fast")}), self.stand_in(answer()):
            _, _, problems, _, rec = agent_fixtures.run_one("fast-reviewer-tally-defects",
                                                            FIXTURES["fast-reviewer-tally-defects"], 1, False, None)
            code = agent_fixtures.main(["--only", "fast-reviewer", "--runs", "1"])
        self.assertEqual(self.calls, [])
        self.assertIn("<notes>", problems[0])
        self.assertEqual(rec["problem_count"], 5)
        self.assertEqual(code, 1)

    def test_without_a_fast_repository_its_fixtures_are_skipped(self):
        missing = self.tmp / "nowhere"
        with mock.patch.dict(os.environ, {"FAST_REPO": str(missing)}), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out, self.stand_in(answer()):
            code = agent_fixtures.main(["--only", "fast-reviewer", "--runs", "1"])
        self.assertEqual((code, self.calls), (1, []), "nothing measured is not a pass, and nothing was spent")
        for name in FAST:
            self.assertRegex(out.getvalue(), rf"SKIP +{name} +no fast repository at {re.escape(str(missing))}")
        self.assertIn("agent-fixtures: SKIP (nothing ran", out.getvalue())
        self.assertFalse((self.tmp / "repo/.evidence").exists(), "a skipped run records nothing")
        verdict = {"verdict": "ACCEPT-READY", "intent_diff": [], "blocking": []}
        with mock.patch.dict(os.environ, {"FAST_REPO": str(missing)}), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out, self.stand_in("```json\n" + json.dumps(verdict)
                                                                                          + "\n```\n"):
            code = agent_fixtures.main(["--only", "fast-reviewer,gate-judge-clean", "--runs", "1"])
        self.assertEqual((code, len(self.calls)), (0, 1), "the other fixtures still run, and a skip fails nothing")
        self.assertIn(f"1/1 runs passed, {len(FAST)} skipped", out.getvalue())

    def test_the_pooled_line_adds_up_the_planted_trials_the_clean_runs_and_the_dollars(self):
        recs = [{"kind": "planted", "problem_count": 1, "items": 4, "pass": False, "dollars": 0.5},
                {"kind": "planted", "problem_count": 0, "items": 2, "pass": True, "dollars": 0.25},
                {"kind": "clean", "problem_count": 1, "items": 0, "pass": False, "dollars": None},
                {"kind": "clean", "problem_count": 0, "items": 0, "pass": True, "dollars": 0.25}]
        self.assertEqual(agent_fixtures.pooled(recs), "pooled: 1 problem(s) over 6 planted item-trial(s); "
                                                      "1/2 clean run(s) failed; $1.00")


class FastProductTest(unittest.TestCase):
    """The fast-reviewer products as each fixture lays them out: each passes its plan's test command, and the faked
    Done-when items are really faked."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def product(self, name):
        spec = FIXTURES[name]
        dest = Path(tempfile.mkdtemp(dir=self.tmp)) / "project"
        if spec.get("base"):
            shutil.copytree(FIX / spec["base"], dest)
        shutil.copytree(FIX / spec["folder"], dest, dirs_exist_ok=True)
        return dest

    def test_every_product_passes_its_plans_test_command(self):
        for name in FAST:
            with self.subTest(name):
                if FIXTURES[name]["folder"] == "tally-clean" and hasattr(os, "geteuid") and os.geteuid() == 0:
                    self.skipTest("as root a read-only folder takes writes, so tally-clean's own read-only test fails")
                plan = agent_fixtures.plan_sections((FIX / FIXTURES[name]["fast_plan"]).read_text())
                command = agent_fixtures.plan_commands(plan["Commands"])["test"]
                r = subprocess.run(command, shell=True, cwd=self.product(name), capture_output=True, text=True,
                                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
                self.assertEqual(r.returncode, 0, r.stderr[-800:])

    def test_the_faked_status_shows_the_plans_example_and_nothing_else(self):
        project = self.product("fast-reviewer-faked-done")
        folder = Path(tempfile.mkdtemp(dir=self.tmp))
        tally = lambda *a: subprocess.run([sys.executable, "-m", "tally", *a], cwd=folder, capture_output=True, text=True,
                                          env={**os.environ, "PYTHONPATH": str(project), "PYTHONDONTWRITEBYTECODE": "1"})
        for args in (("add", "food", "5", "--on", "2026-09-03"), ("add", "travel", "40", "--on", "2026-09-10"),
                     ("add", "food", "7.50", "--on", "2026-09-20"), ("budget", "food", "100"), ("budget", "travel", "30")):
            self.assertEqual(tally(*args).returncode, 0, args)
        self.assertEqual(tally("status", "2026-09").stdout.splitlines(), ["food 12.50 of 100.00", "travel 40.00 of 30.00"],
                         "the plan's example without its over mark: the over check is a stub")
        tally("add", "food", "99", "--on", "2026-11-02")
        self.assertEqual(tally("status", "2026-11").stdout.splitlines()[0], "food 0.00 of 100.00",
                         "a month the table does not hold shows nothing spent: the spending is hard-coded")
        self.assertEqual(tally("total", "food").stdout.strip(), "Total food: 111.50", "the ledger holds the expense")


if __name__ == "__main__":
    unittest.main()
