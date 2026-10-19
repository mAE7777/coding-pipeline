#!/usr/bin/env python3
"""Install the pipeline into ~/.claude, and prove afterwards that what Claude Code loads is exactly this
repository's version.

Usage:
  python3 install.py plan  [--home <dir>]     show every action, change nothing
  python3 install.py apply [--home <dir>] [--overwrite-live-edits] [--no-codex]
                                              install, archive what the pipeline retired, write the manifest,
                                              and bring Codex's copies up to date in the same run
  python3 install.py check [--home <dir>]     compare the installed files with this repository and hunt shadows

What is managed:
  skills/<name>/          every file of each pipeline skill (SKILL.md, references/, scripts/; for code-craft,
                          the vendored pstack layer with UPSTREAM.json and LICENSE-pstack); files the repository no
                          longer has are removed, except the owner's own brain.md, friction.log, and tests/
  skills/_shared/         gate.sh, scripts/, templates/, models.json (the routing table: each checker's model and
                          effort), and the pipeline's references, agent-product/ included (other _shared files are
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
installed file, the repository revision, and the routing table's sha256 on its own (routing_table): which model
and effort each checker runs on is part of the released behavior. The owner's personal files beside it,
~/.claude/.pipeline-models.json (the routing override), ~/.claude/.pipeline-shadow.jsonl (shadow-run records), and
pipeline_sync.py's state (.pipeline-sessions/, .pipeline-runs/, .pipeline-sync.json), are never written or removed,
not even from the private/ overlay.

Codex. When ~/.agents/skills links into a Codex package (the folder holding scripts/convert_helm.py) and Codex's
copies are older than what was just installed, apply brings them up to date in the same run (--no-codex skips it
and says so): the package is cloned beside itself, the converter and the acceptance run on the clone, and only a
clone that passes every gate replaces the package (two renames); the package's installer then runs. A failed
converter, an acceptance that writes no report, reports no gates, exits in disagreement with its report, or reports
any failing gate, and a package that changed while the clone was checked leave the package untouched (Codex keeps
its last accepted version) and fail the install, keeping the failed report under ~/.claude/_backups/. A failed
installer puts the last accepted package back. A sync stopped at any point is finished or undone at the next apply,
and check fails until then. Exit 0 only when Claude Code and Codex are both current.

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
SKILLS = ("pipeline", "next", "capture", "scout", "plan", "dev", "gate", "loyal", "fix", "handoff", "inbox", "deploy", "explain",
          "polish", "evolve", "code-craft")
RETIRED_SKILLS = ("qa", "integrate")
# scripts/ goes whole, so every shared script (models.py, pr_watch.py, craft_sync.py, and the rest) is installed.
SHARED = ("gate.sh", "scripts", "templates", "models.json", "references/project-control.md",
          "references/pipeline-constitution.md", "references/steal-protocol.md", "references/steal-spec.md",
          "references/record-glossary.md", "references/agent-product")
ROUTING_TABLE = "skills/_shared/models.json"
# The owner's own files under ~/.claude that the pipeline's scripts read or append to: never installed over, never
# removed, never listed in the manifest. A folder's name covers everything in it (pipeline_sync.py's session
# records and run registry).
PERSONAL = (".pipeline-models.json", ".pipeline-shadow.jsonl", ".pipeline-sessions", ".pipeline-runs",
            ".pipeline-sync.json")
AGENTS = ("code-verifier", "loyal-evaluator", "gate-judge", "cold-reader", "claim-verifier", "change-reviewer")
RETIRED_AGENTS = ("dev-planner", "task-implementer", "qa-planner", "category-executor", "project-analyzer",
                  "migration-planner", "doc-generator", "market-researcher", "winners-board")
KEEP_LIVE = ("brain.md", "friction.log", "tests")
HOOKS = ("heavy-guard.py", "reload-gate.py", "snapshot-state.py", "typecheck-once.py", "verify-pipeline-completion.sh")
HOOK_COMMANDS = ("heavy-guard.py", "reload-gate.py arm", "reload-gate.py track", "reload-gate.py guard",
                 "snapshot-state.py", "typecheck-once.py", "continuity.py session-start", "continuity.py claim",
                 "continuity.py stop", "verify-pipeline-completion.sh", "pipeline_sync.py session-start",
                 "pipeline_sync.py prompt")
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
            if f.relative_to(overlay).parts[0] in PERSONAL:
                continue  # the owner's routing override, shadow records, and update state are theirs alone
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


def cmd_apply(home, overwrite=False, no_codex=False):
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
    # Hooks importing a new shared module must never see an incomplete upgrade.
    actions.sort(key=lambda row: 0 if row[0] in ("add", "update") and row[1].name == "project_policy.py" else 1)
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
    table = home / ".claude" / ROUTING_TABLE
    manifest = {"installed": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "revision": revision(), "repo": str(REPO),
                "routing_table": {"path": str(table), "sha256": sha(want[table])} if table in want else None,
                "files": {str(d): sha(s) for d, s in sorted(want.items())}}
    (home / ".claude/.pipeline-install.json").write_text(json.dumps(manifest, indent=1))
    print(f"installed: {len(actions)} action(s); manifest {home / '.claude/.pipeline-install.json'}"
          + (f"; replaced files backed up in {backup}" if backup.exists() else ""))
    fails, notes = ([], ["Codex not synced (--no-codex)"]) if no_codex else sync_codex(home, want)
    for n in notes:
        print(f"NOTE   install     {n}")
    for f in fails:
        print(f"FAIL   install     {f}")
    code = cmd_check(home)
    return 1 if fails else code


def codex_package(home):
    """The Codex package ~/.agents/skills links into: the folder that holds .agents/skills/plan, found from the link
    even while the package itself is missing (a sync stopped between its two renames), or None."""
    link = home / ".agents/skills/plan"
    if not link.is_symlink() and not link.exists():
        return None
    target = link.resolve(strict=False)
    return target.parents[2] if len(target.parents) > 2 and target.parent.name == "skills" else None


def beside(pkg, kind):
    """The folders a sync keeps next to the package, each naming one state: the clone being converted (staging), the
    last accepted package while the new one is accepted in its place (previous), the same once the new one passed
    (superseded), and the last package that failed (rejected, kept for a look and replaced by the next one)."""
    return pkg.parent / f".{pkg.name}.{kind}"


def tree_state(root):
    """Every file under root (apart from .git) with its size and modification time: enough to see a change."""
    state = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for f in filenames:
            p = Path(dirpath) / f
            try:
                st = p.lstat()
            except OSError:
                continue
            state[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns)
    return state


def clone(src, dst):
    """A copy of src, its git folder included (the acceptance checks the package is a project root), cloned
    copy-on-write where the disk allows."""
    dst.mkdir()
    for entry in src.iterdir():
        if subprocess.run(["cp", "-cRp", str(entry), str(dst / entry.name)], capture_output=True).returncode != 0:
            if entry.is_dir() and not entry.is_symlink():
                shutil.copytree(entry, dst / entry.name, symlinks=True)
            else:
                shutil.copy2(entry, dst / entry.name, follow_symlinks=False)


def reject(pkg, last):
    """Put the last accepted package back in place and keep the one that failed beside it, named, never deleted
    unseen."""
    rejected = beside(pkg, "rejected")
    if rejected.exists():
        shutil.rmtree(rejected)
    os.rename(pkg, rejected)
    os.rename(last, pkg)
    return rejected


def finish_interrupted(pkg, notes):
    """Put the package in one known state after a sync that was stopped, read from the folders beside it: a package
    missing with the last accepted one beside it is put back; a new package still under acceptance (previous beside
    it) is rejected; a clone being converted is dropped (the package was never touched by it). Returns True when a new
    package passed its acceptance but its installer may not have finished (superseded beside it)."""
    previous, superseded, staging = beside(pkg, "previous"), beside(pkg, "superseded"), beside(pkg, "staging")
    for last in (previous, superseded):
        if not pkg.exists() and (last / "scripts/convert_helm.py").is_file():
            os.rename(last, pkg)
            notes.append("a Codex sync stopped halfway through replacing the package; the last accepted package is back")
    if previous.exists():
        kept = reject(pkg, previous)
        notes.append(f"a Codex sync stopped before its acceptance finished; the last accepted package is back and the "
                     f"unaccepted one is kept at {kept}")
    if staging.exists():
        shutil.rmtree(staging)
        notes.append("a Codex copy left by a stopped sync was removed; the package itself was untouched")
    return superseded.exists()


def sync_codex(home, want):
    """Bring Codex's copies up to date with what was just installed: (fails, notes). Nothing runs when Codex is
    already current. Otherwise the package is cloned beside itself and the converter runs on the clone, so it never
    writes into the package Codex loads. If the package did not change meanwhile, the clone takes its place (a
    rename; the last accepted package waits beside it) and the acceptance runs there, where Codex finds it (its
    discovery gate needs the place the global links point to): while it runs, the new copies are what Codex would
    load. A failing acceptance puts the last accepted package back and keeps the failed one beside it, named; a
    passing one is followed by the installer, and a failing installer puts the last accepted package back too. Every
    step is a rename, so a sync stopped anywhere is finished or undone at the next apply."""
    pkg = codex_package(home)
    if pkg is None:
        return [], (["no Codex package links into ~/.agents/skills, so Codex was not synced"]
                    if (home / ".agents/skills").is_dir() else [])
    notes = []
    accepted_unfinished = finish_interrupted(pkg, notes)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(home)}
    previous, superseded, staging = beside(pkg, "previous"), beside(pkg, "superseded"), beside(pkg, "staging")

    def install(root):
        return subprocess.run([sys.executable, str(root / "scripts/install_global.py"), "--install", "--home", str(home)],
                              capture_output=True, text=True, env=env, cwd=root)

    if accepted_unfinished:
        r = install(pkg)
        if r.returncode != 0:
            return [f"Codex installer failed (exit {r.returncode}) finishing a stopped sync: "
                    f"{(r.stdout + r.stderr).strip()[-300:]}"], notes
        shutil.rmtree(superseded)
        notes.append("a stopped sync's installer step was run again")
    if not codex_conversion_check(home, want):
        return [], notes + ["Codex already current"]
    if not (pkg / "scripts/convert_helm.py").is_file():
        return [f"the package ~/.agents/skills links into ({pkg}) has no scripts/convert_helm.py for install.py to "
                "run; rebuild it by hand"], notes
    report = pkg / "validation/acceptance.json"

    def keep_report():
        if not report.is_file():
            return ""
        keep = home / ".claude/_backups" / f"codex-acceptance-{datetime.datetime.now():%Y%m%dT%H%M%S}.json"
        keep.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(report, keep)
        return f"; its report is kept at {keep}"

    before = tree_state(pkg)
    clone(pkg, staging)
    r = subprocess.run([sys.executable, str(staging / "scripts/convert_helm.py"), "--source", str(home / ".claude"),
                        "--destination", str(staging)], capture_output=True, text=True, env=env, cwd=staging)
    if r.returncode != 0:
        shutil.rmtree(staging, ignore_errors=True)
        return [f"Codex converter failed (exit {r.returncode}): {(r.stdout + r.stderr).strip()[-300:]}; the package "
                "was not touched, so Codex keeps its last accepted copies"], notes
    after = tree_state(pkg)
    if after != before:
        shutil.rmtree(staging, ignore_errors=True)
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        return [f"the package changed while its new copies were being built ({len(changed)} file(s), such as "
                f"{', '.join(changed[:3])}); nothing was replaced, run install.py apply again"], notes
    os.rename(pkg, previous)
    os.rename(staging, pkg)
    report.unlink(missing_ok=True)  # a report carried over from the last run is not this one's
    r = subprocess.run([sys.executable, str(pkg / "scripts/acceptance.py"), "--root", str(pkg), "--json", str(report)],
                       capture_output=True, text=True, env=env, cwd=pkg)
    try:
        gates = {g["name"]: g["status"] for g in json.loads(report.read_text())["gates"]}
        problem = "" if gates else f"Codex acceptance reported no gates (exit {r.returncode})"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        gates, problem = {}, (f"Codex acceptance wrote no readable report (exit {r.returncode}, "
                              f"{exc.__class__.__name__}): {(r.stdout + r.stderr).strip()[-300:]}")
    failing = sorted(g for g, st in gates.items() if st != "PASS")
    if not problem and bool(failing) != (r.returncode != 0):
        problem = f"Codex acceptance exited {r.returncode} while its report lists {len(failing)} failing gate(s)"
    if not problem and failing:
        problem = f"Codex acceptance: {', '.join(failing)} fail"
    if problem:
        kept = keep_report()
        rejected = reject(pkg, previous)
        return [problem + kept + f"; the last accepted package is back (the rejected one is kept at {rejected}), so "
                "Codex keeps its last accepted copies"], notes
    os.rename(previous, superseded)
    r = install(pkg)
    if r.returncode != 0:
        rejected = reject(pkg, superseded)
        back = install(pkg)
        return [f"Codex installer failed (exit {r.returncode}): {(r.stdout + r.stderr).strip()[-300:]}; the last "
                f"accepted package is back (the new one is kept at {rejected}) and its installer ran again"
                + ("" if back.returncode == 0 else f" but failed too (exit {back.returncode})")], notes
    shutil.rmtree(superseded)
    notes.append(f"Codex synced from the package at {pkg}")
    return [], notes


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
    pkg = codex_package(home)
    if pkg and not pkg.exists() and (beside(pkg, "previous").exists() or beside(pkg, "superseded").exists()):
        return ["a Codex sync stopped halfway through replacing the package, so Codex has no package now: "
                "install.py apply puts the last accepted one back"]
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
    if pkg and beside(pkg, "previous").exists():
        fails.append("a Codex sync stopped before its acceptance finished, so unaccepted copies are live: install.py "
                     "apply puts the last accepted package back")
    if pkg and beside(pkg, "superseded").exists():
        fails.append("a Codex sync stopped before its installer finished: install.py apply runs it again")
    fix = "install.py apply rebuilds them" if pkg and (pkg / "scripts/convert_helm.py").is_file() else \
        "the package ~/.agents/skills links into has no scripts/convert_helm.py for install.py to run; rebuild it by hand"
    stale = [str(dst.relative_to(claude)) for dst in sorted(want) if dst.is_file()
             and str(dst.relative_to(claude)) in recorded and recorded[str(dst.relative_to(claude))] != sha(dst)]
    if stale:
        fails.append(f"Codex's copies were converted from older versions of {len(stale)} file(s) ({', '.join(stale[:5])}"
                     + (" ..." if len(stale) > 5 else "") + "): " + fix)
    # Every managed file must be carried, except the hooks, which Codex runs from ~/.claude/hooks directly. Nothing
    # newer is left out on purpose: the code-craft skill converts like every other skill, models.json must reach Codex
    # because models.py (imported by run_isolated.py) reads the table beside the scripts and fails without it, and
    # the agent-product reference ships like the other references.
    absent = [str(dst.relative_to(claude)) for dst in sorted(want)
              if dst.relative_to(claude).parts[0] != "hooks" and str(dst.relative_to(claude)) not in recorded]
    if absent:
        fails.append(f"Codex's package does not carry {len(absent)} installed file(s) ({', '.join(absent[:5])}"
                     + (" ..." if len(absent) > 5 else "") + "): " + fix)
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
    table = home / ".claude" / ROUTING_TABLE
    for dst, src in sorted(want.items()):
        what = " (the routing table, so checkers would not run on the repository's models and efforts)" \
            if dst == table else ""
        if not dst.exists():
            fails.append(f"missing: {dst}{what}")
        elif sha(dst) != sha(src):
            fails.append(f"differs from the repository: {dst}{what}")
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
        return cmd_apply(home, overwrite="--overwrite-live-edits" in argv, no_codex="--no-codex" in argv)
    return {"plan": cmd_plan, "check": cmd_check}[argv[0]](home)


if __name__ == "__main__":
    if "--help" in sys.argv[1:3] or sys.argv[1:] == ["-h"]:
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
