"""Unit tests for models.py: the routing table, the personal override, validation, and route derivation."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/_shared/scripts/models.py"
spec = importlib.util.spec_from_file_location("models", SCRIPT)
models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(models)

CHECKERS = ("code-verifier.review", "code-verifier.reverify", "code-verifier.demo", "loyal-evaluator", "gate-judge",
            "cold-reader.documents", "cold-reader.reread", "cold-reader.understanding", "cold-reader.extract",
            "cold-reader.fidelity", "cold-reader.refidelity", "claim-verifier", "change-reviewer")
BUILDER = ("explorer", "delegate", "architect-runner", "explain", "scout-map")


class HomeCase(unittest.TestCase):
    """Each test has its own HOME, so the owner's real override file is never read or written."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        (self.home / ".claude").mkdir(parents=True)
        env = {k: v for k, v in os.environ.items() if k != "PIPELINE_MODELS_IGNORE_OVERRIDE"}
        env["HOME"] = str(self.home)
        self.patch = mock.patch.dict(os.environ, env, clear=True)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def override(self, routes, **extra):
        (self.home / ".claude/.pipeline-models.json").write_text(json.dumps({"routes": routes, **extra}))

    def tree(self, table):
        root = Path(self.tmp.name) / "tree"
        (root / "skills/_shared").mkdir(parents=True, exist_ok=True)
        (root / "skills/_shared/models.json").write_text(json.dumps(table))
        return root

    def cli(self, *args, env=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                              env={**os.environ, **(env or {})}, timeout=60)


