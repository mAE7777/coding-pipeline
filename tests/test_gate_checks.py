"""Unit tests for gate_checks.py: which markers count, how timeouts pair, what prose-lint reads, and its usage."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/_shared/scripts/gate_checks.py"
sys.path.insert(0, str(SCRIPT.parent))
import gate_checks as gc  # noqa: E402


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=120)


class MarkerTest(unittest.TestCase):
    def test_every_named_marker_is_caught_when_added(self):
        cases = {
            "it.skip('a', () => {})": "skip", "test.skip('a')": "skip", "describe.skip('a')": "skip",
            "this.skip();": "skip", "xit('a', () => {})": "skip", "xdescribe('a', () => {})": "skip",
            "it.only('a')": "only", "describe.only('a')": "only", "test.only('a')": "only",
            "fit('a', () => {})": "only", "fdescribe('a', () => {})": "only",
            "@pytest.mark.skip(reason='x')": "skip", "@pytest.mark.skipif(True, reason='x')": "skip",
            "@pytest.mark.xfail": "expected-failure", "@unittest.skip('x')": "skip",
            "@unittest.expectedFailure": "expected-failure", "    pytest.skip('x')": "skip",
            "    self.skipTest('x')": "skip", '\tt.Skip("flaky")': "skip", '\tt.Skipf("x %d", 1)': "skip",
            "#[ignore]": "skip", '#[ignore = "slow"]': "skip", 'throw XCTSkip("x")': "skip",
            "try XCTSkipIf(true)": "skip", 'XCTExpectFailure("x")': "expected-failure", "@Disabled": "skip",
            "test.fixme('a')": "skip", "it.fails('a')": "expected-failure", "test.failing('a')": "expected-failure",
        }
        for line, kind in cases.items():
            with self.subTest(line=line):
                found = gc.new_markers([], [line])
                self.assertEqual(len(found), 1, found)
                self.assertIn(f"new {kind} marker", found[0][1])

    def test_lookalikes_are_not_markers(self):
        for line in ("model.fit(X, y)", "benefit(x)", "exit(1)", "Model.objects.only('id')",
                     "items.Skip(1).ToList()", "stream.skip(1)", "it('only works once', () => {})",
                     "expected = failure()"):
            with self.subTest(line=line):
                self.assertEqual(gc.new_markers([], [line]), [])

    def test_a_marker_already_there_is_not_new(self):
        old = ["@pytest.mark.skip", "def test_a():", "    assert 1"]
        self.assertEqual(gc.new_markers(old, ["# moved down", *old]), [])
        found = gc.new_markers(old, old + ["@pytest.mark.skip", "def test_b():", "    assert 1"])
        self.assertEqual([n for n, _ in found], [4])

    def test_f_and_x_prefixed_calls_are_markers_only_in_js_with_a_string_argument(self):
        for line in ("assert fit([1]) == 1", "model = fit(X, y)", "xit(data)", "fdescribe(suite)"):
            self.assertEqual(gc.new_markers([], [line], js=False), [], line)
        for line in ("const y = fit(x)", "xit(data)", "fdescribe(suite)"):
            self.assertEqual(gc.new_markers([], [line], js=True), [], line)
        for line in ("fit('a', () => {})", 'xtest("a")', "xcontext(`a`, fn)", "fcontext('a', fn)"):
            self.assertEqual(len(gc.new_markers([], [line], js=True)), 1, line)
            self.assertEqual(gc.new_markers([], [line], js=False), [], line)

    def test_a_marker_is_keyed_to_the_test_it_applies_to(self):
        old = ['@pytest.mark.skip(reason="flaky")', "def test_legacy_sync():", "    sync()", "",
               "def test_total():", "    assert total() == 3"]
        moved = ['@pytest.mark.skip(reason="flaky")', "def test_total():", "    assert total() == 3"]
        self.assertEqual(gc.new_markers(old, moved), [(1, "new skip marker @pytest.mark.skip")],
                         "a skip moved from a deleted test onto one that ran")
        reworded = ['@pytest.mark.skip(reason="flaky, see #12")', "def test_legacy_sync():", "    sync()"]
        self.assertEqual(gc.new_markers(old, reworded), [], "a reworded marker on the same test")
        renamed = ['@pytest.mark.skip(reason="flaky")', "def test_legacy_sync_v2():", "    sync()", "",
                   "def test_total():", "    assert total() == 3"]
        self.assertEqual(gc.new_markers(old, renamed), [], "the same marker on its renamed test")
        inline_old = ["def test_a():", "    pytest.skip('slow')", "", "def test_b():", "    assert 1"]
        inline_new = ["def test_a():", "    pytest.skip('slow')", "", "def test_new():", "    assert 2", "",
                      "def test_b():", "    assert 1"]
        self.assertEqual(gc.new_markers(inline_old, inline_new), [], "a test added after a skipped one")
        inline_moved = ["def test_a():", "    assert 0", "", "def test_b():", "    pytest.skip('slow')"]
        self.assertEqual(gc.new_markers(inline_old, inline_moved), [(5, "new skip marker pytest.skip(")])

    def test_test_files_follow_the_usual_conventions(self):
        for rel in ("tests/a.py", "test/a.js", "src/__tests__/a.ts", "spec/a.rb", "pkg/a_test.go", "a.test.tsx",
                    "a.spec.js", "test_a.py", "a_test.py", "AppTests.swift", "conftest.py"):
            self.assertTrue(gc.is_test_file(rel), rel)
        for rel in ("src/app.py", "tests/fixtures/app.py", "tests/data.json", "contest.py", "latest.swift"):
            self.assertFalse(gc.is_test_file(rel), rel)


class TimeoutTest(unittest.TestCase):
    def test_a_grown_number_on_a_timeout_line_is_named(self):
        old = ["jest.setTimeout(5000);", "const TIMEOUT_MS = 200;", "  timeout: 30,"]
        new = ["// slower CI", "jest.setTimeout(30_000);", "const TIMEOUT_MS = 100;", "  timeout: 30,"]
        self.assertEqual(gc.raised_timeouts(old, new), [(2, "timeout raised 5000 -> 30_000")])

    def test_a_new_timeout_line_has_nothing_to_compare_with(self):
        self.assertEqual(gc.raised_timeouts([], ["jest.setTimeout(60000);"]), [])

    def test_package_json_compares_only_the_runners_numeric_timeouts(self):
        old = '{\n  "dependencies": {"p-timeout": "^5.1.0"},\n  "jest": {"testTimeout": 5000},\n  "mocha": {"timeout": 2000}\n}\n'
        new = old.replace("^5.1.0", "^6.0.0").replace('"timeout": 2000', '"timeout": 1000')
        self.assertEqual(gc.package_timeouts(old, new), [], "a dependency upgrade and a lowered timeout")
        new = new.replace("5000", "60000")
        self.assertEqual(gc.package_timeouts(old, new), [(3, "timeout raised 5000 -> 60000 (jest.testTimeout)")])
        with self.assertRaises(ValueError):
            gc.package_timeouts(old, "{not json")


class TamperTest(unittest.TestCase):
    """test-tamper end to end, against a recorded baseline."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def baseline(self, files):
        for rel, text in files.items():
            (self.p / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.p / rel).write_text(text)
        subprocess.run([sys.executable, str(SCRIPT.parent / "baseline.py"), "record", str(self.p), "M1"], check=True,
                       capture_output=True)

    def tamper(self):
        return gc.test_tamper(self.p, "M1")[0]

    def move(self, a, b):
        (self.p / b).parent.mkdir(parents=True, exist_ok=True)
        (self.p / a).rename(self.p / b)

    def test_a_move_out_of_the_runners_collection_is_a_deletion(self):
        body = "from store import total\n\ndef test_total():\n    assert total() == 3\n"
        self.baseline({"tests/test_store.py": body, "tests/helpers.py": "def h():\n    return 1\n",
                       "web/total.test.js": "test('t', () => { expect(total()).toBe(3) })\n"})
        self.move("tests/test_store.py", "tests/unit/test_store.py")  # still collected
        self.move("tests/helpers.py", "tests/support/helpers.py")      # never collected
        self.assertEqual(self.tamper()[0], "PASS", self.tamper())
        self.move("tests/unit/test_store.py", "tests/unit/store_checks.py")
        self.move("web/total.test.js", "web/total.js")
        status, detail = self.tamper()
        self.assertEqual(status, "FAIL")
        self.assertIn("tests/test_store.py moved to tests/unit/store_checks.py, a name the test runner does not "
                      "collect", detail)
        self.assertNotIn("web/total.test.js moved", detail, "web/total.js is no test file: a plain deletion")
        self.assertIn("web/total.test.js deleted", detail)

    def test_ordinary_edits_are_not_tampering(self):
        pkg = '{\n  "name": "x",\n  "dependencies": {\n    "p-timeout": "^5.1.0"\n  }\n}\n'
        self.baseline({"tests/test_model.py": "from model import fit\n\ndef test_a():\n    assert fit([1]) == 1\n",
                       "package.json": pkg, "tests/a.test.js": "test('a', () => { expect(1).toBe(1) })\n"})
        (self.p / "tests/test_model.py").write_text("from model import fit\n\ndef test_a():\n    assert fit([1]) == 1"
                                                    "\n\ndef test_b():\n    assert fit([1, 2]) == 2\n")
        (self.p / "package.json").write_text(pkg.replace("^5.1.0", "^6.0.0"))
        self.assertEqual(self.tamper()[0], "PASS", self.tamper())
        (self.p / "tests/a.test.js").write_text("fit('a', () => { expect(1).toBe(1) })\n")
        self.assertIn("tests/a.test.js:1 new only marker fit(", self.tamper()[1])


