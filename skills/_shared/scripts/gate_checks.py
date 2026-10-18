#!/usr/bin/env python3
"""Gate checks against the milestone's starting point: test tampering, file growth, and outbound prose.

Usage:
  gate_checks.py test-tamper [project-dir] [--milestone M<k>]
  gate_checks.py file-growth [project-dir] [--milestone M<k>]
  gate_checks.py prose-lint [project-dir] [--milestone M<k>]
  gate_checks.py all [project-dir] [--milestone M<k>]       the three, in this order (gate.sh runs this)

Each check prints lines in gate.sh's report format, "<PASS|FAIL|WARN|SKIP>  <check>  <detail>", and gate.sh
prints them again through its report function. The milestone is the one named first in the Milestone section of
docs/project/state.md (--milestone overrides it). Its baseline is .evidence/baseline-M<k>.txt with the copy of
every product file in .evidence/baseline/M<k>/, both written by baseline.py record at the milestone start.

test-tamper   FAIL when, since the baseline: a test file was deleted (a move with unchanged content is not a
              deletion, unless it moves a file the runner collects by its default pattern, such as test_*.py or
              *.test.js, to a name it does not collect); a skip, only (focus), or expected-failure marker was
              added to a test file, each marker keyed to the test it applies to (so one moved onto a test that
              did not carry it is new; the f- and x-prefixed runner calls such as fit and xit count only in a
              JavaScript or TypeScript test file and only with a string first argument); or a number grew on a
              line that mentions a timeout, in a test file or a test runner's config, matched with the baseline
              line that reads the same apart from its numbers (in package.json, only the numeric values of keys
              naming a timeout inside the jest, mocha, vitest, ava, playwright, cypress, karma, or jasmine
              settings, never a version string). WARN when the test files hold fewer assertions in total than at
              the baseline. Findings for a file are cleared only by an entry in
              docs/project/decisions.md that holds "[test-change: <path>]" and whose Source line is an owner
              ruling ("Source: [owner ..."); rulings.py check proves the owner's words. SKIP when no baseline was
              recorded; FAIL when state.md records one that is gone.
file-growth   WARN when a code file had fewer than 1,000 lines at the baseline (or did not exist) and has 1,000
              or more now. Lockfiles and vendored, generated, and binary files are left out, as are the paths
              under "Gate exclude" in docs/project/gate.md.
prose-lint    WARN only, never FAIL, on text that leaves the machine: README* and CHANGELOG* files, docs/ outside
              docs/project/, and the commit messages since the baseline when the baseline records its git
              commit (.evidence/baseline-M<k>.head, the commit hash). Rules: spaced em dashes, other em dashes,
              en dashes, curly quotes, unslop's AI vocabulary, chatbot phrases. Fenced code blocks and inline
              code are ignored. Locale and translation files are left out, and a line holding CJK characters is
              not checked for dashes or quotes.

A check that cannot run says so on its own named line: FAIL for test-tamper, WARN for the others.
Exit 0 when nothing FAILs, 1 when a check FAILs, 2 on bad usage (--help exits 0).
"""
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from adopt import BINARY_EXT, GENERATED, LOCKFILES, TEST, VENDORED  # noqa: E402
from baseline import paths as baseline_paths, read_listing  # noqa: E402
from fingerprint import fingerprint  # noqa: E402
from gate_keys import read_keys  # noqa: E402
from languages import CODE  # noqa: E402

CHECKS = ("test-tamper", "file-growth", "prose-lint")
BROKEN = {"test-tamper": "FAIL", "file-growth": "WARN", "prose-lint": "WARN"}
GROWTH_LIMIT = 1000
EXAMPLES = 5

# ---- what a test file is ------------------------------------------------------------------------------------
# adopt.py's convention (tests/, test/, __tests__/, spec/, e2e/, *.test.*, *.spec.*, test_*.py, *_test.go|py),
# plus Swift test files and pytest's conftest.py. Fixture and snapshot folders hold test data, not tests.
TEST_FILE = re.compile(TEST.pattern + r"|Tests?\.swift$|(^|/)conftest\.py$")
TEST_DATA = re.compile(r"(^|/)(fixtures|__fixtures__|testdata|__snapshots__)/")
# Test runners' own config: only its timeout lines are compared.
TEST_CONFIG = re.compile(r"(^|/)((jest|vitest|playwright|cypress)\.config\.[^/]+|vitest\.workspace\.[^/]+|"
                         r"karma\.conf\.[^/]+|\.mocharc(\.[^/]+)?|pytest\.ini|package\.json)$")

