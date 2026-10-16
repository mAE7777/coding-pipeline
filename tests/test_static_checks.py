"""Tests for static_checks.py on small synthetic trees: the always-loaded budget, the craft budget, routes against
agents, agent frontmatter, model IDs the pipeline never routes to, and craft provenance."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # importing the checker and the runner leaves no __pycache__ in the repository
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/_shared/scripts"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(SCRIPTS))
import static_checks as sc  # noqa: E402
import run_isolated  # noqa: E402

# Built from parts, so this file never holds the IDs the repository-wide check refuses.
F, M = "fa" + "ble", "myth" + "os"


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def skill(name, desc, extra=""):
    return f'---\nname: {name}\ndescription: "{desc}"\n{extra}---\n\n# /{name}\n\nThe body.\n'


def agent(name, desc, tools, extra=""):
    return f'---\nname: {name}\ndescription: "{desc}"\ntools: {", ".join(tools)}\n{extra}---\n\nYou check things.\n'


def tree(root):
    """A tree every check passes: the real routing table and models.py, a runner holding the real roles, one agent
    file per role, a small craft layer whose manifest matches it, and one skill."""
    put(root / "skills/alpha/SKILL.md", skill("alpha", "Do alpha things. Use for /alpha."))
    shared = root / "skills/_shared"
    (shared / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "skills/_shared/models.json", shared / "models.json")
    for name in ("models.py", "craft_sync.py"):
        shutil.copy(SCRIPTS / name, shared / "scripts" / name)
    put(shared / "scripts/run_isolated.py", f"ROLES = {json.dumps(run_isolated.ROLES)}\n")
    for role, tools in run_isolated.ROLES.items():
        if role not in sc.NO_AGENT_FILE:
            put(root / "agents" / f"{role}.md", agent(role, "Internal checker. Not for direct use.", tools))
    craft = root / "skills/craft"
    put(craft / "SKILL.md", skill("craft", "Code craft on demand: /craft review."))
    put(craft / "index.md", "# Craft index\n")
    write_manifest(craft)
    return root


def write_manifest(craft):
    index = (craft / "index.md").read_bytes()
    put(craft / "UPSTREAM.json", json.dumps({
        "upstream": {"name": "pstack", "commit": "c0ffee"}, "own": ["SKILL.md", "UPSTREAM.json"],
        "files": [{"local": "index.md", "upstream": "skills/index.md", "commit": "c0ffee",
                   "sha256": hashlib.sha256(index).hexdigest(), "local_edit": None}]}))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = tree(Path(self.tmp.name))
        sc.results.clear()

    def tearDown(self):
        self.tmp.cleanup()
        sc.results.clear()

    def fails(self):
        return [f"{where}  {detail}" for status, where, detail in sc.results if status == "FAIL"]

    def assertFails(self, *words):
        found = self.fails()
        for w in words:
            self.assertTrue(any(w in f for f in found), f"no FAIL with {w!r} in {found}")

    def check(self, fn):
        sc.results.clear()
        return fn(self.root)


class WholeRunTest(Base):
    def test_a_clean_tree_passes_and_prints_its_total(self):
        out = subprocess.run([sys.executable, "-B", str(ROOT / "tests/static_checks.py"), str(self.root)],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("INFO   always-loaded  skill and agent descriptions total", out.stdout)
        self.assertIn("static-checks: PASS", out.stdout)
        self.assertIn(f"of {sc.ALWAYS_LOADED_BUDGET} bytes", out.stdout.splitlines()[-1])

    def test_the_repository_passes(self):
        out = subprocess.run([sys.executable, "-B", str(ROOT / "tests/static_checks.py"), str(ROOT)],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout[-2000:] + out.stderr)

    def test_help_and_bad_usage(self):
        out = subprocess.run([sys.executable, "-B", str(ROOT / "tests/static_checks.py"), "--help"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        self.assertIn("static_checks.py", out.stdout)
        out = subprocess.run([sys.executable, "-B", str(ROOT / "tests/static_checks.py"), str(self.root / "nowhere")],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)


class AlwaysLoadedTest(Base):
    def test_each_description_has_a_limit_and_the_total_has_a_budget(self):
        base = self.check(sc.check_always_loaded)
        self.assertEqual(self.fails(), [])
        self.assertTrue(any(s == "INFO" and str(base) in d for s, _, d in sc.results))
        put(self.root / "skills/alpha/SKILL.md", skill("alpha", "x" * 451))
        self.check(sc.check_always_loaded)
        self.assertFails("skills/alpha/SKILL.md  description is 451 characters (limit 450")
        put(self.root / "skills/alpha/SKILL.md", skill("alpha", "x" * 450))
        self.assertEqual(self.check(sc.check_always_loaded), base - len("Do alpha things. Use for /alpha.") + 450)
        self.assertEqual(self.fails(), [])
        put(self.root / "skills/alpha/SKILL.md", skill("alpha", "x" * 400, "when_to_use: \"" + "y" * 60 + "\"\n"))
        self.check(sc.check_always_loaded)
        self.assertFails("description is 460 characters")

    def test_a_skill_only_the_owner_types_is_left_out(self):
        base = self.check(sc.check_always_loaded)
        put(self.root / "skills/alpha/SKILL.md", skill("alpha", "x" * 900, "disable-model-invocation: true\n"))
        total = self.check(sc.check_always_loaded)
        self.assertEqual(self.fails(), [], "no listing entry, so no listing limit")
        self.assertEqual(total, base - len("Do alpha things. Use for /alpha."))

    def test_an_agent_description_is_one_short_line(self):
        path = self.root / "agents/gate-judge.md"
        tools = run_isolated.ROLES["gate-judge"]
        put(path, agent("gate-judge", "x" * 121, tools))
        self.check(sc.check_always_loaded)
        self.assertFails("agents/gate-judge.md  description is 121 characters (limit 120")
        put(path, f"---\nname: gate-judge\ndescription: >\n  Judges one gate.\n  Not for direct use.\ntools: "
                  f"{', '.join(tools)}\n---\nbody\n")
        self.check(sc.check_always_loaded)
        self.assertFails("agents/gate-judge.md  description is not on one line")
        put(path, f"---\nname: gate-judge\ndescription: Judges one gate,\n  not for direct use.\ntools: "
                  f"{', '.join(tools)}\n---\nbody\n")
        self.check(sc.check_always_loaded)
        self.assertFails("description is not on one line")
        put(path, f"---\nname: gate-judge\ndescription: Internal checker run by the gate: judges. Not for direct "
                  f"use.\ntools: {', '.join(tools)}\n---\nbody\n")
        self.check(sc.check_always_loaded)
        self.assertFails("description: an unquoted value holding ': ' is not valid YAML")

    def test_the_total_over_budget_fails(self):
        for i in range(sc.ALWAYS_LOADED_BUDGET // 440 + 1):
            put(self.root / f"skills/s{i}/SKILL.md", skill(f"s{i}", "x" * 440))
        total = self.check(sc.check_always_loaded)
        self.assertGreater(total, sc.ALWAYS_LOADED_BUDGET)
        self.assertFails(f"always-loaded  skill and agent descriptions total {total} bytes (budget "
                         f"{sc.ALWAYS_LOADED_BUDGET})")
        self.assertFalse(any(s == "INFO" for s, _, _ in sc.results))


class CraftBudgetTest(Base):
    def test_the_index_and_the_skill_have_byte_budgets(self):
        put(self.root / "skills/craft/index.md", "x" * 10240)
        put(self.root / "skills/craft/SKILL.md", "x" * 6144)
        self.check(sc.check_craft_budget)
        self.assertEqual(self.fails(), [])
        put(self.root / "skills/craft/index.md", "x" * 10241)
        put(self.root / "skills/craft/SKILL.md", "x" * 6145)
        self.check(sc.check_craft_budget)
        self.assertFails("skills/craft/index.md  10241 bytes (budget 10240", "skills/craft/SKILL.md  6145 bytes "
                                                                              "(budget 6144")
        (self.root / "skills/craft/index.md").unlink()
        self.check(sc.check_craft_budget)
        self.assertFails("skills/craft/index.md  missing")


class RoutesAndAgentsTest(Base):
    def test_a_matching_tree_passes(self):
        self.check(sc.check_routes_and_agents)
        self.assertEqual(self.fails(), [])

    def test_a_route_without_its_agent_fails(self):
        (self.root / "agents/gate-judge.md").unlink()
        self.check(sc.check_routes_and_agents)
        self.assertFails("agents/gate-judge.md  missing: checker route gate-judge runs this agent")

    def test_an_agent_no_script_runs_fails(self):
        put(self.root / "agents/stranger.md", agent("stranger", "Internal checker. Not for direct use.", ["Read"]))
        self.check(sc.check_routes_and_agents)
        self.assertFails("agents/stranger.md  role stranger is not in run_isolated.ROLES",
                         "agents/stranger.md  no checker route for stranger")

    def test_a_role_without_a_route_fails(self):
        table = json.loads((self.root / "skills/_shared/models.json").read_text())
        del table["routes"]["claim-verifier"]
        put(self.root / "skills/_shared/models.json", json.dumps(table))
        self.check(sc.check_routes_and_agents)
        self.assertFails("agents/claim-verifier.md  no checker route for claim-verifier",
                         "models.py check: FAIL")

    def test_a_builder_side_route_has_no_agent_file(self):
        put(self.root / "agents/explorer.md", agent("explorer", "Helper.", ["Read"]))
        self.check(sc.check_routes_and_agents)
        self.assertFails("agents/explorer.md  route explorer is builder-side (model session)")

    def test_the_table_is_checked_by_models_py(self):
        table = json.loads((self.root / "skills/_shared/models.json").read_text())
        table["routes"]["gate-judge"]["model"] = f"claude-{F}-5"
        put(self.root / "skills/_shared/models.json", json.dumps(table))
        self.check(sc.check_routes_and_agents)
        self.assertFails("skills/_shared/models.json  models.py check: FAIL route gate-judge")

    def test_a_route_whose_role_the_runner_lacks_fails(self):
        roles = {k: v for k, v in run_isolated.ROLES.items() if k != "change-reviewer"}
        put(self.root / "skills/_shared/scripts/run_isolated.py", f"ROLES = {json.dumps(roles)}\n")
        self.check(sc.check_routes_and_agents)
        self.assertFails("checker route change-reviewer: role change-reviewer is not in run_isolated.ROLES",
                         "agents/change-reviewer.md  role change-reviewer is not in run_isolated.ROLES")

    def test_an_unreadable_runner_is_named(self):
        put(self.root / "skills/_shared/scripts/run_isolated.py", "ROLES = (\n")
        self.check(sc.check_routes_and_agents)
        self.assertFails("cannot read models.CHECKER_ROUTES and run_isolated.ROLES", "SyntaxError")

    def test_agent_frontmatter_holds_no_model_or_effort_and_the_runners_tools(self):
        tools = run_isolated.ROLES["cold-reader"]
        put(self.root / "agents/cold-reader.md", agent("cold-reader", "Internal checker.", tools,
                                                       "model: inherit\neffort: xhigh\n"))
        self.check(sc.check_routes_and_agents)
        self.assertFails("agents/cold-reader.md  frontmatter sets model", "agents/cold-reader.md  frontmatter sets "
                                                                          "effort")
        put(self.root / "agents/cold-reader.md", agent("cold-reader", "Internal checker.", list(reversed(tools))))
        self.check(sc.check_routes_and_agents)
        self.assertEqual(self.fails(), [], "the order of the tools does not matter")
        put(self.root / "agents/cold-reader.md", agent("cold-reader", "Internal checker.", tools + ["Bash"]))
        self.check(sc.check_routes_and_agents)
        self.assertFails("agents/cold-reader.md  tools (Read, Grep, Glob, Bash) differ from run_isolated.ROLES")

    def test_missing_routing_files_are_named(self):
        (self.root / "skills/_shared/models.json").unlink()
        self.check(sc.check_routes_and_agents)
        self.assertFails("skills/_shared/models.json  missing")


class ForbiddenModelTest(Base):
    def test_ids_fields_and_flags_fail_anywhere_published_tests_included(self):
        cases = {"skills/alpha/references/routing.md": f"Run the judge with model: claude-{F}-5 for speed.\n",
                 "skills/_shared/routes.json": '{"model": "' + M.capitalize() + '"}\n',
                 "hooks/run.sh": f"claude -p --model {F}-preview\n",
                 "tests/test_other.py": f'MODEL = "us.anthropic.claude-{M}-1"\n',
                 "README.md": f"Use {F.capitalize()}-5 for drafts.\n"}
        for rel, text in cases.items():
            put(self.root / rel, text)
        self.check(sc.check_forbidden_models)
        for rel in cases:
            self.assertFails(f"{rel}:1  names a {F.capitalize()} or {M.capitalize()} model")
        self.assertEqual(len(self.fails()), len(cases))

    def test_prose_and_the_files_that_reject_them_by_name_pass(self):
        exempt = ["skills/_shared/scripts/models.py", "tests/test_models.py", "tests/test_run_isolated.py",
                  "tests/test_spend.py", "tests/static_checks.py", "docs/plan.md", "docs/routing/model-routing.md"]
        for rel in exempt:
            put(self.root / rel, f'BAD = "claude-{F}-5"\n')
        for rel in (".claude/worktrees/x/notes.md", "private/notes.md", "tests/fixtures/agents/x/notes.md"):
            put(self.root / rel, f"claude-{F}-5\n")
        put(self.root / "skills/alpha/references/story.md", f"A {F} about owls; the {M} of the founders.\n")
        self.check(sc.check_forbidden_models)
        self.assertEqual(self.fails(), [])
        self.assertTrue(set(exempt[:5]) <= {e for e in sc.FORBIDDEN_MODEL_EXEMPT}, "one constant holds them")


class CraftProvenanceTest(Base):
    def test_a_vendored_file_that_drifted_or_an_unlisted_one_fails(self):
        self.check(sc.check_craft_provenance)
        self.assertEqual(self.fails(), [])
        put(self.root / "skills/craft/index.md", "# Craft index, edited\n")
        self.check(sc.check_craft_provenance)
        self.assertFails("skills/craft  craft_sync.py verify", "index.md")
        write_manifest(self.root / "skills/craft")
        put(self.root / "skills/craft/extra.md", "not listed\n")
        self.check(sc.check_craft_provenance)
        self.assertFails("extra.md")


if __name__ == "__main__":
    unittest.main()
