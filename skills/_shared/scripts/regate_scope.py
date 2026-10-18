#!/usr/bin/env python3
"""Decide whether a gate round is focused or full, and keep the candidate snapshots that decision compares.

Usage:
  regate_scope.py decide <project> --milestone M<k> --round <n> --out <ev>/scope.json [--full]

decide writes scope.json and prints one line: the scope and its reasons. gate_run.py calls it at the start of
every gate round; a focused round carries the blind evaluator's results from the last full round and runs the
code-verifier in re-verify mode on the open findings and the delta.

A round is focused only when ALL of these hold; otherwise it is full, and every reason that applies is listed:
  - it is not round 1 and --full was not given;
  - kind "changes": the previous round of this milestone ended CHANGES, and the milestone is not the final one
    (the last milestone in milestones.md whose Status is not dropped: its build rounds are always full); or
    kind "hotfix" (on any milestone, the final one included): the milestone is accepted (Status accepted and
    an owner acceptance in decisions.md naming a fingerprint) and docs/project/fix-log.md has entries dated on
    or after that acceptance that were not yet in the log when the accepted candidate passed (the entry IDs
    accepted-candidate.json records; without that record, entries dated after the acceptance day only);
  - since: the candidate of the last FULL round, whose evaluator results are carried, for both kinds: the
    whole change since it must meet every rule below, however many focused rounds and hotfixes lie between.
    Its listing (r<n>/candidate.txt) and its content snapshot (.evidence/gate/M<k>/full-candidate/) must
    exist; a hotfix also needs the accepted candidate's (accepted-candidate/), which its re-verify starts from;
  - every file changed since then is a test file (gate_checks.py's patterns) or is named in the files of a
    finding that was blocking in some round since then (the findings ledger, reviews/M<k>.findings.json), or,
    for a hotfix, in the Change line of a fix-log entry since the acceptance; a blocking finding without files
    forces full; logged findings never count;
  - fewer than 150 changed lines since then (added plus removed); a changed file whose lines cannot be counted
    (binary, not UTF-8 text, or a symlink) forces full;
  - no changed file is intent-bearing (gate.md "Intent-bearing paths", docs/project/), a dependency manifest,
    a lockfile, a migration, or build or CI configuration; intent.md and the milestone's contract are as
    they were when the carried evidence was made;
  - the carried evidence is usable: the last full round's loyal-evaluator pass 1 and pass 2 summaries are
    status OK, their result files exist, and the fingerprint they ran on is recorded.

scope.json: scope ("focused" or "full"), milestone, kind ("changes", "hotfix", or null), reasons, since {round,
fingerprint, snapshot} (the last full round's candidate), changed_files [{path, status, added, removed}] and
changed_lines (since then; added and removed are null, with binary true, for a file whose lines cannot be
counted), delta_patch (the unified diff from that snapshot to the current tree, <ev>/delta.patch), reverify
{since, changed_files, changed_lines, delta_patch}: the delta the re-verify reviews (for kind changes the same
as above; for a hotfix the change since the accepted candidate, <ev>/reverify-delta.patch), findings [{id,
status, fixed_round, summary, class, severity, files, where, fixed_when}] (every finding blocking in some round
since the last full round, open or fixed, each with its current ledger status: the re-verify re-checks them
all, so a fix undone later is caught), fixes [{id, title, symptom, reproduction, change}] (a hotfix's fix-log
entries), carried {"loyal-evaluator": {round, fingerprint, summary, result}, "loyal-evaluator-pass2": {...}}.

Snapshots (kept by gate_run.py through this module): every round writes <ev>/candidate.txt (fingerprint.py
--list format); a full round keeps .evidence/gate/M<k>/full-candidate/ and an ACCEPT-READY round keeps
accepted-candidate/, each a copy of the candidate's product files (a clone where the disk supports it) that
replaces the previous one, with <name>.json beside it recording the round, the fingerprint, the intent's hash,
and the milestone's contract hash; accepted-candidate.json also records fix_log_ids, the fix-log entries
present when that candidate passed.
Exit 0 when scope.json was written (focused or full), 1 when it could not be, 2 on bad usage.
"""
import datetime
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from baseline import diff_lines, read_listing, text_of, unified  # noqa: E402
from fingerprint import fingerprint, fingerprint_of  # noqa: E402
from gate_checks import is_test_file  # noqa: E402
from gate_keys import read_keys  # noqa: E402

