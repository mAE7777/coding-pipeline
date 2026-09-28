#!/usr/bin/env python3
"""Build the two copies of a milestone candidate that the gate's isolated checkers work in.

Usage:
  gate_copies.py make <project-dir> [--dest <dir>] [--milestone M<k>]
  gate_copies.py cleanup <copies-dir>
  gate_copies.py sweep [--dest <dir>] [--older-than-hours 48]

`make` creates <dest>/<random>/ (dest defaults to ~/.gate-copies; both mode 0700; the random name keeps the
project's name out of the checkers' paths) holding:
  review/        the candidate, for the correctness reviewer (who may edit it while probing)
  demo/          an identical, untouched copy, for the demo run from a clean start
  blind/         the candidate minus everything that states intent, for the intent evaluator
  manifest.json  outside both copies, so no checker can read where they came from
Settings come from docs/project/gate.md (see gate_keys.py).

What a copy holds. Exactly the files in the candidate's product fingerprint (tracked plus non-ignored
untracked files, minus the build record), plus whole dependency folders (node_modules, .venv, venv, .yarn,
Pods, and "Dependency folders"), plus AGENTS.md. Both copies leave out docs/project/ (the builder's record
and wording; checkers get their inputs from rendered packs), .evidence/, .git (unless "Review copy keeps"
names it for the review copy), "Gate exclude" paths, and .env files other than example/sample/template ones
unless named in "Gate env files". Copies are APFS clones (`cp -c`: instant, copy-on-write) where the
filesystem supports it, otherwise plain copies (method "copy" is recorded).

Paths back into the real project. Symlink targets and the small files where package managers write absolute
paths (node_modules/.bin and venv bin scripts, site-packages .pth, .egg-link, direct_url.json, setuptools
__editable__ finders, pyvenv.cfg) are rewritten to the copy. A resolution probe then fails the run if any such
reference is left, because a copy that still resolves into the live tree would test the wrong code.

Proof the copy is the candidate. Every kept product file is hashed again in the review copy and must equal
the source's fingerprint row (rewritten links excepted and listed); a mismatch means the tree changed while
copying and FAILs the run.

The blind copy also drops truth/, narrative/, .claude/, .github/, test folders (tests, test, __tests__,
cypress always; spec, specs, e2e only when they hold test code) and test files, Rust #[cfg(test)] modules,
Markdown outside "Blind copy keeps", spec-style requirement files (requirements*.json, acceptance*),
legacy intent-anchor*/slices*/contracts* files, "Intent-bearing paths", and the description field of
package.json, pyproject.toml, Cargo.toml, and composer.json. Its AGENTS.md holds only the labeled command
lines and command blocks of the Commands section.

Scans on the blind copy (generated files included):
  - leak scan: distinctive five-word phrases from docs/project/intent.md and the milestone's section of
    milestones.md. A hit in a non-code file FAILs (intent leaked into documentation); a hit in a code file
    is listed as product text for the judge (user-facing strings rightly share words with done examples).
  - ID scan: build-record IDs (I-D3, L-01, M1.D2, M1.C1, M1-F03) anywhere FAIL: the builder wrote intent
    references into the product. Generic-looking IDs (D-001, C-01, A-01, U-01) are listed as warnings.

Output: the manifest as JSON on stdout. Exit 0 = usable copies, 1 = a problem above (the copies are kept
for inspection), 2 = bad usage.
"""
import datetime
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fingerprint import file_hash, fingerprint  # noqa: E402
from gate_keys import commands, read_keys  # noqa: E402

DEFAULT_ROOT = Path.home() / ".gate-copies"
DEP_DIRS = ("node_modules", ".venv", "venv", ".yarn", "Pods")
BLIND_DIRS = ("truth", "narrative", ".claude", ".github", ".cursor", ".windsurf", ".continue", ".aider")
# Documents state intent in any format: Markdown and its cousins, doc-named text files, extensionless READMEs and
# changelogs, and other coding tools' rule files.
DOC_SUFFIX = {".md", ".mdx", ".rst", ".adoc", ".org"}
DOC_NAME = re.compile(r"^(readme|changelog|changes|history|contributing|notes|todo|roadmap|design|architecture|"
                      r"requirements-notes)(\.(txt|text))?$", re.I)
