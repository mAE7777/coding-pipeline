#!/usr/bin/env python3
"""Record and diff a milestone's starting point.

Usage:
  baseline.py record <project> M<k>
  baseline.py diff <project> M<k> [--max-bytes 200000]
  baseline.py changed <project> M<k> [--write]

record writes .evidence/baseline-M<k>.txt (the fingerprint and per-file hashes, fingerprint.py --list
format) and .evidence/baseline/M<k>/ (a copy of every product file: an APFS clone where the disk supports
it, so it costs almost no space). Inside a git work tree with at least one commit it also writes
.evidence/baseline-M<k>.head, the full hash of the commit the milestone started from (gate_checks.py
prose-lint reads the commit messages since it); elsewhere it writes no .head file. It refuses to overwrite
an existing baseline for the same milestone: the start of a milestone happens once.
diff prints the files added, deleted, and modified since then, followed by unified diffs of the modified
and added text files up to --max-bytes (the rest are listed as not shown, never silently dropped).
changed prints the files added, modified, or deleted since the baseline, one relative path per line,
sorted. With --write it writes docs/project/reviews/M<k>.changed.txt instead (first line "# M<k>: files
changed since its baseline, at fingerprint <the current product fingerprint>", then the paths) and prints
its path; render_pack.py's demo mode reads these lists to decide which earlier demo endings to replay.
Exit 0 on success, 1 when there is no baseline or it cannot be written, 2 on bad usage.
"""
import difflib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fingerprint import fingerprint  # noqa: E402


def paths(project, mid):
    return project / f".evidence/baseline-{mid}.txt", project / f".evidence/baseline/{mid}"


def git_head(project):
    """The full hash of HEAD when the project is inside a git work tree with at least one commit, else None."""
    try:
        inside = subprocess.run(["git", "-C", str(project), "rev-parse", "--is-inside-work-tree"],
                                capture_output=True, text=True, timeout=60)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        r = subprocess.run(["git", "-C", str(project), "rev-parse", "--verify", "--quiet", "HEAD"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    sha = r.stdout.strip()
    return sha if r.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha) else None


def record(project, mid):
    listing, snap = paths(project, mid)
    if listing.exists() or snap.exists():
        print(f"baseline: {mid} already has a baseline ({listing}); a milestone starts once", file=sys.stderr)
        return 1
    fp, rows = fingerprint(project, "product")
    snap.mkdir(parents=True)
    for rel, h in rows:
        if h == "deleted":
            continue
        src, dst = project / rel, snap / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            os.symlink(os.readlink(src), dst)
            continue
        r = subprocess.run(["cp", "-c", str(src), str(dst)], capture_output=True)
        if r.returncode != 0:
            shutil.copy2(src, dst)
    listing.write_text(fp + "\n" + "".join(f"{h[:16]}  {rel}\n" for rel, h in rows))
    sha = git_head(project)
    if sha:
        (project / f".evidence/baseline-{mid}.head").write_text(sha + "\n")
    print(f"{mid} baseline {fp} · {len(rows)} files · {listing}")
    return 0


def read_listing(listing):
    lines = listing.read_text().splitlines()
    rows = {}
    for line in lines[1:]:
        if "  " in line:
            h, rel = line.split("  ", 1)
            rows[rel] = h
    return lines[0] if lines else "", rows


def text_of(path):
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def diff_lines(text):
    """Lines for difflib that keep their ends; a last line without one carries git's marker, so the change
    shows and the next diff line is never glued to it."""
    parts = text.split("\n")
    lines = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1] + "\n\\ No newline at end of file\n")
    return lines


def unified(rel, old, new, status):
    """The unified diff of one text file (old or new is "" for an added or a deleted file)."""
    a = "/dev/null" if status == "added" else f"a/{rel}"
    b = "/dev/null" if status == "deleted" else f"b/{rel}"
    return "".join(difflib.unified_diff(diff_lines(old), diff_lines(new), a, b))


def counts(diff_text):
    """(added, removed) lines of one file's unified diff (the lines in its hunks, so never the header)."""
    added = removed = 0
    in_hunks = False
    for line in diff_text.split("\n"):
        in_hunks = in_hunks or line.startswith("@@")
        if in_hunks and line.startswith("+"):
            added += 1
        elif in_hunks and line.startswith("-"):
            removed += 1
    return added, removed


def split_hunks(diff_text):
    """(the file header, [each hunk with its lines]) of one file's unified diff."""
    head, hunks = [], []
    for line in diff_text.splitlines(True):
        if line.startswith("@@"):
            hunks.append(line)
        elif hunks:
            hunks[-1] += line
        else:
            head.append(line)
    return "".join(head), hunks


HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


