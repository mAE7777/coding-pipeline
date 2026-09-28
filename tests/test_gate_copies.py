"""Tests for gate_copies.py."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GC = ROOT / "skills/_shared/scripts/gate_copies.py"
sys.path.insert(0, str(ROOT / "skills/_shared/scripts"))
spec = importlib.util.spec_from_file_location("gate_copies", GC)
gc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gc)

AGENTS = """# Project map
Code in app/, help pages in content/.

## Commands
install: pip install -r requirements.txt
run: python3 -m app
test: python3 -m unittest

## Conventions
This app exists so that families never lose a shared grocery list.
"""
GATE = """# Gate settings
Intent-bearing paths: design/directive.md, notes/
- vision/
Blind copy keeps: content/
Gate env files: .env.test
"""
INTENT = """# Intent
## Goal
Families never lose a shared grocery list between two phones.
## Must not lose
- L-01 Deleting a list deletes it on every phone that shares it
"""


def build(d, gate_in_agents=False):
    root = Path(d) / "proj"
    files = {
        "app/__init__.py": "",
        "app/__main__.py": "print('lists')\n",
        "app/copy.py": "BANNER = 'Families never lose a shared grocery list between phones'\n",
        "README.md": "Families never lose a shared grocery list.\n",
        "AGENTS.md": AGENTS + ("\n" + GATE if gate_in_agents else ""),
        "CLAUDE.md": "@AGENTS.md\n",
        "docs/project/intent.md": INTENT,
        "docs/project/state.md": "builder notes: the delete sync is hacky\n",
        "docs/guide/usage.md": "Run python3 -m app\n",
        "content/help.md": "Tap a list to open it.\n",
        "truth/narrative-lock.md": "lock\n",
        "design/directive.md": "the directive\n",
        "notes/idea.md": "idea\n",
        "vision/v.md": "vision\n",
        "old/intent-anchor.md": "anchor\n",
        "old/slices.md": "slices\n",
        "tests/test_app.py": "# families never lose a shared grocery list\n",
        "app/store.test.js": "test('x', () => {})\n",
        "requirements.organic.json": "{}\n",
        "requirements.txt": "requests\n",
        "package.json": json.dumps({"name": "lists", "description": "Families never lose a shared grocery list"}),
        "pyproject.toml": '[project]\nname = "lists"\ndescription = "Shared grocery lists that never get lost"\n',
        ".env": "SECRET=1\n",
        ".env.test": "TEST_KEY=abc\n",
        ".env.example": "SECRET=\n",
        "node_modules/pkg/index.js": "module.exports = 1\n",
        ".evidence/log.txt": "log\n",
        "dist/bundle.js": "stale\n",
        "spec/openapi.py": "ROUTES = ['/lists']\n",
        "e2e/flow.spec.ts": "describe('flow', () => { it('works', () => expect(1).toBe(1)) })\n",
        "src/lib.rs": "pub fn add(a: i32) -> i32 { a + 1 }\n#[cfg(test)]\nmod tests {\n    #[test]\n"
                      "    fn deleting_a_list_removes_it_everywhere() { assert_eq!(1, 1); }\n}\n",
    }
    if not gate_in_agents:
        files["docs/project/gate.md"] = GATE
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    bindir = root / "node_modules/.bin"
    bindir.mkdir(parents=True)
    (bindir / "tool").write_text(f"#!/bin/sh\nexec node {root}/node_modules/pkg/index.js\n")
    os.symlink(str(root / "node_modules/pkg/index.js"), bindir / "abs-link")
    site = root / ".venv/lib/python3.12/site-packages"
    site.mkdir(parents=True)
    (site / "__editable___lists_0_1_finder.py").write_text(f"MAPPING = {{'lists': '{root}/app'}}\n")
    return root


def make(root, dest, milestone="M1"):
    out = subprocess.run([sys.executable, str(GC), "make", str(root), "--dest", str(dest), "--milestone", milestone],
                         capture_output=True, text=True)
    info = json.loads(out.stdout) if out.stdout.strip().startswith("{") else {"stderr": out.stderr}
    return out.returncode, info


class GateCopiesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = build(self.tmp.name)
        self.dest = Path(self.tmp.name) / "copies"

    def tearDown(self):
        self.tmp.cleanup()

    def test_blind_copy_has_no_intent(self):
        code, info = make(self.root, self.dest)
        self.assertEqual(code, 0, json.dumps(info, indent=1))
        blind = Path(info["blind"]["path"])
        for gone in ("docs/project", "truth", "README.md", "design/directive.md", "notes", "vision",
                     "old/intent-anchor.md", "old/slices.md", "tests", "app/store.test.js", "e2e",
                     "requirements.organic.json", ".git", "docs/guide/usage.md"):
            self.assertFalse((blind / gone).exists(), gone)
        self.assertTrue((blind / "content/help.md").exists(), "declared product content stays")
        self.assertTrue((blind / "requirements.txt").exists(), "dependency lists stay")
        self.assertTrue((blind / "spec/openapi.py").exists(), "a product folder named spec stays")
        self.assertEqual(json.loads((blind / "package.json").read_text())["description"], "")
        self.assertIn('description = ""', (blind / "pyproject.toml").read_text())
        self.assertNotIn("deleting_a_list", (blind / "src/lib.rs").read_text(), "Rust inline tests stripped")
        self.assertIn("pub fn add", (blind / "src/lib.rs").read_text())
        agents = (blind / "AGENTS.md").read_text()
        self.assertIn("test: python3 -m unittest", agents)
        self.assertNotIn("grocery", agents, "only command lines survive")
        self.assertNotIn("Project map", agents)

    def test_review_copy_holds_the_product_not_the_builder_record(self):
        code, info = make(self.root, self.dest)
        review = Path(info["review"]["path"])
        for kept in ("README.md", "AGENTS.md", "app/__main__.py", "tests/test_app.py", "e2e/flow.spec.ts"):
            self.assertTrue((review / kept).exists(), kept)
        for gone in ("docs/project/state.md", "docs/project/intent.md", ".evidence", "dist"):
            self.assertFalse((review / gone).exists(), gone)
        self.assertEqual(info["review"]["changed_since_fingerprint"], [])

    def test_random_base_and_manifest_outside_the_copies(self):
        code, info = make(self.root, self.dest)
        base = Path(info["base"])
        self.assertNotIn("proj", base.name, "the copy path does not name the project")
        self.assertEqual(len(base.name), 16)
        self.assertTrue((base / "manifest.json").exists())
        self.assertFalse((base / "review/manifest.json").exists())
        self.assertEqual(oct(base.stat().st_mode & 0o777), "0o700")

    def test_secrets_build_output_and_evidence_excluded(self):
        code, info = make(self.root, self.dest)
        for name in ("review", "blind"):
            copy = Path(info[name]["path"])
            self.assertFalse((copy / ".env").exists())
            self.assertTrue((copy / ".env.test").exists(), "listed gate env file kept")
            self.assertTrue((copy / ".env.example").exists())
            self.assertFalse((copy / ".evidence").exists())
            self.assertFalse((copy / "dist").exists())
            self.assertTrue((copy / "node_modules/pkg/index.js").exists(), "dependency folders come whole")

    def test_absolute_references_rewritten_into_the_copy(self):
        code, info = make(self.root, self.dest)
        for name in ("review", "blind"):
            copy = Path(info[name]["path"])
            self.assertNotIn(str(self.root), (copy / "node_modules/.bin/tool").read_text())
            self.assertTrue(os.readlink(copy / "node_modules/.bin/abs-link").startswith(str(copy)))
            finder = copy / ".venv/lib/python3.12/site-packages/__editable___lists_0_1_finder.py"
            self.assertIn(str(copy), finder.read_text(), "setuptools editable finder rewritten")
            self.assertEqual(info[name]["unresolved_references"], [])

    def test_probe_fails_when_a_reference_cannot_be_rewritten(self):
        shim = self.root / "node_modules/.bin/tool"
        shim.chmod(0o444)
        try:
            code, info = make(self.root, self.dest)
            self.assertEqual(code, 1, json.dumps(info, indent=1))
            self.assertIn("node_modules/.bin/tool", info["review"]["unresolved_references"])
        finally:
            shim.chmod(0o644)

    def test_leak_scan(self):
        (self.root / "config").mkdir()
        (self.root / "config/spec.yaml").write_text("goal: families never lose a shared grocery list between two phones\n")
        code, info = make(self.root, self.dest)
        self.assertEqual(code, 1, "intent phrase in a non-code file fails")
        self.assertTrue(any("config/spec.yaml" in h for h in info["leaks_in_documents"]), info["leaks_in_documents"])
        self.assertTrue(any("app/copy.py" in h for h in info["intent_phrases_in_code"]), "product text is listed")

    def test_build_record_ids_in_code_fail(self):
        (self.root / "app/sync.py").write_text("# implements I-D3 and L-01 from the plan\nSYNC = True\n")
        code, info = make(self.root, self.dest)
        self.assertEqual(code, 1)
        self.assertTrue(any("app/sync.py" in h for h in info["build_record_ids"]), info.get("build_record_ids"))

    def test_svg_path_data_is_not_a_build_record_id(self):
        (self.root / "app/icon.svg").write_text('<svg><path d="M 40 10 L-20 30 L-15 5 Z"/></svg>\n')
        (self.root / "app/draw.js").write_text('export const arrow = "M0 0 L-20 30 L-15 5";\n')
        code, info = make(self.root, self.dest)
        self.assertEqual(code, 0, info.get("problems"))
        self.assertEqual(info["build_record_ids"], [])

    def test_every_document_format_leaves_the_blind_copy(self):
        for rel, text in (("docs-src/guide.rst", "Usage\n=====\n"), ("NOTES.txt", "why we built it\n"),
                          ("CHANGELOG", "0.1 first\n"), ("site/page.mdx", "# Page\n"), (".cursorrules", "be nice\n"),
                          (".cursor/rules/main.mdc", "rules\n"), ("app/spec_helpers.py", "X = 1\n")):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text)
        code, info = make(self.root, self.dest)
        blind = Path(info["blind"]["path"])
        for gone in ("docs-src/guide.rst", "NOTES.txt", "CHANGELOG", "site/page.mdx", ".cursorrules", ".cursor"):
            self.assertFalse((blind / gone).exists(), gone)
        self.assertTrue((blind / "app/spec_helpers.py").exists(), "code stays whatever its name")
        self.assertTrue((blind / "requirements.txt").exists(), "a dependency list is not a document")

    def test_a_chinese_intent_is_scanned_too(self):
        intent = self.root / "docs/project/intent.md"
        intent.write_text(intent.read_text() + "\n## Goal note\n在纽约租房的中国留学生看懂租约里的隐藏费用\n")
        (self.root / "app/strings.py").write_text('TAGLINE = "帮在纽约租房的中国留学生看懂租约里的隐藏费用"\n')
        code, info = make(self.root, self.dest)
        self.assertTrue(any("app/strings.py" in h for h in info["intent_phrases_in_code"]), info["intent_phrases_in_code"])

    def test_generic_ids_only_warn(self):
        (self.root / "app/codes.py").write_text("ROOM = 'C-01'\n")
        code, info = make(self.root, self.dest)
        self.assertEqual(code, 0, info.get("problems"))
        self.assertTrue(any("app/codes.py" in h for h in info["id_like_tokens"]))

    def test_legacy_keys_in_agents_md(self):
        legacy = build(Path(self.tmp.name) / "legacy", gate_in_agents=True)
        code, info = make(legacy, self.dest)
        self.assertEqual(info["keys_source"], "AGENTS.md (legacy location)")
        self.assertFalse((Path(info["blind"]["path"]) / "design/directive.md").exists())

    def test_change_during_copy_is_caught(self):
        keys = gc.read_keys(self.root)
        fp, rows = gc.fingerprint(self.root, "product")
        (self.root / "app/__main__.py").write_text("print('edited after the fingerprint')\n")
        info = gc.build_copy(self.root, Path(self.tmp.name) / "c1", rows, keys, "review")
        self.assertIn("app/__main__.py", info["changed_since_fingerprint"])

    def test_git_ignored_files_stay_out(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".gitignore").write_text("node_modules/\n.venv/\nlocal.log\n.env\n.env.test\ndist/\n.evidence/\n")
        (self.root / "local.log").write_text("private scratch\n")
        code, info = make(self.root, self.dest)
        review = Path(info["review"]["path"])
        self.assertFalse((review / "local.log").exists(), "an ignored file is not part of the candidate")
        self.assertFalse((review / ".git").exists(), ".git stays out of the review copy by default")
        self.assertTrue((review / "node_modules/pkg/index.js").exists())

    def test_copy_is_independent_of_the_live_tree(self):
        code, info = make(self.root, self.dest)
        (self.root / "app/__main__.py").write_text("print('changed after copy')\n")
        out = subprocess.run([sys.executable, "-m", "app"], cwd=info["blind"]["path"], capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "lists")

    def test_cleanup(self):
        code, info = make(self.root, self.dest)
        base = Path(info["base"])
        self.assertEqual(subprocess.run([sys.executable, str(GC), "cleanup", str(base), "--dest", str(self.dest)]).returncode, 0)
        self.assertFalse(base.exists())
        self.assertEqual(subprocess.run([sys.executable, str(GC), "cleanup", str(self.root), "--dest", str(self.dest)],
                                        capture_output=True).returncode, 2, "refuses to delete a non-copies folder")


if __name__ == "__main__":
    unittest.main()
