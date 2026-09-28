#!/usr/bin/env python3
"""Classify a project's build record, so every tool notices at once when a project needs adopting.

Usage: record_check.py [project-dir] [--json]

Kinds:
  complete      docs/project/ holds intent.md (locked), milestones.md, state.md, brief.md, interfaces.md,
                decisions.md, and AGENTS.md has a labeled Commands section
  partial       some of those exist; the missing ones are listed
  legacy-v2     an earlier pipeline's files (slices.md, intent-anchor.md, qa-reports/, pipeline-state.md,
                phases.md) and no docs/project/milestones.md
  foreign-docs  no build record, but the project carries its own planning documents (docs/, PRD, ADRs,
                specs, a long README, milestone or roadmap files)
  none          code without any build record or planning documents
  empty         nothing to adopt (no code, no documents), for example a fresh idea folder
  inconclusive  the scan stopped at its limit (200,000 entries or 10 seconds) before it found code or
                documents, so "empty" cannot be claimed
Code is any file languages.py knows (the same table adopt.py and inventory.py use). Dependency, build, and
cache folders are pruned from the walk, never counted.
A venture project's own documents never count as foreign: truth/ and narrative/ always, and when truth/ exists
also helm's root files (blueprint-*.md, solution-concept.md, idea-stage-status.md, docent-ledger.md,
CODEX-HANDOFF.md) and its design/ and vnv/ folders. A helm project that has reached the build with no code yet
is therefore "empty": new work for /plan, not an adoption.
The route for anything but complete (and empty) is `/plan adopt`: read everything, reconstruct, verify,
lock with the owner.
Prints one line (or JSON with --json). Exit 0 for complete or empty, 3 when adoption is needed, 2 on bad usage.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from languages import CODE, DOC  # noqa: E402

RECORD = ("intent.md", "milestones.md", "state.md", "brief.md", "interfaces.md", "decisions.md")
LEGACY = ("slices.md", "intent-anchor.md", "pipeline-state.md", "phases.md", "qa-reports", "key-learnings.md")
PLANNING_NAMES = re.compile(r"(prd|spec|requirements|roadmap|milestone|design|architecture|adr|rfc|plan|vision|"
                            r"brief|decision|todo|notes|changelog)", re.I)
SKIP = {".git", "node_modules", ".venv", "venv", "dist", "build", ".next", "target", "Pods", "DerivedData",
        ".gate-copies", ".evidence", "__pycache__", "truth", "narrative"}
VENTURE_DIRS = {"design", "vnv"}
VENTURE_FILES = re.compile(r"^(blueprint-.*|solution-concept|idea-stage-status|docent-ledger|CODEX-HANDOFF)\.md$")


def scan(root, limit=200_000, seconds=10.0):
    """(code files, docs, planning docs, legacy files, complete?) from one pruned walk of the tree."""
    code = docs = 0
    planning, legacy = [], []
    seen, started, complete = 0, time.monotonic(), True
    venture = (root / "truth").is_dir()
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath).relative_to(root)
        top = not here.parts
        for d in list(dirnames):
            if d in LEGACY:
                legacy.append((here / d).as_posix())
        dirnames[:] = [d for d in dirnames if d not in SKIP and not (venture and top and d in VENTURE_DIRS)]
        for name in filenames:
            if venture and top and VENTURE_FILES.match(name):
                continue
            seen += 1
            rel = (here / name).as_posix()
            if name in LEGACY:
                legacy.append(rel)
            suffix = Path(name).suffix
            if suffix in CODE or suffix.lower() in CODE:
                code += 1
            elif suffix.lower() in DOC:
                docs += 1
                if not rel.startswith("docs/project/") and (PLANNING_NAMES.search(Path(name).stem) or rel.startswith("docs/")):
                    planning.append(rel)
        if seen > limit or time.monotonic() - started > seconds:
            complete = False
            break
    readme = root / "README.md"
    if readme.is_file() and len(readme.read_text(errors="ignore")) > 3000:
        planning.append("README.md")
    return code, docs, sorted(set(planning)), sorted(set(legacy)), complete


def classify(root):
    root = Path(root).resolve()
    rec = root / "docs/project"
    present = [f for f in RECORD if (rec / f).is_file()]
    missing = [f for f in RECORD if f not in present]
    agents = root / "AGENTS.md"
    commands = agents.is_file() and re.search(r"^#+\s*Commands\s*$", agents.read_text(errors="ignore"), re.M)
    intent_locked = (rec / "intent.md").is_file() and \
        "Locked by the owner" in (rec / "intent.md").read_text(errors="ignore")
    code, docs, planning, legacy, complete = scan(root)
    info = {"project": str(root), "venture": (root / "truth").is_dir(), "present": present, "missing": missing,
            "commands": bool(commands),
            "intent_locked": intent_locked, "code_files": code, "planning_docs": planning[:40],
            "legacy_files": legacy[:40], "scan_complete": complete}
    if not missing and commands and intent_locked:
        kind = "complete"
    elif present:
        kind = "partial"
        if not commands:
            info["missing"].append("AGENTS.md Commands")
        if not intent_locked and "intent.md" in present:
            info["missing"].append("intent lock")
    elif legacy:
        kind = "legacy-v2"
    elif planning:
        kind = "foreign-docs"
    elif code:
        kind = "none"
    elif not complete:
        kind = "inconclusive"
    else:
        kind = "empty"
    info["kind"] = kind
    info["route"] = None if kind in ("complete", "empty") else "/plan adopt"
    return info


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    root = Path(args[0]) if args else Path(".")
    if not root.is_dir():
        print(f"record_check: not a directory: {root}", file=sys.stderr)
        return 2
    info = classify(root)
    if "--json" in argv:
        print(json.dumps(info, indent=2))
    else:
        extra = f" · missing: {', '.join(info['missing'])}" if info["kind"] == "partial" else ""
        print(f"{info['kind']}{extra}" + (f" · route: {info['route']}" if info["route"] else ""))
    return 0 if info["kind"] in ("complete", "empty") else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
