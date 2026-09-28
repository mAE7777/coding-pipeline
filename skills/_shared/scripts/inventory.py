#!/usr/bin/env python3
"""List candidate sites for the reviewer to adjudicate: silent degradation, unfinished work, and the
wiring surface (routes, model calls, events).

Usage: inventory.py [project-dir]

This is a candidate list, not a verdict. Degradation categories: swallowed-error, silent-optional,
fallback, stand-in-import, feature-flag, unfinished. Wiring categories, compared by the reviewer with the
milestone's wiring table (a route, model call, or event no row accounts for is UNWIRED, UNCONSUMED, or
PHANTOM until shown otherwise): route (HTTP handlers and page routes), model-call (calls into model
provider SDKs and endpoints), event (emits and listeners). Test, fixture, mock, and vendored code is
skipped. Every language in languages.py is read except markup, styles, and SQL; the last line names the
languages present in the tree that were not scanned, so "no candidates" is never mistaken for a clean read of
code that was never looked at. Output: "category  path:line  text" lines, then a count per category. Exit 0
always (candidates are not failures), 2 on bad usage.
"""
import os
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", ".next", "out", "target",
             "__pycache__", "coverage", "vendor", "Pods", "DerivedData", ".evidence", "fixtures",
             "mocks", "__mocks__", "tests", "test", "spec", "__tests__", ".build", "docs"}
TEST_FILE = re.compile(r"(\.test\.|\.spec\.|_test\.|test_[^/]*\.py$|Tests?\.swift$|\.stories\.)")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from languages import CODE, NOT_SCANNED  # noqa: E402
EXT = {ext for ext, lang in CODE.items() if lang not in NOT_SCANNED}
UNSCANNED = {}

PATTERNS = [
    ("swallowed-error", re.compile(r"catch\s*(\([^)]*\))?\s*\{\s*\}", re.S)),
    ("swallowed-error", re.compile(r"catch\s*(\([^)]*\))?\s*\{\s*return\s*(null|undefined|\[\]|\{\}|''|\"\"|0|false)?\s*;?\s*\}", re.S)),
    ("swallowed-error", re.compile(r"\.catch\(\s*\(?[^)]*\)?\s*=>\s*(null|undefined|\[\]|\{\}|''|\"\"|0|false|\{\s*\})\s*\)")),
    ("swallowed-error", re.compile(r"except(\s+[\w.,() ]+)?(\s+as\s+\w+)?\s*:\s*\n\s*(pass|return( None| \[\]| \{\}| \"\"| ''| 0| False)?|continue)\s*$", re.M)),
    ("swallowed-error", re.compile(r"if\s+err\s*!=\s*nil\s*\{\s*return\s+nil\s*\}")),
    ("silent-optional", re.compile(r"\btry\?\s")),
    ("silent-optional", re.compile(r"\.(unwrap_or_default|ok)\(\)")),
    ("fallback", re.compile(r"\bfall[_ -]?back\b", re.I)),
    ("stand-in-import", re.compile(r"(import|from|require\()[^\n]*?['\"][^'\"\n]*(fixture|mock|fake|dummy|sample[-_]?data)[^'\"\n]*['\"]", re.I)),
    ("stand-in-import", re.compile(r"^[ \t]*from\s+[\w.]*(fixtures?|mocks?|fakes?)\b[\w.]*\s+import", re.M | re.I)),
    ("feature-flag", re.compile(r"\b(process\.env|os\.environ(\.get)?|getenv)\W+['\"]?[A-Z0-9_]*(FLAG|ENABLE|DISABLE|FEATURE)[A-Z0-9_]*")),
    ("feature-flag", re.compile(r"\b(featureFlag|isEnabled|FEATURE_[A-Z0-9_]+)\b")),
    ("unfinished", re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")),
    ("unfinished", re.compile(r"(NotImplementedError|not implemented|unimplemented!\(|todo!\(|fatalError\(\"TODO)", re.I)),
    ("route", re.compile(r"\b(app|router|server|api|bp|blueprint)\.(get|post|put|patch|delete|route|all|use)\s*\(\s*['\"`][^'\"`]+", re.I)),
    ("route", re.compile(r"^[ \t]*@(app|router|api|bp)\.(get|post|put|patch|delete|route|websocket)\s*\(\s*['\"][^'\"]+", re.M)),
    ("route", re.compile(r"^[ \t]*export\s+(async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE)\b", re.M)),
    ("route", re.compile(r"\bhttp\.HandleFunc\(\s*\"[^\"]+|\.(HandleFunc|Handle)\(\s*\"[^\"]+")),
    ("model-call", re.compile(r"\b(anthropic|openai|OpenAI|Anthropic|genai|GoogleGenerativeAI|ollama|replicate|cohere|mistral)\b[^\n]{0,60}\.(messages|chat|completions|responses|generate\w*|create|invoke|embed\w*)\b")),
    ("model-call", re.compile(r"\.(messages|chat\.completions|responses|completions)\.(create|stream|parse)\s*\(|"
                              r"\bgenerateContent(Stream)?\s*\(|\b(ChatAnthropic|ChatOpenAI|ChatGoogleGenerativeAI)\s*\(")),
    ("model-call", re.compile(r"(api\.anthropic\.com|api\.openai\.com|generativelanguage\.googleapis\.com|/v1/(messages|chat/completions|responses))")),
    ("event", re.compile(r"\.(emit|dispatchEvent|publish|postMessage)\s*\(\s*['\"`]?[\w:.-]+")),
    ("event", re.compile(r"\.(on|addEventListener|subscribe|addListener)\s*\(\s*['\"`][\w:.-]+")),
    ("event", re.compile(r"NotificationCenter\.default\.(post|addObserver)")),
]


def files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix in EXT and not TEST_FILE.search(p.as_posix()):
                yield p
            elif CODE.get(p.suffix) in NOT_SCANNED:
                UNSCANNED[CODE[p.suffix]] = UNSCANNED.get(CODE[p.suffix], 0) + 1


def main(argv):
    if len(argv) > 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    root = Path(argv[0]) if argv else Path(".")
    if not root.is_dir():
        print(f"inventory: not a directory: {root}", file=sys.stderr)
        return 2
    hits, counts = [], {}
    for p in files(root):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for cat, rx in PATTERNS:
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                snippet = " ".join(m.group(0).split())[:90]
                key = (cat, p, line)
                if key in {(h[0], h[1], h[2]) for h in hits}:
                    continue
                hits.append((cat, p, line, snippet))
                counts[cat] = counts.get(cat, 0) + 1
    for cat, p, line, snippet in sorted(hits, key=lambda h: (h[0], str(h[1]), h[2])):
        print(f"{cat:<16} {p.relative_to(root)}:{line}  {snippet}")
    summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "no candidates"
    print(f"inventory: {summary}")
    if UNSCANNED:
        print("not scanned (markup, styles, SQL): " + ", ".join(f"{k} {v} file(s)" for k, v in sorted(UNSCANNED.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