RUNNER = r"(?:it|test|describe|context|suite|specify)"
JS_EXT = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
# The f- and x-prefixed runner calls (fit, xit, xdescribe, ...) are markers only in JavaScript or TypeScript and
# only with a string first argument: fit(X, y) in Python is a function call.
JS_MARKERS = [
    ("skip", re.compile(r"(?<![\w.$])x(?:it|test|describe|context|specify)\s*\((?=\s*['\"`])")),
    ("only", re.compile(r"(?<![\w.$])f(?:it|describe|context)\s*\((?=\s*['\"`])")),
]
MARKERS = [
    ("skip", re.compile(r"\b(?:it|test|describe|context|suite|specify|this)\.skip\b")),
    ("skip", re.compile(r"@pytest\.mark\.skip(?:if)?\b")),
    ("skip", re.compile(r"\bpytest\.(?:skip|importorskip)\s*\(")),
    ("skip", re.compile(r"@unittest\.skip(?:If|Unless)?\b")),
    ("skip", re.compile(r"\.skipTest\s*\(")),
    ("skip", re.compile(r"\b(?:t|tt|tb|b|s|T\(\))\.Skip(?:f|Now)?\s*\(")),  # Go; not C#'s LINQ .Skip(n)
    ("skip", re.compile(r"#\[ignore\b")),
    ("skip", re.compile(r"\bXCTSkip(?:If|Unless)?\b")),
    ("skip", re.compile(r"@(?:Disabled|Ignore)\b")),
    ("skip", re.compile(r"\b(?:it|test)\.fixme\b")),
    ("only", re.compile(rf"\b{RUNNER}\.only\b")),
    ("expected-failure", re.compile(r"@pytest\.mark\.xfail\b")),
    ("expected-failure", re.compile(r"\bpytest\.xfail\s*\(")),
    ("expected-failure", re.compile(r"@(?:unittest\.)?expectedFailure\b")),
    ("expected-failure", re.compile(r"\bXCTExpectFailure\b")),
    ("expected-failure", re.compile(r"\b(?:it|test)\.(?:fails|failing)\b|\btest\.fail\s*\(")),
]
# A test definition line, which a marker applies to: Python, Rust, Go, Swift, Kotlin, Java and C# test methods,
# and in JavaScript or TypeScript a runner call.
DEFINITION = re.compile(r"^\s*(?:async\s+)?def\s+\w+|^\s*class\s+\w+|^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+\w+|"
                        r"^\s*func\s+(?:\([^)]*\)\s*)?\w+|^\s*(?:(?:public|private|protected|internal|static|async|"
                        r"override|open)\s+)*(?:fun|void|Task)\s+\w+\s*\(")
JS_DEFINITION = re.compile(r"(?<![\w.$])[fx]?(?:it|test|describe|context|suite|specify)(?:\.\w+)*\s*\(")
# The file names test runners collect by default: pytest and unittest, jest, vitest, and mocha, go test, RSpec and
# minitest, JUnit, NUnit and xUnit, PHPUnit, ExUnit, dart test, Rust's tests/, XCTest.
COLLECTED = re.compile(r"(^|/)test[^/]*\.py$|_test\.py$|(^|/)conftest\.py$|(^|/)__tests__/.+\.[cm]?[jt]sx?$|"
                       r"[./](test|spec)\.[cm]?[jt]sx?$|(^|/)test/[^/]+\.[cm]?[jt]s$|_test\.go$|"
                       r"(_test|_spec|Test|Tests|Spec|IT)\.[A-Za-z]+$|(^|/)test_[^/]+\.[A-Za-z]+$|(^|/)tests/[^/]+\.rs$|"
                       r"(^|/)Tests?/.+\.swift$")
# package.json: the test runners' own settings, whose numeric timeout values are compared.
RUNNER_SETTINGS = ("jest", "mocha", "vitest", "ava", "playwright", "cypress", "karma", "jasmine")
TIMEOUT = re.compile(r"timeout", re.I)
NUMBER = re.compile(r"(?<![\w.])\d[\d_]*(?:\.\d+)?")
ASSERTION = re.compile(r"\bassert|\bexpect\s*\(|\.should\b|XCTAssert|\b(?:t|tb|b)\.(?:Error|Fatal)f?\s*\(")
DECISION = re.compile(r"^## (D-\d{3,})\b.*?(?=^## D-\d{3,}\b|\Z)", re.M | re.S)
TEST_CHANGE = re.compile(r"\[test-change:\s*([^\]]+?)\s*\]")
OWNER_SOURCE = re.compile(r"^Source:[ \t]*\[owner ", re.M)