RULE_FILES = {".cursorrules", ".windsurfrules", ".clinerules"}
PATH_DATA = re.compile(r"""(\b(d|points|path)\s*[=:]\s*["'`])|((^|["'`\s])[MmLlHhVvCcSsQqTtAaZz]\s*-?\d+(\.\d+)?[\s,]+-?\d)""")
TEST_DIRS_ALWAYS = {"tests", "test", "__tests__", "cypress"}
TEST_DIRS_MAYBE = {"spec", "specs", "e2e"}
TEST_FILE = re.compile(r"(\.test\.|\.spec\.|^test_.*\.py$|_test\.(py|go)$|Tests?\.swift$|\.stories\.|^conftest\.py$)")
TEST_CODE = re.compile(r"\b(describe|it|test)\s*\(|\bexpect\s*\(|\bassert\b|XCTest|#\[test\]|unittest|pytest")
LEGACY = re.compile(r"^(intent-anchor|slices|contracts)[^/]*\.md$")
SPEC_FILES = re.compile(r"^(requirements[^/]*\.json|acceptance[^/]*)$", re.I)
ENV_FILE = re.compile(r"^\.env(\..+)?$")
ENV_OK = re.compile(r"(example|sample|template)", re.I)
CODE_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".go", ".rs", ".swift", ".kt", ".java",
            ".rb", ".vue", ".svelte", ".html", ".css", ".c", ".cc", ".cpp", ".h", ".cs", ".gd", ".lua", ".dart"}
STRONG_ID = re.compile(r"\b(I-D\d+[a-z]?|L-\d{2,3}|M\d+\.[DC]\d+|M\d+-F\d{2,3})\b")
WEAK_ID = re.compile(r"\b(D-\d{3}|C-\d{2}|A-\d{2}|U-\d{2})\b")
STOP = set("the a an and or of to in on for with by at is are be as it this that from when if then its "
           "their they them you your we our can will shall not no any each into than so".split())


def clone(src, dst):
    r = subprocess.run(["cp", "-cR", str(src), str(dst)], capture_output=True, text=True)
    if r.returncode == 0:
        return "clone"
    if dst.exists():
        shutil.rmtree(dst)
    r = subprocess.run(["cp", "-R", str(src), str(dst)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"copy failed: {r.stderr.strip()}")
    return "copy"


def remove(path, root, log):
    if not (path.exists() or path.is_symlink()):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    log.append(path.relative_to(root).as_posix())


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in DEP_DIRS]
        yield Path(dirpath), dirnames, filenames


def prune(copy, keep_files, keep_dirs, log):
    """Delete everything that is neither a kept file nor inside a kept folder; then drop empty folders."""
    removed = 0
    visited = []
    for dirpath, dirnames, filenames in os.walk(copy, topdown=True):
        d = Path(dirpath)
        rel_d = "" if d == copy else d.relative_to(copy).as_posix()
        visited.append(d)
        descend = []
        for name in dirnames:
            rel = f"{rel_d}/{name}" if rel_d else name
            if (d / name).is_symlink():
                filenames.append(name)  # a link to a folder is one entry, kept only if it is in the set
            elif rel in keep_dirs or name in DEP_DIRS:
                continue
            else:
                descend.append(name)
        dirnames[:] = descend
        for name in filenames:
            rel = f"{rel_d}/{name}" if rel_d else name
            if rel not in keep_files:
                (d / name).unlink()
                removed += 1
    for d in reversed(visited):
        if d != copy and not any(d.iterdir()):
            d.rmdir()
    log.append(f"(pruned {removed} files outside the product file set)")


