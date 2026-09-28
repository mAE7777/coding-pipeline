#!/usr/bin/env python3
"""The one parser for the idea-anchor closure and blueprint part coverage, shared by milestone_lint.py
and any other checker that reads the same footer, so two checkers can never demand different formats.

Usage: closure.py <milestones.md> [--anchor <idea-anchor.md>] [--blueprint <blueprint.md> | --find-blueprint <project>]

Grammar, in milestones.md:
  a heading "## Idea-anchor closure" (any "## idea-anchor <word>" heading is accepted, case-insensitive),
  then a table whose rows are "| <key> | <what it is> | <where it lives> |" and where the last cell is one of
    IN-MILESTONE @M<k>
    named non-goal (<reason>)
    contract-blocked @<entry>
  and, when the product has blueprint parts, a "Parts: [P1] [P3]" line in each milestone that builds them.
A key is the anchor's own item id, never renumbered: K<n>, or any capital id ending in a number (P3, R-P12).
An anchor's items are the rows of its tables whose first cell is such a key; a blueprint's parts are lines
starting "**P<n>".

The composition blueprint of a project (find_blueprint) is the one root file blueprint-*.md (or blueprint.md),
or, when there are several, the one named by a "Blueprint: <file>" line in docs/project/gate.md; several with
none named is a problem, never a guess. truth/blueprint.md (helm's progress table) is never a composition
blueprint.

Prints one line per problem ("FAIL  closure  ...") and exits 1 when there is any, else 0.
"""
import re
import sys
from pathlib import Path

HEADING = re.compile(r"^##\s+idea-anchor\s+\S.*$", re.I | re.M)
ITEM = r"(?:K\d+|[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*\d+[a-z]?)"
ROW = re.compile(rf"^\|\s*({ITEM})\s*\|(.*)\|\s*$")
STATE = re.compile(r"^(IN-MILESTONE @M\d+|named non-goal \(.+\)|contract-blocked @\S+)$", re.I)
NOT_A_STATE = re.compile(r"\b(later|v2|future version|someday|tbd|to be decided)\b", re.I)
PARTS = re.compile(r"^Parts:\s*(.*)$", re.M)
PART_ID = re.compile(r"\[(P\d+[a-z]?)\]")
MILESTONE = re.compile(r"^## (M\d+) · ", re.M)


def closure_section(text):
    m = HEADING.search(text)
    if not m:
        return None
    rest = text[m.end():]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def closure_rows(text):
    """[(key, what, where)] from the closure table; None when the file has no closure heading."""
    section = closure_section(text)
    if section is None:
        return None
    rows = []
    for line in section.splitlines():
        m = ROW.match(line.strip())
        if m:
            cells = [c.strip() for c in m.group(2).split("|")]
            rows.append((m.group(1), cells[0] if cells else "", cells[-1] if cells else ""))
    return rows


def natural(key):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", key)]


def anchor_items(anchor_text):
    return sorted(set(re.findall(rf"^\|\s*({ITEM})\s*\|", anchor_text, re.M)), key=natural)


def find_blueprint(root):
    """(path or None, problem or None): the project's composition blueprint, never a guess."""
    root = Path(root)
    found = sorted(root.glob("blueprint-*.md")) + ([root / "blueprint.md"] if (root / "blueprint.md").is_file() else [])
    gate = root / "docs/project/gate.md"
    named = re.search(r"^Blueprint:[ \t]*`?([^`\n]+?)`?[ \t]*$", gate.read_text(encoding="utf-8"), re.M | re.I) \
        if gate.is_file() else None
    if named and named.group(1).strip().lower() != "none":
        path = root / named.group(1).strip()
        return (path, None) if path.is_file() else (None, f"docs/project/gate.md names Blueprint {named.group(1)}, "
                                                          "which does not exist")
    if len(found) > 1:
        return None, ("several composition blueprints (" + ", ".join(p.name for p in found) + "): name the one this "
                      "build follows in docs/project/gate.md as 'Blueprint: <file>'")
    return (found[0], None) if found else (None, None)


def blueprint_parts(blueprint_text):
    return sorted(set(re.findall(r"^\*\*(P\d+[a-z]?)\b", blueprint_text, re.M)))


def milestone_parts(text):
    """{M<k>: [P..]} from each milestone's Parts line."""
    out = {}
    heads = list(MILESTONE.finditer(text))
    for i, h in enumerate(heads):
        body = text[h.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        m = PARTS.search(body)
        out[h.group(1)] = PART_ID.findall(m.group(1)) if m else []
    return out


def problems(milestones_text, anchor_text=None, blueprint_text=None):
    out = []
    rows = closure_rows(milestones_text)
    ids = set(MILESTONE.findall(milestones_text))
    if rows is not None:
        if not rows:
            out.append("the closure heading has no '| <key> | ... | ... |' rows")
        for key, what, where in rows:
            if not STATE.match(where):
                out.append(f"{key}: '{where[:60]}' is not IN-MILESTONE @M<k>, named non-goal (reason), "
                           "or contract-blocked @entry")
            elif NOT_A_STATE.search(where):
                out.append(f"{key}: '{NOT_A_STATE.search(where).group(0)}' is not a state")
            ref = re.match(r"IN-MILESTONE @(M\d+)", where, re.I)
            if ref and ref.group(1) not in ids:
                out.append(f"{key}: points at {ref.group(1)}, which is not a milestone in this file")
    if anchor_text is not None:
        have = {k for k, _, _ in rows or []}
        for k in anchor_items(anchor_text):
            if k not in have:
                out.append(f"{k} is in the idea anchor and has no row in the closure")
    if blueprint_text is not None:
        covered = {p for parts in milestone_parts(milestones_text).values() for p in parts}
        blocked = " ".join(w for _, _, w in rows or [])
        for p in blueprint_parts(blueprint_text):
            if p not in covered and p not in blocked:
                out.append(f"{p} is in the blueprint and in no milestone's Parts line")
    return out


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    text = Path(args[0]).read_text(encoding="utf-8")
    anchor = blueprint = None
    if "--anchor" in argv:
        anchor = Path(argv[argv.index("--anchor") + 1]).read_text(encoding="utf-8")
    if "--blueprint" in argv:
        blueprint = Path(argv[argv.index("--blueprint") + 1]).read_text(encoding="utf-8")
    found = problems(text, anchor, blueprint)
    if "--find-blueprint" in argv:
        root = Path(argv[argv.index("--find-blueprint") + 1])
        path, problem = find_blueprint(root)
        if problem:
            found.append(problem)
        elif path and blueprint is None:
            found += problems(text, None, path.read_text(encoding="utf-8"))
    for p in found:
        print(f"FAIL   closure     {p}")
    if not found:
        print("PASS   closure     closure and parts complete")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
