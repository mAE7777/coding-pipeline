#!/usr/bin/env python3
"""Static checks over the pipeline's publishable files (Level 1 of the verification plan).

Usage: static_checks.py <repo-root>

Checks skills/*/SKILL.md, agents/*.md, hooks/*, skills/**/references|templates|scripts, and README.md
(the private/ overlay is skipped: it is never published). Prints FAIL/WARN/PASS lines; exit 1 on any FAIL.
"""
import re
import sys
from pathlib import Path

results = []


# Installed alongside the pipeline when the owner has them; every skill that names one says what happens
# when it is absent.
OPTIONAL_SHARED = {"_shared/references/owner-standing.md", "_shared/references/venture-mode.md",
                   "_shared/references/research-craft.md", "_shared/references/stacks/README.md"}


def report(status, where, detail):
    results.append((status, where, detail))


def frontmatter(text):
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    fm, key = {}, None
    for line in text[4:end].splitlines():
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m:
            key = m.group(1)
            fm[key] = m.group(2).strip().strip('"').strip("'")
        elif key and line.startswith((" ", "\t")):
            fm[key] = (fm[key] + " " + line.strip()).strip()
    return fm


def publishable(root):
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if not p.is_file() or rel.startswith((".git/", ".evidence/", "private/", "tests/fixtures/")) \
                or "/__pycache__/" in rel:
            continue
        if p.suffix in (".md", ".py", ".sh", ".json") or p.name == "gate.sh":
            yield p, rel


def main(argv):
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    root = Path(argv[0]).resolve()

    for skill in sorted((root / "skills").glob("*/SKILL.md")):
        rel = skill.relative_to(root).as_posix()
        text = skill.read_text(encoding="utf-8")
        fm = frontmatter(text)
        if fm is None:
            report("FAIL", rel, "no YAML frontmatter")
            continue
        for k in ("name", "description"):
            if not fm.get(k):
                report("FAIL", rel, f"frontmatter has no {k}")
        if fm.get("name") and fm["name"] != skill.parent.name:
            report("FAIL", rel, f"name '{fm['name']}' differs from directory '{skill.parent.name}'")
        desc = fm.get("description", "") + fm.get("when_to_use", "")
        if len(desc) > 1536:
            report("FAIL", rel, f"description + when_to_use is {len(desc)} chars (limit 1536)")
        lines = text.count("\n")
        if lines > 200:
            report("FAIL", rel, f"{lines} lines (budget 200; move depth to references)")
        elif lines > 170:
            report("WARN", rel, f"{lines} lines (aim for about 150)")
        body = text.split("\n---", 2)[-1]
        shouts = re.findall(r"\b(MUST|NEVER|ALWAYS|CRITICAL|IMPORTANT)\b", body)
        if len(shouts) > 3:
            report("WARN", rel, f"{len(shouts)} capitalized pressure words (say it plainly, with the reason)")
        for ref in re.findall(r"`((?:references|templates|scripts)/[\w./-]+)`", body):
            if not (skill.parent / ref).exists():
                report("FAIL", rel, f"references missing file {ref}")
        for ref in re.findall(r"`(?:~/\.claude/skills/)?(_shared/[\w./-]+)`", body):
            if ref in OPTIONAL_SHARED:
                continue
            if not (root / "skills" / ref).exists():
                report("FAIL", rel, f"references missing shared file {ref}")
        for agent in re.findall(r"`([a-z]+-(?:verifier|evaluator|reader))`", body):
            if not (root / "agents" / f"{agent}.md").exists():
                report("FAIL", rel, f"names agent {agent} which is not in agents/")

    for agent in sorted((root / "agents").glob("*.md")):
        rel = agent.relative_to(root).as_posix()
        fm = frontmatter(agent.read_text(encoding="utf-8"))
        if fm is None:
            report("FAIL", rel, "no YAML frontmatter (Claude Code will not register this agent)")
            continue
        for k in ("name", "description"):
            if not fm.get(k):
                report("FAIL", rel, f"frontmatter has no {k}")
        if fm.get("name") and fm["name"] != agent.stem:
            report("FAIL", rel, f"name '{fm['name']}' differs from file name")

    stale = [
        (re.compile(r"\bslices\.md\b"), "names slices.md (retired; milestones.md)"),
        (re.compile(r"(?<![\w-])/qa\b"), "names /qa (retired; /gate)"),
        (re.compile(r"(?<![\w-])/integrate\b"), "names /integrate (retired; final /gate)"),
        (re.compile(r"\bqa-reports\b"), "names qa-reports (retired)"),
        (re.compile(r"Guard (ADV|JDG)-\d"), "archived guard code"),
        (re.compile(r"\bphases\.md\b|pipeline-state\.md"), "names a v1 artifact"),
    ]
    # Files that read the earlier pipeline's formats on purpose (conversion, detection, adoption).
    legacy_readers = {"skills/plan/references/convert.md", "skills/_shared/scripts/record_check.py",
                      "skills/_shared/scripts/adopt.py", "skills/plan/references/adopt.md", "install.py"}
    # Files that must contain the patterns they detect.
    detectors = {"skills/_shared/gate.sh"}
    private = [
        (re.compile(r"/Users/(?!Shared\b)|sitaoma|Projects/lab"), "private path"),
        (re.compile(r"\bEric\b"), "owner's name in a publishable file (write 'the owner' or 'the user')"),
        (re.compile(r"Co-Authored-By|Generated with \[?Claude|🤖"), "AI trace"),
        (re.compile(r"[一-鿿]"), "Chinese text in a publishable file (belongs in the private overlay)"),
    ]
    for p, rel in publishable(root):
        if rel.startswith("tests/"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for rx, what in (stale if rel not in legacy_readers else []):
            for m in rx.finditer(text):
                line = text[:m.start()].count("\n") + 1
                ctx = text.splitlines()[line - 1]
                if "legacy" in ctx.lower() or "retired" in ctx.lower() or "v2" in ctx.lower():
                    continue
                report("FAIL", f"{rel}:{line}", what)
        for rx, what in private:
            if what == "AI trace" and rel in detectors:
                continue
            m = rx.search(text)
            if m:
                line = text[:m.start()].count("\n") + 1
                report("FAIL", f"{rel}:{line}", what)
        n = text.count(" — ")
        if n > 2:
            report("FAIL", rel, f"{n} spaced em-dashes")
        elif n:
            report("WARN", rel, f"{n} spaced em-dash(es)")

    fails = sum(1 for r in results if r[0] == "FAIL")
    for status, where, detail in results:
        print(f"{status:<5}  {where}  {detail}")
    print(f"static-checks: {'FAIL' if fails else 'PASS'} ({fails} fail, "
          f"{sum(1 for r in results if r[0] == 'WARN')} warn)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