def rewrite_candidates(copy):
    """Symlinks anywhere, plus small text files where package managers write absolute paths."""
    for dirpath, dirnames, filenames in os.walk(copy):
        d = Path(dirpath)
        for name in dirnames + filenames:
            p = d / name
            if p.is_symlink():
                yield p, "link"
        parts = d.parts
        in_bin = d.name in ("bin", ".bin") and any(x in parts for x in DEP_DIRS)
        in_site = "site-packages" in parts
        for name in filenames:
            p = d / name
            if p.is_symlink():
                continue
            editable = in_site and name.startswith("__editable__") and name.endswith(".py")
            if in_bin or editable or (in_site and (name.endswith((".pth", ".egg-link")) or name == "direct_url.json")) \
                    or name == "pyvenv.cfg":
                yield p, "text"


def spellings(src):
    """Every way the project path may be written: resolved, as given, and without macOS's /private."""
    forms = {str(src.resolve()), str(src.absolute())}
    for f in list(forms):
        if f.startswith("/private/"):
            forms.add(f[len("/private"):])
    return sorted(forms, key=len, reverse=True)


def rewrite_paths(src, copy):
    forms, copy_s = spellings(src), str(copy)
    rewritten, failed = [], []
    for p, kind in rewrite_candidates(copy):
        try:
            if kind == "link":
                target = os.readlink(p)
                for f in forms:
                    if target.startswith(f + "/") or target == f:
                        p.unlink()
                        os.symlink(copy_s + target[len(f):], p)
                        rewritten.append(p.relative_to(copy).as_posix())
                        break
            else:
                if p.stat().st_size > 262144:
                    continue
                data = p.read_bytes()
                new = data
                for f in forms:
                    new = new.replace(f.encode() + b"/", copy_s.encode() + b"/")
                    new = new.replace(f.encode() + b"'", copy_s.encode() + b"'")
                    new = new.replace(f.encode() + b'"', copy_s.encode() + b'"')
                if new != data:
                    p.write_bytes(new)
                    rewritten.append(p.relative_to(copy).as_posix())
        except OSError as exc:
            failed.append(f"{p.relative_to(copy)}: {exc.strerror or exc}")
    return rewritten, failed


def resolution_probe(src, copy):
    forms = spellings(src)
    left = []
    for p, kind in rewrite_candidates(copy):
        try:
            if kind == "link":
                target = os.readlink(p)
                if any(target.startswith(f + "/") or target == f for f in forms):
                    left.append(p.relative_to(copy).as_posix())
            elif p.stat().st_size <= 262144:
                data = p.read_bytes()
                if any(f.encode() in data for f in forms):
                    left.append(p.relative_to(copy).as_posix())
        except OSError:
            continue
    return left


def kept_product_files(rows, keys):
    """The product files a copy keeps, before blind stripping: fingerprint rows minus excluded paths and
    secret .env files."""
    excl = [e.rstrip("/") for e in keys["Gate exclude"]]
    env_keep = set(keys["Gate env files"])
    out = {}
    for rel, h in rows:
        if h == "deleted":
            continue
        if any(rel == e or rel.startswith(e + "/") for e in excl):
            continue
        name = rel.rsplit("/", 1)[-1]
        if ENV_FILE.match(name) and not ENV_OK.search(name) and rel not in env_keep:
            continue
        out[rel] = h
    return out


def build_copy(src, copy, rows, keys, kind):
    method = clone(src, copy)
    log = []
    product = kept_product_files(rows, keys)
    keep_files = set(product) | set(keys["Gate env files"])
    if (src / "AGENTS.md").is_file():
        keep_files.add("AGENTS.md")
    keep_dirs = {d.rstrip("/") for d in keys["Dependency folders"]}
    if kind == "review":
        for extra in keys["Review copy keeps"]:
            extra = extra.rstrip("/")
            if (src / extra).is_dir():
                keep_dirs.add(extra)
            else:
                keep_files.add(extra)
    prune(copy, keep_files, keep_dirs, log)
    rewritten, failed = rewrite_paths(src, copy)
    mismatched = sorted(rel for rel, h in product.items()
                        if rel not in rewritten and file_hash(copy / rel) != h)
    return {"path": str(copy), "method": method, "product_files": len(product), "stripped": log,
            "rewritten": rewritten, "rewrite_failures": failed,
            "unresolved_references": resolution_probe(src, copy), "changed_since_fingerprint": mismatched}


