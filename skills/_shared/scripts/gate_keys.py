#!/usr/bin/env python3
"""Read a project's gate settings from docs/project/gate.md (a local-only file).

Usage: gate_keys.py [project-dir] [--json]

Each setting is a line "<Label>: a, b" optionally followed by "- item" lines. Labels:
  Intent-bearing paths   files or folders that state intent (the blind copy drops them)
  Blind copy keeps       Markdown that is product content (kept in the blind copy)
  Review copy keeps      extra paths the review copy keeps (for example .git when tests need it)
  Gate exclude           paths neither copy gets
  Gate env files         .env files both copies get (default: none, apart from example/sample/template)
  Dependency folders     extra dependency folders the copies keep whole (node_modules, .venv, venv,
                         .yarn and Pods are always kept)
  Heavy commands         extra command prefixes that must run under the machine-wide heavy lock
  Gate network           extra hosts a checker's shell may reach (default: localhost only)
  Gate read allow        extra paths a checker may read (toolchains outside the default list)
  Gate command           the project's own gate script, run in the review copy at layer 1
  Design lint            the registered design lint command, run at layer 1 for UI milestones
  Stack pack             the stack pack name
  Blueprint              the composition blueprint this build follows, when the project has several
  Holdout                the path of an AI-feature eval holdout, outside the project

The file is local-only because these keys name the tooling. For projects set up before the file existed,
the same labels are read from AGENTS.md and the result says so under "source".
"""
import json
import re
import sys
from pathlib import Path

LABELS = ("Intent-bearing paths", "Blind copy keeps", "Review copy keeps", "Gate exclude", "Gate env files",
          "Dependency folders", "Heavy commands", "Gate network", "Gate read allow", "Gate command",
          "Design lint", "Stack pack", "Blueprint", "Holdout")
SINGLE = ("Gate command", "Design lint", "Stack pack", "Blueprint", "Holdout")


def parse_list(text, label):
    m = re.search(rf"^{re.escape(label)}:[ \t]*(.*)$", text, flags=re.M | re.I)
    if not m:
        return None
    items = [p.strip().strip("`") for p in m.group(1).split(",") if p.strip()]
    for line in text[m.end():].split("\n")[1:]:
        s = line.strip()
        if s.startswith("- "):
            items.append(s[2:].strip().strip("`"))
        elif s:
            break
    return [i for i in items if i and i.lower() != "none"]


def parse_single(text, label):
    m = re.search(rf"^{re.escape(label)}:[ \t]*(.+)$", text, flags=re.M | re.I)
    if not m:
        return None
    value = m.group(1).strip().strip("`")
    return None if value.lower() in ("", "none") else value


def read_keys(project):
    project = Path(project)
    gate = project / "docs/project/gate.md"
    agents = project / "AGENTS.md"
    if gate.is_file():
        text, source = gate.read_text(encoding="utf-8"), "docs/project/gate.md"
    elif agents.is_file():
        text, source = agents.read_text(encoding="utf-8"), "AGENTS.md (legacy location)"
    else:
        text, source = "", "none"
    keys = {"source": source}
    for label in LABELS:
        if label in SINGLE:
            keys[label] = parse_single(text, label)
        else:
            keys[label] = parse_list(text, label) or []
    return keys


def commands(project):
    """Labeled command lines from AGENTS.md's Commands section: install, build, test, run, demo, and any
    other "<label>: <command>" line there."""
    agents = Path(project) / "AGENTS.md"
    if not agents.is_file():
        return {}
    text = agents.read_text(encoding="utf-8")
    m = re.search(r"^#+\s*Commands\s*$(.*?)(?=^#+\s|\Z)", text, flags=re.M | re.S | re.I)
    body = m.group(1) if m else ""
    out = {}
    for line in body.splitlines():
        lm = re.match(r"^\s*[-*]?\s*`?([a-z][a-z0-9 _-]{1,24})`?:\s*`?(.+?)`?\s*$", line, flags=re.I)
        if lm:
            out[lm.group(1).strip().lower()] = lm.group(2).strip()
    return out


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    project = Path(args[0]) if args else Path(".")
    keys = read_keys(project)
    keys["commands"] = commands(project)
    print(json.dumps(keys, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