LINE_LIMIT = 150
EVALUATOR = ("loyal-evaluator", "loyal-evaluator-pass2")
# A change to any of these reaches past the files a finding names, so the round is full whatever else holds.
FULL_PATHS = (
    ("dependency manifest", re.compile(
        r"(^|/)(package\.json|pyproject\.toml|setup\.py|setup\.cfg|requirements[^/]*\.(txt|in)|Pipfile|Cargo\.toml|"
        r"go\.mod|Gemfile|[^/]+\.gemspec|composer\.json|Podfile|Package\.swift|build\.gradle(\.kts)?|"
        r"settings\.gradle(\.kts)?|pom\.xml|[^/]+\.(csproj|fsproj|vbproj)|deno\.jsonc?|environment\.ya?ml|mix\.exs|"
        r"pubspec\.yaml|vcpkg\.json|conanfile\.(txt|py))$")),
    ("lockfile", re.compile(
        r"(^|/)(package-lock\.json|npm-shrinkwrap\.json|yarn\.lock|pnpm-lock\.yaml|bun\.lockb?|poetry\.lock|uv\.lock|"
        r"Pipfile\.lock|Cargo\.lock|go\.sum|Gemfile\.lock|composer\.lock|Podfile\.lock|Package\.resolved|"
        r"pubspec\.lock|mix\.lock|deno\.lock|flake\.lock|gradle\.lockfile|[^/]+\.lock)$")),
    ("migration", re.compile(
        r"(^|/)(migrations?|migrate|alembic|flyway|liquibase)/|(^|/)(schema\.(prisma|sql|rb)|structure\.sql)$")),
    ("build or CI configuration", re.compile(
        r"(^|/)(\.github|\.gitlab|\.circleci|\.buildkite|\.husky)/|"
        r"(^|/)(\.gitlab-ci\.ya?ml|\.travis\.ya?ml|azure-pipelines\.ya?ml|bitbucket-pipelines\.ya?ml|Jenkinsfile|"
        r"Makefile|makefile|GNUmakefile|[^/]+\.mk|Dockerfile[^/]*|[^/]+\.dockerfile|docker-compose[^/]*\.ya?ml|"
        r"compose\.ya?ml|Procfile|tsconfig[^/]*\.json|jsconfig\.json|"
        r"(webpack|vite|rollup|babel|next|nuxt|svelte|astro|remix|esbuild|tsup|metro|jest|vitest|playwright|"
        r"cypress|karma|postcss|tailwind)\.config\.[^/]+|vitest\.workspace\.[^/]+|\.babelrc[^/]*|\.swcrc|"
        r"\.eslintrc[^/]*|eslint\.config\.[^/]+|\.mocharc[^/]*|turbo\.json|nx\.json|lerna\.json|CMakeLists\.txt|"
        r"[^/]+\.cmake|meson\.build|build\.rs|BUILD(\.bazel)?|WORKSPACE(\.bazel)?|MODULE\.bazel|Rakefile|"
        r"noxfile\.py|tox\.ini|pytest\.ini|\.coveragerc|gradle\.properties|gradlew|[^/]+\.xcodeproj/[^/]+|"
        r"netlify\.toml|vercel\.json|fly\.toml|\.tool-versions|\.nvmrc|\.python-version|"
        r"rust-toolchain(\.toml)?)$")),
)
FIX_ENTRY = re.compile(r"^## (F-\d+)\s*\u00b7\s*(\d{4}-\d{2}-\d{2})\s*\u00b7\s*(.*?)\s*$(.*?)(?=^## |\Z)", re.M | re.S)
DECISION = re.compile(r"^## (D-\d+)\s*\u00b7\s*(\d{4}-\d{2}-\d{2})\b.*?$(.*?)(?=^## |\Z)", re.M | re.S)
PATH_TOKEN = re.compile(r"[\w.@+-]*[\w@+-](?:/[\w.@+-]+)+/?|[\w.@+-]+\.[A-Za-z0-9]{1,8}\b")


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def base_dir(project, mid):
    return Path(project) / f".evidence/gate/{mid}"


