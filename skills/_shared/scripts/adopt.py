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
  reading-plan.md   areas in reading order with sizes, so the modules that carry the documented mechanisms
                    and the entry points are read first
  coverage.md       the ledger: one row per document and code file ("todo"), with lock files, vendored,
                    generated, binary, and asset files pre-accounted as "skipped (<class>)"
Ledger statuses: captured (SRC-<n>: imported by capture.py add --inventory, read by an independent extraction
and cleared by an audit) · read (a document, citing SRC-<n>) · mapped (<how>: code and tests, understood through
the code map, the reading of the modules that matter, and the characterization) · registered (<summary>: data,
raw output, and logs, summarized by script in bulk.md) · skipped (<reason>) · stale (<evidence>) · superseded
(<by what>).

check FAILs when: a file the inventory lists (other than pre-accounted lock, vendored, generated, binary, and
record files) has no ledger row, or a row still todo; a document is not read, captured, registered, stale, or
superseded; a code, test, configuration, or other file is not captured, mapped, registered, stale, superseded, or
skipped with a reason; a captured or read row cites no source the sources index holds; the dossier fails
capture.py check (every unit of every source accounted for, every source extracted once and audited until an
audit finds nothing material) or capture.py closure (every point lands in the record); a git repository's
history is not captured
(capture.py add --git-log); a GitHub project's issue tracker is neither captured (--tracker) nor recorded in
brief.md as "Tracker: not read (<reason>)"; a record file is missing (intent, brief, milestones, interfaces,
decisions, state, gate); AGENTS.md has no labeled Commands; the commands were never run (adopt.py commands);
milestones.md has no M0 (the product as found); a reconstructed done example or must-not-lose item carries no
evidence label ([code ...], [doc ...], [git ...], [owner ...], [capture ...]); an earlier pipeline's file is not
marked superseded; the characterization of M0 (gate_run.py --intent-only) never ran, ran on an older draft of
the intent, or could not conclude (INCONCLUSIVE or ERROR), or a discrepancy it found (a row not HOLDS, or a
finding only the owner can settle) is missing from brief.md's "## Discrepancies" section.
Exit 0 on success, 1 on a FAIL, 2 on bad usage.
"""
import datetime
import hashlib
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
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".gz", ".mp3", ".mp4", ".mov",
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
            "Documents are read by an independent extraction and audited (/capture's reading); read the highest in "
            "this list yourself as well. Code is understood through the map: read the entry points and every module "
            "that carries a documented mechanism in full, the rest where the map leaves its role open, and write what "
            "you learn to areas/<area>.md as you go; never read a file twice.", "", "## Documents (by authority signal)"]
    plan += [f"- {d['path']} · {d['lines']} lines · last change {d.get('last_change') or 'unknown'}" for d in docs] or ["- none"]
    plan += ["", "## Areas", "| Area | Files | Lines | How |", "|---|---|---|---|"]
    for key, a in sorted(areas.items(), key=lambda kv: -kv[1]["lines"]):
        how = f"map first, then its load-bearing modules; notes in areas/{re.sub(r'[^a-z0-9]+', '-', key.lower()).strip('-')}.md" \
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


def characterization_problems(project, brief_text):
    """The blind characterization of M0 must have run on the current draft, and each discrepancy it found must be
    listed for the owner."""
    rounds = sorted((Path(project) / ".evidence/loyal/M0").glob("r*"),
                    key=lambda p: int(p.name[1:]) if p.name[1:].isdigit() else 0)
    finished = [r for r in rounds if (r / "verdict.json").is_file()]
    if not finished:
        return ["the characterization of M0 never ran (gate_run.py <project> --milestone M0 --intent-only)"]
    last = finished[-1]
    verdict = json.loads((last / "verdict.json").read_text())
    if verdict.get("verdict") in ("INCONCLUSIVE", "ERROR"):
        return [f"the latest characterization ({last.name}) ended {verdict.get('verdict')}; run it again once the "
                "cause is cleared: " + "; ".join(verdict.get("reasons") or [])[:300]]
    intent = Path(project) / "docs/project/intent.md"
    now_sha = hashlib.sha256(intent.read_bytes()).hexdigest() if intent.is_file() else None
    if verdict.get("intent_sha") != now_sha:
        return [f"the draft intent changed after the latest characterization ({last.name}); run it again on this draft"]
    judge = (last / "gate-judge.result.md").read_text(encoding="utf-8") if (last / "gate-judge.result.md").is_file() else ""
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", judge, flags=re.S)
    rows = []
    for b in reversed(blocks):
        try:
            rows = json.loads(b).get("intent_diff") or []
            break
        except ValueError:
            continue
    section = re.search(r"^## Discrepancies\s*$(.*?)(?=^## |\Z)", brief_text, re.M | re.S)
    listed = section.group(1) if section else ""
    out = []
    for r in rows:
        if str(r.get("status", "")).upper() != "HOLDS" and str(r.get("id", "")) not in listed:
            out.append(f"characterization found {r.get('id')} {str(r.get('status', '')).upper()}, which brief.md's "
                       "## Discrepancies does not list for the owner")
    # A finding only the owner can settle (the round ends BLOCKED) is exactly a discrepancy for the lock.
    for b in judge_blocking(judge):
        if b.get("id") and str(b["id"]) not in listed:
            out.append(f"characterization raised {b['id']} ({str(b.get('summary', ''))[:60]}), which brief.md's "
                       "## Discrepancies does not list for the owner")
    return out


def judge_blocking(judge_text):
    for b in reversed(re.findall(r"```json\s*(\{.*?\})\s*```", judge_text or "", flags=re.S)):
        try:
            return json.loads(b).get("blocking") or []
        except ValueError:
            continue
    return []


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
                fails.append(f"{path}: not accounted for yet" + (f" ({note})" if note else ""))
            elif cls in ("doc", "legacy-record") and not re.match(
                    r"^(read|captured|registered \(.+\)|stale \(.+\)|superseded \(.+\))$", status):
                fails.append(f"{path}: a document must be read or captured, or registered as bulk (or marked "
                             f"stale/superseded with evidence), not '{status}'")
            elif cls not in ("doc", "legacy-record") and not re.match(
                    r"^(captured|mapped \(.+\)|registered \(.+\)|skipped \(.+\)|stale \(.+\)|superseded \(.+\))$", status):
                fails.append(f"{path}: code and tests are mapped, configuration captured, data registered (capture.py "
                             f"add --inventory), or skipped with a reason; '{status}' is not enough")
    inv_path = d / "inventory.json"
    listed = set()
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 4 and cells[0] not in ("Path", "") and not set(cells[0]) <= set("-: "):
                listed.add(cells[0])
                if cells[3] in ("read", "captured"):
                    src = re.findall(r"\bSRC-\d+\b", cells[4] if len(cells) > 4 else "")
                    index = project / "docs/project/sources/index.md"
                    known = set(re.findall(r"\bSRC-\d+\b", index.read_text(encoding="utf-8"))) if index.is_file() else set()
                    if not src:
                        fails.append(f"{cells[0]}: marked {cells[3]}, but its note cites no imported source (capture.py "
                                     "add, then SRC-<n> in the note)")
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
            if re.match(r"^- (I-D\d+|L-\d+)", line) and not re.search(r"\[(code|doc|git|owner|capture) ", line):
                fails.append(f"reconstructed done example or must-not-lose item without an evidence label: {line[:60]}")
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
            fails.append("the dossier fails capture.py check:\n" + r.stdout.strip()[:800])
        r = subprocess.run([sys.executable, str(HERE / "capture.py"), "closure", str(project)], capture_output=True, text=True)
        if r.returncode != 0:
            fails.append("a point the reading found does not land in the record (capture.py closure):\n"
                         + r.stdout.strip()[:800])
    kinds = set()
    for meta in (rec / "sources").glob("SRC-*/meta.json") if (rec / "sources").is_dir() else []:
        try:
            kinds.add(json.loads(meta.read_text())["kind"])
        except (OSError, ValueError, KeyError):
            continue
    has_history = (project / ".git").exists() and bool(git(project, "rev-list", "-n", "1", "HEAD").strip())
    if has_history and "git-history" not in kinds:
        fails.append("the commit history was not read (capture.py add <project> --git-log)")
    remotes = git(project, "remote", "-v") if (project / ".git").exists() else ""
    brief_text = (rec / "brief.md").read_text(encoding="utf-8") if (rec / "brief.md").is_file() else ""
    if "github.com" in remotes and "tracker" not in kinds and not re.search(r"^Tracker: not read \(.+\)", brief_text, re.M):
        fails.append("the GitHub issues and pull requests were not read (capture.py add <project> --tracker), and "
                     "brief.md does not say why (Tracker: not read (<reason>))")
    fails += characterization_problems(project, brief_text)
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
