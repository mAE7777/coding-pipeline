#!/usr/bin/env python3
"""Fingerprint the current state of a project's files.

Usage: fingerprint.py [project-dir] [--scope product|all] [--list]

The fingerprint is a SHA-256 over (path, content hash, executable bit) for every file in scope, read from the working
tree, so uncommitted edits and untracked files count and commits are not required. In a git repo the
file set is tracked files plus untracked files that are not ignored; elsewhere it is every file outside
common dependency and build folders.

Scope "product" (the default) leaves out the project's planning and evidence files (docs/project/,
.evidence/, truth/, narrative/, and every AGENTS.md and CLAUDE.md, nested ones included), so editing a plan
never makes product evidence stale. Scope "all" includes them. Operating-system clutter (.DS_Store,
Thumbs.db) and browser-tool output (.playwright-cli/ snapshots, test-results/, playwright-report/) are never
counted: looking at the product must not change its fingerprint.

Prints one line: "<scope>:<16 hex chars>" (with --list, the per-file hashes too). Exit 2 on bad usage.
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", ".next", "out", "target",
             "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "coverage", ".turbo",
             ".cache", "DerivedData", ".gradle", ".idea", ".vscode", ".evidence"}
PLANNING = ("docs/project/", ".evidence/", "truth/", "narrative/")
PLANNING_NAMES = ("AGENTS.md", "CLAUDE.md")
CLUTTER = (".DS_Store", "Thumbs.db", "desktop.ini")
TOOL_OUTPUT = (".playwright-cli", "test-results", "playwright-report")


def git_files(root):
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    if Path(top).resolve() != root.resolve():
        # A subdirectory of a larger repo: restrict to it.
        prefix = root.resolve().relative_to(Path(top).resolve()).as_posix() + "/"
    else:
        prefix = ""
    out = subprocess.run(["git", "-C", top, "ls-files", "-z", "--cached", "--others",
                          "--exclude-standard"], capture_output=True, check=True).stdout
    files = []
    for raw in out.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", "surrogateescape")
        if prefix and not rel.startswith(prefix):
            continue
        files.append(rel[len(prefix):])
    return sorted(set(files))


def walk_files(root):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            full = Path(dirpath) / name
            files.append(full.relative_to(root).as_posix())
    return sorted(files)


def in_scope(rel, scope):
    if rel.rsplit("/", 1)[-1] in CLUTTER or any(part in TOOL_OUTPUT for part in rel.split("/")[:-1]):
        return False
    if scope == "all":
        return True
    if rel.rsplit("/", 1)[-1] in PLANNING_NAMES:
        return False
    return not any(rel == p or rel.startswith(p) for p in PLANNING)


def file_hash(path):
    if path.is_symlink():
        return "link:" + hashlib.sha256(os.readlink(path).encode()).hexdigest()
    if not path.exists():
        return "deleted"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    executable = "x" if os.stat(path).st_mode & 0o111 else "-"
    return h.hexdigest() + executable


def combine(scope, rows):
    total = hashlib.sha256()
    for rel, h in rows:
        total.update(rel.encode("utf-8", "surrogateescape") + b"\0" + h.encode() + b"\n")
    return f"{scope}:{total.hexdigest()[:16]}"


def fingerprint(root, scope="product"):
    root = Path(root)
    files = git_files(root)
    if files is None:
        files = walk_files(root)
    rows = [(rel, file_hash(root / rel)) for rel in files if in_scope(rel, scope)]
    return combine(scope, rows), rows


def fingerprint_of(root, rels, scope="product"):
    """The fingerprint the given relative paths have under root (used to prove a copy matches its source)."""
    root = Path(root)
    return combine(scope, [(rel, file_hash(root / rel)) for rel in rels])


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    scope = "product"
    if "--scope" in argv:
        i = argv.index("--scope")
        if i + 1 >= len(argv) or argv[i + 1] not in ("product", "all"):
            print(__doc__.strip(), file=sys.stderr)
            return 2
        scope = argv[i + 1]
        args = [a for a in args if a != scope]
    root = Path(args[0]) if args else Path(".")
    if not root.is_dir():
        print(f"fingerprint: not a directory: {root}", file=sys.stderr)
        return 2
    fp, rows = fingerprint(root, scope)
    print(fp)
    if "--list" in argv:
        for rel, h in rows:
            print(f"{h[:16]}  {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
