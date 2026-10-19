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

    def test_skip_markers_without_the_at_or_the_prefix_and_conditional_skips(self):
        # Ported from the fast repository's tests (test_checks.py, ReviewFindings), which fast.py must match.
        py = "import pytest\n\ndef test_a():\n    assert 1 == 1\n"
        ut = "import unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertEqual(1, 1)\n"
        vt = "import { it, expect } from 'vitest'\nit('adds', () => {\n  expect(add(1, 2)).toBe(3)\n})\n"
        mark = "from pytest import mark\n\ndef test_a():\n    assert 1\n"
        cases = [
            ("tests/test_a.py", py, py.replace("\n\ndef", '\npytestmark = pytest.mark.skip(reason="flaky")\n\ndef'),
             "new skip marker pytest.mark.skip"),
            ("tests/test_a.py", mark, mark.replace("\ndef", '\n@mark.skip(reason="x")\ndef'), "new skip marker mark.skip"),
            ("tests/test_a.py", mark, mark.replace("\ndef", "\n@mark.skipif(True, reason='x')\ndef"),
             "new skip marker mark.skipif"),
            ("tests/test_a.py", mark, mark.replace("\ndef", "\n@mark.xfail\ndef"), "new expected-failure marker mark.xfail"),
            ("tests/test_a.py", ut, ut.replace("    def test_a(self):\n", "    def test_a(self):\n        raise "
                                               "unittest.SkipTest('later')\n"), "new skip marker SkipTest("),
            ("tests/test_a.py", ut, ut.replace("    def test_a(self):\n", "    def test_a(self):\n        raise "
                                               "SkipTest('later')\n"), "new skip marker SkipTest("),
            ("src/add.test.ts", vt, vt.replace("it('adds'", "it.skipIf(true)('adds'"), "new skip marker it.skipIf"),
            ("src/add.test.ts", vt, vt.replace("it('adds'", "it.runIf(false)('adds'"), "new skip marker it.runIf"),
            ("src/add.test.ts", vt, vt.replace("it('adds'", "describe.skipIf(ci)('adds'"),
             "new skip marker describe.skipIf"),
            ("src/add.test.ts", vt, vt.replace("it('adds'", "test.runIf(ok)('adds'"), "new skip marker test.runIf"),
            ("src/add.test.ts", vt, vt.replace("it('adds'", "suite.skipIf(x)('adds'"), "new skip marker suite.skipIf"),
        ]
        for rel, base, new, want in cases:
            with self.subTest(want=want, new=new):
                self.assertEqual([w for _, w in gc.new_markers(base.splitlines(), new.splitlines(), gc.is_js(rel))],
                                 [want])
        for line in ("bookmark.skip(1)", "watermark.xfail = 2", "class MySkipTest(Base):", "except unittest.SkipTest:",
                     "items.skipIfEmpty()", "it.skipped", "runIfNeeded()", "self.mark.skipped = True"):
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
        self.assertEqual(gc.new_markers(old, moved), [(1, "new skip marker pytest.mark.skip")],
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

    def test_timeouts_in_go_rust_junit_and_annotated_forms_are_caught(self):
        loud = [  # (baseline line, line now): each raises a test's timeout
            ("\ttimeout := 2 * time.Second", "\ttimeout := 60 * time.Second"),
            ("\tctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)",
             "\tctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)"),
            ("    tokio::time::timeout(Duration::from_millis(500), fut).await", 
             "    tokio::time::timeout(Duration::from_millis(5000), fut).await"),
            ("    @Timeout(value = 2, unit = TimeUnit.SECONDS)", "    @Timeout(value = 60, unit = TimeUnit.SECONDS)"),
            ("    timeout: float = 3.0", "    timeout: float = 30.0"),
        ]
        for old, new in loud:
            self.assertTrue(gc.raised_timeouts([old], [new]), new)
        self.assertEqual(gc.raised_timeouts(["  await page.waitForTimeout(100);"],
                                            ["  await page.waitForTimeout(1000);"]), [], "a sleep, not a timeout")

    def test_a_new_timeout_line_has_nothing_to_compare_with(self):
        self.assertEqual(gc.raised_timeouts([], ["jest.setTimeout(60000);"]), [])

    def test_only_numbers_bound_to_a_timeout_count(self):
        quiet = [  # (baseline line, line now): no test timeout grew
            ("    assert retry(timeout=5, attempts=3) == 3", "    assert retry(timeout=5, attempts=4) == 4"),
            ("    assert DEFAULT_TIMEOUT == 30", "    assert DEFAULT_TIMEOUT == 60"),
            ("    result = retry(timeout=5, attempts=3)", "    result = retry(timeout=5, attempts=4)"),
            ("  setTimeout(fn, 500);", "  setTimeout(fn, 5000);"),
            ("  setTimeout(() => done(), 500);", "  setTimeout(() => done(), 5000);"),
            ("  await setTimeout(100);", "  await setTimeout(900);"),
            ("  // jest.setTimeout(5000);", "  // jest.setTimeout(60000);"),
            ("  await expect(page).toHaveURL(u, { timeout: 5000 });", "  await expect(page).toHaveURL(u, { timeout: 9000 });"),
            ("  const TIMEOUT_MS = 200; const RETRIES = 2;", "  const TIMEOUT_MS = 200; const RETRIES = 9;"),
        ]
        for old, new in quiet:
            self.assertEqual(gc.raised_timeouts([old], [new]), [], new)
        loud = [
            ("jest.setTimeout(5000);", "jest.setTimeout(30_000);", "5000 -> 30_000"),
            ("  this.timeout(5000);", "  this.timeout(10000);", "5000 -> 10000"),
            ("@pytest.mark.timeout(5)", "@pytest.mark.timeout(50)", "5 -> 50"),
            ("@timeout(5)", "@timeout(10)", "5 -> 10"),
            ("  timeout(5)", "  timeout(10)", "5 -> 10"),
            ("  testTimeout: 5000,", "  testTimeout: 60000,", "5000 -> 60000"),
            ('  "testTimeout": 5000,', '  "testTimeout": 9000,', "5000 -> 9000"),
            ("    r = fetch(url, timeout=5, retries=3)", "    r = fetch(url, timeout=50, retries=3)", "5 -> 50"),
            ("jasmine.DEFAULT_TIMEOUT_INTERVAL = 5000;", "jasmine.DEFAULT_TIMEOUT_INTERVAL = 20000;", "5000 -> 20000"),
            ("  timeout: 30 * 1000,", "  timeout: 60 * 1000,", "30 * 1000 -> 60 * 1000"),
            ("vi.setConfig({ testTimeout: 1000, hookTimeout: 500 })", "vi.setConfig({ testTimeout: 1000, hookTimeout: 900 })",
             "500 -> 900"),
        ]
        for old, new, want in loud:
            self.assertEqual(gc.raised_timeouts([old], [new]), [(1, f"timeout raised {want}")], new)

    def test_commented_out_assertions_count_for_none(self):
        for line, n in (("# assert x", 0), ("// expect(x)", 0), (" * expect(x)", 0), ("-- assert", 0), ("/* assert", 0),
                        ("assert x  # assert y", 2), ("#[test] assert_eq!(a, b)", 1)):
            self.assertEqual(sum(c for *_, c in gc.assertion_lines([line])), n, line)

    def test_dependency_folders_hold_no_test_files(self):
        for rel in ("node_modules/pkg/test/index.test.js", "web/node_modules/pkg/test/index.test.js",
                    ".venv/lib/pkg/test/index.test.js", "venv/pkg/test/index.test.js",
                    "lib/site-packages/pkg/test/index.test.js", "bower_components/pkg/test/index.test.js"):
            self.assertFalse(gc.is_test_file(rel), rel)
        self.assertTrue(gc.is_test_file("src/myvenv/test_a.py"), "only the folder itself")
        self.assertEqual(gc.VENDORED, ("vendor/", "third_party/", "third-party/", "external/", "Pods/"),
                         "adopt.py's own list is unchanged (the fast repository compares it)")

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

    def write(self, files):
        for rel, text in files.items():
            (self.p / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.p / rel).write_text(text)

    def failing(self):
        return " ".join(d for s, d in gc.test_tamper(self.p, "M1") if s == "FAIL")

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

    # Ported from the fast repository's tests (test_checks.py, ReviewFindings), which fast.py must match.

    def test_a_skip_written_as_pytestmark_fails(self):
        py = "import pytest\n\ndef test_a():\n    assert 1 == 1\n"
        self.baseline({"tests/test_a.py": py})
        self.write({"tests/test_a.py": py.replace("\n\ndef", '\npytestmark = pytest.mark.skip(reason="flaky")\n\ndef')})
        self.assertIn("tests/test_a.py:2 new skip marker pytest.mark.skip", self.failing())

    def test_commented_out_assertions_count_for_none(self):
        body = "def test_a():\n    r = compute()\n    assert r == 42\n    assert r > 0\n"
        self.baseline({"tests/test_a.py": body, "web/a.test.js": "it('a', () => {\n  expect(a()).toBe(1)\n})\n"})
        self.write({"tests/test_a.py": body.replace("    assert", "    # assert"),
                    "web/a.test.js": "it('a', () => {\n  // expect(a()).toBe(1)\n  /* expect(b()) */\n})\n"})
        got = gc.test_tamper(self.p, "M1")
        self.assertEqual([s for s, _ in got], ["WARN"], got)
        self.assertIn("fell from 3 to 0", got[0][1])

    def test_a_number_beside_a_timeout_that_is_not_one_passes(self):
        self.baseline({"tests/test_retry.py": "def test_retry():\n    assert retry(timeout=5, attempts=3) == 3\n",
                       "tests/test_default.py": "from app import DEFAULT_TIMEOUT\n\ndef test_d():\n"
                                                "    assert DEFAULT_TIMEOUT == 30\n"})
        self.write({"tests/test_retry.py": "def test_retry():\n    assert retry(timeout=5, attempts=4) == 4\n",
                    "tests/test_default.py": "from app import DEFAULT_TIMEOUT\n\ndef test_d():\n"
                                             "    assert DEFAULT_TIMEOUT == 60\n"})
        self.assertEqual(self.tamper()[0], "PASS", self.tamper())

    def test_pytest_timeouts_in_pyproject_setup_cfg_and_tox_ini(self):
        pyproject = ('[project]\nname = "x"\ntimeout = 1\n\n[tool.pytest.ini_options]\ntimeout = 10\n'
                     'addopts = "--timeout=20"\n\n[tool.other]\ntimeout = 3\n')
        setup_cfg = "[metadata]\nname = x\n\n[tool:pytest]\naddopts =\n    -x\n    --timeout=30\n# timeout = 1\n"
        tox_ini = "[tox]\nenvlist = py\n\n[pytest]\ntimeout = 40\n\n[testenv]\ncommands = pytest --timeout=1\n"
        self.baseline({"pyproject.toml": pyproject, "setup.cfg": setup_cfg, "tox.ini": tox_ini,
                       "pytest.ini": "[pytest]\ntimeout = 50\n", "tests/test_a.py": "def test_a():\n    assert 1\n"})
        self.write({"pyproject.toml": pyproject.replace("timeout = 1\n", "timeout = 9\n").replace("timeout = 3", "timeout = 99"),
                    "setup.cfg": setup_cfg.replace("# timeout = 1", "# timeout = 99"),
                    "tox.ini": tox_ini.replace("--timeout=1", "--timeout=99")})
        self.assertEqual(self.tamper()[0], "PASS", "outside pytest's own section, or a comment")
        self.write({"pyproject.toml": pyproject.replace("timeout = 10", "timeout = 600").replace("--timeout=20", "--timeout=200"),
                    "setup.cfg": setup_cfg.replace("--timeout=30", "--timeout=300"),
                    "tox.ini": tox_ini.replace("timeout = 40", "timeout = 400"),
                    "pytest.ini": "[pytest]\ntimeout = 500\n"})
        fail = self.failing()
        for want in ("pyproject.toml:6 timeout raised 10 -> 600", "pyproject.toml:7 timeout raised 20 -> 200",
                     "setup.cfg:7 timeout raised 30 -> 300", "tox.ini:5 timeout raised 40 -> 400",
                     "pytest.ini:2 timeout raised 50 -> 500"):
            self.assertIn(want, fail)

    def test_a_project_without_tests_stays_a_skip_when_pyproject_changes(self):
        self.baseline({"pyproject.toml": '[project]\nname = "x"\nversion = "1"\n'})
        self.write({"pyproject.toml": '[project]\nname = "x"\nversion = "2"\n'})
        self.assertEqual(self.tamper()[0], "SKIP")

    def test_dependency_folders_hold_no_test_files(self):
        deps = {f"{d}pkg/test/index.test.js": "it('a', () => { expect(1).toBe(1) })\n"
                for d in ("lib/site-packages/", "bower_components/", "web/node_modules/")}
        self.baseline({**deps, "tests/test_a.py": "def test_a():\n    assert 1\n"})
        for rel in deps:
            (self.p / rel).unlink()
        status, detail = self.tamper()
        self.assertEqual(status, "PASS", detail)
        self.assertIn("(1 test file(s);", detail)

    def test_a_skipped_test_moved_to_another_file_is_not_new(self):
        old_all = ('import pytest\n\ndef test_a():\n    assert 1\n\n@pytest.mark.skip(reason="needs network")\n'
                   "def test_net():\n    assert fetch()\n")
        self.baseline({"tests/test_all.py": old_all, "tests/test_other.py": "def test_x():\n    assert 1\n",
                       "tests/test_gone.py": "import pytest\n\n@pytest.mark.xfail\ndef test_old():\n    assert 0\n"})
        self.write({"tests/test_all.py": "def test_a():\n    assert 1\n",
                    "tests/test_network.py": 'import pytest\n\n@pytest.mark.skip(reason="needs network")\n'
                                             "def test_net():\n    assert fetch()\n"})
        self.assertEqual(self.tamper()[0], "PASS", self.tamper())
        self.write({"tests/test_other.py": 'import pytest\n\n@pytest.mark.skip(reason="needs network")\n'
                                           "def test_x():\n    assert 1\n"})
        fail = self.failing()
        self.assertIn("tests/test_other.py:3 new skip marker", fail, "another test, so a new skip")
        self.assertNotIn("test_network.py", fail)
        self.write({"tests/test_other.py": "def test_x():\n    assert 1\n"})
        (self.p / "tests/test_gone.py").unlink()
        others = "".join(f"\ndef test_more_{i}(tmp_path):\n    assert make({i}).ready\n" for i in range(8))
        self.write({"tests/test_new_home.py": "import pytest\n\n@pytest.mark.xfail\ndef test_old():\n    assert 0\n"
                                              + others})
        fail = self.failing()
        self.assertIn("tests/test_gone.py deleted", fail)
        self.assertNotIn("test_new_home.py", fail, "its marker moved with the test from the deleted file")

    def test_a_skip_on_another_test_of_the_same_name_is_new(self):
        api = "import pytest\n\ndef test_create():\n    assert make().ok\n"
        old_v1 = "import pytest\n\n@pytest.mark.skip(reason='v1 is gone')\ndef test_create():\n    assert 0\n"
        self.baseline({"tests/test_api.py": api, "tests/test_v1_api.py": old_v1})
        (self.p / "tests/test_v1_api.py").unlink()
        self.write({"tests/test_api.py": api.replace("def test_create", "@pytest.mark.skip(reason='v1 is gone')\n"
                                                                        "def test_create")})
        fail = self.failing()
        self.assertIn("tests/test_v1_api.py deleted", fail)
        self.assertIn("tests/test_api.py:3 new skip marker", fail, "test_api.py defined test_create at the base")

    def test_a_moved_test_file_keeps_its_markers(self):
        skipped = "import pytest\n\n@pytest.mark.skip(reason='slow')\ndef test_a():\n    assert 1\n"
        self.baseline({"tests/test_a.py": skipped})
        self.move("tests/test_a.py", "tests/unit/test_a.py")
        self.assertEqual(self.tamper()[0], "PASS", "a move with its content unchanged adds no marker")


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