def test_dir_holds_tests(path):
    total = hits = 0
    for dirpath, _, filenames in os.walk(path):
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix not in CODE_EXT:
                continue
            total += 1
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")[:20000]
            except OSError:
                continue
            if TEST_FILE.search(name) or TEST_CODE.search(text):
                hits += 1
    return total > 0 and hits * 2 >= total


def strip_rust_tests(path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    out, i, changed = [], 0, False
    for m in re.finditer(r"#\[cfg\(test\)\]\s*mod\s+\w+\s*\{", text):
        if m.start() < i:
            continue
        depth, j = 1, m.end()
        while j < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            j += 1
        out.append(text[i:m.start()])
        i, changed = j, True
    if changed:
        out.append(text[i:])
        path.write_text("".join(out), encoding="utf-8")
    return changed


def blank_descriptions(blind, log):
    for name in ("package.json", "composer.json"):
        p = blind / name
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("description"):
                    data["description"] = ""
                    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                    log.append(f"{name}#description")
            except ValueError:
                pass
    for name in ("pyproject.toml", "Cargo.toml"):
        p = blind / name
        if p.is_file():
            text = p.read_text(encoding="utf-8")
            new = re.sub(r'^(description\s*=\s*)(".*?"|\'.*?\')\s*$', r'\1""', text, flags=re.M)
            if new != text:
                p.write_text(new, encoding="utf-8")
                log.append(f"{name}#description")


def commands_only(project):
    cmds = commands(project)
    lines = ["# Commands", ""]
    lines += [f"{label}: {cmd}" for label, cmd in cmds.items()] or ["(none recorded)"]
    agents = project / "AGENTS.md"
    if agents.is_file():
        text = agents.read_text(encoding="utf-8")
        m = re.search(r"^#+\s*Commands\s*$(.*?)(?=^#+\s|\Z)", text, flags=re.M | re.S | re.I)
        for block in re.findall(r"```(?:bash|sh|shell|zsh)?\n(.*?)```", m.group(1) if m else "", flags=re.S):
            lines += ["", "```", block.strip(), "```"]
    return "\n".join(lines) + "\n"


def blind_strip(src, blind, keys, log):
    for name in (".git",) + BLIND_DIRS:
        remove(blind / name, blind, log)
    keeps = [k.rstrip("/") for k in keys["Blind copy keeps"]]
    for extra in keys["Intent-bearing paths"]:
        remove(blind / extra.rstrip("/"), blind, log)
    for d, dirnames, filenames in walk(blind):
        for name in list(dirnames):
            if name in TEST_DIRS_ALWAYS or (name in TEST_DIRS_MAYBE and test_dir_holds_tests(d / name)):
                remove(d / name, blind, log)
                dirnames.remove(name)
            elif name in TEST_DIRS_MAYBE:
                log.append(f"(kept {(d / name).relative_to(blind).as_posix()}/: no test code in it)")
        for name in filenames:
            p = d / name
            rel = p.relative_to(blind).as_posix()
            kept = any(rel == k or rel.startswith(k + "/") for k in keeps)
            if (Path(name).suffix.lower() in DOC_SUFFIX or DOC_NAME.match(name) or name in RULE_FILES) and not kept:
                remove(p, blind, log)
            elif TEST_FILE.search(name) or LEGACY.match(name) or SPEC_FILES.match(name):
                remove(p, blind, log)
            elif name.endswith(".rs") and strip_rust_tests(p):
                log.append(f"{rel}#cfg(test)")
    blank_descriptions(blind, log)
    (blind / "AGENTS.md").write_text(commands_only(src), encoding="utf-8")
    (blind / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")


def leftover_intent(blind, keys):
    bad = [d for d in BLIND_DIRS + (".git", "docs/project") if (blind / d).exists()]
    keeps = [k.rstrip("/") for k in keys["Blind copy keeps"]]
    for d, dirnames, filenames in walk(blind):
        for name in filenames:
            rel = (d / name).relative_to(blind).as_posix()
            kept = any(rel == k or rel.startswith(k + "/") for k in keeps)
            if name.endswith(".md") and rel not in ("AGENTS.md", "CLAUDE.md") and not kept:
                bad.append(rel)
            if LEGACY.match(name):
                bad.append(rel)
    bad += [e for e in keys["Intent-bearing paths"] if (blind / e.rstrip("/")).exists()]
    return bad


CJK_CHAR = r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]"
CJK_STOP = set("\u7684\u4e86\u662f\u5728\u548c\u4e0e\u53ca\u6216\u4e00\u4e2a\u6211\u4f60\u4ed6\u5979\u5b83\u4eec\u8fd9\u90a3\u6709\u4e5f\u90fd\u5c31\u8981\u4f1a\u80fd\u53ef\u4ee5\u4e3a\u7740\u8fc7\u628a\u88ab\u8ba9\u7ed9\u5bf9\u4ece\u5230\u800c\u4e14\u4f46\u5f88\u66f4\u6700\u53c8\u518d\u8fd8\u4e4b\u5176\u6240")


def shingles(text, n=5):
    """Every run of n tokens with at least four that carry meaning. A token is an English word, or a single
    Chinese, Japanese, or Korean character, so intent written in those languages is compared too."""
    words = [w for w in re.findall(rf"[a-z0-9]+|{CJK_CHAR}", text.lower())
             if len(w) > 1 or re.match(CJK_CHAR, w)]
    out = set()
    for i in range(len(words) - n + 1):
        window = words[i:i + n]
        if sum(1 for w in window if w not in STOP and w not in CJK_STOP) >= 4:
            out.add(" ".join(window))
    return out


def intent_phrases(project, milestone):
    texts = []
    intent = project / "docs/project/intent.md"
    if intent.is_file():
        body = re.sub(r"<!--.*?-->", "", intent.read_text(encoding="utf-8"), flags=re.S)
        texts.append(re.sub(r"<[^>]+>", " ", body))
    ms = project / "docs/project/milestones.md"
    if ms.is_file() and milestone:
        m = re.search(rf"^## {re.escape(milestone)} ·.*?(?=^## M\d+ ·|\Z)", ms.read_text(encoding="utf-8"),
                      flags=re.M | re.S)
        if m:
            texts.append(m.group(0))
    phrases = set()
    for t in texts:
        phrases |= shingles(t)
    if any(t.strip() for t in texts) and not phrases:
        raise ValueError("the intent yields no comparable phrases, so the blind copy cannot be scanned for it")
    return phrases


def scan_blind(blind, phrases):
    doc_hits, code_hits, strong, weak = [], [], [], []
    for dirpath, dirnames, filenames in os.walk(blind):
        dirnames[:] = [d for d in dirnames if d not in DEP_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            try:
                if p.is_symlink() or p.stat().st_size > 1048576:
                    continue
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            rel = p.relative_to(blind).as_posix()
            found = shingles(text) & phrases if phrases else set()
            if found:
                hit = f"{rel}: \"{sorted(found)[0]}\""
                (code_hits if p.suffix in CODE_EXT else doc_hits).append(hit)
            for m in STRONG_ID.finditer(text):
                line = text[text.rfind("\n", 0, m.start()) + 1:text.find("\n", m.end()) if "\n" in text[m.end():] else len(text)]
                if p.suffix.lower() == ".svg" or PATH_DATA.search(line):
                    continue  # drawing coordinates such as "L-20 30" in path data, not a build-record ID
                strong.append(f"{rel}: {m.group(0)}")
                break
            for m in WEAK_ID.finditer(text):
                weak.append(f"{rel}: {m.group(0)}")
                break
    return doc_hits, code_hits, strong, weak


def make(argv):
    if not argv or argv[0].startswith("--"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    src = Path(argv[0]).absolute()
    if not src.is_dir():
        print(f"gate_copies: not a directory: {src}", file=sys.stderr)
        return 2
    opts = {argv[i]: argv[i + 1] for i in range(1, len(argv) - 1) if argv[i] in ("--dest", "--milestone")}
    keys = read_keys(src)
    fp, rows = fingerprint(src, "product")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = Path(opts.get("--dest") or DEFAULT_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    base = root / secrets.token_hex(8)
    base.mkdir(mode=0o700)
    manifest = {"source": str(src), "fingerprint": fp, "milestone": opts.get("--milestone"), "created": stamp,
                "base": str(base), "keys_source": keys["source"]}
    manifest["review"] = build_copy(src, base / "review", rows, keys, "review")
    manifest["demo"] = build_copy(src, base / "demo", rows, keys, "review")
    manifest["blind"] = build_copy(src, base / "blind", rows, keys, "blind")
    blind = base / "blind"
    stripped = []
    blind_strip(src, blind, keys, stripped)
    manifest["blind"]["stripped"] += stripped
    manifest["leftover_intent_files"] = leftover_intent(blind, keys)
    try:
        phrases, scan_problem = intent_phrases(src, opts.get("--milestone")), []
    except ValueError as exc:
        phrases, scan_problem = set(), [str(exc)]
    doc_hits, code_hits, strong, weak = scan_blind(blind, phrases)
    manifest["leaks_in_documents"] = doc_hits
    manifest["intent_phrases_in_code"] = code_hits
    manifest["build_record_ids"] = strong
    manifest["id_like_tokens"] = weak
    manifest["secrets_copied"] = keys["Gate env files"]
    problems = {
        "leftover intent files": manifest["leftover_intent_files"],
        "intent phrases in documents": doc_hits,
        "build-record IDs in the blind copy": strong,
        "unresolved references (review)": manifest["review"]["unresolved_references"],
        "unresolved references (demo)": manifest["demo"]["unresolved_references"],
        "unresolved references (blind)": manifest["blind"]["unresolved_references"],
        "files changed while copying": manifest["review"]["changed_since_fingerprint"],
        "intent scan could not run": scan_problem,
    }
    manifest["problems"] = {k: v for k, v in problems.items() if v}
    manifest["status"] = "FAIL" if manifest["problems"] else "PASS"
    (base / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
    return 1 if manifest["problems"] else 0


def cleanup(argv):
    if len(argv) not in (1, 3):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    base = Path(argv[0]).resolve()
    root = Path(argv[2]).resolve() if len(argv) == 3 and argv[1] == "--dest" else DEFAULT_ROOT.resolve()
    if base.parent != root or not (base / "manifest.json").exists():
        print(f"gate_copies: refusing to delete {base} (not a copies run under {root})", file=sys.stderr)
        return 2
    shutil.rmtree(base)
    return 0


def sweep(argv):
    opts = {argv[i]: argv[i + 1] for i in range(len(argv) - 1) if argv[i] in ("--dest", "--older-than-hours")}
    root = Path(opts.get("--dest") or DEFAULT_ROOT)
    limit = time.time() - float(opts.get("--older-than-hours", 48)) * 3600
    removed = 0
    for base in root.glob("*") if root.exists() else []:
        if (base / "manifest.json").exists() and base.stat().st_mtime < limit:
            shutil.rmtree(base)
            removed += 1
    print(f"gate_copies: swept {removed} old run(s)")
    return 0


def main(argv):
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    cmd = argv[0]
    if cmd == "make":
        return make(argv[1:])
    if cmd == "cleanup":
        return cleanup(argv[1:])
    if cmd == "sweep":
        return sweep(argv[1:])
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
