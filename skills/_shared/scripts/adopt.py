#!/usr/bin/env python3
"""The deterministic half of adopting a project that has no build record (or an incomplete one).

Usage:
  adopt.py inventory <project>   write the inventory, the reading plan, and the coverage ledger
  adopt.py commands <project>    run the labeled build and test commands through the heavy lock, record results
  adopt.py check <project>       adoption is complete: every file accounted for, every record file present

inventory writes docs/project/research/adoption/:
  inventory.json    every file (tracked plus untracked non-ignored, or a walk) with class, language, size,
                    lines, last change; documents ranked by authority signals; discovered commands (package
                    scripts, Makefile targets, pyproject, Cargo, go, Xcode, CI steps); entry points; the
                    route, model-call, and degradation candidates (inventory.py); git facts; areas
  reading-plan.md   areas in reading order with sizes; which to read directly and which to hand to a
                    read-only explorer (at most 3 at once), each writing areas/<area>.md
  coverage.md       the ledger: one row per document and code file ("todo"), with lock files, vendored,
                    generated, binary, and asset files pre-accounted as "skipped (<class>)"
Ledger statuses: read · outlined (<why the rest was not needed>) · delegated (areas/<area>.md) · skipped
(<reason>) · stale (<evidence>) · superseded (<by what>). Documents must be read, stale, or superseded,
never skipped or outlined: they carry intent.

check FAILs when: a file the inventory lists (other than pre-accounted lock, vendored, generated, binary, and
record files) has no ledger row; a document marked read cites no imported capture source (SRC-<n> in its note,
present in docs/project/sources/index.md); a ledger row is still todo; a document row is outlined or skipped; a delegated row's area
note is missing; an outlined row has no reason; a record file is missing (intent, brief, milestones,
interfaces, decisions, state, gate); AGENTS.md has no labeled Commands; the commands were never run (adopt.py
commands); milestones.md has no M0 (the product as found); a reconstructed done example carries no
evidence label ([code ...], [doc ...], [git ...], [owner ...]); an earlier pipeline's file is not marked
superseded; the imported documents' dossier fails capture.py check (which also requires every document read by
independent extraction rounds until one found nothing missed); an area note does not open with "Load-bearing:
yes (...)" or "no (...)"; a load-bearing area has no second, independent reading (areas/<area>.second.md) or no
settled "## Reconciled" section.
Exit 0 on success, 1 on a FAIL, 2 on bad usage.
"""
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fingerprint import git_files, walk_files  # noqa: E402
from gate_keys import commands as labeled_commands  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from languages import CODE as LANG, DOC as DOC_EXT  # noqa: E402
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".mp3", ".mp4", ".mov",
              ".wav", ".woff", ".woff2", ".ttf", ".otf", ".sqlite", ".db", ".bin", ".psd", ".sketch", ".fig"}
LOCKFILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "go.sum",
             "Gemfile.lock", "composer.lock", "Podfile.lock", "uv.lock", "bun.lockb"}
VENDORED = ("vendor/", "third_party/", "third-party/", "external/", "Pods/")
GENERATED = re.compile(r"(\.min\.(js|css)$|\.generated\.|_pb2\.py$|\.pb\.go$|^dist/|^build/|\.map$|\.snap$)")
TEST = re.compile(r"(^|/)(tests?|__tests__|spec|e2e)/|\.test\.|\.spec\.|(^|/)test_[^/]*\.py$|_test\.(go|py)$")
LEGACY = re.compile(r"(^|/)(slices|intent-anchor|phases|pipeline-state|key-learnings)[^/]*\.md$|(^|/)qa-reports/")
AUTHORITY = re.compile(r"(prd|spec|requirement|architecture|design|adr|rfc|decision|vision|roadmap|milestone|brief|"
                       r"plan|contract|readme|agents|claude)", re.I)
RECORD = ("intent.md", "brief.md", "milestones.md", "interfaces.md", "decisions.md", "state.md", "gate.md")
BIG_AREA_LINES = 4000