# ---- listings and snapshots ---------------------------------------------------------------------------------
def write_listing(path, fp, rows):
    """The candidate's listing, in fingerprint.py --list format (the fingerprint, then "<hash16>  <path>")."""
    Path(path).write_text(fp + "\n" + "".join(f"{h[:16]}  {rel}\n" for rel, h in rows), encoding="utf-8")


def intent_hash(project):
    p = Path(project) / "docs/project/intent.md"
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def contract_of(project, mid):
    """The milestone's contract hash (Promise, Carries, Demo ending, Done examples), as milestone_lint computes it."""
    p = Path(project) / "docs/project/milestones.md"
    if not p.is_file():
        return None
    import milestone_lint  # noqa: E402
    sections = milestone_lint.split_sections(p.read_text(encoding="utf-8"))[0]
    return milestone_lint.contract_hash(sections[mid]) if mid in sections else None


def copy_files(src_root, rels, dst):
    """Copy rels from src_root into dst: an APFS clone (cp -c) where the disk supports it, else a plain copy.
    The method is settled on the first file, so a disk without clones does not pay a failed cp per file."""
    method = None
    for rel in rels:
        src, out = Path(src_root) / rel, Path(dst) / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            os.symlink(os.readlink(src), out)
            continue
        if method in (None, "clone"):
            r = subprocess.run(["cp", "-c", str(src), str(out)], capture_output=True)
            if r.returncode == 0:
                method = "clone"
                continue
            method = "copy"
        shutil.copy2(src, out)
    return method or "copy"


