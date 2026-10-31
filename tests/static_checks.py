#!/usr/bin/env python3
"""Static checks over the pipeline's publishable files (Level 1 of the verification plan).

Usage: static_checks.py <repo-root>

Checks skills/*/SKILL.md, agents/*.md, hooks/*, skills/**/references|templates|scripts, and README.md
(the private/ overlay and Claude Code's local .claude/ folder are skipped: neither is ever published), and:
  always-loaded text  every model-invocable skill's description (with when_to_use) is at most 450 characters;
                      every agent's description is one line of at most 120; all of them together, the text every
                      session loads, stay within ALWAYS_LOADED_BUDGET bytes. Skills marked
                      disable-model-invocation: true are left out of both (they are not in the model's listing).
                      The total is printed on an INFO line and in the summary.
  craft budget        skills/code-craft/index.md at most 10,240 bytes, skills/code-craft/SKILL.md at most 6,144
  routes and agents   models.py check passes on skills/_shared/models.json; every checker route
                      (models.CHECKER_ROUTES) is a role in run_isolated.ROLES and, apart from probe, has
                      agents/<role>.md; every agents/*.md is a role in ROLES with a checker route in the table; a
                      builder-side route (model "session") has no agent file
  agent frontmatter   no model or effort key (the routing table is their single home: run_isolated.py passes
                      --model and --effort and reads only the description), and tools equal the role's tools in
                      run_isolated.ROLES
  model IDs           no Fable or Mythos model ID, model field, or --model flag in any publishable file, tests
                      included, apart from FORBIDDEN_MODEL_EXEMPT (the files that reject them by name)
  craft provenance    craft_sync.py verify passes (every vendored file matches UPSTREAM.json)
Prints FAIL, WARN, and INFO lines and a summary; exit 0 when nothing FAILs, 1 otherwise, 2 on bad usage.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

results = []


# Installed alongside the pipeline when the owner has them; every skill that names one says what happens
# when it is absent.
OPTIONAL_SHARED = {"_shared/references/owner-standing.md", "_shared/references/venture-mode.md",
                   "_shared/references/research-craft.md", "_shared/references/stacks/README.md"}

# The descriptions every session loads. The budget is the total after the October 2026 trims (5,916
# bytes) plus 10 percent, rounded: raising it is a decision, never drift.
ALWAYS_LOADED_BUDGET = 6500
SKILL_DESCRIPTION_LIMIT = 450
AGENT_DESCRIPTION_LIMIT = 120
# The craft layer is read lazily: the index once per milestone or fix session, the skill on /code-craft.
CRAFT_BUDGETS = {"skills/code-craft/index.md": 10240, "skills/code-craft/SKILL.md": 6144}
# The checker role whose agent file comes from the fixture that runs it (--agent-file), never from agents/.
NO_AGENT_FILE = ("probe",)
# The files that name Fable or Mythos models on purpose, to prove they are rejected: the routing code, the tests
# that refuse or price them, this checker, and the repository-only documents under docs/ that state the rule
# (never installed). An entry ending in / exempts that folder.
FORBIDDEN_MODEL_EXEMPT = ("skills/_shared/scripts/models.py", "tests/test_models.py", "tests/test_run_isolated.py",
                          "tests/test_spend.py", "tests/static_checks.py", "docs/")
FORBIDDEN_MODEL = re.compile(
    r"claude-[\w.-]*?(?:fable|mythos)"                                           # a model ID
    r"|\b(?:fable|mythos)[-_.]?\d"                                               # a versioned name
    r"|(?:\bmodel\b[\"']?\s*[:=]\s*[\"']?|--model[= ]+[\"']?)[\w./-]*?(?:fable|mythos)",  # a model field or flag
    re.I)
# Reads the checker routes and the runner's roles from the tree being checked, in a fresh interpreter.
ROLES_PROBE = ("import json, sys\n"
               "sys.path.insert(0, sys.argv[1])\n"
               "import models, run_isolated\n"
               "print(json.dumps({'routes': list(models.CHECKER_ROUTES),\n"
               "                  'roles': {k: list(v) for k, v in run_isolated.ROLES.items()}}))\n")


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


def frontmatter_problems(text):
    """What a YAML parser (Claude Code's) would refuse or read otherwise in the frontmatter's top-level lines: an
    unquoted value holding ': ', and a description that is not on one line."""
    end = text.find("\n---", 4)
    lines = text[4:end].splitlines() if text.startswith("---\n") and end >= 0 else []
    out = []
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Za-z_-]+):[ \t]*(.*)$", line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if value and value[0] not in "\"'" and ": " in value:
            out.append(f"{key}: an unquoted value holding ': ' is not valid YAML (quote it)")
        if key == "description":
            continued = i + 1 < len(lines) and lines[i + 1][:1] in (" ", "\t")
            if value in ("", "|", ">", "|-", ">-", "|+", ">+") or continued:
                out.append("description is not on one line")
    return out


def invocable(fm):
    """False for a skill only the owner can start (it is left out of the model's listing)."""
    return fm.get("disable-model-invocation", "").strip().lower() != "true"


def publishable(root):
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if not p.is_file() or rel.startswith((".git/", ".claude/", ".evidence/", "private/", "tests/fixtures/")) \
                or "/__pycache__/" in rel:
            continue
        if p.suffix in (".md", ".py", ".sh", ".json") or p.name == "gate.sh":
            yield p, rel


def check_always_loaded(root):
    """The descriptions Claude Code lists in every session: each one's limit, and their total in bytes."""
    total = 0
    for skill in sorted((root / "skills").glob("*/SKILL.md")):
        rel = skill.relative_to(root).as_posix()
        text = skill.read_text(encoding="utf-8")
        fm = frontmatter(text)
        if fm is None:
            continue
        for problem in frontmatter_problems(text):
            report("FAIL", rel, problem)
        if not invocable(fm):
            continue
        desc = fm.get("description", "") + fm.get("when_to_use", "")
        total += len(desc.encode("utf-8"))
        if len(desc) > SKILL_DESCRIPTION_LIMIT:
            report("FAIL", rel, f"description is {len(desc)} characters (limit {SKILL_DESCRIPTION_LIMIT} for a "
                                "model-invocable skill; the body holds the procedure)")
    for agent in sorted((root / "agents").glob("*.md")):
        rel = agent.relative_to(root).as_posix()
        text = agent.read_text(encoding="utf-8")
        fm = frontmatter(text)
        if fm is None:
            continue
        for problem in frontmatter_problems(text):
            report("FAIL", rel, problem)
        desc = fm.get("description", "")
        total += len(desc.encode("utf-8"))
        if len(desc) > AGENT_DESCRIPTION_LIMIT:
            report("FAIL", rel, f"description is {len(desc)} characters (limit {AGENT_DESCRIPTION_LIMIT}: one line "
                                "saying it is an internal checker)")
    if total > ALWAYS_LOADED_BUDGET:
        report("FAIL", "always-loaded", f"skill and agent descriptions total {total} bytes (budget "
                                        f"{ALWAYS_LOADED_BUDGET}); every session loads them")
    else:
        report("INFO", "always-loaded", f"skill and agent descriptions total {total} bytes (budget "
                                        f"{ALWAYS_LOADED_BUDGET})")
    return total


def check_craft_budget(root):
    for rel, limit in CRAFT_BUDGETS.items():
        path = root / rel
        if not path.is_file():
            report("FAIL", rel, "missing")
        elif path.stat().st_size > limit:
            report("FAIL", rel, f"{path.stat().st_size} bytes (budget {limit}; read before any craft leaf, so "
                                "depth belongs in the leaves)")


def run_python(*args, timeout=120):
    """(exit code, standard output, standard error) of the tree's own code, in a fresh interpreter that writes no
    caches; exit code None when it could not run."""
    try:
        r = subprocess.run([sys.executable, "-I", "-B", *map(str, args)], capture_output=True, text=True,
                           timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "", str(exc)
    return r.returncode, r.stdout, r.stderr


def check_routes_and_agents(root):
    """The routing table, the runner's roles, and the agent files name the same checkers."""
    scripts = root / "skills/_shared/scripts"
    table_rel = "skills/_shared/models.json"
    for rel in (table_rel, "skills/_shared/scripts/models.py", "skills/_shared/scripts/run_isolated.py"):
        if not (root / rel).is_file():
            report("FAIL", rel, "missing, so routes cannot be matched to agents")
            return
    code, out, err = run_python(scripts / "models.py", "check", root / table_rel)
    if code != 0:
        lines = [line for line in (out + err).splitlines() if line.startswith("FAIL")]
        for line in lines or [(out + err).strip()[-300:] or f"exit {code}"]:
            report("FAIL", table_rel, f"models.py check: {line}")
    try:
        routes = json.loads((root / table_rel).read_text(encoding="utf-8"))["routes"]
        if not isinstance(routes, dict):
            raise TypeError
    except (OSError, ValueError, KeyError, TypeError):
        report("FAIL", table_rel, "has no readable routes object")
        return
    code, out, err = run_python("-c", ROLES_PROBE, scripts, timeout=60)
    try:
        known = json.loads(out)
        checker_routes = [str(r) for r in known["routes"]]
        roles = {str(k): [str(t) for t in v] for k, v in known["roles"].items()}
    except (ValueError, KeyError, TypeError, AttributeError):
        report("FAIL", "skills/_shared/scripts", "cannot read models.CHECKER_ROUTES and run_isolated.ROLES: "
               + ((err or out).strip()[-300:] or f"exit {code}"))
        return
    agents = {p.stem: p for p in sorted((root / "agents").glob("*.md"))}
    missing = {}
    for route in checker_routes:
        role = route.split(".", 1)[0]
        if role not in roles:
            report("FAIL", "skills/_shared/scripts/models.py",
                   f"checker route {route}: role {role} is not in run_isolated.ROLES")
        if role not in NO_AGENT_FILE and role not in agents:
            missing.setdefault(role, f"checker route {route} runs this agent")
    for role in roles:
        if role not in NO_AGENT_FILE and role not in agents:
            missing.setdefault(role, f"run_isolated.ROLES runs role {role}")
    for role, why in missing.items():
        report("FAIL", f"agents/{role}.md", f"missing: {why}")
    builder_side = {route for route, e in routes.items() if isinstance(e, dict) and e.get("model") == "session"}
    for route in sorted(builder_side):
        role = route.split(".", 1)[0]
        if role in agents:
            report("FAIL", f"agents/{role}.md", f"route {route} is builder-side (model session), so it has no "
                                                "agent file")
    routed = {route.split(".", 1)[0] for route in routes if route not in builder_side}
    for role, path in agents.items():
        rel = path.relative_to(root).as_posix()
        if role not in roles:
            report("FAIL", rel, f"role {role} is not in run_isolated.ROLES, so no script runs it")
        if role not in routed:
            report("FAIL", rel, f"no checker route for {role} in {table_rel}")
        fm = frontmatter(path.read_text(encoding="utf-8")) or {}
        for key in ("model", "effort"):
            if key in fm:
                report("FAIL", rel, f"frontmatter sets {key}: {table_rel} is the single home of each checker's "
                                    "model and effort (run_isolated.py passes them as flags and never reads this)")
        if role in roles:
            tools = [t.strip() for t in fm.get("tools", "").split(",") if t.strip()]
            if sorted(tools) != sorted(roles[role]):
                report("FAIL", rel, f"tools ({', '.join(tools) or 'none'}) differ from run_isolated.ROLES "
                                    f"({', '.join(roles[role])}), which is what a run gets")


def check_forbidden_models(root):
    for p, rel in publishable(root):
        if any(rel == e or (e.endswith("/") and rel.startswith(e)) for e in FORBIDDEN_MODEL_EXEMPT):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in FORBIDDEN_MODEL.finditer(text):
            line = text[:m.start()].count("\n") + 1
            report("FAIL", f"{rel}:{line}", f"names a Fable or Mythos model ({m.group(0)}), which the pipeline "
                                            "never routes to")


def check_craft_provenance(root):
    script = root / "skills/_shared/scripts/craft_sync.py"
    if not script.is_file():
        report("FAIL", "skills/_shared/scripts/craft_sync.py",
               "missing, so the vendored craft files cannot be checked against UPSTREAM.json")
        return
    code, out, err = run_python(script, "verify", "--craft", root / "skills/code-craft")
    if code != 0:
        detail = (out + err).strip()
        report("FAIL", "skills/code-craft", f"craft_sync.py verify: {detail[-600:] or f'exit {code}'}")


def main(argv):
    if len(argv) != 1 or not Path(argv[0]).is_dir():
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
        for agent in re.findall(r"`([a-z]+-(?:verifier|evaluator|reader|reviewer|judge))`", body):
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

    total = check_always_loaded(root)
    check_craft_budget(root)
    check_routes_and_agents(root)
    check_forbidden_models(root)
    check_craft_provenance(root)

    fails = sum(1 for r in results if r[0] == "FAIL")
    for status, where, detail in results:
        print(f"{status:<5}  {where}  {detail}")
    print(f"static-checks: {'FAIL' if fails else 'PASS'} ({fails} fail, "
          f"{sum(1 for r in results if r[0] == 'WARN')} warn; always-loaded descriptions {total} of "
          f"{ALWAYS_LOADED_BUDGET} bytes)")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] in (["--help"], ["-h"]):
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