class ExemptionTest(unittest.TestCase):
    def test_only_an_entry_with_an_owner_source_clears(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "docs/project/decisions.md"
            p.parent.mkdir(parents=True)
            p.write_text("# Decisions\n<!--\n## D-000 \u00b7 example\n[test-change: tests/c.py]\nSource: [owner x]\n-->\n"
                         "## D-001 \u00b7 a\nDecision: drop it [test-change: ./tests/a.py]\n"
                         "Source: [owner 2026-10-16] \"Drop it.\"\n\n"
                         "## D-002 \u00b7 b\nDecision: as the owner said [owner 2026-10-16] \"skip b\" "
                         "[test-change: `tests/b.py`]\nSource: [proposed]\n")
            owner, other = gc.exemptions(Path(d))
            self.assertEqual(owner, {"tests/a.py": "D-001"})
            self.assertEqual(other, {"tests/b.py": "D-002"}, "an owner quote elsewhere in the entry is not its Source")


class ProseTest(unittest.TestCase):
    def rules(self, text):
        return {rule: [n for n, _ in hits] for rule, hits in gc.lint(text).items()}

    def test_each_rule(self):
        text = ("A \u2014 B\nA\u2014B\n1\u20132\n\u2018x\u2019 \u201cy\u201d\n"
                "We delve into the vibrant landscape.\nThis underscores the risk.\n"
                "Use snake_case: an underscore joins words.\nRotate to landscape mode. orientation: landscape\n"
                "Great question! Of course! Let me know if it breaks.\n")
        self.assertEqual(self.rules(text), {"spaced em dash": [1], "em dash": [2], "en dash": [3],
                                            "curly quote": [4, 4, 4, 4], "AI vocabulary": [5, 5, 5, 6],
                                            "chatbot phrase": [9, 9, 9]})

    def test_code_is_ignored_and_cjk_lines_keep_their_punctuation(self):
        text = ("```js\nconst a = '\u2014';\n```\n~~~\ndelve\n~~~\nRun `a \u2014 b` now.\n"
                "\u4e2d\u6587\u201c\u5f15\u201d \u2014 x\n\u4e2d\u6587 delve\n")
        self.assertEqual(self.rules(text), {"AI vocabulary": [9]}, "a CJK line is still read for vocabulary")

    def test_scope(self):
        for rel, want in (("README.md", True), ("README", True), ("pkg/README.rst", True), ("CHANGELOG.md", True),
                          ("docs/guide.md", True), ("docs/project/intent.md", False), ("docs/api.json", False),
                          ("src/notes.md", False), ("tests/fixtures/x/README.md", False),
                          ("vendor/lib/README.md", False)):
            self.assertEqual(gc.outbound(rel), want, rel)
        for rel in ("locales/zh/README.md", "docs/i18n/fr.md", "docs/l10n/a.md", "docs/translations/de.md",
                    "locale/x.md", "app.po", "app.pot", "a.xliff", "Base.strings"):
            self.assertTrue(gc.LOCALE.search(rel), rel)


class UsageTest(unittest.TestCase):
    def test_help_and_bad_usage(self):
        out = run("--help")
        self.assertEqual(out.returncode, 0)
        self.assertIn("gate_checks.py", out.stdout)
        for args in ((), ("nope", "."), ("all", ".", "--milestone"), ("all", ".", "--milestone", "3"),
                     ("all", "/nonexistent/project"), ("all", ".", "extra")):
            self.assertEqual(run(*args).returncode, 2, args)

    def test_milestone_flag_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "tests").mkdir()
            (Path(d) / "tests/test_a.py").write_text("def test_a():\n    assert 1\n")
            subprocess.run([sys.executable, str(SCRIPT.parent / "baseline.py"), "record", d, "M3"], check=True,
                           capture_output=True)
            out = run("test-tamper", d, "--milestone", "M3")
            self.assertEqual(out.returncode, 0, out.stdout)
            self.assertRegex(out.stdout, r"^PASS\s+test-tamper\s+.*M3 baseline")
            (Path(d) / "tests/test_a.py").unlink()
            out = run("all", d, "--milestone", "M3")
            self.assertEqual(out.returncode, 1, out.stdout)
            self.assertEqual([l.split()[1] for l in out.stdout.splitlines()],
                             ["test-tamper", "test-tamper", "file-growth", "prose-lint"])


if __name__ == "__main__":
    unittest.main()