def keep_snapshot(project, mid, which, rnd, fp, rows, source=None):
    """Keep <which>-candidate/ (which: full or accepted) for round rnd: the product files of rows, copied from the
    project (or from the snapshot folder source), checked against fp, replacing the previous one. Returns
    (True, line) or (False, reason); on failure the old snapshot and its record are removed too, so a later
    decide reads "snapshot missing" instead of comparing against a candidate that is not this one."""
    base = base_dir(project, mid)
    base.mkdir(parents=True, exist_ok=True)
    snap, rec = base / f"{which}-candidate", base / f"{which}-candidate.json"
    tmp = base / f".{which}-candidate.new"
    shutil.rmtree(tmp, ignore_errors=True)
    rels = [rel for rel, h in rows if h != "deleted"]
    try:
        tmp.mkdir()
        method = copy_files(source or project, rels, tmp)
        got = fingerprint_of(tmp, [rel for rel, _ in rows])
        if got != fp:
            raise OSError(f"the copy has fingerprint {got}, the candidate is {fp} (the tree changed while copying)")
        rec.unlink(missing_ok=True)  # no record names a half-replaced snapshot
        shutil.rmtree(snap, ignore_errors=True)
        tmp.rename(snap)
        record = {"round": rnd, "fingerprint": fp, "files": len(rels), "method": method,
                  "intent_sha256": intent_hash(project), "contract": contract_of(project, mid),
                  "kept": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        if which == "accepted":
            # The fix-log entries written before this candidate passed: a later hotfix counts only the others,
            # whatever their date says (an entry of the gate fix itself is often dated the acceptance day).
            record["fix_log_ids"] = fix_log_ids(project)
        rec.write_text(json.dumps(record, indent=2))
    except OSError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(snap, ignore_errors=True)
        rec.unlink(missing_ok=True)
        return False, f"{which}-candidate not kept: {exc}"
    return True, f"{which}-candidate kept: r{rnd} {fp}, {len(rels)} files ({method})"


# ---- the record ---------------------------------------------------------------------------------------------
def milestones(project):
    p = Path(project) / "docs/project/milestones.md"
    text = p.read_text(encoding="utf-8") if p.is_file() else ""
    return [(m.group(1), m.group(0)) for m in re.finditer(r"^## (M\d+) \u00b7.*?(?=^## |\Z)", text, flags=re.M | re.S)]


def status_of(section):
    m = re.search(r"^Status:\s*(\S+)", section, flags=re.M)
    return m.group(1).lower() if m else ""


def acceptance(project, mid):
    """The latest owner acceptance of mid in decisions.md: {id, date, fingerprint}, or None."""
    p = Path(project) / "docs/project/decisions.md"
    found = None
    for m in DECISION.finditer(p.read_text(encoding="utf-8") if p.is_file() else ""):
        body = m.group(0)
        acc = re.search(rf"Accept {re.escape(mid)} \u00b7 contract \S+ \u00b7 fingerprint (\S+)", body)
        if acc and re.search(r"^Source:[ \t]*\[owner ", body, flags=re.M):
            found = {"id": m.group(1), "date": m.group(2), "fingerprint": acc.group(1)}
    return found


def fix_log_text(project):
    p = Path(project) / "docs/project/fix-log.md"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def fix_log_ids(project):
    """The IDs of every entry in docs/project/fix-log.md now."""
    return [m.group(1) for m in FIX_ENTRY.finditer(fix_log_text(project))]


def fix_entries(project, since_date, known=None):
    """Fix-log entries dated on or after since_date and not among known (the entries already in the log when the
    accepted candidate passed). With known None (no such record), an entry dated since_date itself may predate
    the acceptance, so only entries dated after it count."""
    out = []
    for m in FIX_ENTRY.finditer(fix_log_text(project)):
        if m.group(2) < since_date or (known is None and m.group(2) == since_date) or \
                (known is not None and m.group(1) in known):
            continue
        body = m.group(4)

        def line(label):
            lm = re.search(rf"^{label}:[ \t]*(.*)$", body, flags=re.M)
            return lm.group(1).strip() if lm else ""
        out.append({"id": m.group(1), "date": m.group(2), "title": m.group(3), "symptom": line("Symptom"),
                    "reproduction": line("Reproduction"), "change": line("Change")})
    return out


def norm(path):
    """A finding's file as a project-relative path: no ./, no leading /, no :line suffix, no backticks."""
    p = str(path or "").strip().strip("`'\"")
    p = re.sub(r":\d+(?:[-:]\d+)?$", "", p)
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def covered(rel, names):
    return any(n and (rel == n or rel.startswith(n.rstrip("/") + "/")) for n in names)


def named_in_changes(fixes, product):
    """The product paths a fix-log Change line names: exact paths, or a bare file name that only one product file
    has."""
    by_name = {}
    for rel in product:
        by_name.setdefault(rel.rsplit("/", 1)[-1], []).append(rel)
    names = set()
    for f in fixes:
        for tok in PATH_TOKEN.findall(f.get("change") or ""):
            tok = norm(tok.rstrip(".,;:)"))
            if tok in product or "/" in tok:
                names.add(tok)
            elif len(by_name.get(tok, [])) == 1:
                names.add(by_name[tok][0])
    return names


# ---- the delta ----------------------------------------------------------------------------------------------
def delta(project, snap, old, cur, patch_path):
    """Every file changed between the snapshot (listing old) and the tree (rows cur), with its added and removed
    lines, and the unified diff written to patch_path by baseline.py's writer (the one the review patch uses: a
    last line without a newline carries git's marker, so the next line is never glued to it). A file whose lines
    cannot be counted (binary, not UTF-8 text, or a symlink) has added and removed None and binary True, and a
    git-style "Binary files ... differ" line in the patch."""
    changed, chunks = [], []
    for rel in sorted(set(old) | set(cur)):
        o = old.get(rel) if old.get(rel) != "deleted" else None
        c = cur.get(rel) if cur.get(rel) != "deleted" else None
        if o == c:
            continue
        status = "added" if o is None else "deleted" if c is None else "modified"
        link = (o is not None and (Path(snap) / rel).is_symlink()) or \
            (c is not None and (Path(project) / rel).is_symlink())
        before = text_of(Path(snap) / rel) if o is not None else ""
        after = text_of(Path(project) / rel) if c is not None else ""
        if before is None or after is None or link:
            a_name = "/dev/null" if o is None else f"a/{rel}"
            b_name = "/dev/null" if c is None else f"b/{rel}"
            chunks.append(f"Binary files {a_name} and {b_name} differ\n")
            changed.append({"path": rel, "status": status, "added": None, "removed": None, "binary": True,
                            "why": "a symlink" if link else "binary or not UTF-8 text"})
            continue
        added = removed = 0
        opcodes = difflib.SequenceMatcher(None, diff_lines(before), diff_lines(after), autojunk=False).get_opcodes()
        for tag, i1, i2, j1, j2 in opcodes:
            if tag in ("replace", "delete"):
                removed += i2 - i1
            if tag in ("replace", "insert"):
                added += j2 - j1
        chunks.append(unified(rel, before, after, status))
        changed.append({"path": rel, "status": status, "added": added, "removed": removed})
    Path(patch_path).write_text("".join(chunks), encoding="utf-8")
    return changed


def counted_lines(changed):
    return sum(c["added"] + c["removed"] for c in changed if isinstance(c.get("added"), int))


# ---- the decision -------------------------------------------------------------------------------------------
def carried_evidence(base, full_rec):
    """The last full round's evaluator results ({stem: {round, fingerprint, summary, result}}) and what makes them
    unusable."""
    if not full_rec:
        return {}, ["no full round on record whose evaluator results could be carried"]
    rnd, fp = full_rec.get("round"), full_rec.get("fingerprint")
    rdir = base / f"r{rnd}"
    listing = rdir / "candidate.txt"
    ran_on = read_listing(listing)[0] if listing.is_file() else None
    problems = [] if fp and ran_on == fp else \
        [f"the fingerprint r{rnd}'s evaluator ran on is not recorded (r{rnd}/candidate.txt)"]
    out = {}
    for stem in EVALUATOR:
        summary, result = rdir / f"{stem}.summary.json", rdir / f"{stem}.result.md"
        s = load(summary)
        if not isinstance(s, dict):
            problems.append(f"r{rnd} has no {stem} summary")
        elif s.get("status") != "OK":
            problems.append(f"r{rnd}'s {stem} ended {s.get('status')}, so it cannot be carried")
        if not result.is_file():
            problems.append(f"r{rnd} has no {stem} result")
        out[stem] = {"round": rnd, "fingerprint": fp, "summary": str(summary), "result": str(result)}
    return out, problems


def snapshot_of(base, rec, name, what, full):
    """(listing rows, {round, fingerprint, snapshot}) of the snapshot <name>/ that rec records, or (None, None) with
    the reason appended to full."""
    snap = base / name
    listing = base / f"r{(rec or {}).get('round')}/candidate.txt"
    if not rec or not snap.is_dir() or not listing.is_file():
        full.append(f"snapshot missing: no listing and content snapshot of {what} to measure the change from")
        return None, None
    fp, rows = read_listing(listing)
    if fp != rec.get("fingerprint"):
        full.append(f"snapshot missing: r{rec.get('round')}/candidate.txt names {fp}, the {name} snapshot "
                    f"{rec.get('fingerprint')}")
        return None, None
    return rows, {"round": rec.get("round"), "fingerprint": fp, "snapshot": str(snap)}


def decide(project, mid, rnd, out, force_full=False):
    project = Path(project).resolve()
    base, ev = base_dir(project, mid), Path(out).resolve().parent
    ev.mkdir(parents=True, exist_ok=True)
    full, ok = [], []
    scope = {"scope": "full", "milestone": mid, "kind": None, "reasons": [], "since": None, "changed_files": [],
             "changed_lines": 0, "delta_patch": None, "reverify": None, "findings": [], "fixes": [], "carried": {}}

    def finish():
        scope["scope"] = "focused" if not full else "full"
        scope["reasons"] = full or ok
        Path(out).write_text(json.dumps(scope, indent=2, ensure_ascii=False), encoding="utf-8")
        return scope

    if rnd <= 1:
        full.append("round 1 is always full")
        return finish()
    if force_full:
        full.append("--full was given")
    ms = milestones(project)
    sections = dict(ms)
    if mid not in sections:
        full.append(f"{mid} is not in docs/project/milestones.md")
        return finish()
    live = [m for m, text in ms if status_of(text) != "dropped"]
    final = bool(live and live[-1] == mid)

    # The kind of re-gate. Whatever the kind, the change is measured from the last full round, whose evaluator
    # results are carried; a hotfix's re-verify reviews only what changed since the accepted candidate.
    full_rec = load(base / "full-candidate.json")
    full_rec = full_rec if isinstance(full_rec, dict) else None
    prev = load(base / f"r{rnd - 1}/verdict.json") or {}
    acc = acc_rec = since_problem = None
    fixes = []
    if status_of(sections[mid]) == "accepted":
        acc = acceptance(project, mid)
        if not acc:
            full.append(f"{mid} is accepted, but decisions.md has no owner acceptance naming a fingerprint")
        else:
            rec = load(base / "accepted-candidate.json")
            acc_rec = rec if isinstance(rec, dict) else None
            known = (acc_rec or {}).get("fix_log_ids")
            fixes = fix_entries(project, acc["date"], known if isinstance(known, list) else None)
            if not fixes:
                full.append(f"{mid} is accepted ({acc['id']}, {acc['date']}) and the fix log has no entry since "
                            "(dated on or after it and not yet logged when the accepted candidate passed), so this "
                            "is not a hotfix re-gate")
            else:
                scope.update(kind="hotfix", fixes=[{k: f[k] for k in ("id", "title", "symptom", "reproduction",
                                                                       "change")} for f in fixes])
                ok.append(f"a hotfix re-gate of accepted {mid}: fix-log {', '.join(f['id'] for f in fixes)} since "
                          f"the acceptance on {acc['date']}")
                if acc_rec and acc_rec.get("fingerprint") != acc["fingerprint"]:
                    since_problem = (f"the accepted-candidate snapshot is {acc_rec.get('fingerprint')}, but "
                                     f"{acc['id']} accepted {acc['fingerprint']}")
    elif str(prev.get("verdict")).upper() == "CHANGES":
        scope["kind"] = "changes"
        ok.append(f"the previous round (r{rnd - 1}) ended CHANGES")
    else:
        full.append(f"the previous round (r{rnd - 1}) ended {prev.get('verdict') or 'without a verdict'}, not "
                    "CHANGES, and this is not a hotfix after acceptance")
    if final and scope["kind"] != "hotfix":
        # The final milestone's build rounds are always full; a hotfix after its acceptance may still be focused.
        full.append(f"{mid} is the final milestone (the last one not dropped), so every round is full")
    if not scope["kind"]:
        return finish()

    carried, problems = carried_evidence(base, full_rec)
    scope["carried"] = carried
    full += [f"carried evidence unusable: {p}" for p in problems]
    if not problems:
        ok.append(f"the evaluator's results from r{full_rec['round']} ({full_rec['fingerprint']}) are carried")
        if full_rec.get("intent_sha256") != intent_hash(project):
            full.append(f"docs/project/intent.md changed since r{full_rec['round']}, whose evaluator results "
                        "would be carried")
        if full_rec.get("contract") != contract_of(project, mid):
            full.append(f"{mid}'s contract (Promise, Carries, Demo ending, Done examples) changed since "
                        f"r{full_rec['round']}")

    if since_problem:
        full.append(since_problem)
        return finish()
    old, since = snapshot_of(base, full_rec, "full-candidate",
                             "the last full round's candidate (the one the carried evaluator results ran on)", full)
    if since is None:
        return finish()
    scope["since"] = since
    acc_old = acc_since = None
    if scope["kind"] == "hotfix":
        acc_old, acc_since = snapshot_of(base, acc_rec, "accepted-candidate", "the accepted candidate", full)
        if acc_since is None:
            return finish()

    # The change since the last full round: every rule below measures all of it, cumulatively.
    _, rows = fingerprint(project, "product")
    cur = {rel: h[:16] for rel, h in rows}
    patch = ev / "delta.patch"
    changed = delta(project, Path(since["snapshot"]), old, cur, patch)
    scope.update(changed_files=changed, changed_lines=counted_lines(changed), delta_patch=str(patch))
    if scope["kind"] == "hotfix":
        rpatch = ev / "reverify-delta.patch"
        rchanged = delta(project, Path(acc_since["snapshot"]), acc_old, cur, rpatch)
        scope["reverify"] = {"since": acc_since, "changed_files": rchanged, "changed_lines": counted_lines(rchanged),
                             "delta_patch": str(rpatch)}
    else:
        scope["reverify"] = {"since": since, "changed_files": changed, "changed_lines": scope["changed_lines"],
                             "delta_patch": str(patch)}

    # The findings blocking in some round since the last full round, open or fixed: their files bound the change,
    # and the re-verify re-checks every one (a fix undone by a later fix is caught there). A logged finding never
    # blocked, so it never counts.
    ledger = load(project / f"docs/project/reviews/{mid}.findings.json")
    ledger = ledger if isinstance(ledger, dict) else {}
    since_round = since.get("round") or 0
    in_range = {fid: row for fid, row in ledger.items() if isinstance(row, dict) and
                any(isinstance(n, int) and n >= since_round for n in row.get("rounds_blocking") or [])}
    files = {fid: [norm(f) for f in ([row["files"]] if isinstance(row.get("files"), str) else
                                     row.get("files") or []) if norm(f)] for fid, row in in_range.items()}
    bare = sorted(fid for fid in in_range if not files[fid])
    if bare:
        full.append("blocking finding(s) without files, so the fix cannot be bounded: " + ", ".join(bare))
    names = {f for fs in files.values() for f in fs}
    scope["findings"] = [{"id": fid, "status": row.get("status"), "fixed_round": row.get("fixed_round"),
                          **{k: row.get(k) for k in ("summary", "class", "severity", "files", "where", "fixed_when")}}
                         for fid, row in in_range.items()]
    named_by = f"a finding blocking since r{since_round}"
    if scope["kind"] == "hotfix":
        names |= named_in_changes(fixes, set(cur) | set(old) | set(acc_old))
        named_by += " or a fix-log Change line since the acceptance"
    intent_paths = [norm(p) for p in read_keys(project).get("Intent-bearing paths") or []] + ["docs/project/"]
    outside = []
    for c in changed:
        rel = c["path"]
        if covered(rel, intent_paths):
            full.append(f"{rel} is intent-bearing")
            continue
        kinds = [k for k, rx in FULL_PATHS if rx.search(rel)]
        if kinds:
            full.append(f"{rel} is a {kinds[0]}")
            continue
        if c.get("binary"):
            full.append(f"{rel} changed since r{since_round} and its lines cannot be counted ({c.get('why')})")
            continue
        if not (is_test_file(rel) or covered(rel, names)):
            outside.append(rel)
    if outside:
        full.append(f"changed since r{since_round} but neither a test file nor named in {named_by}: "
                    + ", ".join(outside))
    if scope["changed_lines"] >= LINE_LIMIT:
        full.append(f"{scope['changed_lines']} changed lines since r{since_round} (the limit for a focused round is "
                    f"under {LINE_LIMIT})")
    ok.append(f"{len(changed)} file(s) and {scope['changed_lines']} line(s) changed since r{since_round}, "
              f"each a test file or named in {named_by}")
    if scope["kind"] == "hotfix":
        rv = scope["reverify"]
        ok.append(f"the re-verify reviews the change since the accepted candidate (r{acc_since['round']}): "
                  f"{len(rv['changed_files'])} file(s), {rv['changed_lines']} line(s)")
    return finish()


def main(argv):
    if len(argv) < 2 or argv[0] != "decide" or argv[1].startswith("--"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    opts = {argv[i]: argv[i + 1] for i in range(2, len(argv) - 1) if argv[i] in ("--milestone", "--round", "--out")}
    if set(opts) != {"--milestone", "--round", "--out"} or not opts["--round"].isdigit() or \
            not re.fullmatch(r"M\d+", opts["--milestone"]):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    project = Path(argv[1])
    if not project.is_dir():
        print(f"regate_scope: not a directory: {project}", file=sys.stderr)
        return 2
    try:
        scope = decide(project, opts["--milestone"], int(opts["--round"]), Path(opts["--out"]), "--full" in argv)
    except OSError as exc:
        print(f"regate_scope: scope.json not written: {exc}", file=sys.stderr)
        return 1
    print(f"{scope['scope']}: " + "; ".join(scope["reasons"]))
    return 0


if __name__ == "__main__":
    if "--help" in sys.argv[1:3] or sys.argv[1:] == ["-h"]:
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