class TableTest(HomeCase):
    def test_the_repository_table_keeps_todays_behavior(self):
        table, over, path, opath = models.load()
        self.assertEqual(path, ROOT / "skills/_shared/models.json")
        self.assertIsNone(over)
        self.assertEqual(table["allowed_models"], ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"])
        self.assertEqual(table["escalate"], {"model": "claude-opus-5-5", "effort": "xhigh"})
        for route in CHECKERS + ("probe",):
            r = models.resolve(route)
            self.assertEqual((r["model"], r["effort"], r["source"]), ("default", "xhigh", "repo"), route)
        for route in BUILDER:
            r = models.resolve(route)
            self.assertEqual((r["model"], r["effort"]), ("session", "inherit"), route)
        self.assertEqual(set(table["routes"]), set(CHECKERS + BUILDER + ("probe",)))

    def test_every_route_run_isolated_derives_is_in_the_table(self):
        table = models.load()[0]
        derived = {models.route_for(role, mode, prev, inputs)
                   for role in ("code-verifier", "cold-reader", "loyal-evaluator", "gate-judge", "claim-verifier",
                                "change-reviewer", "probe")
                   for mode in (None, "demo", "reverify", "extract", "fidelity")
                   for prev in (False, True) for inputs in ([], ["understanding"])}
        self.assertEqual(derived - set(table["routes"]), set())
        self.assertEqual(set(models.CHECKER_ROUTES) - set(table["routes"]), set())

    def test_a_tree_root_reads_that_trees_table(self):
        table = json.loads((ROOT / "skills/_shared/models.json").read_text())
        table["routes"]["gate-judge"] = {"model": "claude-opus-5-5", "effort": "high"}
        root = self.tree(table)
        r = models.resolve("gate-judge", root=root)
        self.assertEqual((r["model"], r["effort"], r["table"]), ("claude-opus-5-5", "high",
                                                                 str(root / "skills/_shared/models.json")))

    def test_a_missing_table_is_named(self):
        with self.assertRaises(models.ModelsError) as cm:
            models.resolve("gate-judge", root=Path(self.tmp.name) / "nowhere")
        self.assertIn("is missing", str(cm.exception))


class OverrideTest(HomeCase):
    def test_a_partial_override_changes_only_what_it_names(self):
        self.override({"gate-judge": {"effort": "high"}, "code-verifier.demo": {"model": "claude-sonnet-5-5",
                                                                               "effort": "high"}})
        judge = models.resolve("gate-judge")
        self.assertEqual((judge["model"], judge["effort"], judge["source"]), ("default", "high", "override"))
        self.assertEqual(judge["override_fields"], ["effort"])
        demo = models.resolve("code-verifier.demo")
        self.assertEqual((demo["model"], demo["effort"]), ("claude-sonnet-5-5", "high"))
        review = models.resolve("code-verifier.review")
        self.assertEqual((review["model"], review["source"]), ("default", "repo"), "an unnamed route keeps the table")

    def test_the_ignore_variable_measures_the_repository_table(self):
        self.override({"gate-judge": {"model": "claude-opus-5-5", "effort": "high"}})
        with mock.patch.dict(os.environ, {"PIPELINE_MODELS_IGNORE_OVERRIDE": "1"}):
            r = models.resolve("gate-judge")
        self.assertEqual((r["model"], r["effort"], r["source"]), ("default", "xhigh", "repo"))
        self.assertEqual(models.resolve("gate-judge")["source"], "override", "without the variable it applies")
        self.assertEqual(models.resolve("gate-judge", ignore_override=True)["source"], "repo")

    def test_choose_puts_flags_over_the_route_and_names_each_source(self):
        self.override({"cold-reader.extract": {"model": "claude-sonnet-5-5"}})
        c = models.choose("cold-reader.extract")
        self.assertEqual((c["model"], c["model_source"], c["effort"], c["effort_source"]),
                         ("claude-sonnet-5-5", "override", "xhigh", "repo"))
        c = models.choose("cold-reader.extract", model="claude-opus-5-5", effort="high")
        self.assertEqual((c["model"], c["model_source"], c["effort"], c["effort_source"]),
                         ("claude-opus-5-5", "flag", "high", "flag"))


class ValidationTest(HomeCase):
    def assertRefused(self, route, *words):
        with self.assertRaises(models.ModelsError) as cm:
            models.resolve(route)
        for w in words:
            self.assertIn(w, str(cm.exception))
        return str(cm.exception)

    def test_fable_and_mythos_are_refused_naming_the_route(self):
        for model in ("claude-fable-5", "Fable", "claude-mythos-1"):
            self.override({"gate-judge": {"model": model}})
            self.assertRefused("gate-judge", "route gate-judge", "Fable or Mythos", model)
        table = json.loads((ROOT / "skills/_shared/models.json").read_text())
        table["allowed_models"].append("claude-fable-5")
        with self.assertRaises(models.ModelsError) as cm:
            models.resolve("gate-judge", root=self.tree(table), ignore_override=True)
        self.assertIn("never allowed", str(cm.exception))

    def test_a_model_outside_the_allowed_list_is_an_error_never_a_fallback(self):
        for model in ("claude-opus-4-1", "opus", "sonnet[1m]"):
            self.override({"cold-reader.extract": {"model": model}})
            self.assertRefused("cold-reader.extract", "route cold-reader.extract", "not allowed")
        msg = self.assertRefused("gate-judge", "route cold-reader.extract")
        self.assertIn(".pipeline-models.json", msg, "every lookup fails until the file is fixed, naming it")

    def test_an_alias_cannot_enter_the_allowed_list(self):
        table = json.loads((ROOT / "skills/_shared/models.json").read_text())
        table["allowed_models"].append("opus")
        with self.assertRaises(models.ModelsError) as cm:
            models.resolve("gate-judge", root=self.tree(table), ignore_override=True)
        self.assertIn("not a full model ID", str(cm.exception))

    def test_unknown_effort_route_and_field_are_errors(self):
        self.override({"gate-judge": {"effort": "extreme"}})
        self.assertRefused("gate-judge", "route gate-judge", "effort 'extreme'")
        self.override({"gate-jduge": {"effort": "high"}})
        self.assertRefused("gate-judge", "route gate-jduge", "unknown route")
        self.override({"gate-judge": {"modle": "claude-opus-5-5"}})
        self.assertRefused("gate-judge", "unknown field(s) modle")
        (self.home / ".claude/.pipeline-models.json").unlink()
        self.assertRefused("no-such-route", "unknown route 'no-such-route'")

    def test_a_malformed_override_file_is_named(self):
        (self.home / ".claude/.pipeline-models.json").write_text("{not json")
        self.assertRefused("gate-judge", "personal override file", "cannot be read as JSON")

    def test_builder_side_values_are_refused_for_an_isolated_run(self):
        with self.assertRaises(models.ModelsError) as cm:
            models.choose("explorer")
        self.assertIn("builder-side", str(cm.exception))
        with self.assertRaises(models.ModelsError):
            models.choose("gate-judge", effort="inherit")
        with self.assertRaises(models.ModelsError) as cm:
            models.choose("gate-judge", model="claude-fable-5")
        self.assertIn("the --model flag", str(cm.exception))


class DerivationTest(unittest.TestCase):
    def test_route_for(self):
        rows = [
            (("cold-reader",), {}, "cold-reader.documents"),
            (("cold-reader",), {"previous": True}, "cold-reader.reread"),
            (("cold-reader",), {"mode": "extract"}, "cold-reader.extract"),
            (("cold-reader",), {"mode": "fidelity"}, "cold-reader.fidelity"),
            (("cold-reader",), {"mode": "fidelity", "previous": True}, "cold-reader.refidelity"),
            (("cold-reader",), {"inputs": ["understanding"]}, "cold-reader.understanding"),
            (("code-verifier",), {}, "code-verifier.review"),
            (("code-verifier",), {"mode": "review"}, "code-verifier.review"),
            (("code-verifier",), {"mode": "demo"}, "code-verifier.demo"),
            (("code-verifier",), {"mode": "reverify"}, "code-verifier.reverify"),
            (("loyal-evaluator",), {"previous": True}, "loyal-evaluator"),
            (("gate-judge",), {}, "gate-judge"),
            (("claim-verifier",), {"inputs": ["claims.md"]}, "claim-verifier"),
            (("change-reviewer",), {}, "change-reviewer"),
            (("probe",), {}, "probe"),
        ]
        for args, kw, want in rows:
            self.assertEqual(models.route_for(*args, **kw), want, (args, kw))

    def test_section_names_keep_the_mode_and_its_earlier_name(self):
        self.assertEqual(models.section_names("cold-reader.reread"), {"reread", "documents"})
        self.assertEqual(models.section_names("cold-reader.refidelity"), {"refidelity", "fidelity"})
        self.assertEqual(models.section_names("code-verifier.reverify"), {"reverify", "review"})
        self.assertEqual(models.section_names("code-verifier.demo"), {"demo"})
        self.assertEqual(models.section_names("gate-judge"), set())

    def test_escalation(self):
        esc = {"model": "claude-opus-5-5", "effort": "xhigh"}
        self.assertIsNone(models.escalation("default", "xhigh", esc), "today's setting is not moved")
        self.assertIsNone(models.escalation("claude-opus-5-5", "xhigh", esc))
        self.assertIsNone(models.escalation("claude-opus-5-5", "max", esc))
        self.assertIn("claude-sonnet-5-5 is not claude-opus-5-5", models.escalation("claude-sonnet-5-5", "xhigh", esc))
        self.assertIn("effort high is below xhigh", models.escalation("claude-opus-5-5", "high", esc))
        self.assertIn("effort medium is below xhigh", models.escalation("default", "medium", esc))


class CliTest(HomeCase):
    def test_check_passes_on_the_repository_and_names_every_bad_entry(self):
        out = self.cli("check")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("models: OK", out.stdout)
        bad = Path(self.tmp.name) / "bad.json"
        table = json.loads((ROOT / "skills/_shared/models.json").read_text())
        table["routes"]["gate-judge"]["model"] = "claude-fable-5"
        table["routes"]["claim-verifier"]["effort"] = "huge"
        del table["routes"]["cold-reader.extract"]
        bad.write_text(json.dumps(table))
        out = self.cli("check", str(bad))
        self.assertEqual(out.returncode, 1)
        for words in ("route gate-judge", "Fable or Mythos", "route claim-verifier", "cold-reader.extract is derived"):
            self.assertIn(words, out.stdout)

    def test_check_reads_the_override_unless_ignored(self):
        self.override({"gate-judge": {"model": "claude-opus-9-9"}})
        out = self.cli("check")
        self.assertEqual(out.returncode, 1)
        self.assertIn("route gate-judge", out.stdout)
        out = self.cli("check", env={"PIPELINE_MODELS_IGNORE_OVERRIDE": "1"})
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("override ignored", out.stdout)
        out = self.cli("check", str(self.home / ".claude/.pipeline-models.json"))
        self.assertEqual(out.returncode, 1, "an override file checked on its own, against the table")

    def test_resolve_and_list(self):
        self.override({"gate-judge": {"effort": "high"}})
        out = self.cli("resolve", "gate-judge", "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        r = json.loads(out.stdout)
        self.assertEqual((r["model"], r["effort"], r["source"]), ("default", "high", "override"))
        out = self.cli("resolve", "gate-judge")
        self.assertIn("gate-judge: model default", out.stdout)
        self.assertIn("personal override (effort)", out.stdout)
        out = self.cli("list", "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        listed = json.loads(out.stdout)
        self.assertEqual(listed["routes"]["gate-judge"]["effort"], "high")
        self.assertEqual(len(listed["routes"]), 19)
        out = self.cli("resolve", "no-such-route")
        self.assertEqual(out.returncode, 1)
        self.assertIn("unknown route", out.stderr)

    def test_usage(self):
        for args in ([], ["resolve"], ["frobnicate"], ["list", "x"]):
            self.assertEqual(self.cli(*args).returncode, 2, args)
        for args in (["--help"], ["-h"]):
            out = self.cli(*args)
            self.assertEqual(out.returncode, 0)
            self.assertIn("models.py", out.stdout)


if __name__ == "__main__":
    unittest.main()