def out_dir(project):
    d = Path(project) / "docs/project/research/adoption"
    d.mkdir(parents=True, exist_ok=True)
    return d


def classify(rel, path):
    name = rel.rsplit("/", 1)[-1]
    ext = path.suffix.lower()
    if name in LOCKFILES:
        return "lockfile"
    if any(rel.startswith(v) or f"/{v}" in rel for v in VENDORED):
        return "vendored"
    if GENERATED.search(rel):
        return "generated"
    if ext in BINARY_EXT:
        return "binary"
    if LEGACY.search(rel):
        return "legacy-record"
    if rel.startswith("docs/project/"):
        return "record"
    if ext in DOC_EXT:
        return "doc"
    if TEST.search(rel) and ext in LANG:
        return "test"
    if ext in LANG:
        return "code"
    if name in ("package.json", "pyproject.toml", "Cargo.toml", "go.mod", "Makefile", "Dockerfile", "Gemfile",
                "Podfile", "justfile", "tsconfig.json") or ext in (".toml", ".yaml", ".yml", ".json", ".ini", ".cfg",
                                                                      ".xcconfig", ".plist", ".gradle"):
        return "config"
    return "other"


def git(project, *args):
    r = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def discover_commands(project):
    found = {}
    pkg = project / "package.json"
    if pkg.is_file():
        try:
            for k, v in (json.loads(pkg.read_text()).get("scripts") or {}).items():
                found[f"npm run {k}"] = v
        except ValueError:
            pass
    mk = project / "Makefile"
    if mk.is_file():
        for t in re.findall(r"^([a-zA-Z0-9_-]+):", mk.read_text(errors="ignore"), re.M):
            found[f"make {t}"] = "Makefile target"
    py = project / "pyproject.toml"
    if py.is_file():
        text = py.read_text(errors="ignore")
        if "[tool.pytest" in text or (project / "tests").is_dir():
            found["python3 -m pytest"] = "pytest"
        for k in re.findall(r"^\[project\.scripts\]\s*$((?:\n[^\[].*)*)", text, re.M):
            for name in re.findall(r"^(\S+)\s*=", k, re.M):
                found[name] = "project script"
    if (project / "Cargo.toml").is_file():
        found.update({"cargo build": "cargo", "cargo test": "cargo"})
    if (project / "go.mod").is_file():
        found.update({"go build ./...": "go", "go test ./...": "go"})
    for wf in sorted((project / ".github/workflows").glob("*.y*ml")) if (project / ".github/workflows").is_dir() else []:
        for run_line in re.findall(r"^\s*-?\s*run:\s*(.+)$", wf.read_text(errors="ignore"), re.M):
            found[run_line.strip()] = f"CI step ({wf.name})"
    return found


def entry_points(project, files):
    out = []
    pkg = project / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text())
            for k in ("main", "module", "bin"):
                if data.get(k):
                    out.append(f"package.json {k}: {data[k]}")
        except ValueError:
            pass
    for rel in files:
        if re.search(r"(^|/)(__main__\.py|main\.(go|rs|py|ts|js|swift|kt)|index\.(html|ts|js|tsx)|app\.(py|ts|js|tsx)|"
                     r"server\.(py|ts|js)|manage\.py|AppDelegate\.swift|\w+App\.swift)$", rel):
            out.append(rel)
    return out[:60]