# ---- outbound prose -------------------------------------------------------------------------------------------
LOCALE = re.compile(r"(^|/)(locales?|i18n|l10n|translations)/|\.(po|pot|xliff|xlf|strings)$", re.I)
PROSE_EXT = {".md", ".mdx", ".markdown", ".txt", ".rst", ".adoc", ".org"}
CJK = re.compile(r"[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]")
EM, EN = "\u2014", "\u2013"
CURLY = re.compile(r"[\u2018\u2019\u201c\u201d]")
FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1")
# unslop's AI vocabulary, with the usual inflections. "landscape" and "tapestry" count only in their abstract
# sense (not after "orientation", not before "mode", "orientation", or "layout"); "underscore" only as a verb.
VOCAB = re.compile(
    r"\b(?P<w>additionally|crucial(?:ly)?|delv(?:e|es|ed|ing)|enduring|enhanc(?:e|es|ed|ing)|"
    r"foster(?:ing|s|ed)|garner(?:s|ed|ing)?|interplay|intricate(?:ly)?|pivotal|showcas(?:e|es|ed|ing)|"
    r"testament|vibrant|landscapes?|tapestr(?:y|ies)|underscor(?:e|es|ed|ing))\b", re.I)
ORIENTATION_BEFORE = re.compile(r"orientation\W{0,3}$", re.I)
TECH_AFTER = re.compile(r"^\s+(?:mode|orientation|layout)\b", re.I)
VERB_OBJECT = re.compile(r"^\s+(?:the|a|an|how|that|its|their|our|this|these|those|why|what|his|her|your|my)\b",
                         re.I)
NOUN_BEFORE = re.compile(r"\b(?:a|an|the|one|single|double|leading|trailing)\s+$", re.I)
CHATBOT = re.compile(r"\bI hope this helps\b|\bLet me know if\b|\bGreat question\b|\bCertainly!|\bOf course!|"
                     r"\bFound the smoking gun\b", re.I)
PROSE_RULES = ("spaced em dash", "em dash", "en dash", "curly quote", "AI vocabulary", "chatbot phrase")


class CannotRun(Exception):
    """A check that cannot vouch for anything: reported as "<check> could not run: <reason>"."""


def report_line(status, check, detail):
    return f"{status:<5}  {check:<16}  {' '.join(str(detail).split())}"