def split_patch(text, known=()):
    """{path: {"status", "binary", "text"}} for each file of a multi-file unified diff, git style or plain.
    Each hunk's line counts are followed, so a removed line that reads "-- x" is never taken for a header.
    A path is taken without its a/ or b/ prefix unless it is in known as written."""
    files, cur, left = [], None, [0, 0]
    lines = text.splitlines(True)
    for i, line in enumerate(lines):
        hunk = HUNK.match(line)
        if cur is not None and (left[0] > 0 or left[1] > 0):  # a line inside a hunk
            if line.startswith("-"):
                left[0] -= 1
            elif line.startswith("+"):
                left[1] -= 1
            elif not line.startswith("\\"):
                left = [left[0] - 1, left[1] - 1]
        elif cur is not None and hunk:
            left = [int(n) if n is not None else 1 for n in hunk.groups()]
            cur["hunks"] = True
        else:
            git = line.startswith("diff --git ")
            header = line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")
            binary = line.startswith("Binary files ") and line.rstrip().endswith(" differ")
            # git's extended header (index, mode, ---/+++, or Binary files) belongs to its diff --git line
            extended = cur is not None and cur["git"] and not cur["header"] and not cur["hunks"]
            if git or ((header or binary) and not extended):
                cur = {"git": git, "header": False, "hunks": False, "lines": []}
                files.append(cur)
            if cur is None:
                continue  # text before the first file
            cur["header"] = cur["header"] or header or binary
        cur["lines"].append(line)
    out = {}
    for f in files:
        old = new = None
        status, binary = "modified", False
        head = [ln.rstrip("\n") for ln in f["lines"]]
        head = head[:next((k for k, ln in enumerate(head) if ln.startswith("@@")), len(head))]
        for ln in head:
            if ln.startswith("--- "):
                old = ln[4:].split("\t")[0].strip()
            elif ln.startswith("+++ "):
                new = ln[4:].split("\t")[0].strip()
            elif ln.startswith(("Binary files ", "GIT binary patch")):
                binary = True
                m = re.match(r"Binary files (.+) and (.+) differ$", ln)
                if m:
                    old, new = old or m.group(1), new or m.group(2)
            elif ln.startswith("new file"):
                status = "added"
            elif ln.startswith("deleted file"):
                status = "deleted"
        m = re.match(r"diff --git (\S+) (\S+)$", head[0]) if head else None
        if old is None and new is None and m:
            old, new = m.group(1), m.group(2)
        status = "added" if old == "/dev/null" else "deleted" if new == "/dev/null" else status
        raw = new if new and new != "/dev/null" else old
        if not raw or raw == "/dev/null":
            continue
        path = raw if raw in known or raw[:2] not in ("a/", "b/") else raw[2:]
        out[path] = {"status": status, "binary": binary, "text": "".join(f["lines"])}
    return out


def changes(project, mid):
    """What changed since the milestone's baseline, or None when it has none:
    {"from": <fingerprint at the baseline>, "to": <fingerprint now>, "files": [{"path", "status" (added,
    deleted, or modified), "added", "removed", "diff" (the unified diff; None for a binary file)}]}, by path."""
    listing, snap = paths(project, mid)
    if not listing.is_file():
        return None
    fp_old, old = read_listing(listing)
    old = {rel: h for rel, h in old.items() if h != "deleted"}
    fp_new, rows = fingerprint(project, "product")
    cur = {rel: h[:16] for rel, h in rows if h != "deleted"}
    status = {r: "added" for r in set(cur) - set(old)}
    status.update({r: "deleted" for r in set(old) - set(cur)})
    status.update({r: "modified" for r in set(old) & set(cur) if old[r] != cur[r]})
    files = []
    for rel in sorted(status):
        st = status[rel]
        oldt = text_of(snap / rel) if st != "added" else ""
        new = text_of(project / rel) if st != "deleted" else ""
        d = unified(rel, oldt, new, st) if oldt is not None and new is not None else None
        a, r = counts(d) if d is not None else (None, None)
        files.append({"path": rel, "status": st, "added": a, "removed": r, "diff": d})
    return {"from": fp_old, "to": fp_new, "files": files}


def no_baseline(mid):
    print(f"baseline: no baseline for {mid} (run: baseline.py record <project> {mid} when the milestone starts)",
          file=sys.stderr)


def diff(project, mid, max_bytes=200000):
    ch = changes(project, mid)
    if ch is None:
        no_baseline(mid)
        return 1, None
    by = {s: [f["path"] for f in ch["files"] if f["status"] == s] for s in ("added", "deleted", "modified")}
    out = [f"baseline {ch['from']} -> now {ch['to']}", ""]
    out += [f"added     {r}" for r in by["added"]] + [f"deleted   {r}" for r in by["deleted"]] + \
        [f"modified  {r}" for r in by["modified"]]
    if not ch["files"]:
        out.append("no changes")
    files = {f["path"]: f for f in ch["files"]}
    budget, skipped = max_bytes, []
    for rel in by["modified"] + by["added"]:
        chunk = files[rel]["diff"]
        if chunk is None:
            skipped.append(f"{rel} (binary)")
            continue
        if len(chunk) > budget:
            skipped.append(f"{rel} ({len(chunk)} bytes of diff)")
            continue
        budget -= len(chunk)
        out.append("")
        out.append(chunk.rstrip("\n"))
    if skipped:
        out += ["", "Diff not shown (over the size budget or binary), inspect in the copy:"] + [f"- {s}" for s in skipped]
    return 0, "\n".join(out)


def changed(project, mid, write=False):
    ch = changes(project, mid)
    if ch is None:
        no_baseline(mid)
        return 1
    rels = [f["path"] for f in ch["files"]]
    if not write:
        if rels:
            print("\n".join(rels))
        return 0
    out = project / f"docs/project/reviews/{mid}.changed.txt"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# {mid}: files changed since its baseline, at fingerprint {ch['to']}\n" +
                       "".join(f"{r}\n" for r in rels), encoding="utf-8")
    except OSError as exc:
        print(f"baseline: cannot write {out}: {exc}", file=sys.stderr)
        return 1
    print(out)
    return 0


def main(argv):
    if len(argv) < 3 or argv[0] not in ("record", "diff", "changed"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    cmd, project, mid, rest = argv[0], Path(argv[1]).resolve(), argv[2], argv[3:]
    if cmd == "record" and not rest:
        return record(project, mid)
    if cmd == "changed" and rest in ([], ["--write"]):
        return changed(project, mid, write=bool(rest))
    if cmd == "diff" and (not rest or (len(rest) == 2 and rest[0] == "--max-bytes" and rest[1].isdigit())):
        code, text = diff(project, mid, int(rest[1]) if rest else 200000)
        if text:
            print(text)
        return code
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    if "--help" in sys.argv[1:3] or sys.argv[1:] == ["-h"]:
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