def inventory(project):
    project = Path(project).resolve()
    files = git_files(project)
    source = "git"
    if files is None:
        files, source = walk_files(project), "walk"
    rows = []
    for rel in files:
        p = project / rel
        if not p.is_file():
            continue
        cls = classify(rel, p)
        size = p.stat().st_size
        lines = 0
        if cls in ("code", "test", "doc", "config", "legacy-record", "record", "other") and size < 5_000_000:
            try:
                lines = p.read_bytes().count(b"\n")
            except OSError:
                pass
        rows.append({"path": rel, "class": cls, "language": LANG.get(p.suffix.lower()), "bytes": size, "lines": lines})
    docs = [r for r in rows if r["class"] in ("doc", "legacy-record")]
    for d in docs:
        last = git(project, "log", "-1", "--format=%cs", "--", d["path"]).strip()
        d["last_change"] = last
        score = 0
        score += 3 if AUTHORITY.search(d["path"]) else 0
        score += 2 if d["path"].startswith("docs/") else 0
        score += min(d["lines"] // 100, 3)
        d["authority_signal"] = score
    docs.sort(key=lambda d: (-d["authority_signal"], d.get("last_change") or "", d["path"]))
    areas = {}
    for r in rows:
        if r["class"] not in ("code", "test"):
            continue
        parts = r["path"].split("/")
        key = "/".join(parts[:2]) if parts[0] in ("src", "lib", "app", "packages", "apps", "internal", "pkg") and len(parts) > 2 else parts[0] if len(parts) > 1 else "(root)"
        a = areas.setdefault(key, {"files": 0, "lines": 0})
        a["files"] += 1
        a["lines"] += r["lines"]
    inv_out = subprocess.run([sys.executable, str(HERE / "inventory.py"), str(project)], capture_output=True, text=True).stdout
    commits = git(project, "rev-list", "--count", "HEAD").strip()
    data = {"project": str(project), "file_source": source, "created": datetime.date.today().isoformat(),
            "counts": {c: sum(1 for r in rows if r["class"] == c) for c in sorted({r["class"] for r in rows})},
            "files": rows, "documents_ranked": [{k: d.get(k) for k in ("path", "lines", "last_change", "authority_signal")}
                                                for d in docs],
            "commands_discovered": discover_commands(project), "commands_labeled": labeled_commands(project),
            "entry_points": entry_points(project, [r["path"] for r in rows]),
            "candidates": inv_out.strip().splitlines()[:200],
            "git": {"commits": commits or "none", "first": git(project, "log", "--reverse", "--format=%cs").split("\n")[0],
                    "last": git(project, "log", "-1", "--format=%cs").strip(),
                    "authors": sorted(set(git(project, "log", "--format=%an").split("\n")) - {""})[:20],
                    "recent": git(project, "log", "-30", "--format=%h %cs %s").strip().splitlines(),
                    "dirty": len([l for l in git(project, "status", "--porcelain").splitlines() if l.strip()])},
            "areas": areas}
    d = out_dir(project)
    (d / "inventory.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    plan = ["# Reading plan", "", f"Files: {len(rows)} ({', '.join(f'{k} {v}' for k, v in data['counts'].items())}).",
            "Read every document in the order below, then the areas. Write what you learn to disk as you go (area "
            "notes, the record files); never read a file twice.", "", "## Documents (by authority signal)"]
    plan += [f"- {d['path']} · {d['lines']} lines · last change {d.get('last_change') or 'unknown'}" for d in docs] or ["- none"]
    plan += ["", "## Areas", "| Area | Files | Lines | How |", "|---|---|---|---|"]
    for key, a in sorted(areas.items(), key=lambda kv: -kv[1]["lines"]):
        how = f"explorer, writes areas/{re.sub(r'[^a-z0-9]+', '-', key.lower()).strip('-')}.md" \
            if a["lines"] > BIG_AREA_LINES else "read directly"
        plan.append(f"| {key} | {a['files']} | {a['lines']} | {how} |")
    (d / "reading-plan.md").write_text("\n".join(plan) + "\n")
    ledger = ["# Adoption coverage", "", "| Path | Class | Lines | Status | Note |", "|---|---|---|---|---|"]
    skipped_groups = {}
    for r in rows:
        if r["class"] in ("lockfile", "vendored", "generated", "binary"):
            top = r["path"].split("/")[0] if "/" in r["path"] else "(root)"
            skipped_groups.setdefault((top, r["class"]), 0)
            skipped_groups[(top, r["class"])] += 1
            continue
        if r["class"] == "record":
            continue
        ledger.append(f"| {r['path']} | {r['class']} | {r['lines']} | todo | |")
    for (top, cls), n in sorted(skipped_groups.items()):
        ledger.append(f"| {top}/ ({n} {cls} files) | {cls} | - | skipped ({cls}) | |")
    (d / "coverage.md").write_text("\n".join(ledger) + "\n")
    print(f"inventory: {len(rows)} files · {len(docs)} documents · {len(areas)} areas · ledger {d / 'coverage.md'}")
    return 0


def run_commands(project):
    project = Path(project).resolve()
    cmds = labeled_commands(project)
    results = {}
    for label in ("build", "test"):
        cmd = cmds.get(label)
        if not cmd:
            results[label] = {"status": "SKIP", "reason": f"no '{label}:' line in AGENTS.md Commands"}
            continue
        r = subprocess.run([sys.executable, str(HERE / "heavy.py"), "run", "--timeout", "1500", "--", "/bin/sh", "-c", cmd],
                           cwd=project, capture_output=True, text=True)
        log = project / f".evidence/adoption/{label}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(r.stdout + r.stderr)
        results[label] = {"command": cmd, "exit": r.returncode, "status": "PASS" if r.returncode == 0 else "FAIL",
                          "log": str(log.relative_to(project))}
    for label in ("run", "demo", "install"):
        if cmds.get(label):
            results[label] = {"command": cmds[label], "status": "NOT_RUN",
                              "reason": "starts a process or changes the environment; the M0 demo exercises it"}
    (project / ".evidence/adoption").mkdir(parents=True, exist_ok=True)
    (project / ".evidence/adoption/commands.json").write_text(json.dumps(results, indent=2))
    for k, v in results.items():
        print(f"{v['status']:<8} {k:<8} {v.get('command', '')} {('exit ' + str(v['exit'])) if 'exit' in v else v.get('reason', '')}")
    return 0


def check(project):
    project = Path(project).resolve()
    fails = []
    d = project / "docs/project/research/adoption"
    ledger = d / "coverage.md"
    if not ledger.is_file():
        fails.append("no coverage ledger (adopt.py inventory)")
    else:
        for line in ledger.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\|\s*([^|]+?)\s*\|\s*([a-z-]+)\s*\|\s*[^|]*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*$", line)
            if not m or m.group(1) in ("Path",) or set(m.group(1)) <= set("-: "):
                continue
            path, cls, status, note = m.groups()
            if status == "todo" or not status:
                fails.append(f"{path}: not accounted for yet")
            elif cls in ("doc", "legacy-record") and not re.match(r"^(read|stale \(.+\)|superseded \(.+\))$", status):
                fails.append(f"{path}: a document must be read (or marked stale/superseded with evidence), not '{status}'")
            elif status.startswith("delegated"):
                area = re.search(r"areas/[^\s)]+\.md", status + " " + note)
                if not area or not (d / area.group(0)).is_file():
                    fails.append(f"{path}: delegated, but its area note is missing")
            elif status.startswith("outlined") and not re.match(r"^outlined \(.+\)$", status):
                fails.append(f"{path}: outlined without saying why the rest was not needed")
            elif not re.match(r"^(read|outlined \(.+\)|delegated.*|skipped \(.+\)|stale \(.+\)|superseded \(.+\))$", status):
                fails.append(f"{path}: status '{status}' is not a ledger status")
    areas = d / "areas"
    for note in sorted(areas.glob("*.md")) if areas.is_dir() else []:
        if note.name.endswith(".second.md"):
            continue
        text = note.read_text(encoding="utf-8")
        first = next((l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")), "")
        lb = re.match(r"^Load-bearing:\s*(yes|no)\b", first, re.I)
        if not lb:
            fails.append(f"areas/{note.name}: does not open with 'Load-bearing: yes (<why>)' or 'Load-bearing: no (<why>)'")
            continue
        if lb.group(1).lower() != "yes":
            continue
        second = note.with_name(note.stem + ".second.md")
        if not second.is_file():
            fails.append(f"areas/{note.name}: a load-bearing area without a second, independent reading ({second.name})")
        rec_sec = re.search(r"^## Reconciled\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
        if not rec_sec:
            fails.append(f"areas/{note.name}: the two readings are not reconciled (## Reconciled)")
            continue
        for line in rec_sec.group(1).splitlines():
            if line.strip().startswith("- ") and not re.search(
                    r"· (note corrected|second reading wrong \(.+\)|unknown U-\d+|owner \(.+\))\s*$", line):
                fails.append(f"areas/{note.name}: a difference between the readings is not settled: {line.strip()[:80]}")
    inv_path = d / "inventory.json"
    listed = set()
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 4 and cells[0] not in ("Path", "") and not set(cells[0]) <= set("-: "):
                listed.add(cells[0])
                if cells[1] in ("doc", "legacy-record") and cells[3] == "read":
                    src = re.findall(r"\bSRC-\d+\b", cells[4] if len(cells) > 4 else "")
                    index = project / "docs/project/sources/index.md"
                    known = set(re.findall(r"\bSRC-\d+\b", index.read_text(encoding="utf-8"))) if index.is_file() else set()
                    if not src:
                        fails.append(f"{cells[0]}: marked read, but its note cites no imported source (capture.py add "
                                     "... --kind doc, then SRC-<n> in the note)")
                    elif not set(src) <= known:
                        fails.append(f"{cells[0]}: cites {', '.join(sorted(set(src) - known))}, which the sources index "
                                     "does not hold")
    cited = ledger.is_file() and re.search(r"\|\s*(doc|legacy-record)\s*\|[^|]*\|\s*read\s*\|", ledger.read_text(encoding="utf-8"))
    if cited and not (project / "docs/project/sources/dossier.md").is_file():
        fails.append("documents were imported and read, but no dossier organizes them (docs/project/sources/dossier.md, "
                     "the /capture grammar), so capture.py check has nothing to prove")
    if inv_path.is_file():
        for r in json.loads(inv_path.read_text()).get("files", []):
            if r["class"] in ("lockfile", "vendored", "generated", "binary", "record"):
                continue
            if r["path"] not in listed:
                fails.append(f"{r['path']}: in the inventory but has no ledger row (a removed row is not an account)")
    rec = project / "docs/project"
    for f in RECORD:
        if not (rec / f).is_file():
            fails.append(f"docs/project/{f} is missing")
    if not labeled_commands(project):
        fails.append("AGENTS.md has no labeled Commands section")
    if not (project / ".evidence/adoption/commands.json").is_file():
        fails.append("the build and test commands were never run (adopt.py commands)")
    ms = rec / "milestones.md"
    if ms.is_file() and not re.search(r"^## M0 · ", ms.read_text(encoding="utf-8"), re.M):
        fails.append("milestones.md has no M0 section (the product as found)")
    intent = rec / "intent.md"
    if intent.is_file():
        for line in intent.read_text(encoding="utf-8").splitlines():
            if re.match(r"^- I-D\d+", line) and not re.search(r"\[(code|doc|git|owner|capture) ", line):
                fails.append(f"reconstructed done example without an evidence label: {line[:60]}")
    inv = d / "inventory.json"
    if inv.is_file():
        for r in json.loads(inv.read_text()).get("files", []):
            if r["class"] == "legacy-record":
                p = project / r["path"]
                if p.is_file() and "SUPERSEDED" not in p.read_text(errors="ignore")[:400]:
                    fails.append(f"{r['path']}: an earlier pipeline's file is not marked '> SUPERSEDED <date>: ...'")
    if (rec / "sources").is_dir() and (rec / "sources/dossier.md").is_file():
        r = subprocess.run([sys.executable, str(HERE / "capture.py"), "check", str(project)], capture_output=True, text=True)
        if r.returncode != 0:
            fails.append("the documents' dossier fails capture.py check:\n" + r.stdout.strip()[:800])
    for f in fails:
        print(f"FAIL   adopt       {f}")
    if not fails:
        print("PASS   adopt       every file accounted for; the record is complete and evidenced")
    return 1 if fails else 0


def main(argv):
    if len(argv) != 2 or argv[0] not in ("inventory", "commands", "check"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    return {"inventory": inventory, "commands": run_commands, "check": check}[argv[0]](argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
