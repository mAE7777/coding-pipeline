#!/usr/bin/env python3
"""Install the pipeline into ~/.claude, and prove afterwards that what Claude Code loads is exactly this
repository's version.

Usage:
  python3 install.py plan  [--home <dir>]     show every action, change nothing
  python3 install.py apply [--home <dir>] [--overwrite-live-edits]
                                              install, archive what the pipeline retired, write the manifest
  python3 install.py check [--home <dir>]     compare the installed files with this repository and hunt shadows

What is managed:
  skills/<name>/          SKILL.md, references/, scripts/ of each pipeline skill; files the repository no longer
                          has are removed, except the owner's own brain.md, friction.log, and tests/
  skills/_shared/         gate.sh, scripts/, templates/, and the pipeline's references (other _shared files are
                          never touched)
  agents/<name>.md        the pipeline's checkers
  hooks/<name>.py         the pipeline's hooks (their registration in settings.json is settings_patch.py's job)
  private/                an optional local overlay (the owner's standing requirements, venture rules, brain
                          files), installed over the same paths; never published
Retired skills and agents move to ~/.claude/_archived-skills/ and ~/.claude/_archived-agents/, outside every
folder Claude Code loads from. Every file apply replaces or removes is first copied to
~/.claude/_backups/pipeline-install-<UTC time>/. An installed file that changed since the last install (an edit
made under ~/.claude, by hand or by /update) stops apply, which lists it: port the change into this repository
(or its private/ overlay) and apply again, or pass --overwrite-live-edits to replace it (the backup keeps it). The manifest (~/.claude/.pipeline-install.json) records the sha256 of every
installed file and the repository revision.

check FAILs when an installed file differs from the repository (or the overlay), a managed file is missing, a
retired skill or agent is still where it would load, a skill of the same name shadows one of ours (a plugin
skill, a project-level .claude/skills folder under the projects root), a pipeline hook is not registered in
settings.json, Codex's skill folder (~/.agents/skills) still offers a retired skill or lacks a current one or was
converted from older files than the ones installed (the converter's source manifest is compared), or a
required program is missing (Claude Code at the minimum version, playwright-cli, Playwright's Chromium for the
checkers' browser); optional programs (Codex, whisper) are listed either way.
Exit 0 when everything is current, 1 otherwise, 2 on bad usage.
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
SKILLS = ("next", "capture", "scout", "plan", "dev", "gate", "loyal", "fix", "handoff", "inbox", "deploy", "explain",
          "polish", "evolve")
RETIRED_SKILLS = ("qa", "integrate")
SHARED = ("gate.sh", "scripts", "templates", "references/pipeline-constitution.md", "references/steal-protocol.md",
          "references/steal-spec.md", "references/record-glossary.md")
AGENTS = ("code-verifier", "loyal-evaluator", "gate-judge", "cold-reader", "claim-verifier", "change-reviewer")
RETIRED_AGENTS = ("dev-planner", "task-implementer", "qa-planner", "category-executor", "project-analyzer",
                  "migration-planner", "doc-generator", "market-researcher", "winners-board")
KEEP_LIVE = ("brain.md", "friction.log", "tests")
HOOKS = ("heavy-guard.py", "reload-gate.py", "snapshot-state.py", "typecheck-once.py", "verify-pipeline-completion.sh")
HOOK_COMMANDS = ("heavy-guard.py", "reload-gate.py arm", "reload-gate.py track", "reload-gate.py guard",
                 "snapshot-state.py", "typecheck-once.py", "continuity.py session-start", "continuity.py claim",
                 "continuity.py stop", "verify-pipeline-completion.sh")
REQUIRED_TOOLS = (("claude", "Claude Code, which runs the builder and every checker"),
                  ("playwright-cli", "the builder's browser (npm install -g @playwright/cli)"))
OPTIONAL_TOOLS = (("codex", "the other model family for code review; without it the review runs on Claude and says so"),
                  ("whisper", "transcribing audio in /capture"))
MIN_CLAUDE = (2, 1, 283)
BROWSER_PROBE = ("import os, sys\nfrom playwright.sync_api import sync_playwright\n"
                 "with sync_playwright() as p:\n    sys.exit(0 if os.path.exists(p.chromium.executable_path) else 3)\n")
SKIP_PARTS = {"__pycache__", ".DS_Store"}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def files_under(root):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("*")):
        if p.is_file() and not any(part in SKIP_PARTS for part in p.parts):
            yield p


def desired(home):
    """{installed path: source path} for every managed file, overlay applied last."""
    want = {}
    claude = home / ".claude"
    for name in SKILLS:
        src = REPO / "skills" / name
        for f in files_under(src):
            want[claude / "skills" / name / f.relative_to(src)] = f
    for part in SHARED:
        src = REPO / "skills/_shared" / part
        for f in files_under(src):
            want[claude / "skills/_shared" / f.relative_to(REPO / "skills/_shared")] = f
    for name in AGENTS:
        want[claude / "agents" / f"{name}.md"] = REPO / "agents" / f"{name}.md"
    for name in HOOKS:
        want[claude / "hooks" / name] = REPO / "hooks" / name
    overlay = REPO / "private"
    if overlay.is_dir():
        for f in files_under(overlay):
            if f.relative_to(overlay).parts[0] == "tests":
                continue  # the overlay's own tests run from the repository, never from ~/.claude
            want[claude / f.relative_to(overlay)] = f
    return want


def stale_in_skill_dirs(home, want):
    out = []
    for name in SKILLS:
        d = home / ".claude/skills" / name
        if not d.is_dir():
            continue
        for f in files_under(d):
            rel = f.relative_to(d)
            if rel.parts[0] in KEEP_LIVE or f in want:
                continue
            out.append(f)
    return out


def revision():
    git = shutil.which("git")
    if not git:
        return "no-git"
    r = subprocess.run([git, "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True)
    dirty = subprocess.run([git, "-C", str(REPO), "status", "--porcelain"], capture_output=True, text=True).stdout
    return (r.stdout.strip() or "no-git") + ("+local-changes" if dirty.strip() else "")


def plan(home):
    want = desired(home)
    actions = []
    for dst, src in sorted(want.items()):
        if not dst.exists():
            actions.append(("add", dst, src))
        elif sha(dst) != sha(src):
            actions.append(("update", dst, src))
    for f in stale_in_skill_dirs(home, want):
        actions.append(("remove", f, None))
    stamp = datetime.date.today().isoformat()
    for name in RETIRED_SKILLS:
        d = home / ".claude/skills" / name
        if d.exists():
            actions.append(("archive", d, home / ".claude/_archived-skills" / f"{name}-{stamp}"))
    for name in RETIRED_AGENTS:
        f = home / ".claude/agents" / f"{name}.md"
        if f.exists():
            actions.append(("archive", f, home / ".claude/_archived-agents" / f"{name}-{stamp}.md"))
    return want, actions


def cmd_plan(home):
    _, actions = plan(home)
    for kind, a, b in actions:
        print(f"{kind:<8} {a}" + (f"  <- {b}" if kind in ("add", "update") else f"  -> {b}" if b else ""))
    print(f"install plan: {len(actions)} action(s)")
    return 0


def live_edits(home, actions):
    """Installed files that changed since the last install (their bytes match neither the manifest nor the repo),
    and files added by hand inside an installed skill folder since then (not in the manifest, so an install
    would remove them). Before the first install there is no manifest, and nothing counts."""
    manifest = home / ".claude/.pipeline-install.json"
    if not manifest.is_file():
        return []
    recorded = json.loads(manifest.read_text()).get("files", {})
    changed = [a for kind, a, _ in actions if kind in ("update", "remove") and str(a) in recorded
               and a.is_file() and sha(a) != recorded[str(a)]]
    added = [a for kind, a, _ in actions if kind == "remove" and str(a) not in recorded and a.is_file()]
    return changed + added


def cmd_apply(home, overwrite=False):
    want, actions = plan(home)
    edited = live_edits(home, actions)
    if edited and not overwrite:
        for f in edited:
            print(f"STOP   install     changed or added under ~/.claude since the last install: {f}")
        print("install: nothing changed. Port these edits into the repository (or private/) and apply again, or "
              "pass --overwrite-live-edits to replace them (each is backed up first).")
        return 1
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = home / ".claude/_backups" / f"pipeline-install-{stamp}"
    for kind, a, b in actions:
        if kind in ("update", "remove") and a.is_file():
            target = backup / a.relative_to(home / ".claude")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(a, target)
    for kind, a, b in actions:
        if kind in ("add", "update"):
            a.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(b, a)
        elif kind == "remove":
            a.unlink()
        elif kind == "archive":
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(a), str(b))
    for name in SKILLS:
        for p in (home / ".claude/skills" / name).rglob("*.py"):
            if "scripts" in p.parts:
                p.chmod(p.stat().st_mode | 0o111)
    for p in (home / ".claude/skills/_shared/scripts").glob("*.py"):
        p.chmod(p.stat().st_mode | 0o111)
    manifest = {"installed": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "revision": revision(), "repo": str(REPO), "files": {str(d): sha(s) for d, s in sorted(want.items())}}
    (home / ".claude/.pipeline-install.json").write_text(json.dumps(manifest, indent=1))
    print(f"installed: {len(actions)} action(s); manifest {home / '.claude/.pipeline-install.json'}"
          + (f"; replaced files backed up in {backup}" if backup.exists() else ""))
    return cmd_check(home)


def registered_commands(home):
    """The hook commands registered in settings.json, as one searchable string."""
    try:
        settings = json.loads((home / ".claude/settings.json").read_text())
    except (OSError, ValueError):
        return ""
    return json.dumps(settings.get("hooks", {}))


def tools_check():
    """(fails, notes) for the programs the skills and checkers call, found on this PATH."""
    fails, notes = [], []
    for name, why in REQUIRED_TOOLS:
        if not shutil.which(name):
            fails.append(f"required tool not installed: {name} ({why})")
    claude = shutil.which("claude")
    if claude:
        out = subprocess.run([claude, "--version"], capture_output=True, text=True).stdout
        found = re.search(r"(\d+)\.(\d+)\.(\d+)", out)
        if not found or tuple(map(int, found.groups())) < MIN_CLAUDE:
            fails.append(f"Claude Code {out.strip() or 'of unknown version'} is older than "
                         f"{'.'.join(map(str, MIN_CLAUDE))} (the checkers' runner needs its flags)")
    python = shutil.which("python3")
    probe = subprocess.run([python, "-c", BROWSER_PROBE], capture_output=True, text=True) if python else None
    if probe is None or probe.returncode != 0:
        fails.append("the checkers' browser is not ready: python3 cannot start Playwright's Chromium "
                     "(pip install playwright; python3 -m playwright install chromium)")
    for name, why in OPTIONAL_TOOLS:
        notes.append(f"optional tool {name}: {'installed' if shutil.which(name) else 'not installed'} ({why})")
    return fails, notes


def codex_conversion_check(home, want):
    """Prove Codex's skills were converted from the files installed now: the converter's source manifest
    (sha256 per ~/.claude-relative path, found beside the package that ~/.agents/skills links into) must
    match every managed pipeline file, and every managed file but the hooks must be in it."""
    link = home / ".agents/skills/plan"
    if not link.exists():
        return []
    manifest = next((d / "source-manifest.sha256" for d in link.resolve().parents
                     if (d / "source-manifest.sha256").is_file()), None)
    if manifest is None:
        return [f"cannot prove Codex's copies are current: no source-manifest.sha256 above {link.resolve()}"]
    recorded = {}
    for line in manifest.read_text().splitlines():
        digest, _, rel = line.partition("  ")
        if rel:
            recorded[rel.strip()] = digest.strip()
    fails, claude = [], home / ".claude"
    stale = [str(dst.relative_to(claude)) for dst in sorted(want) if dst.is_file()
             and str(dst.relative_to(claude)) in recorded and recorded[str(dst.relative_to(claude))] != sha(dst)]
    if stale:
        fails.append(f"Codex's copies were converted from older versions of {len(stale)} file(s) ({', '.join(stale[:5])}"
                     + (" ..." if len(stale) > 5 else "") + "): rerun helm-codex-system's converter, acceptance, and install")
    # Every managed file must be carried, except the hooks, which Codex runs from ~/.claude/hooks directly.
    absent = [str(dst.relative_to(claude)) for dst in sorted(want)
              if dst.relative_to(claude).parts[0] != "hooks" and str(dst.relative_to(claude)) not in recorded]
    if absent:
        fails.append(f"Codex's package does not carry {len(absent)} installed file(s) ({', '.join(absent[:5])}"
                     + (" ..." if len(absent) > 5 else "") + "): rerun helm-codex-system's converter, acceptance, and install")
    return fails


def runtime_notes(home):
    """What the files cannot prove: Codex hook approval, and sessions still running what they loaded earlier."""
    notes = []
    codex_hooks, codex_cfg = home / ".codex/hooks.json", home / ".codex/config.toml"
    if codex_hooks.is_file() and "continuity.py" in codex_hooks.read_text():
        approved = codex_cfg.read_text().count("trusted_hash") if codex_cfg.is_file() else 0
        notes.append("Codex runs its hooks only after you approve them once with /hooks in Codex; "
                     + (f"{approved} hook approval(s) are recorded in ~/.codex/config.toml" if approved
                        else "none are recorded in ~/.codex/config.toml yet"))
    manifest = home / ".claude/.pipeline-install.json"
    if manifest.is_file() and home == Path.home():
        installed = datetime.datetime.strptime(json.loads(manifest.read_text())["installed"], "%Y-%m-%dT%H:%M:%SZ") \
            .replace(tzinfo=datetime.timezone.utc)
        ps = subprocess.run(["ps", "-axo", "pid=,lstart=,comm="], capture_output=True, text=True).stdout
        older = []
        for line in ps.splitlines():
            parts = line.split()
            if len(parts) < 7 or os.path.basename(parts[6]) not in ("claude", "codex"):
                continue
            try:
                started = datetime.datetime.strptime(" ".join(parts[1:6]), "%a %b %d %H:%M:%S %Y").astimezone()
            except ValueError:
                continue
            if started < installed:
                older.append(f"{os.path.basename(parts[6])} pid {parts[0]}")
        if older:
            notes.append(f"{len(older)} session(s) started before this install keep the skills, agents, and hooks "
                         f"they loaded until restarted: {', '.join(older[:8])}" + (" ..." if len(older) > 8 else ""))
    return notes


def cmd_check(home):
    want = desired(home)
    fails = []
    for dst, src in sorted(want.items()):
        if not dst.exists():
            fails.append(f"missing: {dst}")
        elif sha(dst) != sha(src):
            fails.append(f"differs from the repository: {dst}")
    for f in stale_in_skill_dirs(home, want):
        fails.append(f"left over from an earlier version: {f}")
    for name in RETIRED_SKILLS:
        if (home / ".claude/skills" / name).exists():
            fails.append(f"retired skill still loads: {home / '.claude/skills' / name}")
    for name in RETIRED_AGENTS:
        if (home / ".claude/agents" / f"{name}.md").exists():
            fails.append(f"retired agent still loads: {home / '.claude/agents' / (name + '.md')}")
    names = set(SKILLS)
    for skill_md in (home / ".claude/plugins").rglob("skills/*/SKILL.md") if (home / ".claude/plugins").is_dir() else []:
        if skill_md.parent.name in names:
            fails.append(f"a plugin skill shadows ours: {skill_md.parent}")
    projects = home / "Projects"
    if projects.is_dir():
        for pattern in ("*/.claude/skills/*", "*/*/.claude/skills/*"):
            for skill_dir in projects.glob(pattern):
                if skill_dir.name in names | set(RETIRED_SKILLS):
                    fails.append(f"a project-level skill shadows ours inside that project: {skill_dir}")
    hooks = registered_commands(home)
    for cmd in HOOK_COMMANDS:
        if cmd not in hooks:
            fails.append(f"hook not registered in settings.json: {cmd}")
    codex_hooks = home / ".codex/hooks.json"
    if (home / ".codex").is_dir():
        text = codex_hooks.read_text() if codex_hooks.is_file() else ""
        for cmd in ("continuity.py session-start --tool codex", "continuity.py claim --tool codex",
                    "continuity.py stop --tool codex", "heavy-guard.py", "reload-gate.py guard"):
            if cmd not in text:
                fails.append(f"Codex hook not registered in ~/.codex/hooks.json: {cmd} (codex_hooks_patch.py --apply)")
    fails += codex_conversion_check(home, want)
    codex = home / ".agents/skills"
    if codex.is_dir():
        for name in RETIRED_SKILLS:
            if (codex / name).exists():
                fails.append(f"Codex still offers a retired skill: {codex / name}")
        for name in SKILLS:
            target = codex / name
            if not target.exists():
                fails.append(f"Codex has no {name} skill: {target}")
            elif (target / "SKILL.md").is_file() and re.search(r"slices\.md|/qa\b|\$qa\b|intent-anchor\.md",
                                                                (target / "SKILL.md").read_text(errors="ignore")):
                fails.append(f"Codex's {name} skill is an earlier version: {target / 'SKILL.md'}")
    manifest = home / ".claude/.pipeline-install.json"
    if manifest.is_file():
        rev = json.loads(manifest.read_text()).get("revision")
        if rev != revision():
            fails.append(f"installed from revision {rev}; the repository is at {revision()}")
    else:
        fails.append("no install manifest (install.py apply has not run)")
    tool_fails, notes = tools_check()
    notes += runtime_notes(home)
    fails += tool_fails
    for f in fails:
        print(f"FAIL   install     {f}")
    for n in notes:
        print(f"NOTE   install     {n}")
    if not fails:
        print(f"PASS   install     {len(want)} files current; no shadows; hooks registered; Codex current; tools ready")
    return 1 if fails else 0


def main(argv):
    if not argv or argv[0] not in ("plan", "apply", "check"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    home = Path(argv[argv.index("--home") + 1]) if "--home" in argv else Path.home()
    if argv[0] == "apply":
        return cmd_apply(home, overwrite="--overwrite-live-edits" in argv)
    return {"plan": cmd_plan, "check": cmd_check}[argv[0]](home)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