def read_text(path):
    """The text of a file; None when it does not exist or is binary. Any other read error is raised."""
    try:
        data = Path(path).read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def section(text, heading):
    m = re.search(rf"^## {re.escape(heading)}[ \t]*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else None


def state_text(project):
    state = project / "docs/project/state.md"
    if not state.is_file():
        return None
    try:
        text = state.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CannotRun(f"docs/project/state.md is not UTF-8 text ({exc.reason} at byte {exc.start})")
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def milestone(project, given=None):
    """(milestone, why there is none)."""
    if given:
        return given, ""
    text = state_text(project)
    if text is None:
        return None, "there is no docs/project/state.md to name the milestone"
    body = section(text, "Milestone")
    if body is None:
        return None, "docs/project/state.md has no Milestone section"
    m = re.match(r"(M\d+)\b", body)
    if not m:
        first = body.splitlines()[0][:60] if body else "it is empty"
        return None, f"the Milestone section of docs/project/state.md names no milestone ({first})"
    return m.group(1), ""


class Baseline:
    """A milestone's recorded start: the files present then (path: short hash) and the copy of each."""

    def __init__(self, project, mid):
        self.mid = mid
        listing, self.copy = baseline_paths(project, mid)
        _, rows = read_listing(listing)
        self.files = {rel: h for rel, h in rows.items() if h != "deleted"}

    def text(self, rel):
        """The file's text at the baseline; None when it is binary. FileNotFoundError when the copy lacks it."""
        p = self.copy / rel
        if not p.exists() and not p.is_symlink():
            raise FileNotFoundError(f"{rel} is in the {self.mid} baseline listing but not in its copy")
        return read_text(p)


def load_baseline(project, given):
    """(Baseline, None) or (None, the reason for a SKIP). CannotRun when a recorded baseline is unusable."""
    mid, why = milestone(project, given)
    if not mid:
        return None, f"no milestone baseline to compare with ({why})"
    listing, copy = baseline_paths(project, mid)
    if not listing.is_file():
        recorded = None
        text = state_text(project) if not given else None
        if text:
            m = re.search(r"\bproduct:[0-9a-f]{16}\b", section(text, "Baseline") or "")
            recorded = m.group(0) if m else None
        if recorded:
            raise CannotRun(f"docs/project/state.md records the {mid} baseline {recorded}, but "
                            f".evidence/baseline-{mid}.txt is gone, so nothing can be compared with it")
        return None, (f"no baseline recorded for {mid} (.evidence/baseline-{mid}.txt; baseline.py record writes "
                      "it when the milestone starts)")
    if not copy.is_dir():
        raise CannotRun(f".evidence/baseline-{mid}.txt exists but its copy .evidence/baseline/{mid}/ is missing")
    return Baseline(project, mid), None


def product_files(project):
    """{relative path: short hash} of the product files present now (fingerprint.py's list)."""
    _, rows = fingerprint(project, "product")
    return {rel: h[:16] for rel, h in rows if h != "deleted"}


def gate_excluded(project):
    entries = [e.strip().strip("/") for e in read_keys(project).get("Gate exclude") or [] if e.strip().strip("/")]

    def excluded(rel):
        parts = rel.split("/")
        return any(rel == e or rel.startswith(e + "/") or ("/" not in e and e in parts) for e in entries)
    return excluded


def is_vendored(rel):
    return any(rel.startswith(v) or f"/{v}" in rel for v in VENDORED)


# ---- test-tamper ----------------------------------------------------------------------------------------------
def is_test_file(rel):
    return bool(TEST_FILE.search(rel)) and not TEST_DATA.search(rel) and not is_vendored(rel) \
        and (Path(rel).suffix in CODE or Path(rel).suffix.lower() in CODE)


def is_test_config(rel):
    return bool(TEST_CONFIG.search(rel)) and not is_vendored(rel) and not TEST_DATA.search(rel)


def is_js(rel):
    return Path(rel).suffix.lower() in JS_EXT


def defines_test(line, js):
    return bool(DEFINITION.search(line) or (js and JS_DEFINITION.search(line)))


def applies_to(lines, i, js):
    """The definition line (stripped) of the test the marker on lines[i] applies to: the line itself when it
    defines the test (it.skip('a', ...)), the next definition after a decorator or attribute (@pytest.mark.skip,
    #[ignore]), else the definition the call sits in (pytest.skip() in a body). None at file level."""
    if defines_test(lines[i], js):
        return lines[i].strip()
    step = 1 if lines[i].lstrip().startswith(("@", "#[")) else -1
    j = i + step
    while 0 <= j < len(lines):
        if defines_test(lines[j], js):
            return lines[j].strip()
        j += step
    return None


def markers(lines, js=True):
    """(line number, kind, marker text, the line, the test it applies to) for each marker in lines."""
    found = []
    for i, line in enumerate(lines):
        for kind, rx in MARKERS + (JS_MARKERS if js else []):
            for m in rx.finditer(line):
                found.append((i + 1, kind, re.sub(r"\s+", "", m.group(0)), line.strip(), applies_to(lines, i, js)))
    return found


def new_markers(old_lines, new_lines, js=True):
    """Markers added since the baseline, each keyed to the test it applies to. A marker is not new when the
    baseline has it on the same line and test, or reworded on the same test, or with the same line on a test the
    baseline did not have (the test was renamed); one now on a test that existed without it is new. js: the file
    is JavaScript or TypeScript, where the f- and x-prefixed runner calls are markers too."""
    old, new = markers(old_lines, js), markers(new_lines, js)
    old_tests = {line.strip() for line in old_lines if defines_test(line, js)}
    left = list(old)
    pending = list(new)
    keys = (lambda o, n: o[2:5] == n[2:5],                                  # same marker, line, and test
            lambda o, n: n[4] is not None and (o[2], o[4]) == (n[2], n[4]),  # reworded on the same test
            lambda o, n: n[4] not in old_tests and o[2:4] == n[2:4])         # the same line on a renamed test
    for same in keys:
        for nm in list(pending):
            match = next((o for o in left if same(o, nm)), None)
            if match is not None:
                left.remove(match)
                pending.remove(nm)
    return [(n, f"new {kind} marker {text}") for n, kind, text, _, _ in pending]


def as_number(s):
    return float(s.replace("_", ""))


def raised_timeouts(old_lines, new_lines):
    """Lines mentioning a timeout whose numbers grew, each paired with the baseline line that reads the same apart
    from its numbers."""
    left = Counter(l.strip() for l in old_lines if TIMEOUT.search(l))
    changed = []
    for n, line in enumerate(new_lines, 1):
        if not TIMEOUT.search(line):
            continue
        s = line.strip()
        if left[s] > 0:
            left[s] -= 1
        else:
            changed.append((n, s))
    pool = {}
    for s in [l.strip() for l in old_lines if TIMEOUT.search(l)]:
        if left[s] > 0:
            left[s] -= 1
            pool.setdefault(NUMBER.sub("#", s), []).append(s)
    out = []
    for n, s in changed:
        olds = pool.get(NUMBER.sub("#", s))
        if not olds:
            continue
        o = olds.pop(0)
        grew = [f"{a} -> {b}" for a, b in zip(NUMBER.findall(o), NUMBER.findall(s)) if as_number(b) > as_number(a)]
        if grew:
            out.append((n, "timeout raised " + ", ".join(grew)))
    return out


def json_timeouts(data):
    """{key path: number} for each numeric value of a key naming a timeout inside the test runners' settings."""
    out = {}

    def walk(node, path):
        items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
        for k, v in items:
            here = path + (str(k),)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and TIMEOUT.search(str(k)):
                out[here] = v
            else:
                walk(v, here)
    if isinstance(data, dict):
        for name in RUNNER_SETTINGS:
            walk(data.get(name), (name,))
    return out


def package_timeouts(old_text, new_text):
    """package.json: the runners' numeric timeout settings that grew, with the line of the new value. Version
    strings never count (p-timeout ^5 -> ^6 is a dependency upgrade). Raises ValueError when either is not JSON."""
    old, new = json_timeouts(json.loads(old_text)), json_timeouts(json.loads(new_text))
    lines = new_text.splitlines()
    out = []
    for path in sorted(set(old) & set(new)):
        if new[path] > old[path]:
            at = next((n for n, line in enumerate(lines, 1)
                       if re.search(rf'"{re.escape(path[-1])}"\s*:\s*{re.escape(json.dumps(new[path]))}\b', line)), None)
            out.append((at, f"timeout raised {old[path]} -> {new[path]} ({'.'.join(path)})"))
    return out


def assertion_lines(lines):
    return [(n, line.strip(), len(ASSERTION.findall(line))) for n, line in enumerate(lines, 1)
            if ASSERTION.search(line)]


def exemptions(project):
    """({path: entry} for owner-ruled [test-change: <path>] tokens, {path: entry} for tokens in other entries)."""
    p = project / "docs/project/decisions.md"
    if not p.is_file():
        return {}, {}
    text = re.sub(r"<!--.*?-->", "", p.read_text(encoding="utf-8", errors="replace"), flags=re.S)
    owner, other = {}, {}
    for m in DECISION.finditer(text):
        body = m.group(0)
        for raw in TEST_CHANGE.findall(body):
            rel = raw.strip().strip("`")
            rel = rel[2:] if rel.startswith("./") else rel
            (owner if OWNER_SOURCE.search(body) else other).setdefault(rel, m.group(1))
    return owner, other


def test_tamper(project, given=None):
    base, why = load_baseline(project, given)
    if base is None:
        return [("SKIP", why)]
    now = product_files(project)
    old_tests = {r for r in base.files if is_test_file(r)}
    new_tests = {r for r in now if is_test_file(r)}
    configs = {r for r in base.files if r in now and is_test_config(r)}
    if not old_tests and not new_tests and not configs:
        return [("SKIP", f"no test files at the {base.mid} baseline or now (tests/, test/, __tests__/, spec/, e2e/, "
                         "*.test.*, *.spec.*, test_*.py, *_test.py, *_test.go, *Tests.swift)")]
    owner, other = exemptions(project)
    findings = []  # (path, "path[:line] what")
    added = {}
    for r in sorted(new_tests - old_tests):
        added.setdefault(now[r], []).append(r)
    for rel in sorted(old_tests - new_tests):
        targets = added.get(base.files[rel], [])
        if any(not COLLECTED.search(rel) or COLLECTED.search(t) for t in targets):
            continue  # moved with its content unchanged, and still collected when it was before
        if targets:
            findings.append((rel, f"{rel} moved to {targets[0]}, a name the test runner does not collect, so it no "
                                  "longer runs (a deletion)"))
        else:
            findings.append((rel, f"{rel} deleted"))
    before_total = after_total = 0
    drops = []
    for rel in sorted(old_tests | new_tests | configs):
        try:
            old = base.text(rel) if rel in base.files else ""
        except FileNotFoundError as exc:
            findings.append((rel, f"{rel} not compared: {exc}"))
            continue
        except OSError as exc:
            findings.append((rel, f"{rel} not compared: its baseline copy cannot be read ({exc.strerror or exc})"))
            continue
        try:
            new = read_text(project / rel) if rel in now else ""
        except OSError as exc:
            findings.append((rel, f"{rel} not compared: it cannot be read ({exc.strerror or exc})"))
            continue
        if old is None or new is None:
            continue  # binary
        old_lines, new_lines = old.splitlines(), new.splitlines()
        is_test = rel in old_tests or rel in new_tests
        if is_test and rel in now:
            findings += [(rel, f"{rel}:{n} {what}") for n, what in new_markers(old_lines, new_lines, is_js(rel))]
        if rel in base.files and rel in now and rel.rsplit("/", 1)[-1] == "package.json":
            try:
                findings += [(rel, f"{rel}{f':{n}' if n else ''} {what}") for n, what in package_timeouts(old, new)]
            except ValueError as exc:
                findings.append((rel, f"{rel} not compared: it does not parse as JSON ({exc})"))
        elif rel in base.files and rel in now:
            findings += [(rel, f"{rel}:{n} {what}") for n, what in raised_timeouts(old_lines, new_lines)]
        if is_test and rel not in owner:
            olda, newa = assertion_lines(old_lines), assertion_lines(new_lines)
            b, a = sum(c for *_, c in olda), sum(c for *_, c in newa)
            before_total, after_total = before_total + b, after_total + a
            if a < b:
                left = Counter(text for _, text, _ in newa)
                gone = []
                for n, text, _ in olda:
                    if left[text] > 0:
                        left[text] -= 1
                    else:
                        gone.append(str(n))
                where = (f" (baseline line{'s' if len(gone) > 1 else ''} {', '.join(gone[:10])}"
                         f"{' and more' if len(gone) > 10 else ''} gone)") if gone else ""
                drops.append(f"{rel} {b} -> {a}{where}")
    cleared = sorted({f"{rel} ({owner[rel]})" for rel, _ in findings if rel in owner})
    failing = [text for rel, text in findings if rel not in owner]
    tail = []
    if cleared:
        tail.append("cleared by owner ruling: " + ", ".join(cleared))
    unruled = sorted({f"{rel} ({other[rel]})" for rel, _ in findings if rel in other and rel not in owner})
    if unruled:
        tail.append("not cleared, the entry's Source is not an owner ruling: " + ", ".join(unruled))
    out = []
    if failing:
        out.append(["FAIL", f"since the {base.mid} baseline: " + "; ".join(failing) +
                    ". Only an owner ruling in docs/project/decisions.md naming the file as [test-change: <path>] "
                    "clears a finding"])
    if after_total < before_total:
        out.append(["WARN", f"assertions in test files fell from {before_total} to {after_total} since the "
                            f"{base.mid} baseline: " + "; ".join(drops)])
    if not out:
        out.append(["PASS", f"no test file deleted, no skip, only, or expected-failure marker added, no timeout "
                            f"raised since the {base.mid} baseline ({len(new_tests)} test file(s); assertions "
                            f"{before_total} -> {after_total})"])
    out[0][1] += "".join(f"; {t}" for t in tail)
    return [tuple(o) for o in out]


# ---- file-growth ----------------------------------------------------------------------------------------------
def counted_for_growth(rel, excluded):
    name, ext = rel.rsplit("/", 1)[-1], Path(rel).suffix
    return (ext in CODE or ext.lower() in CODE) and name not in LOCKFILES and not is_vendored(rel) \
        and not GENERATED.search(rel) and ext.lower() not in BINARY_EXT and not excluded(rel)


def generated_header(text):
    head = "\n".join(text.splitlines()[:5])
    return bool(re.search(r"@generated|DO NOT EDIT|auto-?generated", head, re.I))


def file_growth(project, given=None):
    base, why = load_baseline(project, given)
    if base is None:
        return [("SKIP", why)]
    excluded = gate_excluded(project)
    grown, unreadable, checked = [], [], 0
    for rel in sorted(product_files(project)):
        if not counted_for_growth(rel, excluded) or (project / rel).is_symlink():
            continue
        checked += 1
        try:
            text = read_text(project / rel)
        except OSError as exc:
            unreadable.append(f"{rel} ({exc.strerror or exc})")
            continue
        if text is None:
            continue
        after = len(text.splitlines())
        if after < GROWTH_LIMIT or generated_header(text):
            continue
        if rel not in base.files:
            grown.append(f"{rel} new -> {after:,}")
            continue
        try:
            old = base.text(rel)
        except OSError:
            grown.append(f"{rel} unknown (no baseline copy) -> {after:,}")
            continue
        before = len(old.splitlines()) if old is not None else 0
        if before < GROWTH_LIMIT:
            grown.append(f"{rel} {before:,} -> {after:,}")
    out = []
    if grown:
        out.append(("WARN", f"reached {GROWTH_LIMIT:,} lines or more since the {base.mid} baseline (lines before -> "
                            f"now): " + "; ".join(grown)))
    if unreadable:
        out.append(("WARN", "could not read, so not counted: " + "; ".join(unreadable)))
    if not out:
        out.append(("PASS", f"no code file reached {GROWTH_LIMIT:,} lines since the {base.mid} baseline "
                            f"({checked} code file(s) checked)"))
    return out


# ---- prose-lint -----------------------------------------------------------------------------------------------
def outbound(rel):
    name = rel.rsplit("/", 1)[-1]
    ext = Path(name).suffix.lower()
    if is_vendored(rel) or TEST_DATA.search(rel):
        return False
    if name.upper().startswith(("README", "CHANGELOG")):
        return ext in PROSE_EXT or "." not in name
    return rel.startswith("docs/") and not rel.startswith("docs/project/") and ext in PROSE_EXT


def prose_lines(text):
    """(line number, text) for each line outside fenced code, with inline code blanked out."""
    fence = None
    for n, line in enumerate(text.splitlines(), 1):
        m = FENCE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
                continue
            yield n, INLINE_CODE.sub(" ", line)
        elif m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip().strip(fence[0]):
            fence = None


def vocabulary(line):
    for m in VOCAB.finditer(line):
        w = m.group("w").lower()
        before, after = line[:m.start()], line[m.end():]
        if w.startswith(("landscape", "tapestr")) and (ORIENTATION_BEFORE.search(before) or TECH_AFTER.match(after)):
            continue
        if w.startswith("underscor") and (not VERB_OBJECT.match(after) or NOUN_BEFORE.search(before)):
            continue
        yield w


def lint(text):
    """{rule: [(line, note)]} for one text."""
    hits = {}
    for n, line in prose_lines(text):
        if not CJK.search(line):
            spaced = line.count(f" {EM} ")
            for rule, count in (("spaced em dash", spaced), ("em dash", line.count(EM) - spaced),
                                ("en dash", line.count(EN)), ("curly quote", len(CURLY.findall(line)))):
                hits.setdefault(rule, []).extend([(n, "")] * count)
        for w in vocabulary(line):
            hits.setdefault("AI vocabulary", []).append((n, w))
        for m in CHATBOT.finditer(line):
            hits.setdefault("chatbot phrase", []).append((n, m.group(0)))
    return {k: v for k, v in hits.items() if v}


def commit_messages(project, base, why):
    """([(short hash, message)], note) for the commits since the baseline's recorded git commit."""
    if base is None:
        return [], f"commit messages not checked: {why}"
    head = project / f".evidence/baseline-{base.mid}.head"
    if not head.is_file():
        return [], f"commit messages not checked: the {base.mid} baseline records no git commit"
    words = head.read_text(encoding="utf-8", errors="replace").split()
    sha = words[0] if words else ""
    if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
        return [], f"commit messages not checked: .evidence/baseline-{base.mid}.head holds no commit hash"
    try:
        r = subprocess.run(["git", "-C", str(project), "log", "--format=%H%x1f%B%x1e", f"{sha}..HEAD", "--", "."],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"commit messages not checked: git could not run ({exc})"
    if r.returncode != 0:
        err = (r.stderr.strip().splitlines() or ["no message"])[-1]
        return [], f"commit messages not checked: git could not list the commits since {sha[:7]} ({err})"
    msgs = []
    for rec in r.stdout.split("\x1e"):
        if "\x1f" in rec:
            h, body = rec.split("\x1f", 1)
            msgs.append((h.strip()[:7], body.strip("\n")))
    return msgs, f"{len(msgs)} commit message(s) since {sha[:7]} checked"


def prose_lint(project, given=None):
    try:
        base, why = load_baseline(project, given)
    except CannotRun as exc:
        base, why = None, str(exc)
    excluded = gate_excluded(project)
    files, locale = [], 0
    for rel in sorted(product_files(project)):
        if not outbound(rel) or excluded(rel):
            continue
        if LOCALE.search(rel):
            locale += 1
            continue
        files.append(rel)
    hits, unreadable = {rule: [] for rule in PROSE_RULES}, []
    for rel in files:
        try:
            text = read_text(project / rel)
        except OSError as exc:
            unreadable.append(f"{rel} ({exc.strerror or exc})")
            continue
        for rule, found in lint(text or "").items():
            hits[rule] += [(f"{rel}:{n}", note) for n, note in found]
    msgs, commit_note = commit_messages(project, base, why)
    for short, body in msgs:
        for rule, found in lint(body).items():
            hits[rule] += [(f"commit {short}:{n}", note) for n, note in found]
    notes = [commit_note]
    if locale:
        notes.append(f"{locale} locale or translation file(s) left out")
    if unreadable:
        notes.append("could not read: " + ", ".join(unreadable))
    scope = f"{len(files)} outbound file(s) (README, CHANGELOG, docs/ outside docs/project/)"
    total = sum(len(v) for v in hits.values())
    if total:
        parts = []
        for rule in PROSE_RULES:
            if not hits[rule]:
                continue
            examples = []
            for where, note in hits[rule]:
                example = f"{where} {note}".strip()
                if example not in examples and len(examples) < EXAMPLES:
                    examples.append(example)
            parts.append(f"{rule} {len(hits[rule])} ({', '.join(examples)})")
        note = "; ".join(notes)
        where = scope + (f" and {len(msgs)} commit message(s)" if msgs else "")
        return [("WARN", f"{total} finding(s) in {where}: " + "; ".join(parts) + ". " + note[:1].upper() + note[1:])]
    if not files and not msgs:
        return [("SKIP" if not unreadable else "WARN",
                 "no README, CHANGELOG, or docs/ file outside docs/project/ to check; " + "; ".join(notes))]
    return [("WARN" if unreadable else "PASS", f"{scope} clean; " + "; ".join(notes))]


# ---- running ----------------------------------------------------------------------------------------------
RUN = {"test-tamper": test_tamper, "file-growth": file_growth, "prose-lint": prose_lint}


def run_check(name, project, given):
    try:
        return [report_line(status, name, detail) for status, detail in RUN[name](project, given)]
    except CannotRun as exc:
        return [report_line(BROKEN[name], name, f"{name} could not run: {exc}")]
    except Exception as exc:  # a check that breaks is named, never silent
        return [report_line(BROKEN[name], name, f"{name} could not run: {type(exc).__name__}: {exc}")]


def main(argv):
    args = list(argv)
    given = None
    if "--milestone" in args:
        i = args.index("--milestone")
        if i + 1 >= len(args) or not re.fullmatch(r"M\d+", args[i + 1]):
            print(__doc__.strip(), file=sys.stderr)
            return 2
        given = args[i + 1]
        del args[i:i + 2]
    if not args or args[0] not in CHECKS + ("all",) or len(args) > 2 or any(a.startswith("-") for a in args):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    project = Path(args[1] if len(args) > 1 else ".").resolve()
    if not project.is_dir():
        print(f"gate_checks: not a directory: {project}", file=sys.stderr)
        return 2
    lines = []
    for name in (CHECKS if args[0] == "all" else (args[0],)):
        out = run_check(name, project, given)
        print("\n".join(out), flush=True)
        lines += out
    return 1 if any(l.startswith("FAIL") for l in lines) else 0


if __name__ == "__main__":
    if "--help" in sys.argv[1:3] or sys.argv[1:] == ["-h"]:
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
